"""
ingestion.py — The Lighthouse · Generalized Signal Ingestion
=============================================================
Topic-agnostic ingestion engine. Works for any client or brief.
Saves signals to Supabase (via db.py) and to data/signals.jsonl as backup.

Sources (all free or already paid):
  • Reddit        — direct JSON API, no auth needed
  • RSS           — curated cultural / trend / trade feeds
  • GDELT         — free global event database
  • Google Trends — pytrends, no auth, shows search velocity over time
  • Hacker News   — free Algolia API, no auth
  • Exa.ai        — semantic web search (needs EXA_API_KEY)
  • YouTube       — trending videos (needs YOUTUBE_API_KEY)

Usage:
  # From CLI:
  python ingestion.py --topic "comfort food UK cost of living" --client "Heinz" --limit 60

  # From Python / Streamlit:
  from ingestion import run_ingestion
  results = run_ingestion(topic="...", client_tag="...", limit=60, callback=print)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional


# ── Signal schema (matches signals.jsonl / Supabase signals table) ────────────

@dataclass
class Signal:
    id: str
    title: str
    content: str
    source: str
    url: str
    timestamp: str
    category: Optional[str] = None
    client_tag: Optional[str] = None
    raw_meta: dict = None

    def __post_init__(self):
        if self.raw_meta is None:
            self.raw_meta = {}


def _make_id(url: str, timestamp: str) -> str:
    return hashlib.sha256(f"{url}{timestamp}".encode()).hexdigest()[:16]


def _clean_title(raw: str, fallback: str = "", max_len: int = 120) -> str:
    if raw and raw.strip() and raw.strip().lower() not in {"none", "null", "(no title)"}:
        return raw.strip()[:max_len]
    for line in fallback.splitlines():
        line = line.strip()
        if len(line) > 15:
            return line[:max_len]
    return "(no title)"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


# ══════════════════════════════════════════════════════════════════════════════
# SOURCES
# ══════════════════════════════════════════════════════════════════════════════

# ── Reddit (free, no auth) ────────────────────────────────────────────────────

# Universal cultural / strategy subreddits — always relevant
_DEFAULT_SUBREDDITS = [
    "advertising", "marketing", "socialmedia", "Futurology",
    "culture", "technology", "femalefashionadvice", "malefashionadvice",
    "AskUK", "AskReddit", "GenZ", "Millennials", "mentalhealth",
    "fitness", "food", "Cooking", "sustainability", "climate",
]


# ── Article text: free first, Firecrawl only for the stubborn ones ───────────
# The Trade Current is written from HEADLINES. GDELT returns titles and no body
# (its own API gives nothing else), and an RSS item is usually a two-line teaser.
# So the model has been asked to read the industry's agenda through a keyhole.
#
# Most trade sites are ordinary server-rendered HTML — a plain GET reads them
# fine, and costs nothing. Firecrawl is kept for the ones that need a real
# browser, at 1 credit a page. Same shape as the Reddit cascade: try free,
# pay only where free fails.

_STRIP_BLOCKS = re.compile(
    r"(?is)<(script|style|noscript|svg|nav|header|footer|aside|form|figure)\b.*?</\1\s*>")
_TAG = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"[ \t\x0b\f\r]+")


def _html_to_text(html: str) -> str:
    """Readable text from an article page, without a parser dependency.

    Paragraph-first: <p> blocks are where article prose lives, and taking only
    those skips menus, cookie banners and share widgets without having to
    identify them. Falls back to the whole document when a page uses divs for
    paragraphs, which some CMSs still do.
    """
    if not html:
        return ""
    body = html
    m = re.search(r"(?is)<body\b[^>]*>(.*)</body\s*>", body)
    if m:
        body = m.group(1)
    body = _STRIP_BLOCKS.sub(" ", body)

    paras = re.findall(r"(?is)<p\b[^>]*>(.*?)</p\s*>", body)
    chunks = []
    for para in paras:
        txt = _unescape(_WS.sub(" ", _TAG.sub(" ", para))).strip()
        # Short fragments are captions, bylines, cookie text and share prompts.
        if len(txt) >= 60:
            chunks.append(txt)
    text = "\n\n".join(chunks)

    if len(text) < 200:                       # divs-as-paragraphs, or a stub
        text = _unescape(_WS.sub(" ", _TAG.sub(" ", body)))
        text = "\n".join(l.strip() for l in text.splitlines() if len(l.strip()) >= 60)
    return text.strip()


def _unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s or "")


def fetch_article_text(url: str, fc_key: str = "", min_chars: int = 400,
                       timeout: int = 8) -> tuple:
    """Body text of one article. Returns (text, how).

    Free path first: a plain GET with browser-shaped headers. Most trade titles
    are server-rendered and answer it. Firecrawl only runs when that comes back
    thin — a paywall, a JavaScript shell, or a 403 — and costs 1 credit.

    `how` is one of "http", "firecrawl" or "" and is reported in the diagnostic,
    so the credit burn is visible rather than inferred from the invoice.
    """
    if not url:
        return "", ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" in ctype or not ctype:
                raw = resp.read(1_500_000)          # cap: some pages are enormous
                enc = resp.headers.get_content_charset() or "utf-8"
                text = _html_to_text(raw.decode(enc, "replace"))
                if len(text) >= min_chars:
                    return text, "http"
    except Exception:
        pass                                        # fall through to the paid path

    if not fc_key:
        return "", ""
    try:
        from firecrawl import Firecrawl
        fc = Firecrawl(api_key=fc_key)
        scrape = getattr(getattr(fc, "v2", None), "scrape", None) or getattr(fc, "scrape", None)
        if scrape is None:
            return "", ""
        # only_main_content strips nav and footers on Firecrawl's side.
        # max_age lets them serve a cached copy — their docs put repeat requests
        # at up to 5x faster, and a trade article does not change hour to hour.
        doc = scrape(url, formats=["markdown"], only_main_content=True,
                     max_age=86_400_000, timeout=20_000)
        md = getattr(doc, "markdown", None) or (doc.get("markdown") if isinstance(doc, dict) else "")
        md = (md or "").strip()
        return (md, "firecrawl") if len(md) >= 120 else ("", "")
    except Exception:
        return "", ""


# ── Reddit authentication (optional, free) ───────────────────────────────────
# The public .json endpoints are what Reddit throttles and soft-blocks from
# datacenter IPs. The authenticated API is free, has a published quota of 100
# requests per minute, and does not do the silent-empty-response thing.
#
# Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (reddit.com/prefs/apps → create
# an app → type "script") and this path is used automatically. Without them the
# public endpoints are still tried, so nothing breaks if they are absent.
_REDDIT_TOKEN: dict = {"value": "", "expires": 0.0}
_REDDIT_TOKEN_LOCK = threading.Lock()


def _reddit_token() -> str:
    """A cached app-only OAuth token, or "" when no credentials are configured."""
    cid = os.environ.get("REDDIT_CLIENT_ID", "")
    sec = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not (cid and sec):
        return ""
    with _REDDIT_TOKEN_LOCK:
        if _REDDIT_TOKEN["value"] and time.time() < _REDDIT_TOKEN["expires"]:
            return _REDDIT_TOKEN["value"]
        import base64
        basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={"Authorization": f"Basic {basic}",
                     "User-Agent": "Lighthouse-Countercurrent/2.0"},
            method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        tok = data.get("access_token", "")
        # Renew a minute early rather than discover expiry mid-scan.
        _REDDIT_TOKEN["value"] = tok
        _REDDIT_TOKEN["expires"] = time.time() + max(60, data.get("expires_in", 3600) - 60)
        return tok


# The caller widens a thin search into up to four progressively broader
# queries. Each one that comes back empty would fire its own billed Apify run —
# four paid actor runs for a single scan, and four more minutes. One attempt per
# scan window is enough to learn whether the fallback works right now.
_REDDIT_APIFY_TRIED = [0.0]
_REDDIT_APIFY_LAST_ERR = [""]     # why the one attempt failed, kept for the retries
_REDDIT_APIFY_COOLDOWN = 300      # seconds


def _scrape_reddit_rss(topic: str, subs: list, client_tag: Optional[str],
                       callback: Optional[Callable]) -> list:
    """Reddit through its RSS endpoints — free, no key, no actor rental.

    Reddit blocks `search.json` from datacenter IPs with a hard 403, but it
    also publishes the same searches as Atom at `search.rss`, and that path is
    policed far less aggressively: feeds are meant to be read by machines.

    Worth trying before paying. What it costs us is the metadata — RSS carries
    title, link and body but no score or comment count, so these posts arrive
    without engagement figures and sort below the ones that have them. A post
    with no number beats no post at all.
    """
    import xml.etree.ElementTree as _ET
    NS = {"a": "http://www.w3.org/2005/Atom"}
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    }
    q = urllib.parse.quote(topic)
    targets = [f"https://www.reddit.com/search.rss?q={q}&sort=hot&t=month"]
    for sub in list(subs)[:10]:
        targets.append(f"https://www.reddit.com/r/{sub}/search.rss?q={q}"
                       f"&restrict_sr=1&sort=hot&t=month")

    def _one(url: str):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return _ET.fromstring(resp.read())

    out, seen, errors = [], set(), []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futs = {pool.submit(_one, u): u for u in targets}
        for fut in as_completed(futs, timeout=25):
            try:
                root = fut.result()
            except Exception as exc:
                errors.append(str(exc))
                continue
            for ent in root.findall("a:entry", NS):
                link_el = ent.find("a:link", NS)
                url = (link_el.get("href") if link_el is not None else "") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                title = (ent.findtext("a:title", "", NS) or "").strip()
                body = _strip_html(ent.findtext("a:content", "", NS) or "")
                ts = (ent.findtext("a:updated", "", NS)
                      or datetime.now(tz=timezone.utc).isoformat())
                content = f"{title}\n\n{body}".strip()
                if not content:
                    continue
                # "/r/Cooking/" out of the category element, when present
                cat = ent.find("a:category", NS)
                sub_name = (cat.get("label", "") if cat is not None else "").strip("/")
                out.append(Signal(
                    id=_make_id(url, ts),
                    title=_clean_title(title, content),
                    content=content[:4000], source="reddit", url=url,
                    timestamp=str(ts), client_tag=client_tag,
                    raw_meta={"subreddit": sub_name.replace("r/", ""), "via": "rss"},
                ))
    if callback:
        callback(f"[Reddit] RSS \u2713 {len(out)} signals"
                 + (f" ({len(errors)} feeds failed)" if errors else ""))
    if not out and errors:
        raise RuntimeError(f"RSS also refused \u2014 {errors[0]}")
    return out


def _scrape_reddit_apify(topic: str, subs: list, max_items: int,
                         client_tag: Optional[str], callback: Optional[Callable]) -> list:
    """Reddit through Apify's proxy pool — the route that survives the block.

    Search URLs, not subreddit crawls: one global Reddit search plus the same
    search inside a handful of relevant subreddits. Billing is per post, so the
    URL list is kept short on purpose.
    """
    token = os.environ.get("APIFY_API_TOKEN", "")
    if not token:
        raise RuntimeError("no APIFY_API_TOKEN, so no fallback available")
    if time.monotonic() - _REDDIT_APIFY_TRIED[0] < _REDDIT_APIFY_COOLDOWN:
        # Report WHY the one attempt failed, not merely that we declined to
        # repeat it. Production surfaced "already tried this scan", which is
        # true and useless — it described the second query's refusal and buried
        # the first query's actual error.
        raise RuntimeError(_REDDIT_APIFY_LAST_ERR[0]
                           or "Apify fallback already tried this scan")
    _REDDIT_APIFY_TRIED[0] = time.monotonic()
    from apify_client import ApifyClient
    ac = ApifyClient(token)

    def _remember(exc):
        _REDDIT_APIFY_LAST_ERR[0] = f"Apify fallback failed: {exc}"
        return exc

    q = urllib.parse.quote(topic)
    urls = [{"url": f"https://www.reddit.com/search/?q={q}&sort=hot&t=month"}]
    for sub in list(subs)[:6]:
        urls.append({"url": f"https://www.reddit.com/r/{sub}/search/?q={q}"
                            f"&sort=hot&restrict_sr=1&t=month"})

    if callback:
        callback(f"[Reddit] Apify: {len(urls)} search URLs")
    # The caller asks for 10 per subreddit on the free path, but here maxItems is
    # the TOTAL across every search URL — 10 would not fill a six-card deck.
    cap = max(25, max_items)
    try:
        run = _apify_call(ac.actor("trudax/reddit-scraper"),
                          run_input={"startUrls": urls, "maxItems": cap,
                                     "proxy": {"useApifyProxy": True}})
    except Exception as exc:
        raise _remember(exc)
    ds = _run_dataset_id(run)
    if not ds:
        raise RuntimeError("Apify returned no dataset id for the Reddit run")

    out, seen = [], set()
    for item in ac.dataset(ds).iterate_items():
        url = item.get("url") or item.get("link") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        ts_raw = item.get("createdAt") or item.get("created_utc") or ""
        try:
            ts = (datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat()
                  if isinstance(ts_raw, (int, float))
                  else str(ts_raw) or datetime.now(tz=timezone.utc).isoformat())
        except Exception:
            ts = datetime.now(tz=timezone.utc).isoformat()
        title = item.get("title") or item.get("heading") or ""
        body = item.get("body") or item.get("text") or item.get("selftext") or ""
        content = f"{title}\n\n{body}".strip()
        if not content:
            continue
        out.append(Signal(
            id=_make_id(url, ts),
            title=_clean_title(title, content),
            content=content[:4000], source="reddit", url=url,
            timestamp=ts, client_tag=client_tag,
            raw_meta={
                "subreddit": item.get("subreddit") or item.get("community", ""),
                "score": item.get("score") or item.get("upVotes")
                         or item.get("upvotes", 0),
                "num_comments": item.get("numberOfComments")
                                or item.get("num_comments", 0),
                "author": item.get("author") or item.get("username", ""),
                "via": "apify",
            },
        ))
    if callback:
        callback(f"[Reddit] Apify \u2713 {len(out)} signals")
    return out


def scrape_reddit(
    topic: str,
    subreddits: Optional[list[str]] = None,
    max_items: int = 30,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """Search Reddit for topic across relevant subreddits. No API key needed.

    THE SUBREDDITS ARE QUERIED IN PARALLEL. In sequence, nine subreddits at a
    12-second timeout could hold the whole scan for 108 seconds — and when the
    caller widened the query and ran this three times, a single scan spent five
    and a half minutes waiting on Reddit alone. The work is pure network
    waiting, so it parallelises perfectly: nine at once costs one timeout.

    A subreddit that fails is skipped. If EVERY one fails the error is raised,
    because "Reddit returned nothing" and "Reddit refused to talk to us" are
    completely different problems and used to look identical in the tally.
    Reddit blocks datacenter IPs on the public JSON endpoints, so a server that
    worked from a laptop can go silent once deployed — that has to be visible.
    """
    subs = subreddits or _DEFAULT_SUBREDDITS
    # Reddit 403s unfamiliar clients. A browser-shaped header is what the RSS
    # probes already needed for the same reason.
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    # ALL OF THEM, not the first eight. The slice was written when these ran in
    # sequence and nine requests were already slow. The list, though, is ordered
    # by the agency's own interests — advertising, marketing, social media,
    # fashion — and r/food and r/Cooking sit at positions 15 and 16. So a search
    # for "Food Soup" politely asked r/femalefashionadvice and r/advertising,
    # got nothing, and reported "0" as though Reddit had no soup on it.
    # Now that the requests run in parallel, the whole list costs one timeout.
    search_targets = list(dict.fromkeys(list(subs) + ["all"]))
    if callback:
        callback(f"[Reddit] Searching {len(search_targets)} subreddits for '{topic[:40]}'…")

    q = urllib.parse.quote(topic)

    token = ""
    try:
        token = _reddit_token()
    except Exception as exc:
        if callback:
            callback(f"[Reddit] auth failed, falling back to public API: {exc}")
    if token:
        headers = {"Authorization": f"bearer {token}",
                   "User-Agent": "Lighthouse-Countercurrent/2.0"}
    host = "oauth.reddit.com" if token else "www.reddit.com"
    leaf = "search" if token else "search.json"

    def _one(sub: str):
        url = (f"https://{host}/r/{sub}/{leaf}?q={q}&sort=hot"
               f"&limit={max_items}&restrict_sr={'1' if sub != 'all' else '0'}&t=month")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())

    signals: list[Signal] = []
    seen: set[str] = set()
    errors: list[str] = []

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=len(search_targets)) as pool:
        futs = {pool.submit(_one, sub): sub for sub in search_targets}
        for fut in as_completed(futs, timeout=30):
            sub = futs[fut]
            try:
                data = fut.result()
            except Exception as exc:
                errors.append(f"r/{sub}: {exc}")
                if callback:
                    callback(f"[Reddit] r/{sub}: {exc}")
                continue
            for post in data.get("data", {}).get("children", []):
                p = post.get("data", {})
                purl = f"https://reddit.com{p.get('permalink', '')}"
                if purl in seen or not p.get("title"):
                    continue
                seen.add(purl)
                ts = datetime.fromtimestamp(
                    p.get("created_utc", datetime.now().timestamp()), tz=timezone.utc
                ).isoformat()
                body = p.get("selftext") or ""
                content = f"{p.get('title', '')}\n\n{body}".strip()[:4000]
                signals.append(Signal(
                    id=_make_id(purl, ts),
                    title=_clean_title(p.get("title", ""), content),
                    content=content, source="reddit",
                    url=purl, timestamp=ts, client_tag=client_tag,
                    raw_meta={
                        "subreddit": p.get("subreddit"),
                        "score": p.get("score", 0),
                        "num_comments": p.get("num_comments", 0),
                    },
                ))

    # SOFT BLOCKING.
    # Reddit does not always answer a refused client with 403. From datacenter
    # IPs it commonly returns 200 OK with an empty children list — a polite lie
    # that is indistinguishable from "no results" unless you notice that ALL of
    # nineteen subreddits, r/all included, came back empty at once. That does
    # not happen for a real query. Saying so is the difference between the team
    # thinking Reddit has nothing on soup and knowing they need credentials.
    # PLAN B: APIFY.
    # This is how Reddit worked in the earlier version of the Lighthouse, and
    # the note in that file said exactly why — "contorna os bloqueios 403".
    # The trudax actor runs through Apify's proxy pool, so Reddit sees a
    # residential address instead of a datacenter one and answers normally.
    #
    # It is deliberately the FALLBACK, not the default: it bills per post
    # (~US$0.002-0.005) while the public endpoints are free. When Reddit is
    # willing to talk to us we pay nothing; when it goes quiet we pay a few
    # cents rather than losing the source. Creating a script app at
    # reddit.com/prefs/apps is no longer possible for everyone, so the OAuth
    # path above cannot be relied on.
    #
    # ORDER MATTERS AND I GOT IT WRONG THE FIRST TIME. This used to sit below a
    # `raise` for "every subreddit failed", so the one situation the fallback
    # exists for — Reddit refusing every request — was the one situation where
    # it never ran. Production said "every subreddit failed — r/socialmedia:
    # HTTP Error 403: Blocked" and stopped there. It is a hard 403 after all,
    # not the soft empty response I guessed at earlier.
    # RUNG 2: RSS. Free, so it goes before anything that bills.
    if not signals:
        try:
            signals = _scrape_reddit_rss(topic, subs, client_tag, callback)
        except Exception as exc:
            errors.append(f"rss: {exc}")

    if not signals:
        if errors and len(errors) >= len(search_targets):
            why = f"every subreddit failed \u2014 {errors[0]}"
        elif errors:
            why = errors[0]
        else:
            why = "all subreddits answered 200 OK with zero results"
        if callback:
            callback(f"[Reddit] public API gave nothing ({why}) \u2014 trying Apify")
        try:
            signals = _scrape_reddit_apify(topic, subs, max_items, client_tag, callback)
        except Exception as exc:
            raise RuntimeError(f"public Reddit failed ({why}); Apify fallback "
                               f"also failed: {exc}")
        if not signals:
            raise RuntimeError(
                f"public Reddit returned nothing ({why}) and the Apify actor "
                f"returned nothing either \u2014 check APIFY_API_TOKEN and credit")
    if callback:
        callback(f"[Reddit] \u2713 {len(signals)} signals"
                 + (f" ({len(errors)} subreddits failed)" if errors else ""))
    return signals


# ── RSS (free, no auth) ───────────────────────────────────────────────────────

# Curated list of cultural intelligence, trends, trade, and strategy feeds
_DEFAULT_RSS_FEEDS: list[tuple[str, str]] = [
    # Culture & trends
    ("https://feeds.feedburner.com/fastcompany/headlines", "Fast Company"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml", "NYT Arts"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/FashionandStyle.xml", "NYT Style"),
    ("https://www.theguardian.com/culture/rss", "Guardian Culture"),
    ("https://www.theguardian.com/society/rss", "Guardian Society"),
    ("https://feeds.wired.com/wired/index", "Wired"),
    ("https://feeds.feedburner.com/TechCrunch", "TechCrunch"),
    ("https://www.vox.com/rss/index.xml", "Vox"),
    ("https://www.theatlantic.com/feed/all/", "The Atlantic"),
    # Marketing & advertising
    ("https://www.marketingweek.com/feed/", "Marketing Week"),
    ("https://adage.com/rss.xml", "Ad Age"),
    ("https://www.campaignlive.co.uk/rss", "Campaign"),
    ("https://www.thedrum.com/rss.xml", "The Drum"),
    # UK-specific (useful for British clients)
    ("https://feeds.bbci.co.uk/news/uk/rss.xml", "BBC UK News"),
    ("https://www.theguardian.com/uk/rss", "Guardian UK"),
    # Wellbeing & lifestyle
    ("https://www.mindbodygreen.com/rss.xml", "MindBodyGreen"),
    ("https://www.psychologytoday.com/us/node/feed/all", "Psychology Today"),
]


def scrape_rss(
    feeds: Optional[list[tuple[str, str]]] = None,
    max_items_per_feed: int = 6,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
    timeout: int = 10,
) -> list[Signal]:
    """Read RSS / Atom feeds. Uses a curated set of cultural / trade sources."""
    feed_list = feeds or _DEFAULT_RSS_FEEDS
    signals: list[Signal] = []

    if callback:
        callback(f"[RSS] Reading {len(feed_list)} feeds…")

    for feed_url, feed_name in feed_list:
        try:
            # Browser-shaped headers. Trade publishers sit behind Cloudflare and
            # similar, and an unrecognised User-Agent gets a 403 before the feed
            # is ever served — which looked, from our side, exactly like "this
            # outlet published nothing". The Accept header matters too: some
            # servers return HTML to clients that do not ask for a feed type.
            req = urllib.request.Request(feed_url, headers={
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0 Safari/537.36"),
                "Accept": ("application/rss+xml, application/atom+xml, "
                           "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"),
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            is_atom = root.tag == "{http://www.w3.org/2005/Atom}feed"

            if is_atom:
                for entry in root.findall("atom:entry", ns)[:max_items_per_feed]:
                    title = entry.findtext("atom:title", "", ns).strip()
                    link = entry.find("atom:link", ns)
                    url = link.get("href", "") if link is not None else ""
                    summary = entry.findtext("atom:summary", "", ns)
                    content_el = entry.find("atom:content", ns)
                    content = _strip_html(content_el.text if content_el is not None else summary)[:4000]
                    ts = entry.findtext("atom:updated", "", ns) or datetime.now(tz=timezone.utc).isoformat()
                    signals.append(Signal(
                        id=_make_id(url, ts), title=_clean_title(title, content),
                        content=content, source="rss", url=url, timestamp=ts,
                        client_tag=client_tag, raw_meta={"feed_name": feed_name},
                    ))
            else:
                channel = root.find("channel") or root
                for item in channel.findall("item")[:max_items_per_feed]:
                    title = (item.findtext("title") or "").strip()
                    url = item.findtext("link") or item.findtext("guid") or ""
                    desc = item.findtext("description") or ""
                    content = _strip_html(desc)[:4000]
                    ts_raw = item.findtext("pubDate") or ""
                    try:
                        from email.utils import parsedate_to_datetime
                        ts = parsedate_to_datetime(ts_raw).isoformat()
                    except Exception:
                        ts = datetime.now(tz=timezone.utc).isoformat()
                    signals.append(Signal(
                        id=_make_id(url, ts), title=_clean_title(title, content),
                        content=content, source="rss", url=url, timestamp=ts,
                        client_tag=client_tag, raw_meta={"feed_name": feed_name},
                    ))
        except Exception as exc:
            if callback:
                callback(f"[RSS] '{feed_name}': {exc}")

    if callback:
        callback(f"[RSS] ✓ {len(signals)} signals")
    return signals


# ── GDELT (free, no auth) ─────────────────────────────────────────────────────

# GDELT rate-limits hard and says so in plain text, not JSON. The Lighthouse
# hits it from two directions at once — the main scan (up to four widened
# queries) and the trade section (one query per outlet, eight in parallel) —
# which is a dozen requests in a couple of seconds. That is a refusal, and the
# refusal used to look like "no news found".
#
# One global gate, one request at a time, spaced out. The trade workers keep
# probing RSS in parallel while they wait their turn here.
# APIFY TIME CAPS — RAISED AFTER THEY BROKE COLLECTION.
# I first set these to 90/100 seconds to stop a slow actor holding the scan
# hostage. The next run came back twitter 0 · instagram 0 · tiktok 0: all three
# actors at once, which is one cause, not three. `timeout_secs` makes Apify
# ABORT the run, and that clock includes the time a run spends QUEUING for a
# free machine — on free credits that queue can eat the whole allowance before
# the scraper starts, so the actor was killed with an empty dataset.
#
# The caps stay, because an uncapped `.call()` really can block forever, but
# generous enough to be a safety net rather than a guillotine. The scan-time
# problem they were meant to solve had a different cause anyway: the Instagram
# hashtag-discovery experiment, since reverted.
_APIFY_RUN_CAP = 300      # seconds the actor may run, queue included


def _apify_call(actor, **kwargs):
    """`.call()` with a run ceiling where the installed client supports one.

    Production reported `ActorClient.call() got an unexpected keyword argument
    'timeout_secs'` on all three actors at once — the deployed apify-client is
    older than the one I tested against. Pinning a version would fix it for one
    environment and break another, so the ceiling is applied only if the client
    accepts it. This is the whole reason to introspect rather than assume.
    """
    try:
        return actor.call(timeout_secs=_APIFY_RUN_CAP, **kwargs)
    except TypeError as exc:
        if "timeout_secs" not in str(exc):
            raise
        return actor.call(**kwargs)

# `wait_secs` IS REMOVED ON PURPOSE. It does not cancel anything — it makes
# .call() give up waiting and return None while the run carries on and still
# bills. The console then shows "Actor succeeded with 19 results" and the app
# reports zero, which is exactly the contradiction we were staring at. Only
# timeout_secs is a real ceiling, because Apify enforces it on its own side.

_GDELT_LOCK = threading.Lock()
_GDELT_MIN_GAP = 1.6          # seconds between consecutive GDELT calls
_GDELT_LAST = [0.0]


def _gdelt_gate():
    with _GDELT_LOCK:
        wait = _GDELT_MIN_GAP - (time.monotonic() - _GDELT_LAST[0])
        if wait > 0:
            time.sleep(wait)
        _GDELT_LAST[0] = time.monotonic()


def scrape_gdelt(
    topic: str,
    n: int = 20,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
    source_country: str = "",
    domains: Optional[list] = None,
    timespan: str = "2weeks",
) -> list[Signal]:
    """Query GDELT Doc 2.0 API for news articles related to the topic.

    Two optional filters, both native GDELT query operators:

      source_country  "US", "GB", "BR"… → ` sourcecountry:US`. Narrows the brief
                      to one market instead of the whole world.
      domains         ["bevnet.com", …] → ` (domainis:a OR domainis:b)`. This is
                      how the trade-press section is collected: the model
                      proposes the outlets, GDELT decides whether they actually
                      published anything, so an invented outlet returns nothing
                      and disappears on its own.

    `domainis` is the exact-match form — `domain:` would also match subdomains
    and lookalikes, which is wrong when the point is "articles from THIS outlet".
    """
    if callback:
        _who = f" @{','.join(domains[:3])}" if domains else ""
        _wh = f" [{source_country}]" if source_country else ""
        callback(f"[GDELT] Querying '{topic[:40]}'{_wh}{_who}…")
    signals: list[Signal] = []
    try:
        # Operators go INSIDE the query string, space-separated, then the whole
        # thing is percent-encoded once.
        query = topic
        if domains:
            query += " (" + " OR ".join(f"domainis:{d.strip()}" for d in domains if d.strip()) + ")"
        if source_country:
            query += f" sourcecountry:{source_country}"
        q = urllib.parse.quote(query)
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={q}&mode=artlist&maxrecords={n}&format=json&timespan={timespan}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Lighthouse/2.0"})
        _gdelt_gate()
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        # GDELT does NOT answer with JSON when it is unhappy. A rate limit, a
        # malformed operator or too many requests all come back as plain text or
        # an HTML page, json.loads raises, and the except below used to turn that
        # into a quiet empty list. Every scan reported "gdelt 0" and no one could
        # tell an empty result from a refusal.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            msg = raw.decode("utf-8", "replace").strip()[:180]
            raise RuntimeError(f"GDELT did not return JSON: {msg or '(empty body)'}")
        for art in data.get("articles", []):
            aurl = art.get("url", "")
            ts = art.get("seendate", datetime.now(tz=timezone.utc).isoformat())
            # GDELT date format: 20240115T120000Z → ISO
            try:
                ts = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
            title = art.get("title", "")
            signals.append(Signal(
                id=_make_id(aurl, ts),
                title=_clean_title(title),
                content=title,  # GDELT only returns titles, no body
                source="gdelt", url=aurl, timestamp=ts,
                client_tag=client_tag,
                raw_meta={"domain": art.get("domain"), "language": art.get("language")},
            ))
    except Exception as exc:
        if callback:
            callback(f"[GDELT] Error: {exc}")
        raise                      # let the caller's tally record it, not hide it
    if callback:
        callback(f"[GDELT] \u2713 {len(signals)} signals")
    return signals


# ── TikTok (Apify actor — needs APIFY_API_TOKEN) ─────────────────────────────

def _fetch_tiktok_comments(video_url: str, api_token: str, max_comments: int = 10) -> str:
    """
    Fetch top comments for a TikTok video URL via Apify.
    Returns a formatted string to append to the signal content.
    Actor: apify/tiktok-comment-scraper
    """
    try:
        from apify_client import ApifyClient
        client = ApifyClient(api_token)
        run = client.actor("apify/tiktok-comment-scraper").call(
            run_input={"postURLs": [video_url], "commentsPerPost": max_comments},
        )

        comments = []
        for c in client.dataset(_run_dataset_id(run) or "").iterate_items():
            text = c.get("text") or c.get("commentText") or ""
            likes = c.get("diggCount") or c.get("likeCount") or 0
            if text:
                comments.append(f"  ↳ {text[:200]} ({likes:,} likes)")
        if comments:
            return "\n\nTop comments:\n" + "\n".join(comments[:max_comments])
    except Exception:
        pass
    return ""


def scrape_tiktok(
    topic: str,
    api_token: str,
    n: int = 20,
    fetch_comments: bool = True,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """
    Search TikTok for videos related to the topic via Apify.
    Actor: clockworks/free-tiktok-scraper (no auth required on actor side).
    If fetch_comments=True, enriches each signal with ~10 top comments
    (Buzzabout-style: comments as context for AI classification).
    Requires: APIFY_API_TOKEN secret.
    """
    if not api_token:
        return []
    if callback:
        callback(f"[TikTok] Searching '{topic[:40]}' via Apify…")
    signals: list[Signal] = []
    try:
        from apify_client import ApifyClient
        client = ApifyClient(api_token)
        run_input = {
            "searchQueries": [topic],
            "resultsPerPage": n,            # REQUIRED for keyword search — without it the actor returns ~1 result
            "maxItems": n,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": True,   # download to Apify storage → stable URL, bypasses TikTok CDN hotlink block
        }
        run = _apify_call(client.actor("clockworks/free-tiktok-scraper"),
                          run_input=run_input)
        # _run_dataset_id, not run.default_dataset_id: the client's own type hint
        # is `dict | None`, and attribute access on either blows up with an
        # AttributeError that the except below turns into a silent zero.
        _ds = _run_dataset_id(run)
        if not _ds:
            raise RuntimeError("Apify returned no dataset id for the TikTok run "
                               f"(call returned {type(run).__name__})")
        videos = list(client.dataset(_ds).iterate_items())
        for idx, item in enumerate(videos):
            vid_url = item.get("webVideoUrl") or item.get("authorMeta", {}).get("url", "")
            ts = item.get("createTimeISO") or datetime.now(tz=timezone.utc).isoformat()
            desc = item.get("text") or ""
            author = item.get("authorMeta", {}).get("name", "")
            plays = item.get("playCount") or 0
            likes = item.get("diggCount") or 0
            content = f"{desc}\n\nAuthor: @{author} | Views: {plays:,} | Likes: {likes:,}"

            # Enrich with comments (Buzzabout-style context enrichment)
            if fetch_comments and vid_url:
                if callback:
                    callback(f"[TikTok] Fetching comments for video {idx + 1}/{len(videos)}…")
                content += _fetch_tiktok_comments(vid_url, api_token, max_comments=10)

            signals.append(Signal(
                id=_make_id(vid_url, str(ts)),
                title=_clean_title(desc[:100], content),
                content=content.strip()[:4000],
                source="tiktok",
                url=vid_url,
                timestamp=str(ts),
                client_tag=client_tag,
                raw_meta={
                    "author": author,
                    "plays": plays,
                    "likes": likes,
                    "hashtags": item.get("hashtags", []),
                    "comments_enriched": fetch_comments,
                    "thumbnail": (
                        # When shouldDownloadCovers=True, Apify stores the image
                        # and returns a stable URL — check common field names
                        item.get("coverUrl")                               # top-level (downloaded)
                        or item.get("imageUrl")                            # alternative top-level
                        or item.get("videoMeta", {}).get("coverUrl")       # nested
                        or item.get("videoMeta", {}).get("originalCoverUrl")
                        or item.get("staticCoverUrl")
                        or item.get("originCoverUrl")
                        or item.get("covers", {}).get("default")
                        or item.get("covers", {}).get("origin")
                        or ""
                    ),
                },
            ))
    except Exception as exc:
        if callback:
            callback(f"[TikTok] Error: {exc}")
        raise            # the caller's tally reports it; silence looked like "no results"
    if callback:
        callback(f"[TikTok] ✓ {len(signals)} signals")
    return signals


# ── Instagram (Apify actor — needs APIFY_API_TOKEN) ───────────────────────────

def scrape_instagram(
    topic: str,
    api_token: str,
    n: int = 20,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """
    Search Instagram hashtags/posts related to the topic via Apify.
    Tries apify/instagram-hashtag-scraper with individual words AND full topic.
    Requires: APIFY_API_TOKEN secret.
    """
    if not api_token:
        return []
    if callback:
        callback(f"[Instagram] Searching '{topic[:40]}' via Apify…")
    signals: list[Signal] = []

    def _parse_ig_items(items):
        result = []
        for item in items:
            post_url = item.get("url") or item.get("shortCode", "")
            if post_url and not post_url.startswith("http"):
                post_url = f"https://www.instagram.com/p/{post_url}/"
            ts = item.get("timestamp") or datetime.now(tz=timezone.utc).isoformat()
            caption = (item.get("caption") or item.get("text") or "").strip()
            owner = item.get("ownerUsername") or item.get("username") or ""
            likes = item.get("likesCount") or item.get("likeCount") or 0
            comments = item.get("commentsCount") or item.get("commentCount") or 0
            if not caption and not post_url:
                continue
            content = f"{caption}\n\n@{owner} | Likes: {likes:,} | Comments: {comments:,}".strip()
            result.append(Signal(
                id=_make_id(post_url, str(ts)),
                title=_clean_title(caption[:100], content),
                content=content[:4000],
                source="instagram",
                url=post_url,
                timestamp=str(ts),
                client_tag=client_tag,
                raw_meta={
                    "owner": owner,
                    "likes": likes,
                    "comments": comments,
                    "hashtags": item.get("hashtags", []),
                    # Instagram CDN URLs are signed and expire within hours, but
                    # for FRESH scrapes they're still valid and load fine when
                    # routed through the wsrv.nl proxy (_tr_proxy_thumb). The UI
                    # falls back to the Instagram-branded gradient if the image
                    # fails, so returning the URL is the best of both worlds.
                    "thumbnail": (
                        item.get("displayUrl")
                        or item.get("thumbnailUrl")
                        or item.get("previewUrl")
                        or item.get("imageUrl")
                        or ""
                    ),
                },
            ))
        return result

    try:
        from apify_client import ApifyClient
        client = ApifyClient(api_token)

        # HASHTAGS, NOT A SENTENCE.
        # This used to glue the whole search phrase into one tag —
        # "Sparkling water Mineral with gas" became #sparklingwatermineralwithgas,
        # a hashtag nobody has ever posted under. That is why Instagram returned
        # one post while X returned sixteen: X does a text search, Instagram
        # needs a tag that real people actually use.
        #
        # So we try a few plausible tags instead: the two-word compound (the one
        # that usually exists — #sparklingwater), then a three-word compound, then
        # the longest single words. Dead tags cost nothing; they just return
        # nothing and the next one is tried.
        words = [w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) >= 3]
        tags: list[str] = []
        if len(words) >= 2:
            tags.append(words[0] + words[1])
        # A three-word compound is almost always dead too, so the remaining
        # slots go to real single words — #sparkling and #mineral exist, and
        # #sparklingwatermineral does not.
        # >= 4, not 5. At five, a search like "Food Soup" produced exactly ONE
        # tag — #foodsoup — because both words are four letters, and the scan
        # came back with a single Instagram post. #food and #soup are perfectly
        # good hashtags; the relevance and language gates downstream handle the
        # breadth they bring.
        tags += sorted([w for w in words if len(w) >= 4], key=len, reverse=True)
        if not tags and words:
            tags = [words[0]]
        tags = list(dict.fromkeys(tags))[:3]

        # COST CONTROL: the actor bills per result and resultsLimit applies PER
        # URL, so the budget is split across the tags rather than multiplied by
        # them. Three tags at 4 each ≈ 12 billed posts, about US$0.03.
        _per = max(2, -(-n // max(1, len(tags))) + 1)
        direct_urls = [f"https://www.instagram.com/explore/tags/{t}/" for t in tags]

        # I TRIED `search` + `searchType: "hashtag"` HERE AND IT MADE THINGS
        # WORSE — reverted. The idea was to let Instagram choose the tags
        # instead of us guessing them. In practice the actor went off doing
        # hashtag discovery, the run went from under a minute to several, and it
        # came back with ONE post instead of five. The scan went from 1m50 to
        # 4m30 and the section lost four cards.
        #
        # Worth recording why the original idea does not work either way:
        # Instagram has no public caption search, so there is no way to find a
        # post that mentions the phrase without tagging it. Guessed tags are the
        # only lever we have here; the honest improvement is to guess better.
        run_input = {
            "directUrls": direct_urls,
            "resultsType": "posts",
            "resultsLimit": _per,
            "addParentData": False,
        }
        run = _apify_call(client.actor("apify/instagram-scraper"),
                          run_input=run_input)
        # _run_dataset_id handles both the dict and the object the client returns
        # depending on version. Reading .default_dataset_id directly threw an
        # AttributeError on the dict form — swallowed by the except below, so it
        # looked exactly like "Instagram had nothing".
        _ds = _run_dataset_id(run)
        if not _ds:
            raise RuntimeError("Apify returned no dataset id for the Instagram run")
        items = list(client.dataset(_ds).iterate_items())
        signals = _parse_ig_items(items)
        # Which tag each post came from — so a future scan can be debugged
        # without guessing.
        for _sg in signals:
            _sg.raw_meta.setdefault("tags_tried", tags)
        # Dedupe: the same post can sit under two of the tags we asked for.
        _seen, _uniq = set(), []
        for _sg in signals:
            if _sg.url in _seen:
                continue
            _seen.add(_sg.url)
            _uniq.append(_sg)
        signals = _uniq[:n]
        if callback:
            callback(f"[Instagram] tags: {', '.join('#' + t for t in tags)}")

    except Exception as exc:
        if callback:
            callback(f"[Instagram] Error: {exc}")
        raise            # the caller's tally reports it; silence looked like "no results"
    if callback:
        callback(f"[Instagram] ✓ {len(signals)} signals")
    return signals


# ── X / Twitter (Apify actor — needs APIFY_API_TOKEN) ────────────────────────

def _run_dataset_id(run) -> Optional[str]:
    """Extract the default dataset id from an Apify actor run result.
    apify-client returns a dict in some versions and a typed object in others —
    support both so version upgrades never silently break retrieval.
    """
    if run is None:
        return None
    if isinstance(run, dict):
        return run.get("defaultDatasetId") or run.get("default_dataset_id")
    return (getattr(run, "default_dataset_id", None)
            or getattr(run, "defaultDatasetId", None))


def _parse_twitter_items(items: list, client_tag: Optional[str] = None) -> list["Signal"]:
    """Parse tweet items from any Apify Twitter actor into Signal objects.
    Handles field names from both danek/twitter-scraper and apidojo/tweet-scraper.
    """
    signals: list[Signal] = []
    for item in items:
        # ── Text ── (covers both actors' field names)
        text = (
            item.get("text") or item.get("rawContent") or item.get("full_text")
            or item.get("fullText") or item.get("content") or item.get("body") or ""
        )
        # ── URL ──
        tweet_url = (
            item.get("url") or item.get("twitterUrl") or item.get("tweetUrl")
            or item.get("tweet_url") or item.get("permanentUrl") or ""
        )
        if not tweet_url:
            _tid = (item.get("id") or item.get("tweet_id") or item.get("id_str") or "")
            if _tid:
                tweet_url = f"https://x.com/i/web/status/{_tid}"
        # ── Timestamp ──
        ts = (
            item.get("date") or item.get("createdAt") or item.get("created_at")
            or item.get("timestamp") or datetime.now(tz=timezone.utc).isoformat()
        )
        # ── Author ── (string in danek, object in apidojo)
        author_raw = item.get("author") or item.get("user") or {}
        if isinstance(author_raw, dict):
            handle = (
                author_raw.get("userName") or author_raw.get("username")
                or author_raw.get("screen_name") or author_raw.get("login") or ""
            )
        else:
            handle = str(author_raw)
        # ── Engagement ──
        likes    = item.get("likes")    or item.get("likeCount")    or item.get("favorite_count") or 0
        retweets = item.get("reposts")  or item.get("retweetCount") or item.get("retweet_count")  or 0
        replies  = item.get("replies")  or item.get("replyCount")   or item.get("reply_count")    or 0
        # Skip items with no content AND no URL
        if not text and not tweet_url:
            continue
        if not text:
            text = f"[Tweet] {tweet_url}"
        content = (
            f"{text}\n\n"
            f"@{handle} · Likes: {likes:,} · Retweets: {retweets:,} · Replies: {replies:,}"
        ).strip()
        signals.append(Signal(
            id=_make_id(tweet_url or text[:40], str(ts)),
            title=_clean_title(text[:100], content),
            content=content[:4000],
            source="twitter",
            url=tweet_url,
            timestamp=str(ts),
            client_tag=client_tag,
            raw_meta={"handle": handle, "likes": likes,
                      "retweets": retweets, "replies": replies},
        ))
    return signals


def scrape_twitter(
    topic: str,
    api_token: str,
    n: int = 20,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """
    Search X/Twitter for posts via Apify.
    Primary:  danek/twitter-scraper  (fast, no credentials needed)
    Fallback: apidojo/tweet-scraper  (if primary returns 0 items)
    Requires: APIFY_API_TOKEN secret.
    """
    if not api_token:
        return []
    if callback:
        callback(f"[X/Twitter] Searching '{topic[:40]}' via Apify…")
    signals: list[Signal] = []
    try:
        from apify_client import ApifyClient
        ac = ApifyClient(api_token)

        # ── Primary: danek/twitter-scraper ────────────────────────────────
        # Verified input schema (build 1.4.28): the search field is "query"
        # (a string), the sort is "search_type", and "max_posts" is required.
        # (searchTerms / search / maxItems are silently ignored by this actor.)
        try:
            run = _apify_call(ac.actor("danek/twitter-scraper"), run_input={
                "query": topic,
                "search_type": "Top",   # Top | Latest | Media | People | Lists
                "max_posts": n,
            })
            _ds_id = _run_dataset_id(run)
            if not _ds_id:
                raise RuntimeError(f"No dataset id in run result (type={type(run).__name__})")
            items_list = list(ac.dataset(_ds_id).iterate_items())
            if callback:
                callback(f"[X/Twitter] danek actor → {len(items_list)} raw items")
            if items_list and callback:
                callback(f"[X/Twitter] Sample keys: {list(items_list[0].keys())[:12]}")
            signals = _parse_twitter_items(items_list, client_tag)
        except Exception as _primary_err:
            if callback:
                callback(f"[X/Twitter] Primary actor error: {_primary_err}")
            items_list = []

        # ── Fallback: apidojo/tweet-scraper ───────────────────────────────
        if not signals:
            if callback:
                callback("[X/Twitter] Trying apidojo/tweet-scraper as fallback…")
            try:
                run2 = _apify_call(ac.actor("apidojo/tweet-scraper"), run_input={
                    "searchTerms": [topic],
                    "maxItems": n,          # correct param (not maxTweets)
                    "sort": "Top",          # correct param (not queryType)
                })
                _ds_id2 = _run_dataset_id(run2)
                if not _ds_id2:
                    raise RuntimeError("No dataset id in fallback run result")
                items2 = list(ac.dataset(_ds_id2).iterate_items())
                if callback:
                    callback(f"[X/Twitter] apidojo actor → {len(items2)} raw items")
                signals = _parse_twitter_items(items2, client_tag)
            except Exception as _fallback_err:
                if callback:
                    callback(f"[X/Twitter] Fallback actor error: {_fallback_err}")
                # Both actors are gone. Swallowing here is why X reported a
                # clean "0" in the very run where the other two showed "✕" for
                # the same underlying cause — it hid the shared error.
                raise RuntimeError(
                    f"both X actors failed \u2014 danek: {_primary_err} \u00b7 "
                    f"apidojo: {_fallback_err}")

    except Exception as exc:
        if callback:
            callback(f"[X/Twitter] Error: {exc}")
        raise            # the caller's tally reports it; silence looked like "no results"
    if callback:
        callback(f"[X/Twitter] \u2713 {len(signals)} signals")
    return signals


# ── Exa.ai (needs EXA_API_KEY) ────────────────────────────────────────────────

def scrape_exa(
    topic: str,
    api_key: str,
    n: int = 15,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """Exa semantic search — finds high-quality web articles by meaning."""
    if not api_key:
        return []
    if callback:
        callback(f"[Exa] Searching '{topic[:40]}'…")
    signals: list[Signal] = []
    try:
        from exa_py import Exa
        exa = Exa(api_key)
        results = exa.search_and_contents(
            topic,
            num_results=n,
            text=True,
            highlights=True,
            use_autoprompt=True,
        )
        for r in results.results:
            url = r.url or ""
            ts = getattr(r, "published_date", None) or datetime.now(tz=timezone.utc).isoformat()
            title = getattr(r, "title", "") or ""
            text = getattr(r, "text", "") or ""
            highlights = getattr(r, "highlights", []) or []
            content = (text or " ".join(highlights))[:4000]
            signals.append(Signal(
                id=_make_id(url, str(ts)),
                title=_clean_title(title, content),
                content=content, source="exa",
                url=url, timestamp=str(ts), client_tag=client_tag,
                raw_meta={"score": getattr(r, "score", None)},
            ))
    except Exception as exc:
        if callback:
            callback(f"[Exa] Error: {exc}")
    if callback:
        callback(f"[Exa] ✓ {len(signals)} signals")
    return signals


# ── Google Trends (free, no auth — needs pytrends) ───────────────────────────

def scrape_google_trends(
    topic: str,
    geo: str = "",          # "" = worldwide; "GB" = UK; "US" = USA
    timeframe: str = "now 7-d",
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """
    Pull Google Trends data for a topic.
    Returns two signal types:
      • One signal per trending search (real-time trending now)
      • One aggregate signal with keyword velocity over the past week
    Requires: pip install pytrends
    """
    if callback:
        callback(f"[Google Trends] Querying '{topic[:40]}' (geo={geo or 'WW'})…")
    signals: list[Signal] = []

    try:
        from pytrends.request import TrendReq
    except ImportError:
        if callback:
            callback("[Google Trends] pytrends not installed — skipping")
        return []

    try:
        # ── 1. Trending searches right now (by country) ──
        pt = TrendReq(hl="en-US", tz=0, retries=2, backoff_factor=0.5, timeout=(10, 25))
        country_map = {"GB": "united_kingdom", "US": "united_states",
                       "BR": "brazil", "": "united_states"}
        country_key = country_map.get(geo, "united_states")

        try:
            trending_df = pt.trending_searches(pn=country_key)
            now_ts = datetime.now(tz=timezone.utc).isoformat()
            for term in trending_df[0].tolist()[:20]:
                term = str(term).strip()
                if not term:
                    continue
                fake_url = f"https://trends.google.com/trends/explore?q={urllib.parse.quote(term)}&geo={geo}"
                signals.append(Signal(
                    id=_make_id(fake_url, now_ts),
                    title=f"Trending: {term}",
                    content=f"'{term}' is trending on Google Search right now ({geo or 'worldwide'}).",
                    source="google_trends",
                    url=fake_url,
                    timestamp=now_ts,
                    client_tag=client_tag,
                    raw_meta={"type": "trending_now", "term": term, "geo": geo},
                ))
        except Exception as exc:
            if callback:
                callback(f"[Google Trends] trending_searches error: {exc}")

        # ── 2. Interest over time for the topic keywords ──
        try:
            # Extract up to 5 keywords from topic string
            keywords = [w for w in topic.replace(",", " ").split() if len(w) > 3][:5]
            if not keywords:
                keywords = [topic[:40]]

            pt.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
            iot = pt.interest_over_time()

            if not iot.empty:
                # Build a velocity signal: peak vs average
                for kw in keywords[:5]:
                    if kw not in iot.columns:
                        continue
                    series = iot[kw]
                    avg = float(series.mean())
                    peak = float(series.max())
                    recent = float(series.iloc[-1]) if len(series) else avg
                    velocity = round(recent / avg, 2) if avg > 0 else 1.0

                    trend_desc = "stable"
                    if velocity >= 1.5:
                        trend_desc = "rising fast 🔺"
                    elif velocity >= 1.2:
                        trend_desc = "rising 📈"
                    elif velocity <= 0.7:
                        trend_desc = "declining 📉"

                    ts = datetime.now(tz=timezone.utc).isoformat()
                    url = f"https://trends.google.com/trends/explore?q={urllib.parse.quote(kw)}&geo={geo}&date={timeframe}"
                    signals.append(Signal(
                        id=_make_id(url, ts),
                        title=f"Search velocity: '{kw}' — {trend_desc}",
                        content=(
                            f"Google Search interest for '{kw}' over the past 7 days: "
                            f"avg={avg:.0f}, peak={peak:.0f}, recent={recent:.0f}. "
                            f"Velocity index: {velocity}x ({trend_desc}). "
                            f"Geography: {geo or 'worldwide'}."
                        ),
                        source="google_trends",
                        url=url,
                        timestamp=ts,
                        client_tag=client_tag,
                        raw_meta={
                            "type": "velocity",
                            "keyword": kw,
                            "avg": avg,
                            "peak": peak,
                            "recent": recent,
                            "velocity_index": velocity,
                            "geo": geo,
                            "timeframe": timeframe,
                        },
                    ))
        except Exception as exc:
            if callback:
                callback(f"[Google Trends] interest_over_time error: {exc}")

    except Exception as exc:
        if callback:
            callback(f"[Google Trends] Error: {exc}")

    if callback:
        callback(f"[Google Trends] ✓ {len(signals)} signals")
    return signals


# ── Hacker News (free, no auth) ───────────────────────────────────────────────

def scrape_hacker_news(
    topic: str,
    n: int = 20,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """
    Search Hacker News via the Algolia API (free, no auth).
    Good for tech/culture/startup signals with high-signal comment threads.
    """
    if callback:
        callback(f"[Hacker News] Searching '{topic[:40]}'…")
    signals: list[Signal] = []

    try:
        q = urllib.parse.quote(topic)
        url = (
            f"https://hn.algolia.com/api/v1/search"
            f"?query={q}&tags=story&hitsPerPage={n}&numericFilters=created_at_i>0"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Lighthouse/2.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())

        for hit in data.get("hits", []):
            story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            ts_unix = hit.get("created_at_i", 0)
            ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat() if ts_unix else datetime.now(tz=timezone.utc).isoformat()
            title = hit.get("title") or ""
            points = hit.get("points") or 0
            num_comments = hit.get("num_comments") or 0
            content = (
                f"{title}\n\n"
                f"Points: {points} | Comments: {num_comments}\n"
                f"{hit.get('story_text') or ''}"
            ).strip()[:4000]

            signals.append(Signal(
                id=_make_id(story_url, ts),
                title=_clean_title(title, content),
                content=content,
                source="hacker_news",
                url=story_url,
                timestamp=ts,
                client_tag=client_tag,
                raw_meta={
                    "points": points,
                    "num_comments": num_comments,
                    "author": hit.get("author"),
                },
            ))
    except Exception as exc:
        if callback:
            callback(f"[Hacker News] Error: {exc}")

    if callback:
        callback(f"[Hacker News] ✓ {len(signals)} signals")
    return signals


# ── YouTube Trending (needs YOUTUBE_API_KEY) ──────────────────────────────────

def _fetch_youtube_transcript(video_id: str, max_chars: int = 1400) -> str:
    """Return an excerpt of a video's captions, or "" if unavailable.

    A YouTube search result only gives us a title and a truncated description,
    which says little about what was actually said. Captions carry the real
    content. Uses youtube-transcript-api (already a dependency, no key, no cost).

    Fails silently by design — plenty of videos have captions disabled, and
    YouTube also throttles caption requests from datacenter IPs, so this has to
    be a bonus rather than something the pipeline depends on.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return ""
    try:
        api = YouTubeTranscriptApi()
        # prefer English, fall back to whatever the video actually has
        try:
            fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        except Exception:
            fetched = api.fetch(video_id)
        parts = []
        for seg in fetched:
            txt = getattr(seg, "text", None) or (seg.get("text") if isinstance(seg, dict) else "")
            if txt:
                parts.append(str(txt).replace("\n", " ").strip())
        text = " ".join(p for p in parts if p)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\[(Music|Applause|Laughter|Áudio|Music)\]", "", text, flags=re.I).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        return text
    except Exception:
        return ""


def scrape_youtube(
    topic: str,
    api_key: str,
    n: int = 15,
    region_code: str = "US",
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
    with_transcripts: bool = True,
    transcript_limit: int = 6,
) -> list[Signal]:
    """
    Search YouTube for videos related to the topic.
    Uses YouTube Data API v3 (free, 10k units/day quota).
    Get key at: console.cloud.google.com → APIs → YouTube Data API v3

    When `with_transcripts` is on, the first `transcript_limit` results are
    enriched with a caption excerpt — far richer signal than the description
    alone, at no API cost. Videos without captions simply keep their metadata.
    """
    if not api_key:
        return []
    if callback:
        callback(f"[YouTube] Searching '{topic[:40]}' (region={region_code})…")
    signals: list[Signal] = []
    n_transcripts = 0          # defined up front: the closing callback reads it
                               # even when the request itself blew up

    try:
        q = urllib.parse.quote(topic)
        url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={q}&type=video&maxResults={n}"
            f"&regionCode={region_code}&relevanceLanguage=en"
            f"&order=viewCount&key={api_key}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Lighthouse/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        # VIEW COUNTS, IN ONE EXTRA CALL.
        # search only returns snippets, so every YouTube signal arrived with no
        # engagement at all — which meant a kids' channel and a video with
        # millions of views were indistinguishable to anything downstream.
        # videos?part=statistics takes up to 50 ids at once and costs 1 quota
        # unit against search's 100, so this is close to free.
        _ids = [it.get("id", {}).get("videoId", "") for it in data.get("items", [])]
        _ids = [i for i in _ids if i]
        _stats: dict = {}
        if _ids:
            try:
                surl = (f"https://www.googleapis.com/youtube/v3/videos"
                        f"?part=statistics&id={','.join(_ids[:50])}&key={api_key}")
                sreq = urllib.request.Request(surl, headers={"User-Agent": "Lighthouse/2.0"})
                with urllib.request.urlopen(sreq, timeout=15) as sresp:
                    for v in json.loads(sresp.read()).get("items", []):
                        st = v.get("statistics", {}) or {}
                        _stats[v.get("id", "")] = {
                            "views": int(st.get("viewCount", 0) or 0),
                            "likes": int(st.get("likeCount", 0) or 0),
                            "comments": int(st.get("commentCount", 0) or 0),
                        }
            except Exception as _sexc:
                if callback:
                    callback(f"[YouTube] statistics unavailable: {_sexc}")

        for idx, item in enumerate(data.get("items", [])):
            vid_id = item.get("id", {}).get("videoId", "")
            if not vid_id:
                continue
            snippet = item.get("snippet", {})
            vid_url = f"https://www.youtube.com/watch?v={vid_id}"
            ts = snippet.get("publishedAt") or datetime.now(tz=timezone.utc).isoformat()
            title = snippet.get("title") or ""
            description = snippet.get("description") or ""
            content = f"{title}\n\n{description}".strip()

            # Captions for the first few results only — each one is an extra
            # round trip, and the top hits are the ones worth transcribing.
            transcript = ""
            if with_transcripts and idx < transcript_limit:
                if callback:
                    callback(f"[YouTube] Reading captions {idx + 1}/{transcript_limit}…")
                transcript = _fetch_youtube_transcript(vid_id)
                if transcript:
                    n_transcripts += 1
                    content += f"\n\nTRANSCRIPT: {transcript}"
            content = content.strip()[:4000]

            signals.append(Signal(
                id=_make_id(vid_url, ts),
                title=_clean_title(title, content),
                content=content,
                source="youtube",
                url=vid_url,
                timestamp=ts,
                client_tag=client_tag,
                raw_meta={
                    **_stats.get(vid_id, {}),
                    "channel": snippet.get("channelTitle"),
                    "region": region_code,
                    "has_transcript": bool(transcript),
                    "thumbnail": (
                        snippet.get("thumbnails", {}).get("medium", {}).get("url")
                        or snippet.get("thumbnails", {}).get("default", {}).get("url")
                        or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
                    ),
                },
            ))
    except Exception as exc:
        if callback:
            callback(f"[YouTube] Error: {exc}")

    if callback:
        extra = f" ({n_transcripts} with captions)" if with_transcripts and signals else ""
        callback(f"[YouTube] ✓ {len(signals)} signals{extra}")
    return signals


# ── Web (Firecrawl) — general web search + full page extraction ───────────────

def scrape_web(
    query: str,
    api_key: str,
    n: int = 10,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """General web search via Firecrawl.
    Returns titles, URLs and full page markdown — ideal for competitive
    research and topics not covered by platform-specific scrapers.
    Requires FIRECRAWL_API_KEY (free tier available at firecrawl.dev).
    """
    if not api_key:
        return []
    if callback:
        callback(f"[Web] Searching '{query[:50]}' via Firecrawl…")
    signals: list[Signal] = []
    try:
        from firecrawl import Firecrawl
        fc = Firecrawl(api_key=api_key)
        # THE SDK MOVED AND TOOK THE METHOD WITH IT.
        # This called fc.search(...) directly. In firecrawl-py 4.x the Firecrawl
        # class is a thin shell — search, scrape and the rest live on .v2, and
        # the only methods left on the top-level object are the academic-paper
        # ones. So the call raised AttributeError, the except below swallowed
        # it, and every scan reported "web 0" as though the web simply had
        # nothing to say. requirements.txt pins no version, so the upgrade
        # arrived on its own.
        _search = getattr(getattr(fc, "v2", None), "search", None) or getattr(fc, "search", None)
        if _search is None:
            raise RuntimeError("this firecrawl-py exposes no search method")
        results = _search(query, limit=n)

        # v2 answers with typed objects, v1 with dicts. Normalise both.
        def _get(o, *names, default=None):
            for nm in names:
                if isinstance(o, dict):
                    if o.get(nm) not in (None, ""):
                        return o[nm]
                else:
                    v = getattr(o, nm, None)
                    if v not in (None, ""):
                        return v
            return default

        pages = _get(results, "web", "data", default=None)
        if pages is None:
            pages = results if isinstance(results, list) else []
        for page in pages:
            url = _get(page, "url", "sourceURL", default="")
            if not url:
                continue
            meta    = _get(page, "metadata", default={}) or {}
            title   = _get(page, "title", default="") or _get(meta, "title", default="")
            content = (_get(page, "markdown", "content", "description", default="")
                       or _get(meta, "description", default=""))
            # Prefer og:image for thumbnail, fall back to screenshot
            thumbnail = (_get(meta, "og_image", "ogImage", default="")
                         or _get(page, "screenshot", default=""))
            ts = (_get(meta, "publishedTime", "modifiedTime", default="")
                  or datetime.now(tz=timezone.utc).isoformat())
            signals.append(Signal(
                id=_make_id(url, str(ts)),
                title=_clean_title(title, content),
                content=content[:4000], source="web",
                url=url, timestamp=str(ts), client_tag=client_tag,
                raw_meta={"thumbnail": thumbnail},
            ))
    except Exception as exc:
        if callback:
            callback(f"[Web] Error: {exc}")
        raise            # the caller's tally reports it; silence read as "no results"
    if callback:
        callback(f"[Web] ✓ {len(signals)} signals")
    return signals


# ══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION
# ══════════════════════════════════════════════════════════════════════════════

def _deduplicate(signals: list[Signal]) -> list[Signal]:
    """Remove duplicates by id, then by URL."""
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    out: list[Signal] = []
    for s in signals:
        if s.id in seen_ids or (s.url and s.url in seen_urls):
            continue
        seen_ids.add(s.id)
        if s.url:
            seen_urls.add(s.url)
        out.append(s)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════════════════

def _save_signals(signals: list[Signal], callback: Optional[Callable] = None):
    """Save to Supabase (primary) + jsonl file (backup)."""
    dicts = [asdict(s) for s in signals]

    # ── Supabase ──
    try:
        import db
        if db.use_supabase():
            db.bulk_save_signals(dicts)
            if callback:
                callback(f"[DB] ✓ {len(dicts)} signals saved to Supabase")
        else:
            if callback:
                callback("[DB] Supabase not configured — using file fallback")
    except Exception as exc:
        if callback:
            callback(f"[DB] Supabase error: {exc}")

    # ── jsonl file backup ──
    try:
        os.makedirs("data", exist_ok=True)
        with open("data/signals.jsonl", "a") as f:
            for d in dicts:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        if callback:
            callback(f"[File] ✓ {len(dicts)} signals appended to data/signals.jsonl")
    except Exception as exc:
        if callback:
            callback(f"[File] Write error: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def run_ingestion(
    topic: str,
    client_tag: Optional[str] = None,
    limit: int = 80,
    use_reddit: bool = True,
    use_rss: bool = True,
    use_gdelt: bool = True,
    use_exa: bool = True,
    use_google_trends: bool = True,
    use_hacker_news: bool = True,
    use_youtube: bool = False,
    use_tiktok: bool = False,
    use_instagram: bool = False,
    use_twitter: bool = False,
    tiktok_comments: bool = True,   # enrich TikTok signals with top comments
    trends_geo: str = "",           # "" = worldwide, "GB", "US", "BR", etc.
    youtube_region: str = "US",
    extra_subreddits: Optional[list[str]] = None,
    extra_rss_feeds: Optional[list[tuple[str, str]]] = None,
    callback: Optional[Callable] = None,
) -> dict:
    """
    Run a full ingestion sweep for a topic.

    Returns:
        {"total": int, "by_source": {"reddit": int, ...}, "signals": [Signal, ...]}
    """
    if callback:
        callback(f"🗼 Starting ingestion sweep for: '{topic}'")
        callback(f"   Client tag: {client_tag or 'none'}")

    all_signals: list[Signal] = []
    counts: dict[str, int] = {}

    exa_key     = os.environ.get("EXA_API_KEY", "")
    youtube_key = os.environ.get("YOUTUBE_API_KEY", "")
    apify_key   = os.environ.get("APIFY_API_TOKEN", "")

    if use_reddit:
        subs = (extra_subreddits or []) + _DEFAULT_SUBREDDITS
        r = scrape_reddit(topic, subreddits=subs[:12], max_items=25,
                          client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["reddit"] = len(r)

    if use_rss:
        feeds = (extra_rss_feeds or []) + _DEFAULT_RSS_FEEDS
        r = scrape_rss(feeds=feeds, max_items_per_feed=5,
                       client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["rss"] = len(r)

    if use_gdelt:
        r = scrape_gdelt(topic, n=20, client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["gdelt"] = len(r)

    if use_google_trends:
        r = scrape_google_trends(topic, geo=trends_geo,
                                 client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["google_trends"] = len(r)

    if use_hacker_news:
        r = scrape_hacker_news(topic, n=15, client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["hacker_news"] = len(r)

    if use_exa and exa_key:
        r = scrape_exa(topic, api_key=exa_key, n=15,
                       client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["exa"] = len(r)

    if use_youtube and youtube_key:
        # Split topic by comma and search each term individually
        # (YouTube API doesn't handle comma-separated multi-topic strings well)
        _yt_terms = [t.strip() for t in topic.split(",") if t.strip()][:3]
        _yt_seen_ids: set = set()
        _yt_count = 0
        for _yt_term in _yt_terms:
            for sig in scrape_youtube(_yt_term, api_key=youtube_key, n=10,
                                      region_code=youtube_region,
                                      client_tag=client_tag, callback=callback):
                if sig.id not in _yt_seen_ids:
                    _yt_seen_ids.add(sig.id)
                    all_signals.append(sig)
                    _yt_count += 1
        counts["youtube"] = _yt_count

    if use_tiktok and apify_key:
        r = scrape_tiktok(topic, api_token=apify_key, n=20,
                          fetch_comments=tiktok_comments,
                          client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["tiktok"] = len(r)

    if use_instagram and apify_key:
        r = scrape_instagram(topic, api_token=apify_key, n=20,
                             client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["instagram"] = len(r)

    if use_twitter and apify_key:
        # Use first term only — long comma-separated strings return noResults on Twitter
        _tw_term = topic.split(",")[0].strip()
        r = scrape_twitter(_tw_term, api_token=apify_key, n=20,
                           client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["twitter"] = len(r)

    # Deduplicate and limit
    all_signals = _deduplicate(all_signals)[:limit]

    if callback:
        callback(f"\n✅ {len(all_signals)} unique signals after dedup")

    # Save
    _save_signals(all_signals, callback=callback)

    return {
        "total": len(all_signals),
        "by_source": counts,
        "signals": all_signals,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Lighthouse Signal Ingestion")
    parser.add_argument("--topic",  required=True, help="Topic / focus brief to search")
    parser.add_argument("--client", default="",    help="Client tag (e.g. 'Heinz_UK')")
    parser.add_argument("--limit",  type=int, default=80, help="Max signals to save")
    parser.add_argument("--no-reddit",        action="store_true")
    parser.add_argument("--no-rss",           action="store_true")
    parser.add_argument("--no-gdelt",         action="store_true")
    parser.add_argument("--no-exa",           action="store_true")
    parser.add_argument("--no-trends",        action="store_true")
    parser.add_argument("--no-hn",            action="store_true")
    parser.add_argument("--youtube",          action="store_true", help="Enable YouTube (needs YOUTUBE_API_KEY)")
    parser.add_argument("--geo",              default="",  help="Google Trends geo (e.g. GB, US). Default=worldwide")
    parser.add_argument("--youtube-region",   default="US")
    args = parser.parse_args()

    result = run_ingestion(
        topic=args.topic,
        client_tag=args.client or None,
        limit=args.limit,
        use_reddit=not args.no_reddit,
        use_rss=not args.no_rss,
        use_gdelt=not args.no_gdelt,
        use_exa=not args.no_exa,
        use_google_trends=not args.no_trends,
        use_hacker_news=not args.no_hn,
        use_youtube=args.youtube,
        trends_geo=args.geo,
        youtube_region=args.youtube_region,
        callback=print,
    )

    print(f"\n── Summary ──")
    for src, cnt in result["by_source"].items():
        print(f"  {src:10s}: {cnt} signals")
    print(f"  {'total':10s}: {result['total']} signals saved")
