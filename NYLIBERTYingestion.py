"""
Countercurrent.ai — Layer 1: Ingestion Hub

Sources and approach:
  Web      → Apify website-content-crawler (free, official)
  Reddit   → Reddit API oficial (100% gratuito, sem Apify)
  RSS      → Feeds de blogs/publicações (gratuito, sem Apify)
  TikTok   → Apify clockworks/free-tiktok-scraper (pay-per-result, cabe no free)
  YouTube  → Apify apify/youtube-scraper (free, official)

  Twitter/X   → PENDENTE (requer plano pago Apify — ativar quando pronto)
  Instagram   → PENDENTE (instável no free — ativar quando pronto)
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
    """Return a clean title, falling back to first line of content."""
    if raw and raw.strip() and raw.strip().lower() not in ["none", "null", "(no title)"]:
        return raw.strip()[:max_len]
    for line in fallback_content.splitlines():
        line = line.strip()
        if len(line) > 15:
            return line[:max_len]
    return "(no title)"


# ══════════════════════════════════════════════════════════════════════════════
# FREE SOURCES (sem custo adicional além dos $5/mês do Apify)
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. Web Crawler (Apify — oficial e gratuito) ───────────────────────────────

def scrape_web(
    start_urls: list[str],
    max_pages_per_url: int = 2,
    client_tag: Optional[str] = None,
) -> list[Signal]:
    """
    Apify website-content-crawler — oficial, gratuito, usa compute units do free plan.
    """
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise EnvironmentError("APIFY_API_TOKEN não encontrado no .env")

    print(f"[Web] Crawling {len(start_urls)} site(s)...")
    client = ApifyClient(token)

    run_input = {
        "startUrls": [{"url": u} for u in start_urls],
        "maxCrawlPages": max_pages_per_url * len(start_urls),
        "crawlerType": "playwright:firefox",
        "removeElementsCssSelector": "nav, footer, header, .ads, .sidebar, .cookie-banner",
    }

    run   = client.actor("apify/website-content-crawler").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

    signals = []
    for item in items:
        ts          = item.get("loadedTime") or datetime.now(tz=timezone.utc).isoformat()
        url         = item.get("url", "")
        raw_content = item.get("text") or item.get("markdown") or ""
        raw_title   = (
            item.get("title")
            or item.get("og:title")
            or item.get("metadata", {}).get("title", "")
        )
        signals.append(Signal(
            id=_make_id(url, ts),
            title=_clean_title(raw_title, raw_content),
            content=raw_content[:6000],
            source="web",
            url=url,
            timestamp=ts,
            category=None,
            client_tag=client_tag,
            raw_meta={"domain": item.get("domain")},
        ))

    print(f"[Web] ✓ {len(signals)} signals")
    return signals


# ── 2. Reddit API Oficial (100% gratuito, sem Apify) ─────────────────────────

def scrape_reddit(
    subreddits: list[str],
    search_terms: list[str],
    max_items: int = 25,
    client_tag: Optional[str] = None,
) -> list[Signal]:
    """
    Usa a API JSON pública do Reddit — sem autenticação, sem custo.
    Busca posts por termo dentro de cada subreddit.
    """
    print(f"[Reddit] Buscando em {subreddits}...")

    headers = {"User-Agent": "Countercurrent/1.0 (cultural intelligence tool)"}
    signals = []
    seen    = set()

    for sub in subreddits:
        for term in search_terms:
            query    = urllib.parse.quote(term)
            api_url  = f"https://www.reddit.com/r/{sub}/search.json?q={query}&sort=hot&limit={max_items}&restrict_sr=1"

            try:
                req  = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())

                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    p   = post.get("data", {})
                    url = f"https://reddit.com{p.get('permalink', '')}"

                    if url in seen:
                        continue
                    seen.add(url)

                    ts      = datetime.fromtimestamp(
                        p.get("created_utc", datetime.now().timestamp()),
                        tz=timezone.utc
                    ).isoformat()
                    body    = p.get("selftext") or ""
                    content = f"{p.get('title','')}\n\n{body}".strip()

                    signals.append(Signal(
                        id=_make_id(url, ts),
                        title=_clean_title(p.get("title", ""), content),
                        content=content[:4000],
                        source="reddit",
                        url=url,
                        timestamp=ts,
                        category=None,
                        client_tag=client_tag,
                        raw_meta={
                            "subreddit":    p.get("subreddit"),
                            "score":        p.get("score"),
                            "num_comments": p.get("num_comments"),
                            "author":       p.get("author"),
                        },
                    ))

            except Exception as e:
                print(f"[Reddit] Erro em r/{sub} '{term}': {e}")
                continue

    print(f"[Reddit] ✓ {len(signals)} signals")
    return signals


# ── 3. RSS Feeds (100% gratuito, sem dependência de Apify) ───────────────────

# Feeds curados para agência de publicidade / cultura / tendências
DEFAULT_RSS_FEEDS = [
    # Publicidade e criatividade — URLs verificadas 2026
    ("https://campaignlive.co.uk/rss/latest",                   "Campaign Live"),
    ("https://www.adweek.com/feed/",                            "Adweek"),
    ("https://www.thedrum.com/feed",                            "The Drum"),
    ("https://www.marketingdive.com/feeds/news",                "Marketing Dive"),
    ("https://www.creativereview.co.uk/feed/",                  "Creative Review"),
    ("https://wearesocial.com/feed/",                           "We Are Social"),
    # Tendências e cultura
    ("https://www.dazeddigital.com/rss",                        "Dazed"),
    ("https://www.wired.com/feed/rss",                          "Wired"),
    ("https://hypebeast.com/feed",                              "Hypebeast"),
    ("https://www.fastcompany.com/feed",                        "Fast Company"),
    # Estratégia
    ("https://hbr.org/topic/subject/marketing.rss",             "HBR Marketing"),
    ("https://marketingaiinstitute.com/blog/rss.xml",           "Marketing AI Institute"),
    # Cultura pop
    ("https://pitchfork.com/rss/news/",                         "Pitchfork"),
    ("https://www.nme.com/feed",                                "NME"),
]

def scrape_rss(
    feeds: Optional[list[tuple[str, str]]] = None,
    max_items_per_feed: int = 5,
    client_tag: Optional[str] = None,
) -> list[Signal]:
    """
    Lê RSS/Atom feeds e normaliza para Signal.
    Completamente gratuito — zero dependências externas além do Python padrão.
    """
    feeds = feeds or DEFAULT_RSS_FEEDS
    print(f"[RSS] Lendo {len(feeds)} feeds...")

    signals = []

    for feed_url, feed_name in feeds:
        try:
            req  = urllib.request.Request(
                feed_url,
                headers={"User-Agent": "Countercurrent/1.0 RSS Reader"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()

            root = ET.fromstring(raw)

            # Suporte a RSS e Atom
            ns      = {"atom": "http://www.w3.org/2005/Atom"}
            is_atom = root.tag == "{http://www.w3.org/2005/Atom}feed"

            if is_atom:
                entries = root.findall("atom:entry", ns)[:max_items_per_feed]
                for entry in entries:
                    title   = entry.findtext("atom:title", "", ns).strip()
                    url     = ""
                    link    = entry.find("atom:link", ns)
                    if link is not None:
                        url = link.get("href", "")
                    summary = entry.findtext("atom:summary", "", ns).strip()
                    content_el = entry.find("atom:content", ns)
                    content = (content_el.text or summary if content_el is not None else summary)[:4000]
                    ts_raw  = entry.findtext("atom:updated", "", ns) or entry.findtext("atom:published", "", ns)
                    ts      = ts_raw or datetime.now(tz=timezone.utc).isoformat()

                    signals.append(Signal(
                        id=_make_id(url, ts),
                        title=_clean_title(title, content),
                        content=content,
                        source="rss",
                        url=url,
                        timestamp=ts,
                        category=None,
                        client_tag=client_tag,
                        raw_meta={"feed_name": feed_name, "feed_url": feed_url},
                    ))

            else:
                # RSS 2.0
                channel = root.find("channel")
                if channel is None:
                    continue
                items = channel.findall("item")[:max_items_per_feed]
                for item in items:
                    title   = (item.findtext("title") or "").strip()
                    url     = item.findtext("link") or item.findtext("guid") or ""
                    desc    = item.findtext("description") or ""
                    # Strip basic HTML tags from description
                    import re
                    content = re.sub(r"<[^>]+>", "", desc).strip()[:4000]
                    ts_raw  = item.findtext("pubDate") or ""
                    try:
                        from email.utils import parsedate_to_datetime
                        ts = parsedate_to_datetime(ts_raw).isoformat()
                    except Exception:
                        ts = datetime.now(tz=timezone.utc).isoformat()

                    signals.append(Signal(
                        id=_make_id(url, ts),
                        title=_clean_title(title, content),
                        content=content,
                        source="rss",
                        url=url,
                        timestamp=ts,
                        category=None,
                        client_tag=client_tag,
                        raw_meta={"feed_name": feed_name, "feed_url": feed_url},
                    ))

        except Exception as e:
            print(f"[RSS] Erro em '{feed_name}': {e}")
            continue

    print(f"[RSS] ✓ {len(signals)} signals")
    return signals


# ── 4. TikTok (Apify — pay-per-result, cabe no $5 free) ──────────────────────

def scrape_tiktok(
    hashtags: list[str],
    max_items: int = 15,
    client_tag: Optional[str] = None,
) -> list[Signal]:
    """
    clockworks/free-tiktok-scraper — pay-per-result ($0.005/item).
    15 items = $0.075, cabe fácil no plano free.
    """
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise EnvironmentError("APIFY_API_TOKEN não encontrado no .env")

    print(f"[TikTok] Scraping hashtags: {hashtags}")
    client  = ApifyClient(token)
    signals = []

    for tag in hashtags:
        try:
            run_input = {
                "hashtags":       [tag.lstrip("#")],
                "resultsPerPage": max_items,
            }
            run   = client.actor("clockworks/free-tiktok-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

            for item in items:
                ts   = item.get("createTimeISO") or datetime.now(tz=timezone.utc).isoformat()
                url  = item.get("webVideoUrl") or item.get("videoUrl") or ""
                text = item.get("text") or item.get("desc") or ""

                signals.append(Signal(
                    id=_make_id(url, ts),
                    title=_clean_title("", text),
                    content=text[:2000],
                    source="tiktok",
                    url=url,
                    timestamp=ts,
                    category=None,
                    client_tag=client_tag,
                    raw_meta={
                        "author":  item.get("authorMeta", {}).get("name") or item.get("author"),
                        "plays":   item.get("playCount"),
                        "likes":   item.get("diggCount"),
                        "shares":  item.get("shareCount"),
                        "hashtag": tag,
                    },
                ))
        except Exception as e:
            print(f"[TikTok] Erro em #{tag}: {e}")
            continue

    print(f"[TikTok] ✓ {len(signals)} signals")
    return signals


# ── 5. YouTube (Apify — oficial e gratuito) ───────────────────────────────────

def scrape_youtube(
    search_terms: list[str],
    max_items: int = 10,
    client_tag: Optional[str] = None,
) -> list[Signal]:
    """
    apify/youtube-scraper — actor oficial Apify, gratuito.
    """
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise EnvironmentError("APIFY_API_TOKEN não encontrado no .env")

    print(f"[YouTube] Scraping: {search_terms}")
    client = ApifyClient(token)

    run_input = {
        "searchKeywords": search_terms,
        "maxResults":     max_items,
        "maxComments":    3,
    }

    try:
        run   = client.actor("apify/youtube-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        print(f"[YouTube] Erro: {e}")
        return []

    signals = []
    for item in items:
        ts          = item.get("date") or datetime.now(tz=timezone.utc).isoformat()
        url         = item.get("url") or item.get("videoUrl") or ""
        description = item.get("description") or ""
        comments    = item.get("comments") or []
        comments_text = "\n".join(c.get("text", "") for c in comments[:3] if c.get("text"))
        content     = f"{description}\n\n{comments_text}".strip()
        raw_title   = item.get("title") or item.get("name") or ""

        signals.append(Signal(
            id=_make_id(url, ts),
            title=_clean_title(raw_title, content),
            content=content[:5000],
            source="youtube",
            url=url,
            timestamp=ts,
            category=None,
            client_tag=client_tag,
            raw_meta={
                "channel":  item.get("channelName"),
                "views":    item.get("viewCount"),
                "likes":    item.get("likes"),
                "duration": item.get("duration"),
            },
        ))

    print(f"[YouTube] ✓ {len(signals)} signals")
    return signals


# ══════════════════════════════════════════════════════════════════════════════
# PENDENTE — ativar quando tiver plano pago no Apify
# ══════════════════════════════════════════════════════════════════════════════

def scrape_twitter_PENDENTE(*args, **kwargs):
    """Twitter/X — requer plano pago Apify. Actor: apidojo/tweet-scraper"""
    print("[Twitter/X] ⚠️  Pendente — requer plano pago Apify.")
    return []

def scrape_instagram_PENDENTE(*args, **kwargs):
    """Instagram — instável no free. Actor: apify/instagram-scraper"""
    print("[Instagram] ⚠️  Pendente — ativar quando estável.")
    return []


# ── Orchestrator ──────────────────────────────────────────────────────────────

class IngestionOrchestrator:

    def __init__(self, output_path: str = "data/signals.jsonl"):
        self.output_path = output_path
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def _load_existing_ids(self) -> set[str]:
        ids = set()
        if os.path.exists(self.output_path):
            with open(self.output_path) as f:
                for line in f:
                    try:
                        ids.add(json.loads(line)["id"])
                    except Exception:
                        pass
        return ids

    def _save_signals(self, signals: list[Signal]) -> int:
        existing    = self._load_existing_ids()
        new_signals = [s for s in signals if s.id not in existing]

        with open(self.output_path, "a") as f:
            for sig in new_signals:
                f.write(json.dumps(asdict(sig), ensure_ascii=False) + "\n")

        print(f"[Save] {len(new_signals)} novos / {len(signals) - len(new_signals)} duplicados ignorados")
        return len(new_signals)

    def run(
        self,
        web_config:     Optional[dict] = None,
        reddit_config:  Optional[dict] = None,
        rss_config:     Optional[dict] = None,
        tiktok_config:  Optional[dict] = None,
        youtube_config: Optional[dict] = None,
        client_tag:     Optional[str]  = None,
    ) -> list[Signal]:

        all_signals: list[Signal] = []

        if web_config:
            all_signals += scrape_web(**web_config, client_tag=client_tag)

        if reddit_config:
            all_signals += scrape_reddit(**reddit_config, client_tag=client_tag)

        if rss_config:
            all_signals += scrape_rss(**rss_config, client_tag=client_tag)

        if tiktok_config:
            all_signals += scrape_tiktok(**tiktok_config, client_tag=client_tag)

        if youtube_config:
            all_signals += scrape_youtube(**youtube_config, client_tag=client_tag)

        total = self._save_signals(all_signals)
        print(f"\n✅ Ingestão completa — {total} novos signals salvos em {self.output_path}")
        return all_signals


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    orchestrator = IngestionOrchestrator(output_path="data/signals.jsonl")

    # TESTE FOCADO: NEW YORK LIBERTY & WNBA CULTURE
    orchestrator.run(
        # RSS — Buscando nas fontes de cultura e tendências
        rss_config={
            "max_items_per_feed": 5,
        },

        # REDDIT — Onde a conversa real acontece
        reddit_config={
            "subreddits": [
                "NYLiberty", "wnba", "womenssports", "sportsmarketing"
            ],
            "search_terms": [
                "Liberty Loud", "fan experience", "stadium style", 
                "Ellie the Elephant", "WNBA fashion"
            ],
            "max_items": 20,
        },

        # WEB — Sites de tendências e notícias esportivas
        web_config={
            "start_urls": [
                "https://www.si.com/wnba/team/new-york-liberty",
                "https://liberty.wnba.com/news/",
            ],
            "max_pages_per_url": 3,
        },

        # TIKTOK — Fundamental para ver o "Tunnel Fashion" e a cultura visual
        tiktok_config={
            "hashtags": ["#nyliberty", "#wnba", "#wnbafashion", "#ellietheelephant"],
            "max_items": 15,
        },

        # YOUTUBE — Para captar análises e vlogs de torcedores
        youtube_config={
            "search_terms": [
                "New York Liberty fan culture",
                "WNBA marketing trends 2026",
                "New York Liberty tunnel walk"
            ],
            "max_items": 10,
        },

        client_tag="NY_Liberty_Pinterest", # Tag específica para o projeto
    )