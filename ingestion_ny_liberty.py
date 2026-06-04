"""
Countercurrent.ai — Ingestion: NY Liberty x Pinterest
Arquivo completo e independente — roda sozinho sem precisar do ingestion.py.
Salva no mesmo signals.jsonl com client_tag="NY_Liberty_Pinterest"
"""

import os
import json
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, asdict

from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

# ── Schema ────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    id: str
    title: str
    content: str
    source: str
    url: str
    timestamp: str
    category: Optional[str]
    client_tag: Optional[str]
    raw_meta: dict


def _make_id(url: str, timestamp: str) -> str:
    return hashlib.sha256(f"{url}{timestamp}".encode()).hexdigest()[:16]


def _clean_title(raw: str, fallback_content: str = "", max_len: int = 120) -> str:
    if raw and raw.strip() and raw.strip().lower() not in ["none", "null", "(no title)"]:
        return raw.strip()[:max_len]
    for line in fallback_content.splitlines():
        line = line.strip()
        if len(line) > 15:
            return line[:max_len]
    return "(no title)"


# ── Web ───────────────────────────────────────────────────────────────────────

def scrape_web(start_urls, max_pages_per_url=2, client_tag=None):
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise EnvironmentError("APIFY_API_TOKEN não encontrado no .env")
    print(f"[Web] Crawling {len(start_urls)} site(s)...")
    client = ApifyClient(token)
    run_input = {
        "startUrls": [{"url": u} for u in start_urls],
        "maxCrawlPages": max_pages_per_url * len(start_urls),
        "crawlerType": "playwright:firefox",
        "removeElementsCssSelector": "nav, footer, header, .ads, .sidebar",
    }
    run = client.actor("apify/website-content-crawler").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    signals = []
    for item in items:
        ts = item.get("loadedTime") or datetime.now(tz=timezone.utc).isoformat()
        url = item.get("url", "")
        raw_content = item.get("text") or item.get("markdown") or ""
        raw_title = item.get("title") or item.get("og:title") or ""
        signals.append(Signal(
            id=_make_id(url, ts),
            title=_clean_title(raw_title, raw_content),
            content=raw_content[:6000],
            source="web", url=url, timestamp=ts,
            category=None, client_tag=client_tag,
            raw_meta={"domain": item.get("domain")},
        ))
    print(f"[Web] ✓ {len(signals)} signals")
    return signals


# ── Reddit ────────────────────────────────────────────────────────────────────

def scrape_reddit(subreddits, search_terms, max_items=25, client_tag=None):
    print(f"[Reddit] Buscando em {subreddits}...")
    headers = {"User-Agent": "Countercurrent/1.0"}
    signals = []
    seen = set()
    for sub in subreddits:
        for term in search_terms:
            query = urllib.parse.quote(term)
            api_url = f"https://www.reddit.com/r/{sub}/search.json?q={query}&sort=hot&limit={max_items}&restrict_sr=1"
            try:
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    p = post.get("data", {})
                    url = f"https://reddit.com{p.get('permalink', '')}"
                    if url in seen:
                        continue
                    seen.add(url)
                    ts = datetime.fromtimestamp(
                        p.get("created_utc", datetime.now().timestamp()), tz=timezone.utc
                    ).isoformat()
                    body = p.get("selftext") or ""
                    content = f"{p.get('title','')}\n\n{body}".strip()
                    signals.append(Signal(
                        id=_make_id(url, ts),
                        title=_clean_title(p.get("title", ""), content),
                        content=content[:4000], source="reddit",
                        url=url, timestamp=ts, category=None,
                        client_tag=client_tag,
                        raw_meta={"subreddit": p.get("subreddit"), "score": p.get("score")},
                    ))
            except Exception as e:
                print(f"[Reddit] Erro em r/{sub} '{term}': {e}")
    print(f"[Reddit] ✓ {len(signals)} signals")
    return signals


# ── RSS ───────────────────────────────────────────────────────────────────────

def scrape_rss(feeds=None, max_items_per_feed=5, client_tag=None):
    print(f"[RSS] Lendo {len(feeds)} feeds...")
    signals = []
    import re
    for feed_url, feed_name in feeds:
        try:
            req = urllib.request.Request(
                feed_url, headers={"User-Agent": "Countercurrent/1.0 RSS Reader"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            is_atom = root.tag == "{http://www.w3.org/2005/Atom}feed"
            if is_atom:
                entries = root.findall("atom:entry", ns)[:max_items_per_feed]
                for entry in entries:
                    title = entry.findtext("atom:title", "", ns).strip()
                    link = entry.find("atom:link", ns)
                    url = link.get("href", "") if link is not None else ""
                    summary = entry.findtext("atom:summary", "", ns).strip()
                    content_el = entry.find("atom:content", ns)
                    content = (content_el.text or summary if content_el is not None else summary)[:4000]
                    ts = entry.findtext("atom:updated", "", ns) or datetime.now(tz=timezone.utc).isoformat()
                    signals.append(Signal(
                        id=_make_id(url, ts), title=_clean_title(title, content),
                        content=content, source="rss", url=url, timestamp=ts,
                        category=None, client_tag=client_tag,
                        raw_meta={"feed_name": feed_name},
                    ))
            else:
                channel = root.find("channel")
                if channel is None:
                    continue
                for item in channel.findall("item")[:max_items_per_feed]:
                    title = (item.findtext("title") or "").strip()
                    url = item.findtext("link") or item.findtext("guid") or ""
                    desc = item.findtext("description") or ""
                    content = re.sub(r"<[^>]+>", "", desc).strip()[:4000]
                    ts_raw = item.findtext("pubDate") or ""
                    try:
                        from email.utils import parsedate_to_datetime
                        ts = parsedate_to_datetime(ts_raw).isoformat()
                    except Exception:
                        ts = datetime.now(tz=timezone.utc).isoformat()
                    signals.append(Signal(
                        id=_make_id(url, ts), title=_clean_title(title, content),
                        content=content, source="rss", url=url, timestamp=ts,
                        category=None, client_tag=client_tag,
                        raw_meta={"feed_name": feed_name},
                    ))
        except Exception as e:
            print(f"[RSS] Erro em '{feed_name}': {e}")
    print(f"[RSS] ✓ {len(signals)} signals")
    return signals


# ── TikTok ────────────────────────────────────────────────────────────────────

def scrape_tiktok(hashtags, max_items=15, client_tag=None):
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise EnvironmentError("APIFY_API_TOKEN não encontrado no .env")
    print(f"[TikTok] Scraping: {hashtags}")
    client = ApifyClient(token)
    signals = []
    for tag in hashtags:
        try:
            run = client.actor("clockworks/free-tiktok-scraper").call(
                run_input={"hashtags": [tag.lstrip("#")], "resultsPerPage": max_items}
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            for item in items:
                ts = item.get("createTimeISO") or datetime.now(tz=timezone.utc).isoformat()
                url = item.get("webVideoUrl") or item.get("videoUrl") or ""
                text = item.get("text") or item.get("desc") or ""
                signals.append(Signal(
                    id=_make_id(url, ts), title=_clean_title("", text),
                    content=text[:2000], source="tiktok", url=url, timestamp=ts,
                    category=None, client_tag=client_tag,
                    raw_meta={"author": item.get("authorMeta", {}).get("name"), "hashtag": tag},
                ))
        except Exception as e:
            print(f"[TikTok] Erro em #{tag}: {e}")
    print(f"[TikTok] ✓ {len(signals)} signals")
    return signals


# ── YouTube ───────────────────────────────────────────────────────────────────

def scrape_youtube(search_terms, max_items=10, client_tag=None):
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise EnvironmentError("APIFY_API_TOKEN não encontrado no .env")
    print(f"[YouTube] Scraping: {search_terms}")
    client = ApifyClient(token)
    try:
        run = client.actor("apify/youtube-scraper").call(
            run_input={"searchKeywords": search_terms, "maxResults": max_items, "maxComments": 3}
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        print(f"[YouTube] Erro: {e}")
        return []
    signals = []
    for item in items:
        ts = item.get("date") or datetime.now(tz=timezone.utc).isoformat()
        url = item.get("url") or ""
        description = item.get("description") or ""
        comments = item.get("comments") or []
        comments_text = "\n".join(c.get("text", "") for c in comments[:3] if c.get("text"))
        content = f"{description}\n\n{comments_text}".strip()
        signals.append(Signal(
            id=_make_id(url, ts),
            title=_clean_title(item.get("title") or "", content),
            content=content[:5000], source="youtube", url=url, timestamp=ts,
            category=None, client_tag=client_tag,
            raw_meta={"channel": item.get("channelName"), "views": item.get("viewCount")},
        ))
    print(f"[YouTube] ✓ {len(signals)} signals")
    return signals


# ── Orchestrator ──────────────────────────────────────────────────────────────

class IngestionOrchestrator:

    def __init__(self, output_path="data/signals.jsonl"):
        self.output_path = output_path
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def _load_existing_ids(self):
        ids = set()
        if os.path.exists(self.output_path):
            with open(self.output_path) as f:
                for line in f:
                    try:
                        ids.add(json.loads(line)["id"])
                    except Exception:
                        pass
        return ids

    def _save_signals(self, signals):
        existing = self._load_existing_ids()
        new_signals = [s for s in signals if s.id not in existing]
        with open(self.output_path, "a") as f:
            for sig in new_signals:
                f.write(json.dumps(asdict(sig), ensure_ascii=False) + "\n")
        print(f"[Save] {len(new_signals)} novos / {len(signals) - len(new_signals)} duplicados ignorados")
        return len(new_signals)

    def run(self, web_config=None, reddit_config=None, rss_config=None,
            tiktok_config=None, youtube_config=None, client_tag=None):
        all_signals = []
        if rss_config:
            all_signals += scrape_rss(**rss_config, client_tag=client_tag)
        if reddit_config:
            all_signals += scrape_reddit(**reddit_config, client_tag=client_tag)
        if web_config:
            all_signals += scrape_web(**web_config, client_tag=client_tag)
        if tiktok_config:
            all_signals += scrape_tiktok(**tiktok_config, client_tag=client_tag)
        if youtube_config:
            all_signals += scrape_youtube(**youtube_config, client_tag=client_tag)
        total = self._save_signals(all_signals)
        print(f"\n✅ Ingestão completa — {total} novos signals em {self.output_path}")
        return all_signals


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    orchestrator = IngestionOrchestrator(output_path="data/signals.jsonl")

    orchestrator.run(

        # RSS — Cultura, moda e esporte feminino
        rss_config={
            "max_items_per_feed": 5,
            "feeds": [
                ("https://www.espn.com/espn/rss/wnba/news",       "ESPN WNBA"),
                ("https://www.si.com/rss/si_wnba.rss",            "Sports Illustrated WNBA"),
                ("https://www.vogue.com/feed/rss",                 "Vogue"),
                ("https://www.harpersbazaar.com/rss/all.xml/",     "Harper's Bazaar"),
                ("https://hypebeast.com/feed",                     "Hypebeast"),
                ("https://hypebae.com/feed",                       "Hypebae"),
                ("https://www.dazeddigital.com/rss",               "Dazed"),
                ("https://www.thefader.com/rss",                   "The Fader"),
                ("https://pitchfork.com/rss/news/",                "Pitchfork"),
                ("https://www.adweek.com/feed/",                   "Adweek"),
                ("https://www.marketingdive.com/feeds/news",       "Marketing Dive"),
            ],
        },

        # Reddit — Comunidade, moda e cultura esportiva
        reddit_config={
            "subreddits": [
                "NYLiberty", "wnba", "womenssports", "sportsmarketing",
                "sportsbusiness", "femalefashionadvice",
                "streetwear", "sneakers",
            ],
            "search_terms": [
                "Liberty Loud", "Ellie the Elephant", "NY Liberty fan culture",
                "Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones",
                "WNBA fashion", "WNBA tunnel walk", "WNBA style",
                "fan experience", "women sports culture",
            ],
            "max_items": 25,
        },

        # Web — Notícias e editorial
        web_config={
            "start_urls": [
                "https://liberty.wnba.com/news/",
                "https://www.espn.com/wnba/team/_/name/ny/new-york-liberty",
                "https://hypebae.com",
            ],
            "max_pages_per_url": 2,
        },

        # TikTok — Cultura visual, tunnel walk e fandom
        tiktok_config={
            "hashtags": [
                "#nyliberty", "#wnba", "#wnba2026",
                "#wnbafashion", "#wnbatunnelwalk", "#wnbastyle",
                "#ellietheelephant", "#libertyloud",
                "#womeninsports", "#nycstyle",
            ],
            "max_items": 15,
        },

        # YouTube — Análises, vlogs e cultura visual
        youtube_config={
            "search_terms": [
                "New York Liberty fan culture 2026",
                "New York Liberty tunnel walk outfits",
                "WNBA fashion style 2026",
                "Sabrina Ionescu style",
                "WNBA brand partnerships",
            ],
            "max_items": 10,
        },

        client_tag="NY_Liberty_Pinterest",
    )
