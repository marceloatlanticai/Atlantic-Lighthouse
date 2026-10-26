"""Where the Lighthouse's facts come from, and how they are checked.

Two jobs, both about trust:

  1. THE WINDOW. Every scan looks back a fixed number of months. Anything a
     source dates before that is history, not a current. (Pat's Puma basketball
     scan surfaced a 2019 trend: YouTube was asked for the most-viewed videos of
     ALL TIME, and Puma's return to basketball was in 2018-19.)

  2. BY THE NUMBERS. Figures for the brief come only from a list of research
     houses and official statistics offices, and only when the number can be
     found again on the page it is credited to. A figure we cannot find there is
     never presented as a fact.

Pure Python: no Streamlit, no network of its own. The model call uses the client
the caller passes in, and the page reader is passed in too, so all of it can be
tested without the app or the internet.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

# ══════════════════════════════════════════════════════════════════════════════
# THE TRUSTED LIST
# ══════════════════════════════════════════════════════════════════════════════
# Pat's list (Oct 23, 2026), plus Pew, which he named in the meeting. Then the
# official statistics office of each market we scan, and two research houses he
# did not name but that publish exactly the category sales figures he asked for
# ("shoe sales up 27%" is usually a Circana number). `added` keeps the list
# honest about whose suggestion each one was.
#
# Most of these sell their data. What we read is what they publish in the open
# (press releases, free charts, articles with headline numbers), which is why
# every figure links back to its page. Their APIs and MCP servers only open what
# a subscription already pays for; if Atlantic subscribes to one, plugging it in
# is a separate step.
#
# `markets` limits a statistics office to scans of its own country (ISO 3166-1
# alpha-2, the same code MARKETS[...]["trends"] carries). No `markets` = global.
TRUSTED: list[dict] = [
    {"name": "Statista", "domains": ("statista.com",), "kind": "research", "added": "pat"},
    {"name": "GWI", "domains": ("gwi.com",), "kind": "research", "added": "pat"},
    {"name": "Mintel", "domains": ("mintel.com",), "kind": "research", "added": "pat"},
    {"name": "IBISWorld", "domains": ("ibisworld.com",), "kind": "research", "added": "pat"},
    {"name": "Kantar", "domains": ("kantar.com",), "kind": "research", "added": "pat"},
    {"name": "Euromonitor", "domains": ("euromonitor.com",), "kind": "research", "added": "pat"},
    {"name": "Gallup", "domains": ("gallup.com",), "kind": "research", "added": "pat"},
    {"name": "YouGov", "domains": ("yougov.com",), "kind": "research", "added": "pat"},
    {"name": "Gartner", "domains": ("gartner.com",), "kind": "research", "added": "pat"},
    {"name": "Forrester", "domains": ("forrester.com",), "kind": "research", "added": "pat"},
    {"name": "EMARKETER", "domains": ("emarketer.com", "insiderintelligence.com"),
     "kind": "research", "added": "pat"},
    {"name": "Bloomberg", "domains": ("bloomberg.com",), "kind": "press", "added": "pat"},
    {"name": "Pew Research Center", "domains": ("pewresearch.org",), "kind": "research",
     "added": "pat"},
    {"name": "US Census Bureau", "domains": ("census.gov",), "kind": "official",
     "markets": ("US",), "added": "pat"},
    {"name": "Circana", "domains": ("circana.com",), "kind": "research", "added": "lighthouse"},
    {"name": "NielsenIQ", "domains": ("nielseniq.com",), "kind": "research", "added": "lighthouse"},
    {"name": "Bureau of Labor Statistics", "domains": ("bls.gov",), "kind": "official",
     "markets": ("US",), "added": "lighthouse"},
    {"name": "Office for National Statistics", "domains": ("ons.gov.uk",), "kind": "official",
     "markets": ("GB",), "added": "lighthouse"},
    {"name": "IBGE", "domains": ("ibge.gov.br",), "kind": "official",
     "markets": ("BR",), "added": "lighthouse"},
    {"name": "Statistics Canada", "domains": ("statcan.gc.ca",), "kind": "official",
     "markets": ("CA",), "added": "lighthouse"},
    {"name": "Australian Bureau of Statistics", "domains": ("abs.gov.au",), "kind": "official",
     "markets": ("AU",), "added": "lighthouse"},
    {"name": "INE Portugal", "domains": ("ine.pt",), "kind": "official",
     "markets": ("PT",), "added": "lighthouse"},
    {"name": "INE Spain", "domains": ("ine.es",), "kind": "official",
     "markets": ("ES",), "added": "lighthouse"},
    {"name": "INSEE", "domains": ("insee.fr",), "kind": "official",
     "markets": ("FR",), "added": "lighthouse"},
    {"name": "Destatis", "domains": ("destatis.de",), "kind": "official",
     "markets": ("DE",), "added": "lighthouse"},
]

_DOMAIN_OK = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def _env_domains(name: str) -> list[str]:
    raw = os.environ.get(name, "") or ""
    out = []
    for d in re.split(r"[,\s]+", raw.lower()):
        d = d.replace("https://", "").replace("http://", "").strip().strip("/")
        if d.startswith("www."):
            d = d[4:]
        if d and _DOMAIN_OK.match(d):
            out.append(d)
    return out


def registry(iso: str = "") -> list[dict]:
    """The trusted sources for a scan of market `iso` ("" = worldwide).

    Two switches in the secrets, so the list can change without a deploy:
      LH_TRUSTED_EXTRA = "nature.com, mckinsey.com"   adds sources
      LH_TRUSTED_OFF   = "bloomberg.com"              removes them
    """
    iso = (iso or "").upper()
    off = set(_env_domains("LH_TRUSTED_OFF"))
    out = []
    for src in TRUSTED:
        mk = src.get("markets")
        if mk and iso not in mk:
            continue
        doms = tuple(d for d in src["domains"] if d not in off)
        if doms:
            out.append(dict(src, domains=doms))
    have = {d for s in out for d in s["domains"]}
    for d in _env_domains("LH_TRUSTED_EXTRA"):
        if d not in have and d not in off:
            out.append({"name": d, "domains": (d,), "kind": "added", "added": "secrets"})
            have.add(d)
    return out


def domains_for(iso: str = "") -> list[str]:
    """Bare domains, the form web search's allowed_domains expects."""
    return [d for s in registry(iso) for d in s["domains"]]


def host_of(url: str) -> str:
    try:
        h = urllib.parse.urlsplit((url or "").strip()).netloc.lower()
    except Exception:
        return ""
    h = h.split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def source_for(url: str, iso: str = "", sources: Optional[list] = None) -> Optional[dict]:
    """The trusted source a URL belongs to, or None.

    Matched on whole domain labels: "notstatista.com" is not statista.com, and
    "statista.com.evil.io" is not either. Subdomains count (news.gallup.com is
    Gallup, today.yougov.com is YouGov) — the same rule web search applies."""
    h = host_of(url)
    if not h:
        return None
    for src in (sources if sources is not None else registry(iso)):
        for d in src["domains"]:
            if h == d or h.endswith("." + d):
                return src
    return None


def norm_url(url: str) -> str:
    """Comparable form of a URL: no scheme, no www, no fragment, no tracking
    parameters, no trailing slash. Two spellings of one page compare equal."""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
    except Exception:
        return ""
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", p.path or "")
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not re.match(r"(utm_|fbclid|gclid|mc_|ref$|ref_)", k.lower())]
    query = urllib.parse.urlencode(sorted(q))
    return host + path + ("?" + query if query else "")


# ══════════════════════════════════════════════════════════════════════════════
# THE WINDOW
# ══════════════════════════════════════════════════════════════════════════════
WINDOWS = {3: "3 months", 6: "6 months", 12: "12 months", 24: "2 years"}
DEFAULT_WINDOW = 12

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def window_label(months: int) -> str:
    return WINDOWS.get(int(months or 0), f"{int(months or 0)} months")


def cutoff(months: int, now: Optional[datetime] = None) -> Optional[datetime]:
    """The oldest moment still inside the window. None when there is no window."""
    if not months:
        return None
    return _now(now) - timedelta(days=round(float(months) * 30.437))


def _month_end(y: int, m: int) -> datetime:
    nxt = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=timezone.utc)
    return nxt - timedelta(seconds=1)


def parse_when(v, end: bool = False, now: Optional[datetime] = None) -> Optional[datetime]:
    """Any date a source hands us, as an aware UTC datetime — or None if unknown.

    Reads ISO dates and datetimes, GDELT's 20261020T120000Z, unix seconds or
    milliseconds, "April 30, 2025", "30 Apr 2025", "April 2025", "2025-04",
    a bare year, and relative ages like "3 days ago" (web search's page_age).

    `end=True` reads a PARTIAL date as the end of its period: "2025-10" is
    31 October, "2025" is 31 December. The window check uses that, so a figure
    dated only by month is never thrown out for being a few days early."""
    if v is None or v == "":
        return None
    now = _now(now)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
        if x > 1e11:
            x /= 1000.0                           # milliseconds
        if x <= 0:
            return None
        try:
            return datetime.fromtimestamp(x, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    if not s:
        return None
    low = s.lower()
    try:
        # GDELT seendate: 20261020T120000Z, or a bare 20261020
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:t(\d{2})(\d{2})(\d{2})z?)?", low)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hh, mm, ss = (int(m.group(i) or 0) for i in (4, 5, 6))
            return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
        # ISO date or datetime
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[t ](\d{1,2}):(\d{2})(?::(\d{2}))?)?", low)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hh, mm, ss = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
            dt = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
            tz = re.search(r"([+-])(\d{2}):?(\d{2})$", s[10:]) if len(s) > 10 else None
            if tz and m.group(4):
                sign = 1 if tz.group(1) == "+" else -1
                dt -= sign * timedelta(hours=int(tz.group(2)), minutes=int(tz.group(3)))
            return dt
        # Year and month: 2025-04 or 2025/04
        m = re.fullmatch(r"(\d{4})[-/](\d{1,2})", low)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            return _month_end(y, mo) if end else datetime(y, mo, 1, tzinfo=timezone.utc)
        # A bare year
        m = re.fullmatch(r"(?:fy\s*)?(\d{4})", low)
        if m:
            y = int(m.group(1))
            return (datetime(y, 12, 31, 23, 59, 59, tzinfo=timezone.utc) if end
                    else datetime(y, 1, 1, tzinfo=timezone.utc))
        # Relative: "3 days ago", "a month ago", "yesterday", "today"
        if low in ("today", "just now", "now"):
            return now
        if low == "yesterday":
            return now - timedelta(days=1)
        m = re.fullmatch(r"(an?|\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", low)
        if m:
            n = 1 if m.group(1) in ("a", "an") else int(m.group(1))
            unit = m.group(2)
            days = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7,
                    "month": 30.437, "year": 365.25}[unit]
            return now - timedelta(days=n * days)
        # "April 30, 2025" / "Apr 30 2025" / "30 April 2025" / "April 2025"
        m = re.fullmatch(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", low)
        if m and m.group(1)[:3] in _MONTHS:
            return datetime(int(m.group(3)), _MONTHS[m.group(1)[:3]], int(m.group(2)),
                            tzinfo=timezone.utc)
        m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})", low)
        if m and m.group(2)[:3] in _MONTHS:
            return datetime(int(m.group(3)), _MONTHS[m.group(2)[:3]], int(m.group(1)),
                            tzinfo=timezone.utc)
        m = re.fullmatch(r"([a-z]{3,9})\.?,?\s+(\d{4})", low)
        if m and m.group(1)[:3] in _MONTHS:
            y, mo = int(m.group(2)), _MONTHS[m.group(1)[:3]]
            return _month_end(y, mo) if end else datetime(y, mo, 1, tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        return None
    return None


def too_old(v, months: int, now: Optional[datetime] = None) -> bool:
    """True only when the date is KNOWN and falls before the window.
    An undated item is not old — it is undated, and is labelled as such."""
    c = cutoff(months, now)
    if c is None:
        return False
    d = parse_when(v, end=True, now=now)
    return bool(d) and d < c


def day(v, now: Optional[datetime] = None) -> str:
    """YYYY-MM-DD for the prompt, or "undated"."""
    d = parse_when(v, now=now)
    return d.strftime("%Y-%m-%d") if d else "undated"


def show_date(v, now: Optional[datetime] = None) -> str:
    """How a figure's date reads on the page: "Aug 2026", "14 Aug 2026"."""
    s = str(v or "").strip()
    if not s:
        return ""
    d = parse_when(s, now=now)
    if not d:
        return ""
    if re.fullmatch(r"\d{4}[-/]\d{1,2}", s) or re.fullmatch(r"[A-Za-z]{3,9}\.?,?\s+\d{4}", s):
        return d.strftime("%b %Y")
    if re.fullmatch(r"(?:FY\s*)?\d{4}", s, flags=re.I):
        return d.strftime("%Y")
    return f"{d.day} {d.strftime('%b %Y')}"


# ── Where the window reaches each source ─────────────────────────────────────
def youtube_after(months: int, now: Optional[datetime] = None) -> str:
    """publishedAfter for the YouTube API (RFC 3339), or "" for no limit."""
    c = cutoff(months, now)
    return c.strftime("%Y-%m-%dT%H:%M:%SZ") if c else ""


def unix_after(months: int, now: Optional[datetime] = None) -> int:
    """created_at_i floor for Hacker News' Algolia API, or 0."""
    c = cutoff(months, now)
    return int(c.timestamp()) if c else 0


def tbs_for(months: int, now: Optional[datetime] = None) -> str:
    """Firecrawl's time filter: a custom date range ending today, or ""."""
    c = cutoff(months, now)
    if not c:
        return ""
    n = _now(now)
    return f"cdr:1,cd_min:{c.month}/{c.day}/{c.year},cd_max:{n.month}/{n.day}/{n.year}"


def in_window(items: Iterable, months: int, when: Callable = lambda x: x.get("timestamp"),
              now: Optional[datetime] = None) -> tuple:
    """Split items into (kept, n_dropped) by their known date."""
    kept, dropped = [], 0
    for it in items:
        try:
            old = too_old(when(it), months, now)
        except Exception:
            old = False
        if old:
            dropped += 1
        else:
            kept.append(it)
    return kept, dropped


# ══════════════════════════════════════════════════════════════════════════════
# FIGURES
# ══════════════════════════════════════════════════════════════════════════════
# A number token: 27 · 4.2 · 1,234,567 · 27,3 (read as 27 and 3, on both sides,
# so a European decimal comma still matches itself).
_NUMTOK = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\d])")
_STOP = frozenset("""a an and are as at be been but by for from has have in into is it its of on
or per percent than that the their this to was were which while who will with year years
month months between since compared versus vs among about over under more less most""".split())


def _norm_num(whole: str, frac: str) -> str:
    w = whole.replace(",", "").lstrip("0") or "0"
    f = (frac or "").rstrip("0")
    return w + ("." + f if f else "")


def numbers_in(text: str) -> list[str]:
    return [_norm_num(m.group(1), m.group(2) or "") for m in _NUMTOK.finditer(text or "")]


def figure_in_text(figure: str, text: str) -> bool:
    """Every number in the figure appears, as a number, in the text."""
    want = set(numbers_in(figure))
    if not want:
        return False
    return want <= set(numbers_in(text))


def _words(text: str) -> set:
    return {w[:6] for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _STOP}


def figure_near_claim(figure: str, claim: str, text: str, radius: int = 260) -> bool:
    """The figure is on the page, next to what the claim says it measures.

    A long page carries plenty of numbers, so "27 is somewhere on it" proves
    nothing (it is also a date). The figure has to appear with at least two of
    the claim's words within a short stretch of text around it."""
    want = numbers_in(figure)
    if not want or not text:
        return False
    main = max(want, key=lambda x: (len(x.replace(".", "")), "." in x))
    keys = _words(claim)
    need = min(2, len(keys))
    for m in _NUMTOK.finditer(text):
        if _norm_num(m.group(1), m.group(2) or "") != main:
            continue
        a, z = max(0, m.start() - radius), min(len(text), m.end() + radius)
        win = text[a:z]
        if not figure_in_text(figure, win):
            continue
        if len(keys & _words(win)) >= need:
            return True
    return False


def is_negative(figure: str) -> bool:
    return (figure or "").strip()[:1] in ("-", "−", "–")


# ══════════════════════════════════════════════════════════════════════════════
# READING A WEB SEARCH RESPONSE
# ══════════════════════════════════════════════════════════════════════════════
def plain(obj) -> dict:
    """An API block as a dict, whether the SDK gave us a model or a dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for name in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                d = fn()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
    try:
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    except TypeError:
        return {}


def read_search(blocks: Iterable) -> dict:
    """Pull apart an assistant turn that used web search.

    Returns the text (all text blocks joined, which is how the JSON lines are
    read back), the citations with the stretch of text each one covers, every
    page the searches returned, the queries run and any search errors."""
    text, spans, results, queries, errors = "", [], {}, [], []
    for b in blocks or []:
        b = plain(b)
        t = b.get("type")
        if t == "text":
            s = b.get("text") or ""
            a = len(text)
            text += s
            cits = []
            for c in b.get("citations") or []:
                c = plain(c)
                if c.get("url"):
                    cits.append({"url": c.get("url", ""), "title": c.get("title", "") or "",
                                 "cited_text": c.get("cited_text", "") or ""})
            if cits:
                spans.append((a, len(text), cits))
        elif t == "server_tool_use":
            if b.get("name") == "web_search":
                q = plain(b.get("input")).get("query")
                if q:
                    queries.append(str(q))
        elif t == "web_search_tool_result":
            c = b.get("content")
            if isinstance(c, list):
                for r in c:
                    r = plain(r)
                    if r.get("url"):
                        results.setdefault(norm_url(r["url"]), {
                            "url": r["url"], "title": r.get("title", "") or "",
                            "page_age": r.get("page_age", "") or ""})
            else:
                c = plain(c)
                if c.get("error_code"):
                    errors.append(str(c["error_code"]))
    return {"text": text, "spans": spans, "results": results,
            "queries": queries, "errors": errors}


def json_lines(text: str) -> list:
    """Every JSON object in the text, with where it sits: [(obj, start, end)]."""
    dec, out, i = json.JSONDecoder(), [], 0
    while True:
        j = (text or "").find("{", i)
        if j < 0:
            return out
        try:
            obj, end = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        if isinstance(obj, dict):
            out.append((obj, j, end))
        i = end


_CHECK_RANK = {"page": 0, "excerpt": 1, "": 2}

# "CAGR 2020-2025": a figure about a stretch of years that is already over. It
# can be published last month and still describe the past — Pat's ring-fence
# is about what is happening NOW, so a multi-year history is not a current
# number. A forecast ("2025-2030") reaches into the future and stays.
_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*(?:-|–|—|to|through|thru)\s*((?:19|20)?\d{2})\b",
                    re.I)


def is_history(text: str, now: Optional[datetime] = None) -> bool:
    """A range of three or more years that ended before this year."""
    y = _now(now).year
    for m in _RANGE.finditer(text or ""):
        a, b = int(m.group(1)), m.group(2)
        b = int(b) if len(b) == 4 else int(str(a)[:2] + b)
        if a < b and b - a >= 3 and b < y:
            return True
    return False


# One page is one source of evidence, however many numbers it carries: three
# IBISWorld figures from the same industry page read as three facts and are
# really one. And no organisation gets more than two of the six tiles.
PER_PAGE, PER_SOURCE = 1, 2


def collect(read: dict, months: int = 0, iso: str = "", now: Optional[datetime] = None,
            limit: int = 8, sources: Optional[list] = None) -> tuple:
    """Turn the model's lines into figures we can stand behind.

    Returns (items, dropped). A line is DROPPED — never shown — when:
      · its page is not on the trusted list;
      · its page was not among the pages the searches actually returned
        (the model wrote a URL it did not find, which is how invented
        statistics usually look);
      · its date, or the page's, is known and older than the window;
      · it carries no number at all.
    What survives is checked against the source's own words: "excerpt" when the
    number is in the text the search quoted for that page. confirm_on_pages()
    can raise that to "page" afterwards. Neither = shown only as unconfirmed."""
    srcs = sources if sources is not None else registry(iso)
    items, dropped, seen = [], [], set()
    by_url: dict = {}
    for a, z, cits in read.get("spans", []):
        for c in cits:
            by_url.setdefault(norm_url(c["url"]), []).append(c.get("cited_text", ""))
    for obj, a, z in json_lines(read.get("text", "")):
        fig = re.sub(r"\s+", " ", str(obj.get("figure") or "")).strip()
        claim = re.sub(r"\s+", " ", str(obj.get("claim") or "")).strip()
        url = str(obj.get("url") or "").strip()
        said = str(obj.get("source") or "").strip()
        date = str(obj.get("date") or "").strip()
        if not (fig or claim or url):
            continue                      # not one of ours (stray braces in prose)
        why = ""
        src = source_for(url, sources=srcs) if url else None
        hit = read.get("results", {}).get(norm_url(url)) if url else None
        if not fig or not numbers_in(fig) or not claim:
            why = "no figure"
        elif not url:
            why = "no page given"
        elif not src:
            why = "not on the trusted list"
        elif hit is None:
            why = "page not among the search results"
        elif too_old(date, months, now) or too_old(hit.get("page_age"), months, now):
            # Either date is enough. The stated one is when the figure was
            # published; page_age is when the page last changed, so a page last
            # touched before the window cannot hold a figure from inside it.
            why = "older than the window"
        elif is_history(f"{claim} {fig}", now):
            why = "describes a multi-year past period"
        if why:
            dropped.append({"figure": fig[:24], "claim": claim[:140], "url": url, "why": why})
            continue
        key = (numbers_in(fig)[0], norm_url(url))
        if key in seen:
            continue
        seen.add(key)
        cited = [c["cited_text"] for s0, s1, cits in read.get("spans", [])
                 if s0 < z and s1 > a for c in cits if c.get("cited_text")]
        cited += [t for t in by_url.get(norm_url(url), []) if t]
        quote = next((t for t in cited if figure_in_text(fig, t)), "")
        check = "excerpt" if quote or figure_in_text(fig, hit.get("title", "")) else ""
        when = date if parse_when(date, now=now) else hit.get("page_age", "")
        items.append({
            "figure": fig[:24], "claim": claim[:240], "source": src["name"],
            "source_said": said[:60], "kind": src.get("kind", ""), "domain": host_of(url),
            "url": url, "title": hit.get("title", "")[:160],
            "date": show_date(when, now=now), "date_raw": str(when)[:40],
            "check": check, "quote": (quote or (cited[0] if cited else ""))[:220],
            "negative": is_negative(fig),
        })
    items.sort(key=lambda x: _CHECK_RANK.get(x["check"], 2))
    # Spread: the best figure of each page, at most two per organisation.
    kept, per_page, per_src = [], {}, {}
    for it in items:
        pg, sn = norm_url(it["url"]), it["source"]
        if per_page.get(pg, 0) >= PER_PAGE:
            dropped.append({"figure": it["figure"], "claim": it["claim"][:140], "url": it["url"],
                            "why": "another figure from the same page"})
            continue
        if per_src.get(sn, 0) >= PER_SOURCE:
            dropped.append({"figure": it["figure"], "claim": it["claim"][:140], "url": it["url"],
                            "why": f"a third figure from {sn}"})
            continue
        per_page[pg] = per_page.get(pg, 0) + 1
        per_src[sn] = per_src.get(sn, 0) + 1
        kept.append(it)
    return kept[:limit], dropped


def confirm_on_pages(items: list, fetch: Callable[[str], str], budget: float = 25.0,
                     workers: int = 6) -> dict:
    """Open each figure's page and look for the number next to its claim.

    `fetch(url) -> text` is passed in (the app hands it ingestion's article
    reader). A page that cannot be read — paywall, bot wall, timeout — leaves
    the figure where it was; it is never a reason to drop one. Returns a small
    tally for the diagnostics: {"read": n, "found": n, "unreadable": n}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _TO
    tally = {"read": 0, "found": 0, "unreadable": 0}
    todo = [it for it in items if it.get("url") and it.get("check") != "page"]
    if not todo:
        return tally
    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo))))
    futs = {pool.submit(fetch, it["url"]): it for it in todo}
    try:
        for f in as_completed(futs, timeout=budget):
            it = futs[f]
            try:
                page = f.result() or ""
            except Exception:
                page = ""
            if isinstance(page, tuple):
                page = page[0] if page else ""
            if not page or len(page) < 200:
                tally["unreadable"] += 1
                continue
            tally["read"] += 1
            if figure_near_claim(it["figure"], it["claim"], page):
                it["check"] = "page"
                tally["found"] += 1
    except _TO:
        tally["unreadable"] += sum(1 for f in futs if not f.done())
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    items.sort(key=lambda x: _CHECK_RANK.get(x.get("check", ""), 2))
    return tally


# ══════════════════════════════════════════════════════════════════════════════
# THE SEARCH
# ══════════════════════════════════════════════════════════════════════════════
def numbers_prompt(brand: str, category: str, product: str, market: str, months: int,
                   competitors: str = "", now: Optional[datetime] = None, focus: str = "") -> str:
    now = _now(now)
    subject = " ".join(dict.fromkeys(f"{category} {product}".split())).strip() or brand
    if focus and focus.strip().lower() not in subject.lower():
        subject += f" (specifically {focus.strip()})"
    where = market if market and market != "Worldwide" else "the world"
    c = cutoff(months, now)
    since = c.strftime("%d %B %Y").lstrip("0") if c else ""
    when = (f", published in the last {window_label(months)} (on or after {since})"
            if since else "")
    comps = ", ".join(x.strip() for x in re.split(r"[,;]", competitors or "") if x.strip())[:200]
    who = f"{brand} and its competitors ({comps})" if comps else (brand or "the leading brands")
    rule_date = (f"- Only figures published on or after {since}. Skip older pages, however "
                 f"good the number.\n" if since else "")
    return f"""BY THE NUMBERS — today is {now.strftime('%d %B %Y').lstrip('0')}.

Find hard numbers a strategist could put on a slide about {subject} in {where}{when}.

Aim for a MIX, one search per angle:
- the market for the product itself: size, sales, growth or decline (the product, not a neighbouring industry such as the shops that sell it);
- the people: how many do, buy, believe or worry about something (surveys);
- {who}: share, sales, reach, sentiment.

Your web search only reaches research houses and official statistics offices. Search 3 or 4 times, each from a different angle.

Rules:
- Every figure must come from a page your searches returned. Never from memory.
{rule_date}- The most recent period available. An average over several past years (e.g. "CAGR 2020-2025") is history: skip it. Forecasts are fine if labelled.
- At most ONE figure per page and TWO per organisation.
- Copy the figure exactly as the page writes it. Give changes a sign: "+27%", "-12%".
- National figures for {where} first; a global figure is fine if the claim says it is global.
- Niche products rarely have their own figures. If nothing exists for {subject} itself, use the closest wider market (for "mineral sparkling water": sparkling water, then bottled water) and say which in the claim — a figure about the wider market, labelled as such, beats no figure.
- Up to 8 figures, strongest first. Fewer is fine. None is fine: say nothing rather than stretch.

When you have finished searching, write each figure as two lines and nothing else:
1. one plain sentence stating the figure, citing the page it is on, as you normally cite;
2. the same figure as one JSON object on its own line:
{{"figure": "+27%", "claim": "what it measures: who, where, when", "source": "Example Research", "date": "2026-08-14", "url": "https://..."}}
figure: the number only, at most 12 characters.
claim: at most 20 words.
source: the organisation that published the figure.
date: when the page was published, YYYY-MM-DD or YYYY-MM.
url: the page the figure is on, exactly as your search returned it."""


def _error_text(exc: Exception) -> str:
    parts = [str(exc)]
    body = getattr(exc, "body", None)
    if body:
        try:
            parts.append(json.dumps(body))
        except Exception:
            parts.append(str(body))
    return " ".join(parts).lower()


def _call(client, model: str, prompt: str, tools: list, max_tokens: int = 3000,
          rounds: int = 3) -> tuple:
    """One turn with server-side search, continued through pause_turn.
    Returns (blocks, n_rounds)."""
    messages = [{"role": "user", "content": prompt}]
    blocks: list = []
    n = 0
    for n in range(1, rounds + 1):
        resp = client.messages.create(model=model, max_tokens=max_tokens,
                                      tools=tools, messages=messages)
        content = list(getattr(resp, "content", None) or [])
        blocks.extend(content)
        if getattr(resp, "stop_reason", "") != "pause_turn":
            break
        # The paused turn goes back exactly as it came, and the API carries on.
        messages = [messages[0], {"role": "assistant", "content": blocks[:]}]
    return blocks, n


def search_numbers(client, model: str, *, brand: str, category: str, product: str = "",
                   market: str = "", iso: str = "", months: int = DEFAULT_WINDOW,
                   competitors: str = "", fallback_model: str = "", max_uses: int = 4,
                   now: Optional[datetime] = None, limit: int = 8, focus: str = "") -> dict:
    """Search the trusted sources for figures. Never raises.

    Returns {"items", "dropped", "queries", "domains", "searches", "error",
    "skipped", "model", "months"}. `error` is a sentence for the reader when the
    search could not run; an empty `items` with no error means it ran and found
    nothing in the window, which is an answer too."""
    srcs = registry(iso)
    doms = [d for s in srcs for d in s["domains"]]
    out = {"items": [], "dropped": [], "queries": [], "domains": doms, "searches": 0,
           "error": "", "skipped": [], "model": model, "months": int(months or 0),
           "search_errors": []}
    if not doms:
        out["error"] = "the trusted list is empty"
        return out
    prompt = numbers_prompt(brand, category, product, market, months, competitors, now, focus)
    tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": int(max_uses),
            "allowed_domains": doms}
    if iso and len(iso) == 2:
        tool["user_location"] = {"type": "approximate", "country": iso.upper()}
    models = [m for m in dict.fromkeys([model, fallback_model]) if m]
    blocks, err = None, ""
    attempt = 0
    while attempt < 5 and models:
        attempt += 1
        try:
            blocks, _ = _call(client, models[0], prompt, [tool])
            out["model"] = models[0]
            err = ""
            break
        except Exception as exc:
            msg = _error_text(exc)
            name = type(exc).__name__
            if "web search" in msg and ("not enabled" in msg or "disabled" in msg):
                err = ("web search is switched off for this Anthropic organisation "
                       "(an admin can turn it on in the Console, under Capabilities)")
                break
            bad = [d for d in tool["allowed_domains"] if d in msg]
            if bad and ("domain" in msg) and len(bad) < len(tool["allowed_domains"]):
                tool = dict(tool, allowed_domains=[d for d in tool["allowed_domains"]
                                                   if d not in bad])
                out["skipped"] += bad
                continue
            if "user_location" in tool and ("user_location" in msg or "country" in msg):
                tool = {k: v for k, v in tool.items() if k != "user_location"}
                continue
            if len(models) > 1 and ("model" in msg or "not supported" in msg
                                    or "does not support" in msg):
                models = models[1:]
                continue
            if "Authentication" in name or "PermissionDenied" in name:
                err = "Anthropic rejected the API key"
            elif "RateLimit" in name:
                err = "Anthropic rate limit reached — the figures will come with the next scan"
            elif "credit balance" in msg:
                err = "the Anthropic account is out of credit"
            elif "Connection" in name or "Timeout" in name:
                err = "could not reach Anthropic"
            else:
                err = f"the search failed ({name}: {str(exc)[:160]})"
            break
    if blocks is None:
        out["error"] = err or "the search did not run"
        return out
    rd = read_search(blocks)
    out["queries"] = rd["queries"][:8]
    out["searches"] = len(rd["queries"])
    out["search_errors"] = rd["errors"][:4]
    out["domains"] = tool["allowed_domains"]
    items, dropped = collect(rd, months=months, now=now, limit=limit,
                             sources=[dict(s, domains=tuple(d for d in s["domains"]
                                                            if d in tool["allowed_domains"]))
                                      for s in srcs])
    out["items"], out["dropped"] = items, dropped[:12]
    if not items and rd["errors"] and not rd["results"]:
        out["error"] = f"web search answered with an error ({', '.join(rd['errors'][:2])})"
    return out


# ══════════════════════════════════════════════════════════════════════════════
# EVERY PERCENTAGE IN THE BRIEF HAS TO COME FROM SOMEWHERE
# ══════════════════════════════════════════════════════════════════════════════
# The prompt says "never invent a percentage". A prompt is a request, not a
# guarantee, and an invented "70% of Gen Z" reads exactly like a real one. So
# after the brief is written, every percentage is looked for in what the model
# was given: the checked figures and the signals' own words. A stat line whose
# percentage nobody stated is removed; anywhere else, it is listed for a person
# to check before the brief goes out.
_PCT = re.compile(r"([+\-−–]?\d[\d,]*(?:\.\d+)?)\s?(?:%|per\s?cent\b|percent\b)", re.I)


def _pct_key(raw: str) -> str:
    raw = re.sub(r"^[+\-−–]", "", raw.strip()).replace(",", "")
    whole, _, frac = raw.partition(".")
    return _norm_num(whole, frac)


def percentages(text: str) -> list:
    """The percentages a text states, normalised: "+27%" → "27", "4.50 percent" → "4.5"."""
    return [_pct_key(m.group(1)) for m in _PCT.finditer(text or "")]


def pct_in_text(pct: str, text: str) -> bool:
    """Does the text STATE this percentage? A bare 27 in a date does not count.
    `pct` may be "27%", "27 percent" or just "27"."""
    keys = percentages(pct) or [_pct_key(m.group(0)) for m in
                                re.finditer(r"\d[\d,]*(?:\.\d+)?", pct or "")][:1]
    return bool(keys) and set(keys) <= set(percentages(text))


def _confirmed_text(items: list) -> str:
    return " \n".join(f"{x.get('figure', '')} {x.get('claim', '')}" for x in (items or [])
                      if x.get("check") in ("page", "excerpt"))


def check_stats(trends: list, items: list, texts: list) -> list:
    """Remove a trend's stat line when it carries a percentage no source states.

    `texts` are the words the model was given (signals, trade, newsletters).
    Also clears a figure_index that points at an unconfirmed figure. Returns
    what was removed, for the diagnostics: [{"trend", "stat"}]."""
    pool = _confirmed_text(items) + " \n" + " \n".join(texts or [])
    have = set(percentages(pool))
    removed = []
    for i, t in enumerate(trends or []):
        if not isinstance(t, dict):
            continue
        fi = t.get("figure_index")
        try:
            fig = (items or [])[int(fi)] if fi is not None and int(fi) >= 0 else None
        except (ValueError, TypeError, IndexError):
            fig = None
        if fi is not None and not (fig and fig.get("check") in ("page", "excerpt")):
            t["figure_index"] = None
        stat = str(t.get("stat") or "")
        miss = [p for p in percentages(stat) if p not in have]
        if miss:
            removed.append({"trend": i, "stat": stat[:160]})
            t["_stat_removed"] = stat[:160]
            t["stat"] = ""
            t["figure_index"] = None
    return removed


def audit_numbers(res: dict, items: list, texts: list, limit: int = 12) -> list:
    """Percentages anywhere in the brief's written fields that no source states.
    Nothing is changed — these are flagged for a person, with where they sit."""
    pool = set(percentages(_confirmed_text(items) + " \n" + " \n".join(texts or [])))
    out = []

    def walk(v, where):
        if len(out) >= limit:
            return
        if isinstance(v, str):
            for m in _PCT.finditer(v):
                p = _pct_key(m.group(1))
                if p not in pool:
                    a = max(0, m.start() - 50)
                    out.append({"where": where, "pct": p + "%", "text": v[a:a + 140]})
                    break
        elif isinstance(v, dict):
            for k, x in v.items():
                if not str(k).startswith("_"):
                    walk(x, f"{where}.{k}" if where else str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{where}[{i}]")

    walk({k: v for k, v in (res or {}).items() if not str(k).startswith("_")}, "")
    return out


def for_prompt(items: list) -> str:
    """The FIGURES block for the brief's prompt: confirmed figures only."""
    rows = []
    for i, it in enumerate(items or []):
        if it.get("check") not in ("page", "excerpt"):
            continue
        rows.append(f"[F{i}] {it['figure']} — {it['claim']} ({it['source']}"
                    + (f", {it['date']}" if it.get("date") else "") + ")")
    return "\n".join(rows)
