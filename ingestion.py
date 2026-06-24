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


def scrape_reddit(
    topic: str,
    subreddits: Optional[list[str]] = None,
    max_items: int = 30,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """Search Reddit for topic across relevant subreddits. No API key needed."""
    subs = subreddits or _DEFAULT_SUBREDDITS
    headers = {"User-Agent": "Lighthouse-Countercurrent/2.0"}
    signals: list[Signal] = []
    seen: set[str] = set()

    if callback:
        callback(f"[Reddit] Searching {len(subs)} subreddits for '{topic[:40]}'…")

    # Also search r/all for broader coverage
    search_targets = subs[:8] + ["all"]

    for sub in search_targets:
        try:
            q = urllib.parse.quote(topic)
            url = f"https://www.reddit.com/r/{sub}/search.json?q={q}&sort=hot&limit={max_items}&restrict_sr={'1' if sub != 'all' else '0'}&t=month"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read())
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
        except Exception as exc:
            if callback:
                callback(f"[Reddit] r/{sub}: {exc}")

    if callback:
        callback(f"[Reddit] ✓ {len(signals)} signals")
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
) -> list[Signal]:
    """Read RSS / Atom feeds. Uses a curated set of cultural / trade sources."""
    feed_list = feeds or _DEFAULT_RSS_FEEDS
    signals: list[Signal] = []

    if callback:
        callback(f"[RSS] Reading {len(feed_list)} feeds…")

    for feed_url, feed_name in feed_list:
        try:
            req = urllib.request.Request(
                feed_url, headers={"User-Agent": "Lighthouse-Countercurrent/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
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

def scrape_gdelt(
    topic: str,
    n: int = 20,
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """Query GDELT Doc 2.0 API for news articles related to the topic."""
    if callback:
        callback(f"[GDELT] Querying '{topic[:40]}'…")
    signals: list[Signal] = []
    try:
        q = urllib.parse.quote(topic)
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={q}&mode=artlist&maxrecords={n}&format=json&timespan=2weeks"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Lighthouse/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
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
    if callback:
        callback(f"[GDELT] ✓ {len(signals)} signals")
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

def scrape_youtube(
    topic: str,
    api_key: str,
    n: int = 15,
    region_code: str = "US",
    client_tag: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> list[Signal]:
    """
    Search YouTube for videos related to the topic.
    Uses YouTube Data API v3 (free, 10k units/day quota).
    Get key at: console.cloud.google.com → APIs → YouTube Data API v3
    """
    if not api_key:
        return []
    if callback:
        callback(f"[YouTube] Searching '{topic[:40]}' (region={region_code})…")
    signals: list[Signal] = []

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

        for item in data.get("items", []):
            vid_id = item.get("id", {}).get("videoId", "")
            if not vid_id:
                continue
            snippet = item.get("snippet", {})
            vid_url = f"https://www.youtube.com/watch?v={vid_id}"
            ts = snippet.get("publishedAt") or datetime.now(tz=timezone.utc).isoformat()
            title = snippet.get("title") or ""
            description = snippet.get("description") or ""
            content = f"{title}\n\n{description}".strip()[:4000]

            signals.append(Signal(
                id=_make_id(vid_url, ts),
                title=_clean_title(title, content),
                content=content,
                source="youtube",
                url=vid_url,
                timestamp=ts,
                client_tag=client_tag,
                raw_meta={
                    "channel": snippet.get("channelTitle"),
                    "region": region_code,
                },
            ))
    except Exception as exc:
        if callback:
            callback(f"[YouTube] Error: {exc}")

    if callback:
        callback(f"[YouTube] ✓ {len(signals)} signals")
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
        r = scrape_youtube(topic, api_key=youtube_key, n=15,
                           region_code=youtube_region,
                           client_tag=client_tag, callback=callback)
        all_signals.extend(r)
        counts["youtube"] = len(r)

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
