"""
pinterest.py — Pinterest as a source for the Lighthouse.

WHY PINTEREST. People come to Pinterest early, before they have decided what to
buy or which brand to choose: they come to plan. What they search for there
runs ahead of what they post anywhere else, which is the Lighthouse's whole
business — the current before it is a current.

TWO WAYS IN (Marcelo, 31 Oct 2026, "as duas"):

  1. THE OFFICIAL ONE — this file. Pinterest's Trends API (v5): the searches
     growing fastest in a region, filtered to the words of the category, each
     with its growth week on week, month on month and year on year, and a
     year of weekly interest (0-100). Made by Pinterest for agencies; the
     access comes through the Pinterest representative. ON as soon as a token
     is in the secrets; until then nothing changes anywhere.

  2. SCRAPED PINS — ingestion.scrape_pinterest, through Apify. OFF unless
     PINTEREST_SCRAPE = "1", and NEVER for a brief about Pinterest itself:
     Pinterest's terms forbid scraping without permission, and a client should
     not be shown data taken from its own platform against its own rules.

THE NUMBERS ARE PINTEREST'S. Every percentage drawn from here is a field of the
API's answer, quoted as given — growth figures, never computed or rounded by
us — so a brief that cites one can always be traced back to the call.

Plain Python on purpose: no Streamlit, no app imports. The HTTP call can be
swapped for a fake, which is how the tests run.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable, Optional

API_URL = (os.environ.get("PINTEREST_API_URL", "") or "https://api.pinterest.com/v5").rstrip("/")
TRENDS_SITE = "https://trends.pinterest.com"

# The regions the Trends API accepts (its TrendsSupportedRegion enum).
REGIONS = ("US", "CA", "DE", "FR", "ES", "IT", "DE+AT+CH", "GB+IE", "IT+ES+PT+GR+MT",
           "PL+RO+HU+SK+CZ", "SE+DK+FI+NO", "NL+BE+LU", "AR", "BR", "CO", "MX",
           "MX+AR+CO+CL", "AU+NZ")
# The app's markets, in Pinterest's terms. Portugal has no region of its own:
# it is read inside Southern Europe, and the brief says so.
MARKET_REGION = {
    "United States": "US", "United Kingdom": "GB+IE", "Brazil": "BR", "Canada": "CA",
    "Australia": "AU+NZ", "Portugal": "IT+ES+PT+GR+MT", "Spain": "ES", "France": "FR",
    "Germany": "DE", "Worldwide": "US",
}
REGION_NAME = {
    "US": "the US", "CA": "Canada", "DE": "Germany", "FR": "France", "ES": "Spain",
    "IT": "Italy", "DE+AT+CH": "Germany, Austria and Switzerland", "GB+IE": "the UK and Ireland",
    "IT+ES+PT+GR+MT": "Southern Europe", "PL+RO+HU+SK+CZ": "Central Europe",
    "SE+DK+FI+NO": "the Nordics", "NL+BE+LU": "the Benelux", "AR": "Argentina", "BR": "Brazil",
    "CO": "Colombia", "MX": "Mexico", "MX+AR+CO+CL": "Latin America", "AU+NZ": "Australia and New Zealand",
}
# growing — strong upward growth over the last quarter: the early ones.
# monthly — the most searched this month: the ones already here.
TREND_TYPES = ("growing", "monthly")
CACHE_TTL = 6 * 3600          # the data is weekly; six hours of reuse costs nothing
MAX_ITEMS = 8
_STOP = {"and", "the", "for", "with", "of", "in", "a", "an", "or", "to", "on", "drinks",
         "drink", "products", "product", "brand", "brands", "category", "platforms", "platform",
         "social", "general", "other", "goods", "items"}


class PinterestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ── Turning it on ────────────────────────────────────────────────────────────
# Either a ready access token (PINTEREST_ACCESS_TOKEN — the developer portal
# makes one for 30 days), or the trio that mints them: PINTEREST_REFRESH_TOKEN,
# PINTEREST_APP_ID and PINTEREST_APP_SECRET. The keys live in the secrets and
# nowhere else; a minted token is kept in memory only.

def _env(k: str) -> str:
    return (os.environ.get(k) or "").strip()


def enabled() -> bool:
    return bool(_env("PINTEREST_ACCESS_TOKEN") or
                (_env("PINTEREST_REFRESH_TOKEN") and _env("PINTEREST_APP_ID") and _env("PINTEREST_APP_SECRET")))


def scrape_on() -> bool:
    """The Apify pins, switched on by hand (PINTEREST_SCRAPE = "1")."""
    return _env("PINTEREST_SCRAPE").lower() in ("1", "true", "yes", "on")


def is_pinterest(*names) -> bool:
    """Is this brief ABOUT Pinterest? Then only official data may be used."""
    return any("pinterest" in str(n or "").lower() for n in names)


def _http(method: str, url: str, headers: dict, data: Optional[bytes] = None,
          timeout: float = 20.0) -> tuple:
    """(status, body bytes). HTTP errors come back as their status, not raised."""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        except Exception:
            return exc.code, b""


_TOK = {"token": "", "exp": 0.0, "err": "", "err_t": 0.0}
_LOCK = threading.Lock()


def _why(status: int, body: bytes = b"") -> str:
    msg = ""
    try:
        msg = str((json.loads(body or b"{}") or {}).get("message") or "")[:140]
    except Exception:
        msg = ""
    plain = {401: "Pinterest refused the token — renew PINTEREST_ACCESS_TOKEN in the secrets",
             403: "this Pinterest app is not cleared for the Trends API yet — ask your Pinterest "
                  "representative to switch it on",
             429: "Pinterest is limiting requests — the next scan will try again"}.get(status)
    return plain or (f"Pinterest answered {status}" + (f": {msg}" if msg else ""))


def access_token(http: Callable = _http, now: Optional[float] = None) -> tuple:
    """(token, "") — or ("", why not)."""
    tok = _env("PINTEREST_ACCESS_TOKEN")
    if tok:
        return tok, ""
    ref, app, sec = _env("PINTEREST_REFRESH_TOKEN"), _env("PINTEREST_APP_ID"), _env("PINTEREST_APP_SECRET")
    if not (ref and app and sec):
        return "", "no PINTEREST_ACCESS_TOKEN in the secrets"
    now = time.time() if now is None else now
    with _LOCK:
        if _TOK["token"] and _TOK["exp"] - now > 300:
            return _TOK["token"], ""
        if _TOK["err"] and now - _TOK["err_t"] < 60:
            return "", _TOK["err"]
    basic = base64.b64encode(f"{app}:{sec}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": ref}).encode()
    try:
        status, body = http("POST", f"{API_URL}/oauth/token",
                            {"Authorization": f"Basic {basic}",
                             "Content-Type": "application/x-www-form-urlencoded"}, data, 15.0)
    except Exception as exc:
        status, body = 0, str(exc).encode()
    if status == 200:
        try:
            obj = json.loads(body or b"{}")
        except ValueError:
            obj = {}
        tok = str(obj.get("access_token") or "")
        if tok:
            with _LOCK:
                _TOK.update(token=tok, exp=now + float(obj.get("expires_in") or 2592000), err="", err_t=0.0)
            return tok, ""
    why = ("Pinterest could not be reached" if status == 0 else
           "Pinterest refused the refresh token — make a new one in the developer portal"
           if status in (400, 401) else _why(status, body))
    with _LOCK:
        _TOK.update(err=why, err_t=now)
    return "", why


# ── What to look for ─────────────────────────────────────────────────────────

def region_for(market: str) -> tuple:
    """(region, note) — the note says when the region is wider than the market."""
    r = MARKET_REGION.get(str(market or "").strip(), "US")
    note = ""
    if market == "Portugal":
        note = "Pinterest reads Portugal inside Southern Europe"
    elif market == "Worldwide" or not market:
        note = "Pinterest Trends works by region — the US is shown"
    elif str(market).strip() not in MARKET_REGION:
        note = f"Pinterest has no region for {market} — the US is shown"
    return r, note


def _words(s: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", str(s or "").lower()) if len(w) >= 3 and w not in _STOP]


def include_words(category: str, product: str, focus: str = "", brand: str = "") -> list:
    """The words a Pinterest search would contain, at most three.

    The product's phrase first (its last two words: the product noun ends the
    phrase), then the category's, then Must mention. A lone head noun only
    when there is nothing longer — "water" on its own brings back watercolours
    and water nails. For a brief about Pinterest itself there is nothing to
    filter by: what matters is what is rising across Pinterest, so the list is
    empty on purpose."""
    if is_pinterest(brand, category, product):
        return []
    out = []
    for phrase in (product, category):
        w = _words(phrase)
        if len(w) >= 2:
            out.append(" ".join(w[-2:]))
        elif w:
            out.append(w[0])
    for f in re.split(r"[,;]", str(focus or "")):
        w = _words(f)
        if w:
            out.append(" ".join(w[:2]))
    seen, keep = set(), []
    for x in out:
        if x and x not in seen and len(x) >= 3:
            seen.add(x)
            keep.append(x)
    return keep[:3]


# ── The call ─────────────────────────────────────────────────────────────────

_CACHE: dict = {}


def _num(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def parse_trends(obj) -> list:
    """The API's answer → [{keyword, wow, mom, yoy, series: [[date, value]…]}]."""
    out = []
    rows = (obj or {}).get("trends") if isinstance(obj, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        kw = re.sub(r"\s+", " ", str(r.get("keyword") or "")).strip()[:80]
        if not kw:
            continue
        ts = r.get("time_series") if isinstance(r.get("time_series"), dict) else {}
        series = []
        for d, v in ts.items():
            n = _num(v)
            if n is not None and re.match(r"^\d{4}-\d{2}-\d{2}", str(d)):
                series.append([str(d)[:10], max(0, min(100, n))])
        series.sort(key=lambda x: x[0])
        out.append({"keyword": kw, "wow": _num(r.get("pct_growth_wow")),
                    "mom": _num(r.get("pct_growth_mom")), "yoy": _num(r.get("pct_growth_yoy")),
                    "series": series[-60:]})
    return out


def fetch(region: str, trend_type: str, include: str = "", limit: int = 50, token: str = "",
          http: Callable = _http, now: Optional[float] = None) -> list:
    """One call to List trending keywords. Raises PinterestError."""
    if region not in REGIONS:
        raise PinterestError(400, f"Pinterest has no region {region}")
    now = time.time() if now is None else now
    key = (region, trend_type, include.lower())
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return [dict(x) for x in hit[1]]
    q = {"limit": str(max(1, min(50, int(limit))))}
    if include:
        q["include_keywords"] = include      # one per call: no doubt about how arrays travel
    url = (f"{API_URL}/trends/keywords/{urllib.parse.quote(region, safe='+')}/top/"
           f"{urllib.parse.quote(trend_type)}?{urllib.parse.urlencode(q)}")
    try:
        status, body = http("GET", url, {"Authorization": f"Bearer {token}",
                                         "Accept": "application/json"}, None, 20.0)
    except Exception as exc:
        raise PinterestError(0, f"Pinterest could not be reached ({type(exc).__name__})")
    if status != 200:
        raise PinterestError(status, _why(status, body))
    try:
        items = parse_trends(json.loads(body or b"{}"))
    except ValueError:
        raise PinterestError(status, "Pinterest sent something that is not JSON")
    _CACHE[key] = (now, items)
    return [dict(x) for x in items]


def contains(keyword: str, phrase: str) -> bool:
    """Does a trending search contain the phrase? Every word of it, singular or
    plural: "sneaker outfits" contains "sneakers", "mocktail" does not contain
    "sparkling water"."""
    k = re.sub(r"[^a-z0-9]+", " ", str(keyword or "").lower())
    for w in re.findall(r"[a-z0-9]+", str(phrase or "").lower()):
        stem = w[:-1] if len(w) > 3 and w.endswith("s") else w
        if not re.search(rf"\b{re.escape(stem)}(?:s|es)?\b", k):
            return False
    return True


def trends_url(keyword: str, region: str) -> str:
    country = (region or "US").split("+")[0]
    return f"{TRENDS_SITE}/search/?{urllib.parse.urlencode({'q': keyword, 'country': country})}"


def week_of(items: list) -> str:
    """The week the figures describe: the last observation's date (end of week)."""
    last = [it["series"][-1][0] for it in items or [] if it.get("series")]
    return max(last) if last else ""


def gather(brand: str, category: str, product: str = "", focus: str = "", market: str = "",
           http: Callable = _http, now: Optional[float] = None, max_items: int = MAX_ITEMS) -> dict:
    """Pinterest's growing searches for this brief. Never raises.

    {"items": [...], "region", "region_name", "keywords", "week", "calls",
     "error", "note", "skipped", "about_pinterest"}"""
    region, note = region_for(market)
    kws = include_words(category, product, focus, brand)
    about = is_pinterest(brand, category, product)
    out = {"items": [], "region": region, "region_name": REGION_NAME.get(region, region),
           "keywords": kws, "week": "", "calls": 0, "error": "", "note": note, "skipped": "",
           "about_pinterest": about, "at": datetime.utcnow().isoformat(timespec="seconds")}
    if not enabled():
        out["skipped"] = "no PINTEREST_ACCESS_TOKEN in the secrets"
        return out
    if not kws and not about:
        out["skipped"] = "no category or product words to look for"
        return out
    token, why = access_token(http, now)
    if not token:
        out["error"] = why
        return out
    merged: dict = {}
    errs = []
    for tt in TREND_TYPES:
        for kw in (kws or [""]):
            try:
                got = fetch(region, tt, kw, 50 if kw else 25, token, http, now)
                out["calls"] += 1
            except PinterestError as exc:
                errs.append(exc)
                if exc.status in (401, 403):
                    break                     # the same answer for every other call
                continue
            for rank, it in enumerate(got):
                k = it["keyword"].lower()
                if kw and not contains(k, kw):
                    continue                  # the filter is Pinterest's; checked again here
                prev = merged.get(k)
                if prev:
                    prev["types"] = sorted(set(prev["types"]) | {tt})
                    continue
                merged[k] = dict(it, types=[tt], match=kw, rank=rank, region=region,
                                 url=trends_url(it["keyword"], region))
        if errs and errs[-1].status in (401, 403):
            break
    if not merged and errs:
        out["error"] = str(errs[0])
        return out
    # The early ones first (growing), then by how fast they climb this month.
    items = sorted(merged.values(), key=lambda x: ("growing" not in x["types"],
                                                    -(x.get("mom") if x.get("mom") is not None else -10 ** 6),
                                                    x["rank"]))
    out["items"] = items[:max_items]
    out["week"] = week_of(out["items"])
    if errs and out["items"]:
        out["note"] = (out["note"] + "; " if out["note"] else "") + f"{len(errs)} call(s) failed: {errs[0]}"
    return out


# ── How it is said ───────────────────────────────────────────────────────────

def pct(v) -> str:
    """+120% · −8% · '' — capped as Pinterest caps it (10001 = more than 10,000%)."""
    if v is None:
        return ""
    if v > 10000:
        return ">10,000%"
    return (f"+{v:,}%" if v > 0 else (f"−{abs(v):,}%" if v < 0 else "0%"))


def headline(it: dict) -> tuple:
    """(figure, what it measures) — the bigger of the year's and the month's growth."""
    yoy, mom = it.get("yoy"), it.get("mom")
    if yoy is not None and (mom is None or abs(yoy) >= abs(mom)):
        return pct(yoy), "on a year ago"
    if mom is not None:
        return pct(mom), "on last month"
    if it.get("wow") is not None:
        return pct(it["wow"]), "on last week"
    return "", ""


def growth_line(it: dict) -> str:
    bits = []
    for k, lab in (("yoy", "on a year ago"), ("mom", "on last month"), ("wow", "on last week")):
        if it.get(k) is not None:
            bits.append(f"{pct(it[k])} {lab}")
    return " · ".join(bits)


def _day(d: str) -> str:
    try:
        x = datetime.strptime(str(d)[:10], "%Y-%m-%d")
        return f"{x.day} {x.strftime('%b %Y')}"
    except ValueError:
        return str(d or "")


def prompt_block(found: dict) -> str:
    """The PINTEREST SEARCHES block for a model prompt — [P#] lines, figures verbatim."""
    items = (found or {}).get("items") or []
    if not items:
        return ""
    rows = [f'[P{i}] "{it["keyword"]}" — {growth_line(it)}' for i, it in enumerate(items)]
    scope = (f"the searches rising fastest across Pinterest in {found.get('region_name')}"
             if found.get("about_pinterest") else
             f"searches containing {', '.join(repr(k) for k in found.get('keywords') or [])} that are growing on "
             f"Pinterest in {found.get('region_name')}")
    return (f"\nPINTEREST SEARCHES (Pinterest Trends API, week ending {_day(found.get('week'))}: {scope}. "
            "What people are PLANNING — an early signal, ahead of what they post. Quote a growth "
            "figure exactly as written here, always with 'on Pinterest', and cite it by [P#]):\n"
            + "\n".join(rows) + "\n")


def texts(found: dict) -> list:
    """The same lines as plain text, so the percentage check knows these figures exist."""
    return [f'Pinterest searches for "{it["keyword"]}" {growth_line(it)}'
            for it in (found or {}).get("items") or []]


def as_figures(found: dict) -> list:
    """For the live session's dig: Pinterest's searches as figures it may cite."""
    out = []
    for it in (found or {}).get("items") or []:
        fig, what = headline(it)
        if not fig:
            continue
        out.append({"figure": fig, "claim": f'Pinterest searches for "{it["keyword"]}", {what} '
                                            f'({found.get("region_name")})',
                    "source": "Pinterest Trends", "date": found.get("week", ""), "url": it.get("url", "")})
    return out


def sparkline(series: list, w: int = 120, h: int = 34, color: str = "") -> str:
    """A year of weekly interest as a small inline SVG (blue line, faint area).
    With `color` the strokes are written inline — for documents that do not
    carry the brief's stylesheet (the PDF)."""
    pts = [v for _, v in (series or [])][-52:]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1
    step = w / (len(pts) - 1)
    xy = [(round(i * step, 1), round(h - 2 - (v - lo) * (h - 4) / span, 1)) for i, v in enumerate(pts)]
    line = "M" + " L".join(f"{x},{y}" for x, y in xy)
    area = line + f" L{xy[-1][0]},{h} L0,{h} Z"
    if color and re.match(r"^#[0-9a-fA-F]{3,8}$", color):
        return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
                f'style="display:block;width:100%;height:{h}px;margin:6px 0 8px;" '
                f'aria-label="Weekly search interest over the last year">'
                f'<path d="{area}" fill="{color}" fill-opacity="0.08" stroke="none"/>'
                f'<path d="{line}" fill="none" stroke="{color}" stroke-width="1.6" '
                f'vector-effect="non-scaling-stroke"/></svg>')
    return (f'<svg class="pnline" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
            f'aria-label="Weekly search interest over the last year">'
            f'<path class="area" d="{area}"/><path d="{line}"/></svg>')
