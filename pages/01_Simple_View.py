"""
Lighthouse · Simple View
========================
Alternative one-page layout based on Pat's sketch (Jul 2026).
Designed to be instantly readable by someone who has never used Lighthouse.

Sections:
  1. WHAT IS TRENDING NOW          — 3 trend summaries + "Dig deeper" (sources/links)
  2. CONSUMER INSIGHTS RIGHT NOW   — synthesis + real posts/comments worth attention
  3. COMPETITOR CURRENTS           — what competitors are doing / the clichés everyone follows
  4. TEST YOUR HUNCH               — hypothesis in → data supports or challenges it

The main app (app.py) is untouched — this is an additive alternative view.
"""

import os
import json
import html as html_mod

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Secrets injection (Streamlit Cloud) ────────────────────────────────────────
try:
    for _k, _v in st.secrets.items():
        if _k not in os.environ:
            os.environ[_k] = str(_v)
except Exception:
    pass

st.set_page_config(
    page_title="Lighthouse · Simple View",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def e(text) -> str:
    return html_mod.escape(str(text))


# ── Require login (session is shared with the main app page) ──────────────────
if not st.session_state.get("logged_in_user"):
    st.markdown(
        "<div style='text-align:center;padding:5rem 2rem;font-family:Georgia,serif;'>"
        "<div style='font-size:2rem;margin-bottom:1rem;'>🗼</div>"
        "<div style='font-size:18px;color:#071828;'>Please log in first</div>"
        "<div style='font-size:13px;color:#6ea8c4;margin-top:8px;'>"
        "Open the main <b>app</b> page in the sidebar, log in, then come back here.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

# ── Client context (shared session state with main page; default Rambler) ─────
_ACTIVE = st.session_state.get("active_client", "Rambler")

_PROFILES = {
    "Rambler": {
        "category":    "mineral sparkling water",
        "tagline":     "Monitoring the currents of the mineral sparkling water category so Rambler can build the countercurrent.",
        "search":      "sparkling water mineral water",
        "competitors": ["Topo Chico", "Liquid Death", "LaCroix", "Waterloo", "Spindrift", "Perrier"],
        "beacon":      "#0f5c9e",
    },
    "Heinz": {
        "category":    "comfort food & soup",
        "tagline":     "Monitoring the currents of Britain's lunch culture so Heinz can build the countercurrent.",
        "search":      "comfort food soup lunch",
        "competitors": ["Cully & Sully", "New Covent Garden", "Batchelors", "Cup-a-Soup"],
        "beacon":      "#cf2b29",
    },
}
_P = _PROFILES.get(_ACTIVE, _PROFILES["Rambler"])

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ── Styles ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
#MainMenu, header, footer {{ visibility: hidden; }}
.block-container {{ padding-top: 2rem; max-width: 1150px; }}

.sv-masthead {{ text-align:center; padding: 1.2rem 0 0.6rem; }}
.sv-logo {{ display:inline-block; font-family:Georgia,serif; font-size: 30px; font-weight:700;
  letter-spacing:.14em; color:#071828; border:2.5px solid #071828; border-radius:6px;
  padding: 6px 22px; }}
.sv-tagline {{ font-family:Georgia,serif; font-style:italic; font-size:15.5px; color:#274d68;
  max-width: 620px; margin: 14px auto 0; line-height:1.55; }}

.sv-section {{ border-top: 2.5px solid #071828; margin-top: 2.6rem; padding-top: 1.1rem; }}
.sv-q {{ font-family:Georgia,serif; font-size: 21px; font-weight:600; color:#071828;
  line-height:1.35; margin-bottom: 4px; }}
.sv-sub {{ font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:.14em;
  text-transform:uppercase; color:{_P["beacon"]}; margin-bottom: 14px; }}

.sv-card {{ background:#fff; border:1.5px solid #071828; border-radius:8px;
  padding: 16px 18px; height: 100%; }}
.sv-card-title {{ font-family:Georgia,serif; font-size:15.5px; font-weight:700; color:#071828;
  margin-bottom:8px; line-height:1.35; }}
.sv-card-body {{ font-size:13px; color:#33566b; line-height:1.6; }}

.sv-quote {{ background:#f4f9fb; border-left:3px solid {_P["beacon"]};
  border-radius:0 8px 8px 0; padding: 12px 16px; margin-bottom: 10px; }}
.sv-quote-text {{ font-family:Georgia,serif; font-style:italic; font-size:14px; color:#071828;
  line-height:1.55; }}
.sv-quote-meta {{ font-family:'JetBrains Mono',monospace; font-size:10px; color:#6ea8c4;
  margin-top:6px; text-transform:uppercase; letter-spacing:.06em; }}
.sv-quote-meta a {{ color:{_P["beacon"]}; text-decoration:none; }}

.sv-headline {{ font-family:Georgia,serif; font-size:15px; font-weight:600; color:#071828;
  padding: 10px 0; border-bottom: 1px solid #d0e4ed; line-height:1.4; }}
.sv-headline small {{ display:block; font-family:'JetBrains Mono',monospace; font-size:10px;
  font-weight:400; color:#6ea8c4; margin-top:3px; text-transform:uppercase; }}

.sv-cliche {{ display:inline-block; background:#fdf1ee; color:#c94f35;
  border:1px solid #eac6bc; border-radius:20px; padding: 4px 13px; font-size:12px;
  margin: 0 6px 8px 0; font-family:'JetBrains Mono',monospace; }}

.sv-empty {{ text-align:center; padding: 2.2rem; color:#9dc4d8;
  font-family:Georgia,serif; font-style:italic; font-size:14px; }}
</style>
""", unsafe_allow_html=True)

# ── Masthead ───────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="sv-masthead">
  <span class="sv-logo">LIGHTHOUSE</span>
  <div class="sv-tagline">{e(_P["tagline"])}</div>
</div>
""", unsafe_allow_html=True)

# ── Scan controls ──────────────────────────────────────────────────────────────
_c1, _c2, _c3 = st.columns([2, 1, 2])
with _c2:
    _run_scan = st.button("⚡ Scan the currents", use_container_width=True, type="primary")

_scan_status = st.empty()


def _set_status(msg: str) -> None:
    _scan_status.markdown(
        f'<div style="text-align:center;font-family:\'JetBrains Mono\',monospace;'
        f'font-size:11.5px;color:#0a5560;padding:6px;">{e(msg)}…</div>',
        unsafe_allow_html=True,
    )


# ── Gather signals (cost-aware caps) ──────────────────────────────────────────
def _gather(search_terms: str) -> list[dict]:
    out: list[dict] = []
    apify = os.environ.get("APIFY_API_TOKEN", "")
    ytkey = os.environ.get("YOUTUBE_API_KEY", "")
    fckey = os.environ.get("FIRECRAWL_API_KEY", "")

    from ingestion import (scrape_reddit, scrape_gdelt, scrape_hacker_news,
                           scrape_youtube, scrape_tiktok, scrape_instagram,
                           scrape_twitter)

    def _push(sigs, src):
        for s in sigs:
            out.append({
                "title": s.title, "content": s.content, "source": src,
                "url": s.url, "timestamp": s.timestamp,
            })

    try:
        _set_status(f"[Reddit] searching '{search_terms}'")
        _push(scrape_reddit(search_terms, max_items=10), "reddit")
    except Exception:
        pass
    try:
        _set_status("[GDELT] scanning news")
        _push(scrape_gdelt(search_terms, n=8), "gdelt")
    except Exception:
        pass
    try:
        _set_status("[Hacker News] searching")
        _push(scrape_hacker_news(search_terms, n=5), "hacker_news")
    except Exception:
        pass
    if ytkey:
        try:
            _set_status("[YouTube] searching")
            _seen: set = set()
            for kw in search_terms.split()[:2]:
                for s in scrape_youtube(kw, api_key=ytkey, n=5, region_code="US"):
                    if s.url not in _seen:
                        _seen.add(s.url)
                        out.append({"title": s.title, "content": s.content,
                                    "source": "youtube", "url": s.url,
                                    "timestamp": s.timestamp})
        except Exception:
            pass
    if apify:
        try:
            _set_status("[TikTok] searching via Apify")
            _push(scrape_tiktok(search_terms, api_token=apify, n=8,
                                fetch_comments=False), "tiktok")
        except Exception:
            pass
        try:
            _set_status("[Instagram] searching via Apify")
            _push(scrape_instagram(search_terms, api_token=apify, n=5), "instagram")
        except Exception:
            pass
        try:
            _set_status("[X/Twitter] searching via Apify")
            _push(scrape_twitter(search_terms, api_token=apify, n=8), "twitter")
        except Exception:
            pass
    if fckey:
        try:
            from ingestion import scrape_web
            _set_status("[Web] searching via Firecrawl")
            _push(scrape_web(search_terms, api_key=fckey, n=6), "web")
        except Exception:
            pass

    # Saved DB signals for this client (free, already paid for)
    try:
        import db as _db
        _set_status("Reading saved signal database")
        for s in _db.load_signals(limit=200):
            tag = str(s.get("client_tag") or "").lower()
            if _ACTIVE.lower() in tag or (not tag and _ACTIVE == "Heinz"):
                out.append({"title": s.get("title", ""), "content": s.get("content", ""),
                            "source": s.get("source", "db"), "url": s.get("url", ""),
                            "timestamp": s.get("timestamp", "")})
    except Exception:
        pass

    return out


# ── Claude synthesis ───────────────────────────────────────────────────────────
def _synthesize(signals: list[dict]) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not signals:
        return {}
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    batch = signals[:60]
    sig_text = "\n\n".join(
        f"[{i}] SOURCE: {s['source']} | URL: {s['url']}\n"
        f"TITLE: {s['title'][:110]}\nCONTENT: {s['content'][:260]}"
        for i, s in enumerate(batch)
    )
    competitors = ", ".join(_P["competitors"])

    prompt = f"""You are a sharp cultural strategist analysing the {_P["category"]} category.

Below are {len(batch)} signals collected from social media, news, communities and the web.

SIGNALS:
{sig_text}

Produce a JSON object with EXACTLY this shape (respond with ONLY valid JSON, no markdown):

{{
  "trends": [
    {{"title": "short punchy trend name", "summary": "2-3 sentences explaining the trend in plain language", "signal_indexes": [0, 5, 12]}},
    ... exactly 3 trends ...
  ],
  "insights_summary": "3-4 sentences: what are consumers really saying about {_P["category"]} that deserves attention? Complaints, love, tensions, surprises.",
  "insight_quotes": [
    {{"signal_index": 3, "why": "one short line on why this post matters"}},
    ... 4 to 6 real signals that best illustrate consumer sentiment — pick posts/comments with authentic human voice ...
  ],
  "competitors_summary": "3-4 sentences: what are competitors ({competitors}) doing right now? What moves, campaigns, positioning?",
  "cliches": ["cliché or bandwagon 1", "cliché 2", "cliché 3", "cliché 4"],
  "competitor_headlines": [
    {{"headline": "short headline of a competitor move", "signal_index": 7}},
    ... exactly 3 ...
  ]
}}

Rules:
- signal_indexes must reference real indexes from the list above.
- "cliches" = the trends/tropes EVERY brand in the category is following (useful to counter later).
- Plain, punchy language. No jargon."""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except Exception:
            return {}
    return {}


# ── Run scan ───────────────────────────────────────────────────────────────────
if _run_scan:
    with st.spinner(""):
        _signals = _gather(_P["search"])
        _set_status(f"Claude synthesising {len(_signals)} signals")
        _result = _synthesize(_signals)
    _scan_status.empty()
    if _result:
        st.session_state["sv_result"]  = _result
        st.session_state["sv_signals"] = _signals
        st.session_state["sv_client"]  = _ACTIVE
        st.rerun()
    else:
        st.error("Scan produced no synthesis — check API keys or try again.")

_res  = st.session_state.get("sv_result") if st.session_state.get("sv_client") == _ACTIVE else None
_sigs = st.session_state.get("sv_signals", [])

_SRC_LABEL = {"reddit": "Reddit", "gdelt": "News", "hacker_news": "HN", "youtube": "YouTube",
              "tiktok": "TikTok", "instagram": "Instagram", "twitter": "X/Twitter",
              "web": "Web", "rss": "RSS", "db": "Archive"}


def _sig(idx):
    try:
        return _sigs[int(idx)]
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — WHAT IS TRENDING NOW
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div class="sv-section">
  <div class="sv-q">What is trending now in {e(_P["category"])}?</div>
  <div class="sv-sub">Three currents, summarised</div>
</div>
""", unsafe_allow_html=True)

if _res and _res.get("trends"):
    _tcols = st.columns(3)
    for _i, _t in enumerate(_res["trends"][:3]):
        with _tcols[_i]:
            st.markdown(f"""
<div class="sv-card">
  <div class="sv-card-title">{e(_t.get("title",""))}</div>
  <div class="sv-card-body">{e(_t.get("summary",""))}</div>
</div>""", unsafe_allow_html=True)
            with st.expander("🔍 Dig deeper"):
                _idxs = _t.get("signal_indexes", [])
                if not _idxs:
                    st.caption("No linked sources for this trend.")
                for _ix in _idxs[:6]:
                    _s = _sig(_ix)
                    if _s:
                        _lbl = _SRC_LABEL.get(_s["source"], _s["source"].title())
                        st.markdown(
                            f"**[{_lbl}]** {e(_s['title'][:90])}  \n"
                            + (f"[Open source ↗]({_s['url']})" if _s.get("url") else ""),
                        )
else:
    st.markdown('<div class="sv-empty">Press ⚡ Scan the currents to fill this page.</div>',
                unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — CONSUMER INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div class="sv-section">
  <div class="sv-q">What are the most insightful consumer posts, comments and critiques right now?</div>
  <div class="sv-sub">From social, communities, Reddit — complaints, love and everything between</div>
</div>
""", unsafe_allow_html=True)

if _res:
    if _res.get("insights_summary"):
        st.markdown(
            f'<div class="sv-card" style="margin-bottom:16px;">'
            f'<div class="sv-card-body" style="font-size:14px;">{e(_res["insights_summary"])}</div></div>',
            unsafe_allow_html=True,
        )
    for _q in _res.get("insight_quotes", [])[:6]:
        _s = _sig(_q.get("signal_index"))
        if not _s:
            continue
        _lbl = _SRC_LABEL.get(_s["source"], _s["source"].title())
        _link = f' · <a href="{_s["url"]}" target="_blank">open ↗</a>' if _s.get("url") else ""
        _text = (_s["content"] or _s["title"])[:280]
        st.markdown(f"""
<div class="sv-quote">
  <div class="sv-quote-text">&ldquo;{e(_text)}&rdquo;</div>
  <div class="sv-quote-meta">{e(_lbl)} · {e(_q.get("why",""))}{_link}</div>
</div>""", unsafe_allow_html=True)
elif not _res:
    st.markdown('<div class="sv-empty">Waiting for a scan…</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — COMPETITOR CURRENTS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div class="sv-section">
  <div class="sv-q">What are the latest moves from competitors in the category?</div>
  <div class="sv-sub">{e(" · ".join(_P["competitors"]))}</div>
</div>
""", unsafe_allow_html=True)

if _res:
    if _res.get("competitors_summary"):
        st.markdown(
            f'<div class="sv-card" style="margin-bottom:16px;">'
            f'<div class="sv-card-body" style="font-size:14px;">{e(_res["competitors_summary"])}</div></div>',
            unsafe_allow_html=True,
        )
    for _h in _res.get("competitor_headlines", [])[:3]:
        _s = _sig(_h.get("signal_index"))
        _link = f' <a href="{_s["url"]}" target="_blank" style="font-size:11px;">↗</a>' if _s and _s.get("url") else ""
        _lbl = _SRC_LABEL.get(_s["source"], "") if _s else ""
        st.markdown(
            f'<div class="sv-headline">{e(_h.get("headline",""))}{_link}'
            f'<small>{e(_lbl)}</small></div>',
            unsafe_allow_html=True,
        )
    if _res.get("cliches"):
        st.markdown(
            '<div style="margin-top:18px;font-family:\'JetBrains Mono\',monospace;'
            'font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#c94f35;'
            'margin-bottom:8px;">⚠ The clichés everyone is following — counter these to unlock white space</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            "".join(f'<span class="sv-cliche">{e(c)}</span>' for c in _res["cliches"][:6]),
            unsafe_allow_html=True,
        )
else:
    st.markdown('<div class="sv-empty">Waiting for a scan…</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — TEST YOUR HUNCH
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="sv-section">
  <div class="sv-q">Test your hunch</div>
  <div class="sv-sub">Type a potential countercurrent — the data supports or challenges it</div>
</div>
""", unsafe_allow_html=True)

_hcol1, _hcol2 = st.columns([5, 1])
with _hcol1:
    _hunch = st.text_input(
        "Hunch", label_visibility="collapsed",
        placeholder=f"e.g. {_ACTIVE} should position against alcohol, not against soda…",
        key="sv_hunch",
    )
with _hcol2:
    _test = st.button("Test →", use_container_width=True, key="sv_test")

if _test and _hunch.strip():
    if not _sigs:
        st.warning("Run ⚡ Scan the currents first — the hypothesis is tested against those signals.")
    else:
        _api = os.environ.get("ANTHROPIC_API_KEY", "")
        if _api:
            import anthropic as _ant
            _cl = _ant.Anthropic(api_key=_api)
            _batch = _sigs[:40]
            _stext = "\n\n".join(
                f"[{i}] [{s['source']}] {s['title'][:100]}\n{s['content'][:200]}"
                for i, s in enumerate(_batch)
            )
            _hprompt = f"""Hypothesis: "{_hunch}"

Signals:
{_stext}

Classify each relevant signal as SUPPORTS or CHALLENGES the hypothesis (skip irrelevant ones).
Respond ONLY with JSON:
{{"verdict": "one sentence overall read on the hypothesis",
  "supports": [{{"index": 0, "reason": "short reason"}}],
  "challenges": [{{"index": 4, "reason": "short reason"}}]}}"""
            with st.spinner("Testing against the signals…"):
                try:
                    _hr = _cl.messages.create(
                        model=CLAUDE_MODEL, max_tokens=1200,
                        messages=[{"role": "user", "content": _hprompt}],
                    )
                    _hraw = _hr.content[0].text.strip()
                    _hs, _he = _hraw.find("{"), _hraw.rfind("}") + 1
                    st.session_state["sv_hunch_result"] = json.loads(_hraw[_hs:_he])
                except Exception as _hexc:
                    st.error(f"Test failed: {_hexc}")

_hres = st.session_state.get("sv_hunch_result")
if _hres:
    st.markdown(
        f'<div class="sv-card" style="margin:14px 0;"><div class="sv-card-body" '
        f'style="font-size:14px;"><b>Verdict:</b> {e(_hres.get("verdict",""))}</div></div>',
        unsafe_allow_html=True,
    )
    _sc, _cc = st.columns(2)
    with _sc:
        st.markdown('<div class="sv-sub" style="color:#1a8a5a;">✓ Supports</div>',
                    unsafe_allow_html=True)
        for _it in _hres.get("supports", [])[:5]:
            _s = _sig(_it.get("index"))
            if _s:
                _lbl = _SRC_LABEL.get(_s["source"], _s["source"])
                _lk = f' <a href="{_s["url"]}" target="_blank">↗</a>' if _s.get("url") else ""
                st.markdown(
                    f'<div class="sv-quote" style="border-left-color:#1a8a5a;">'
                    f'<div class="sv-quote-text" style="font-size:13px;">{e(_s["title"][:100])}</div>'
                    f'<div class="sv-quote-meta">{e(_lbl)} · {e(_it.get("reason",""))}{_lk}</div></div>',
                    unsafe_allow_html=True,
                )
    with _cc:
        st.markdown('<div class="sv-sub" style="color:#c94f35;">✗ Challenges</div>',
                    unsafe_allow_html=True)
        for _it in _hres.get("challenges", [])[:5]:
            _s = _sig(_it.get("index"))
            if _s:
                _lbl = _SRC_LABEL.get(_s["source"], _s["source"])
                _lk = f' <a href="{_s["url"]}" target="_blank">↗</a>' if _s.get("url") else ""
                st.markdown(
                    f'<div class="sv-quote" style="border-left-color:#c94f35;">'
                    f'<div class="sv-quote-text" style="font-size:13px;">{e(_s["title"][:100])}</div>'
                    f'<div class="sv-quote-meta">{e(_lbl)} · {e(_it.get("reason",""))}{_lk}</div></div>',
                    unsafe_allow_html=True,
                )

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin-top:3rem;padding:14px 0;border-top:1px solid #d0e4ed;'
    'font-family:\'JetBrains Mono\',monospace;font-size:9.5px;letter-spacing:.1em;'
    'text-transform:uppercase;color:#9dc4d8;text-align:center;">'
    'The Lighthouse · Simple View · Signals, not solutions — the countercurrent is yours to build'
    '</div>',
    unsafe_allow_html=True,
)
