"""
The Lighthouse — Countercurrent.ai v3
Cultural Intelligence Engine for Strategy Teams

Architecture:
  - Claude (Anthropic)   → strategic content generation (LLM)
  - Gemini embeddings    → vector search (unchanged)
  - Pinecone             → vector database (unchanged)
  - Apify + Reddit + RSS → data ingestion (unchanged)
  - SendGrid             → email dispatch (unchanged)

Run:
    streamlit run app.py
"""

import os
import json
import html as html_mod
from datetime import datetime
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Secrets injection (Streamlit Cloud) ────────────────────────────────────────
try:
    for key, value in st.secrets.items():
        if key not in os.environ:
            os.environ[key] = str(value)
except Exception:
    pass

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="The Lighthouse",
    page_icon="🗼",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
#MainMenu, header, footer { visibility: hidden; }
.block-container { padding: 0.5rem 0.5rem 0 !important; max-width: 100% !important; }
section[data-testid="stSidebar"] { background: #0f0e0c; }
section[data-testid="stSidebar"] * { color: #c8c0b4 !important; }
section[data-testid="stSidebar"] .stButton > button {
    background: #1a1714 !important; border: 1px solid #3a3530 !important;
    color: #e8a838 !important; font-family: monospace !important;
    font-size: 0.72rem !important; text-transform: uppercase !important;
    letter-spacing: 0.08em !important; width: 100%;
}
section[data-testid="stSidebar"] .stButton > button:hover { border-color: #e8a838 !important; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] textarea {
    background: #1a1714 !important; border: 1px solid #2a2520 !important;
    color: #c8c0b4 !important; font-size: 0.82rem !important;
}
iframe { border: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Client brand config (from .env) ───────────────────────────────────────────
# Set these in .env to customise per client:
#   CLIENT_BEACON_COLOR = #cf2b29   (Heinz red, or any brand color)
#   CLIENT_BEACON_2     = #e0502f   (lighter shade of brand color)
#   CLIENT_PILL_COLOR   = #0a4a6e   (pill background — defaults to Atlantic blue)
#   AGENCY_NAME         = Atlantic · New York
CLIENT_BEACON_COLOR = os.environ.get("CLIENT_BEACON_COLOR", "#0a7d8c")   # default: teal
CLIENT_BEACON_2     = os.environ.get("CLIENT_BEACON_2",     "#0fa3b5")
CLIENT_PILL_COLOR   = os.environ.get("CLIENT_PILL_COLOR",   "#0a4a6e")
AGENCY_NAME         = os.environ.get("AGENCY_NAME",         "Atlantic · New York")

# ── Sidebar — config ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
<div style="font-family:'Georgia',serif;font-size:20px;color:#d0eaf0;margin-bottom:4px">
  🗼 THE LIGHTHOUSE
</div>
<div style="font-family:monospace;font-size:10px;color:#0fa3b5;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:16px">
  Atlantic · Countercurrent.ai · v3
</div>
""", unsafe_allow_html=True)

    client_name   = st.text_input("Client", value="Heinz Soup · United Kingdom")
    brief_tagline = st.text_input("Brief tagline", value="Reading Britain's lunch currents so Heinz can build the countercurrent.")
    focus_topic   = st.text_area(
        "Focus topic / brief",
        value="desk lunch, comfort food, cost of living, office return-to-work culture, UK workers",
        height=80,
    )
    client_filter = st.text_input("Client tag filter", value="", placeholder="Leave blank = all signals")

    st.markdown("---")
    use_pinecone  = st.checkbox("Use Pinecone semantic search", value=True)
    signal_limit  = st.slider("Signals to analyse", 10, 50, 20)

    st.markdown("---")
    st.markdown(
        '<div style="font-size:10px;color:#0fa3b5;font-family:monospace;'
        'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">'
        'Mode</div>',
        unsafe_allow_html=True,
    )
    live_mode = st.toggle("Live — call Claude", value=False,
                          help="OFF = mostra último dispatch salvo (sem custo).\nON = gera novo conteúdo via Claude.")
    regenerate = st.button("⚡  Sweep & Generate", use_container_width=True,
                           disabled=not live_mode)

    st.markdown("---")
    st.markdown(
        '<div style="font-size:10px;color:#555;font-family:monospace;'
        'text-transform:uppercase;letter-spacing:0.08em">Email Dispatch</div>',
        unsafe_allow_html=True,
    )
    email_to      = st.text_input("Send to", placeholder="strategist@agency.com", label_visibility="collapsed")
    send_email_btn = st.button("Send via SendGrid", use_container_width=True)

    st.markdown("---")
    st.markdown(
        '<div style="font-size:10px;color:#444;font-family:monospace">'
        'Claude · Gemini Embeddings · Pinecone · Apify</div>',
        unsafe_allow_html=True,
    )


# ── Data loaders ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_signals(path: str = "data/signals.jsonl", limit: int = 200) -> list:
    if not os.path.exists(path):
        return []
    signals = []
    with open(path) as f:
        for line in f:
            try:
                signals.append(json.loads(line))
            except Exception:
                pass
    signals.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return signals[:limit]


def semantic_search(query: str, top_k: int = 15, client_filter: Optional[str] = None) -> list:
    """Query Pinecone via existing vectorizer (Gemini embeddings — unchanged)."""
    try:
        from vectorizer import query_knowledge_base
        filter_meta = {"client_tag": client_filter} if client_filter else None
        return query_knowledge_base(query, top_k=top_k, filter_metadata=filter_meta)
    except ImportError:
        return []
    except Exception as exc:
        st.warning(f"Semantic search unavailable: {exc}")
        return []


def build_context(signals: list, rag_results: list, limit: int = 25) -> str:
    parts = []
    for r in rag_results[:10]:
        parts.append(
            f"SIGNAL [RAG · relevance {r['score']:.2f}] [{r.get('source','?').upper()}]\n"
            f"{r['text'][:450]}"
        )
    seen = {r["text"][:80] for r in rag_results}
    for s in signals[:limit]:
        snippet = f"{s.get('title','')}::{s.get('content','')}"
        if snippet[:80] in seen:
            continue
        seen.add(snippet[:80])
        parts.append(
            f"SIGNAL [{s.get('source','?').upper()}] {s.get('timestamp','')[:10]}\n"
            f"Title: {s.get('title','')}\n"
            f"Content: {s.get('content','')[:320]}"
        )
    return "\n\n---\n\n".join(parts[:25])


def save_dispatch(content: dict, topic: str):
    os.makedirs("data", exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "topic": topic,
        "content": content.get("lead", {}).get("title", ""),
        "full": content,
    }
    with open("data/dispatches.jsonl", "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── Claude model config ────────────────────────────────────────────────────────
# Switch model here based on your phase:
#   Testing  → "claude-haiku-4-5-20251001"  (~$0.014/call, ~350 calls per $5)
#   Staging  → "claude-sonnet-4-6"           (~$0.042/call, ~120 calls per $5)
#   Client   → "claude-opus-4-5"             (~$0.070/call,  ~70 calls per $5)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ── Claude generation ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are The Lighthouse — an elite cultural intelligence engine for advertising strategy teams.

You analyse raw social signals (Reddit, TikTok, RSS, web) and surface strategic intelligence for a brand. Your output feeds a beautiful editorial dashboard that strategists and clients read every morning.

Your writing is sharp, editorial, specific. You think like a senior strategist at a world-class agency: you don't describe trends, you interrogate them. Your pull quotes feel real. Your provocations make people uncomfortable in a productive way.

You return ONLY valid JSON — no markdown fences, no explanation, no preamble. Just the raw JSON object.
"""


def generate(signals: list, rag: list, client: str, tagline: str, topic: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY not found. Add it to .env or Streamlit Secrets.")
        return _fallback()

    try:
        import anthropic as _anthropic
        claude = _anthropic.Anthropic(api_key=api_key)
    except ImportError:
        st.error("anthropic package not installed. Run: pip install anthropic")
        return _fallback()

    context = build_context(signals, rag)
    today   = datetime.utcnow().strftime("%A, %d %B %Y")
    sources = sorted({s.get("source", "?") for s in signals})

    prompt = f"""Client: {client}
Brief: {tagline}
Focus: {topic}
Date: {today}
Signal database: {len(signals)} signals across {', '.join(sources[:8])}

SIGNALS:
{context}

Generate a complete Lighthouse briefing. Return a single JSON object with EXACTLY this shape (no markdown, no fences, raw JSON only):

{{
  "sweep": {{
    "currents_surfaced": <integer>,
    "rising_fast": <integer>,
    "needs_human": <integer>
  }},
  "lead": {{
    "topic_tags": ["tag1", "tag2"],
    "relevance": "Direct | Adjacent | Peripheral",
    "momentum_pct": "+XXX%",
    "momentum_period": "7d",
    "momentum_dir": "up | down | flat",
    "title": "Lead headline — punchy, editorial, max 15 words",
    "dek": "2-3 sentences. Specific cultural tensions. References actual signal content.",
    "pullquote": "Vivid composite quote, 1-2 sentences, written as if by a real person online.",
    "pullquote_cite": "Platform · Community · engagement metric",
    "signal_stack": [
      {{"platform": "Name", "text": "What this signal shows", "num": "Metric"}},
      {{"platform": "Name", "text": "...", "num": "..."}},
      {{"platform": "Name", "text": "...", "num": "..."}},
      {{"platform": "Name", "text": "...", "num": "..."}}
    ],
    "countercurrent_title": "One-sentence strategic directive. Imperative, bold.",
    "countercurrent_body": "2-3 sentences. Specific timing, tactics, formats. Practical."
  }},
  "cards": [
    {{
      "momentum_pct": "+XX%",
      "momentum_dir": "up | down | flat",
      "tags": "Category · Signal type",
      "title": "Card headline — max 12 words",
      "body": "2 sentences. Specific to signals.",
      "sources": "Platform · Platform",
      "reach": "X.XM reach",
      "spark": [30, 40, 55, 65, 75, 85, 95]
    }},
    {{"momentum_pct": "+XX%", "momentum_dir": "up", "tags": "...", "title": "...", "body": "...", "sources": "...", "reach": "...", "spark": [20, 35, 45, 55, 65, 75, 88]}},
    {{"momentum_pct": "+XX%", "momentum_dir": "up", "tags": "...", "title": "...", "body": "...", "sources": "...", "reach": "...", "spark": [25, 38, 48, 58, 68, 78, 90]}},
    {{"momentum_pct": "-XX%", "momentum_dir": "down", "tags": "Format War · Watch", "title": "A declining signal worth watching", "body": "...", "sources": "...", "reach": "...", "spark": [90, 82, 70, 60, 52, 44, 38]}}
  ],
  "voices": [
    {{"platform_class": "p-reddit", "platform_label": "Reddit · r/SubName", "engagement": "▲ 3.1k", "quote": "Vivid, specific, casual voice.", "handle": "u/realistic_handle", "rel_tag": "Short tag"}},
    {{"platform_class": "p-tiktok", "platform_label": "TikTok", "engagement": "410k views", "quote": "...", "handle": "@handle", "rel_tag": "..."}},
    {{"platform_class": "p-x", "platform_label": "X", "engagement": "12k likes", "quote": "...", "handle": "@handle", "rel_tag": "..."}},
    {{"platform_class": "p-mumsnet", "platform_label": "Mumsnet", "engagement": "240 replies", "quote": "...", "handle": "Username", "rel_tag": "..."}},
    {{"platform_class": "p-ig", "platform_label": "Instagram", "engagement": "22k likes", "quote": "...", "handle": "@handle", "rel_tag": "..."}},
    {{"platform_class": "p-reddit", "platform_label": "Reddit · r/SubName", "engagement": "▲ 5.4k", "quote": "...", "handle": "u/handle", "rel_tag": "..."}},
    {{"platform_class": "p-tiktok", "platform_label": "TikTok · Niche", "engagement": "880k views", "quote": "...", "handle": "@handle", "rel_tag": "..."}},
    {{"platform_class": "p-x", "platform_label": "X", "engagement": "8.3k likes", "quote": "...", "handle": "@handle", "rel_tag": "..."}},
    {{"platform_class": "p-reddit", "platform_label": "Reddit · r/SubName", "engagement": "▲ 1.9k", "quote": "...", "handle": "u/handle", "rel_tag": "..."}}
  ],
  "provocations": [
    {{"n": "01", "text": "Open strategic question, 20-30 words, makes a strategist uncomfortable.", "tag": "Short philosophical tag"}},
    {{"n": "02", "text": "...", "tag": "..."}},
    {{"n": "03", "text": "...", "tag": "..."}}
  ],
  "briefing": "The 07:00 briefing. 2-3 sentences. Chief strategist speaking to the room. Ends with a specific call to action.",
  "alerts": [
    {{"sev": "hi", "text": "<b>Short bold phrase</b> brief explanation", "time": "4h ago · Competitor threat"}},
    {{"sev": "mid", "text": "<b>Short bold phrase</b> brief explanation", "time": "42 min ago · Opportunity"}},
    {{"sev": "lo", "text": "<b>Short bold phrase</b> brief explanation", "time": "2h ago · Opportunity"}}
  ]
}}

Be specific. Steal language from the actual signals. Write like a world-class strategist."""

    try:
        msg = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            temperature=0.75,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip accidental markdown fences
        if "```" in raw:
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            raw   = raw[start:end]
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        st.warning(f"JSON parse error: {exc}. Using fallback.")
        return _fallback()
    except Exception as exc:
        st.error(f"Claude error: {exc}")
        return _fallback()


def _fallback() -> dict:
    return {
        "sweep": {"currents_surfaced": 0, "rising_fast": 0, "needs_human": 0},
        "lead": {
            "topic_tags": ["No data yet"],
            "relevance": "—",
            "momentum_pct": "—",
            "momentum_period": "—",
            "momentum_dir": "flat",
            "title": "No signals found — run ingestion first",
            "dek": (
                "The Lighthouse needs data. Run python NYLIBERTYingestion.py (or ingestion.py) "
                "to populate signals.jsonl, then switch to Live mode and generate."
            ),
            "pullquote": "The signal database is empty.",
            "pullquote_cite": "— System",
            "signal_stack": [
                {"platform": "System", "text": "No signals in database. Run ingestion.", "num": "0"}
            ],
            "countercurrent_title": "Run ingestion.py to populate the signal database.",
            "countercurrent_body": (
                "Once you have signals, The Lighthouse will generate a full strategic briefing automatically."
            ),
        },
        "cards": [],
        "voices": [],
        "provocations": [
            {"n": "01", "text": "What would you do if you had real data here?", "tag": "Run ingestion to find out"},
            {"n": "02", "text": "The countercurrent is hiding somewhere in the internet right now.", "tag": "Go get it"},
            {"n": "03", "text": "A brand that moves before the current peaks always looks like a genius in hindsight.", "tag": "Timing is everything"},
        ],
        "briefing": "No dispatch saved yet. Run ingestion.py, switch to Live mode, and generate.",
        "alerts": [{"sev": "mid", "text": "<b>No data</b> — run ingestion.py first", "time": "Now · System"}],
    }


# ── SendGrid email ─────────────────────────────────────────────────────────────

def send_email(to: str, subject: str, html_body: str) -> bool:
    import urllib.request
    api_key   = os.environ.get("SENDGRID_API_KEY")
    from_addr = os.environ.get("SENDGRID_FROM_EMAIL", "dispatch@countercurrent.ai")
    if not api_key:
        return False
    payload = json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_addr},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 202
    except Exception:
        return False


# ── HTML helpers ───────────────────────────────────────────────────────────────

def e(text) -> str:
    """HTML-escape for safe injection."""
    return html_mod.escape(str(text))

def _mclass(d: str) -> str:
    return {"up": "up", "down": "down"}.get(d, "flat")

def _marrow(d: str) -> str:
    return {"up": "▲", "down": "▼"}.get(d, "●")

def render_spark(values) -> str:
    bars = "".join(f'<i style="height:{v}%"></i>' for v in (values or [30, 40, 50, 60, 70, 80, 90]))
    return f'<div class="spark">{bars}</div>'

def render_signal_stack(stack: list) -> str:
    items = "".join(
        f'<div class="signal">'
        f'<span class="plat">{e(s.get("platform",""))}</span>'
        f'<span class="txt">{e(s.get("text",""))}</span>'
        f'<span class="num">{e(s.get("num",""))}</span>'
        f'</div>'
        for s in (stack or [])
    )
    return f'<div class="signal-stack">{items}</div>'

def render_card(c: dict) -> str:
    d = c.get("momentum_dir", "up")
    return (
        f'<article class="card">'
        f'<div class="ctop">'
        f'<span class="momentum {_mclass(d)}">{_marrow(d)} {e(c.get("momentum_pct",""))}</span>'
        f'<span class="brands">{e(c.get("tags",""))}</span>'
        f'</div>'
        f'<h3>{e(c.get("title",""))}</h3>'
        f'<p>{e(c.get("body",""))}</p>'
        f'{render_spark(c.get("spark"))}'
        f'<div class="card-foot">'
        f'<span>{e(c.get("sources",""))}</span>'
        f'<span class="reach">{e(c.get("reach",""))}</span>'
        f'</div></article>'
    )

def render_voice(v: dict) -> str:
    return (
        f'<div class="voice {e(v.get("platform_class","p-reddit"))}">'
        f'<div class="vtop">'
        f'<span class="plat">● {e(v.get("platform_label",""))}</span>'
        f'<span class="eng">{e(v.get("engagement",""))}</span>'
        f'</div>'
        f'<div class="q">&ldquo;{e(v.get("quote",""))}&rdquo;</div>'
        f'<div class="vbot">'
        f'<span class="handle">{e(v.get("handle",""))}</span>'
        f'<span class="rel">{e(v.get("rel_tag",""))}</span>'
        f'</div></div>'
    )

def render_alert(a: dict) -> str:
    # alert text may include <b> tags — intentionally NOT escaped
    return (
        f'<div class="alert">'
        f'<div class="sev {e(a.get("sev","mid"))}"></div>'
        f'<div><div class="atxt">{a.get("text","")}</div>'
        f'<div class="atime">{e(a.get("time",""))}</div></div>'
        f'</div>'
    )

def render_prov(p: dict) -> str:
    return (
        f'<div class="prov">'
        f'<span class="n">{e(p.get("n",""))}</span>'
        f'<p>{e(p.get("text",""))}</p>'
        f'<span class="tag">{e(p.get("tag",""))}</span>'
        f'</div>'
    )

def sources_pills(signals: list) -> str:
    srcs = sorted({s.get("source", "?") for s in signals})
    return "".join(
        f'<span class="src on"><span class="d"></span>{e(s)}</span>'
        for s in srcs[:8]
    )

def chip_buttons(lead: dict) -> str:
    return "".join(
        f'<button class="chip">{e(t)}</button>'
        for t in lead.get("topic_tags", [])[:4]
    )


# ── Full HTML renderer ─────────────────────────────────────────────────────────
# NOTE: All CSS curly braces are doubled ({{ }}) because this is an f-string.
#       Only {python_variable} expressions remain as single braces.

def build_html(content: dict, signals: list, client: str, tagline: str) -> str:
    sw     = content.get("sweep", {})
    lead   = content.get("lead", {})
    cards  = content.get("cards", [])
    voices = content.get("voices", [])
    provs  = content.get("provocations", [])
    alerts = content.get("alerts", [])

    today_str   = datetime.utcnow().strftime("%A, %d %B %Y")
    vol_no      = f"Vol. I · No. {datetime.utcnow().strftime('%j')}"
    ld          = lead.get("momentum_dir", "up")
    topic_str   = " · ".join(e(t) for t in lead.get("topic_tags", []))
    sig_n       = len(signals)
    sig_display = f"{sig_n/1000:.1f}K" if sig_n < 1_000_000 else f"{sig_n/1_000_000:.2f}M"

    cards_html  = "".join(render_card(c)  for c in cards[:4])
    voices_html = "".join(render_voice(v) for v in voices[:9])
    provs_html  = "".join(render_prov(p)  for p in provs[:3])
    alerts_html = "".join(render_alert(a) for a in alerts[:3])
    src_pills   = sources_pills(signals)
    chips_html  = chip_buttons(lead)

    # Client brand colors (from env)
    beacon      = CLIENT_BEACON_COLOR
    beacon_2    = CLIENT_BEACON_2
    pill_color  = CLIENT_PILL_COLOR
    agency      = e(AGENCY_NAME)

    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>The Lighthouse — {e(client)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,400..700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet"/>
<style>
:root{{
  /* ── Atlantic Ocean Palette ─────────────────────── */
  --paper:      #ebf2f7;
  --paper-2:    #dce9f2;
  --ink:        #071828;
  --ink-soft:   #274d68;
  --line:       #9dc4d8;
  --line-strong:#6ea8c4;
  --beacon:     {beacon};
  --beacon-2:   {beacon_2};
  --deep:       #062233;
  --atlantic:   #0a4a6e;
  --rising:     #1a8a6b;
  --falling:    #c94f35;
}}
*{{box-sizing:border-box;}} html{{scroll-behavior:smooth;}}
body{{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:'Inter',-apple-system,sans-serif; -webkit-font-smoothing:antialiased;
  background-image:
    radial-gradient(ellipse 80% 40% at 50% -10%, rgba(10,125,140,.08), transparent),
    radial-gradient(ellipse 60% 30% at 90% 110%, rgba(6,34,51,.05), transparent);
}}
.wrap{{max-width:1240px; margin:0 auto; padding:0 28px;}}
.masthead{{border-bottom:3px double var(--ink); padding-top:22px;}}
.masthead-top{{
  display:flex; justify-content:space-between; align-items:flex-end;
  font-family:'JetBrains Mono',monospace; font-size:11px;
  letter-spacing:.06em; text-transform:uppercase; color:var(--ink-soft);
  padding-bottom:14px; border-bottom:1px solid var(--line);
}}
.masthead-top .edition{{display:flex; gap:22px; align-items:center;}}
.live{{display:inline-flex; align-items:center; gap:7px; color:var(--ink); font-weight:700;}}
.live .dot{{width:8px; height:8px; border-radius:50%; background:var(--beacon); animation:pulse 2.4s infinite;}}
@keyframes pulse{{
  0%{{box-shadow:0 0 0 0 rgba(10,125,140,.5);}}
  70%{{box-shadow:0 0 0 10px rgba(10,125,140,0);}}
  100%{{box-shadow:0 0 0 0 rgba(10,125,140,0);}}
}}
.clientbar{{
  display:flex; justify-content:center; align-items:center; gap:10px; padding:12px 0 2px;
  font-family:'JetBrains Mono',monospace; font-size:11px;
  letter-spacing:.18em; text-transform:uppercase; color:var(--ink-soft);
}}
.clientbar .pill{{background:{pill_color}; color:#fff; padding:3px 11px; border-radius:3px; font-weight:700; letter-spacing:.08em;}}
.title-row{{display:flex; align-items:center; justify-content:center; gap:26px; padding:8px 0 10px;}}
.beacon-mark{{position:relative; width:54px; height:54px; flex:none;}}
.beacon-mark .tower{{
  position:absolute; left:50%; bottom:0; transform:translateX(-50%);
  width:14px; height:34px; background:linear-gradient(var(--ink),#1a3d52);
  clip-path:polygon(28% 0,72% 0,100% 100%,0 100%);
}}
.beacon-mark .lamp{{
  position:absolute; left:50%; top:7px; transform:translateX(-50%);
  width:14px; height:11px; background:var(--beacon); border-radius:3px 3px 0 0;
  box-shadow:0 0 16px 4px rgba(10,125,140,.55); z-index:2;
}}
.beacon-mark .beam{{
  position:absolute; left:50%; top:12px; width:0; height:0;
  transform-origin:left center;
  border-top:16px solid transparent; border-bottom:16px solid transparent;
  border-left:64px solid rgba(15,163,181,.28);
  animation:sweep-beam 7s ease-in-out infinite;
}}
@keyframes sweep-beam{{
  0%,100%{{transform:rotate(-32deg); opacity:.2;}}
  50%{{transform:rotate(28deg); opacity:.5;}}
}}
h1.logo{{font-family:'Fraunces',serif; font-weight:600; font-size:58px; letter-spacing:.01em; margin:0; line-height:.95; text-align:center;}}
h1.logo .the{{display:block; font-size:14px; letter-spacing:.42em; font-weight:500; margin-bottom:4px; color:var(--ink-soft);}}
.tagline{{text-align:center; font-family:'Fraunces',serif; font-style:italic; font-size:16px; color:var(--ink-soft); padding:6px 0 16px;}}
.sweep{{display:grid; grid-template-columns:repeat(5,1fr); border-bottom:1px solid var(--line);}}
.sweep .cell{{padding:16px 18px; border-right:1px solid var(--line);}}
.sweep .cell:last-child{{border-right:none;}}
.sweep .k{{font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.1em; color:var(--ink-soft);}}
.sweep .v{{font-family:'Fraunces',serif; font-size:30px; font-weight:500; margin-top:4px; line-height:1;}}
.sources-line{{display:flex; flex-wrap:wrap; gap:6px; margin-top:7px;}}
.src{{font-family:'JetBrains Mono',monospace; font-size:9.5px; padding:2px 6px; border:1px solid var(--line-strong); border-radius:20px; color:var(--ink-soft); background:var(--paper-2);}}
.src.on{{color:var(--ink); border-color:var(--ink);}}
.src .d{{display:inline-block; width:5px; height:5px; border-radius:50%; background:var(--rising); margin-right:4px; vertical-align:middle;}}
.controls{{display:flex; justify-content:space-between; align-items:center; gap:16px; margin:22px 0 18px; flex-wrap:wrap;}}
.chips{{display:flex; gap:8px; flex-wrap:wrap;}}
.chip{{font-size:12.5px; font-weight:500; padding:7px 14px; border:1px solid var(--line-strong); background:transparent; border-radius:30px; cursor:pointer; color:var(--ink-soft); transition:.15s; font-family:'Inter';}}
.chip:hover{{border-color:var(--ink); color:var(--ink);}}
.chip.active{{background:var(--ink); color:var(--paper); border-color:var(--ink);}}
.section-eyebrow{{font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--beacon); font-weight:700;}}
.grid{{display:grid; grid-template-columns:1fr 326px; gap:34px; padding-bottom:60px;}}
.lead{{border-top:2px solid var(--ink); padding-top:18px; margin-bottom:34px;}}
.lead .meta{{display:flex; gap:14px; align-items:center; font-family:'JetBrains Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--ink-soft); margin-bottom:12px; flex-wrap:wrap;}}
.tag-lead{{background:var(--beacon); color:#fff; padding:3px 9px; font-weight:700; border-radius:3px;}}
.lead h2{{font-family:'Fraunces',serif; font-weight:600; font-size:42px; line-height:1.04; margin:6px 0 14px; letter-spacing:-.01em; max-width:19ch;}}
.lead .dek{{font-size:17px; line-height:1.55; color:var(--ink-soft); max-width:62ch; font-family:'Fraunces',serif;}}
.lead-body{{display:grid; grid-template-columns:1.5fr 1fr; gap:28px; margin-top:22px; align-items:start;}}
.pullquote{{border-left:3px solid var(--beacon); padding:4px 0 4px 18px; font-family:'Fraunces',serif; font-style:italic; font-size:18px; line-height:1.45; color:var(--ink);}}
.pullquote cite{{display:block; font-style:normal; font-family:'JetBrains Mono',monospace; font-size:10.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--ink-soft); margin-top:10px;}}
.signal-stack{{margin-top:18px;}}
.signal{{display:flex; gap:12px; padding:11px 0; border-top:1px solid var(--line); font-size:13px; align-items:baseline;}}
.signal .plat{{font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; color:var(--ink-soft); width:66px; flex:none; letter-spacing:.05em;}}
.signal .txt{{line-height:1.4;}}
.signal .num{{margin-left:auto; font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--ink-soft); white-space:nowrap;}}
.counter{{background:var(--deep); color:#d0eaf0; border-radius:8px; padding:20px; position:relative; overflow:hidden;}}
.counter::before{{content:""; position:absolute; top:-40px; right:-40px; width:160px; height:160px; border-radius:50%; background:radial-gradient(circle, rgba(10,125,140,.25), transparent 70%);}}
.counter .lbl{{font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--beacon-2); font-weight:700;}}
.counter h4{{font-family:'Fraunces',serif; font-size:21px; font-weight:600; margin:8px 0 10px; line-height:1.2;}}
.counter p{{font-size:13.5px; line-height:1.5; color:rgba(208,234,240,.75); margin:0 0 16px;}}
.counter .act{{display:flex; gap:8px;}}
.counter button{{flex:1; font-family:'Inter'; font-size:12px; font-weight:600; padding:9px; border-radius:6px; cursor:pointer; border:1px solid rgba(255,255,255,.25); background:transparent; color:#eef5f4; transition:.15s;}}
.counter button.primary{{background:var(--beacon); border-color:var(--beacon); color:#fff;}}
.counter button:hover{{transform:translateY(-1px);}}
.more-eyebrow{{display:flex; align-items:center; gap:14px; margin:8px 0 18px;}}
.more-eyebrow::after{{content:""; flex:1; height:1px; background:var(--line-strong);}}
.cards{{display:grid; grid-template-columns:1fr 1fr; gap:26px 28px;}}
.card{{border-top:1px solid var(--ink); padding-top:14px; cursor:pointer;}}
.card .ctop{{display:flex; justify-content:space-between; align-items:center; margin-bottom:9px;}}
.momentum{{font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; display:inline-flex; align-items:center; gap:5px;}}
.momentum.up{{color:var(--rising);}} .momentum.down{{color:var(--falling);}} .momentum.flat{{color:var(--ink-soft);}}
.card .brands{{font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-soft);}}
.card h3{{font-family:'Fraunces',serif; font-weight:600; font-size:23px; line-height:1.1; margin:0 0 9px; transition:.15s;}}
.card:hover h3{{color:var(--beacon);}}
.card p{{font-size:13.5px; line-height:1.5; color:var(--ink-soft); margin:0 0 13px;}}
.spark{{height:34px; display:flex; align-items:flex-end; gap:3px; margin-bottom:11px;}}
.spark i{{flex:1; background:var(--line-strong); border-radius:2px 2px 0 0; display:block; transition:.2s;}}
.card:hover .spark i{{background:var(--beacon-2);}}
.card-foot{{display:flex; justify-content:space-between; align-items:center; font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; color:var(--ink-soft); padding-top:9px; border-top:1px dotted var(--line-strong);}}
.reach{{font-weight:700; color:var(--ink);}}
.rail{{display:flex; flex-direction:column; gap:26px;}}
.panel{{border:1px solid var(--line-strong); border-radius:8px; background:rgba(255,255,255,.4);}}
.panel h5{{font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.12em; text-transform:uppercase; margin:0; padding:14px 16px; border-bottom:1px solid var(--line); color:var(--ink); display:flex; justify-content:space-between; align-items:center;}}
.panel h5 .cnt{{color:var(--beacon);}}
.brandrow{{display:flex; align-items:center; gap:12px; padding:11px 16px; border-bottom:1px solid var(--line); cursor:pointer; transition:.12s;}}
.brandrow:last-child{{border-bottom:none;}} .brandrow:hover{{background:var(--paper-2);}}
.brandrow .av{{width:30px; height:30px; border-radius:6px; flex:none; display:grid; place-items:center; font-family:'Fraunces',serif; font-weight:600; font-size:13px; color:#fff;}}
.brandrow .bn{{font-weight:600; font-size:13px; display:flex; align-items:center; gap:6px;}}
.brandrow .bn .ours{{font-family:'JetBrains Mono',monospace; font-size:8px; background:var(--teal); color:#fff; padding:1px 4px; border-radius:3px; letter-spacing:.05em;}}
.brandrow .bi{{font-size:10.5px; color:var(--ink-soft);}}
.brandrow .stat{{margin-left:auto; text-align:right;}}
.brandrow .stat .pct{{font-family:'JetBrains Mono',monospace; font-weight:700; font-size:12px;}}
.brandrow .stat .pct.up{{color:var(--rising);}} .brandrow .stat .pct.down{{color:var(--falling);}}
.brandrow .stat .sub{{font-size:9px; font-family:'JetBrains Mono',monospace; text-transform:uppercase; color:var(--ink-soft);}}
.alert{{padding:13px 16px; border-bottom:1px solid var(--line); display:flex; gap:11px;}}
.alert:last-child{{border-bottom:none;}}
.alert .sev{{width:6px; border-radius:4px; flex:none;}}
.alert .sev.hi{{background:var(--falling);}} .alert .sev.mid{{background:var(--beacon);}} .alert .sev.lo{{background:var(--rising);}}
.alert .atxt{{font-size:13px; line-height:1.4;}} .alert b{{font-weight:600;}}
.alert .atime{{font-family:'JetBrains Mono',monospace; font-size:9.5px; text-transform:uppercase; color:var(--ink-soft); margin-top:4px; letter-spacing:.04em;}}
.digest{{padding:16px;}}
.digest p{{font-family:'Fraunces',serif; font-size:14px; line-height:1.6; color:var(--ink); margin:0 0 14px;}}
.digest .deliver{{display:flex; gap:8px;}}
.digest .deliver button{{flex:1; font-size:11.5px; font-weight:600; padding:9px; border-radius:6px; cursor:pointer; border:1px solid var(--ink); background:var(--ink); color:var(--paper); font-family:'Inter'; transition:.15s;}}
.digest .deliver button.ghost{{background:transparent; color:var(--ink);}}
.digest .deliver button:hover{{opacity:.85;}}
.next{{font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-soft); text-align:center; padding:10px; border-top:1px dashed var(--line-strong);}}
.voices{{margin:0 0 40px;}}
.voices-head{{border-top:2px solid var(--ink); padding-top:16px; margin-bottom:20px;}}
.voices-head .eye{{font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--beacon); font-weight:700;}}
.voices-head h3{{font-family:'Fraunces',serif; font-weight:600; font-size:32px; margin:8px 0 6px; line-height:1.04;}}
.voices-head p{{font-family:'Fraunces',serif; font-style:italic; font-size:15px; color:var(--ink-soft); margin:0; max-width:72ch; line-height:1.5;}}
.voice-grid{{column-count:3; column-gap:22px;}}
.voice{{break-inside:avoid; margin-bottom:22px; background:rgba(255,255,255,.55); border:1px solid var(--line-strong); border-left:3px solid var(--line-strong); border-radius:8px; padding:15px 17px; display:flex; flex-direction:column; gap:11px; transition:.15s;}}
.voice:hover{{transform:translateY(-2px); box-shadow:0 6px 18px rgba(0,0,0,.06);}}
.voice .vtop{{display:flex; justify-content:space-between; align-items:center;}}
.voice .plat{{font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.07em; font-weight:700;}}
.voice .eng{{font-family:'JetBrains Mono',monospace; font-size:9.5px; text-transform:uppercase; letter-spacing:.04em; color:var(--ink-soft);}}
.voice .q{{font-family:'Fraunces',serif; font-size:16.5px; line-height:1.46; color:var(--ink);}}
.voice .vbot{{display:flex; justify-content:space-between; align-items:center; gap:8px; border-top:1px dotted var(--line-strong); padding-top:9px;}}
.voice .handle{{font-family:'JetBrains Mono',monospace; font-size:10px; color:var(--ink-soft);}}
.voice .rel{{font-family:'JetBrains Mono',monospace; font-size:8.5px; text-transform:uppercase; letter-spacing:.04em; color:#fff; background:var(--ink); padding:2px 6px; border-radius:3px; white-space:nowrap;}}
.p-reddit{{border-left-color:#d93a00;}} .p-reddit .plat{{color:#d93a00;}}
.p-tiktok{{border-left-color:#111;}} .p-tiktok .plat{{color:#111;}}
.p-x{{border-left-color:#111;}} .p-x .plat{{color:#111;}}
.p-mumsnet{{border-left-color:#a4117f;}} .p-mumsnet .plat{{color:#a4117f;}}
.p-ig{{border-left-color:#c13584;}} .p-ig .plat{{color:#c13584;}}
.provocations{{background:var(--deep); color:#d0eaf0; border-radius:10px; padding:34px 34px 30px; margin:0 0 40px; position:relative; overflow:hidden;}}
.provocations::before{{content:""; position:absolute; top:-60px; right:-50px; width:260px; height:260px; border-radius:50%; background:radial-gradient(circle, rgba(10,125,140,.2), transparent 70%);}}
.provocations::after{{content:""; position:absolute; bottom:-70px; left:-40px; width:200px; height:200px; border-radius:50%; background:radial-gradient(circle, rgba(15,163,181,.07), transparent 70%);}}
.prov-head{{display:flex; align-items:baseline; gap:16px; flex-wrap:wrap; margin-bottom:8px; position:relative;}}
.prov-head .eye{{font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--beacon-2); font-weight:700;}}
.prov-head h3{{font-family:'Fraunces',serif; font-weight:600; font-size:30px; margin:0; line-height:1.05;}}
.prov-sub{{font-family:'Fraunces',serif; font-style:italic; font-size:15px; line-height:1.5; color:rgba(208,234,240,.6); margin:0 0 26px; max-width:74ch; position:relative;}}
.prov-grid{{display:grid; grid-template-columns:repeat(3,1fr); gap:26px; position:relative;}}
.prov{{border-top:2px solid rgba(255,255,255,.22); padding-top:15px;}}
.prov .n{{font-family:'Fraunces',serif; font-size:34px; font-weight:300; color:var(--beacon-2); line-height:1; margin-bottom:12px; display:block;}}
.prov p{{font-family:'Fraunces',serif; font-size:18px; line-height:1.4; margin:0 0 14px; color:#f3f8f7;}}
.prov .tag{{font-family:'JetBrains Mono',monospace; font-size:9.5px; text-transform:uppercase; letter-spacing:.06em; color:#9fc0bd;}}
.prov-foot{{display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-top:24px; padding-top:16px; border-top:1px solid rgba(255,255,255,.15); position:relative;}}
.prov-foot span{{font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:#9fc0bd;}}
.prov-foot .btns{{display:flex; gap:8px;}}
.prov-foot button{{font-family:'Inter'; font-size:12px; font-weight:600; padding:9px 16px; border-radius:6px; cursor:pointer; border:1px solid rgba(255,255,255,.3); background:transparent; color:#eef5f4; transition:.15s;}}
.prov-foot button.primary{{background:var(--beacon); border-color:var(--beacon); color:#fff;}}
.prov-foot button:hover{{transform:translateY(-1px);}}
footer{{border-top:3px double var(--ink); padding:22px 0 40px; font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--ink-soft); text-transform:uppercase; letter-spacing:.06em; display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px;}}
@media(max-width:1000px){{
  .prov-grid,.grid,.lead-body,.cards{{grid-template-columns:1fr;}}
  .sweep{{grid-template-columns:repeat(2,1fr);}}
  .voice-grid{{column-count:1;}}
  h1.logo{{font-size:44px;}}
  .lead h2{{font-size:31px;}}
}}
</style>
</head>
<body>
<div class="wrap">

  <div style="background:var(--ink);color:rgba(255,255,255,.45);font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.16em;text-transform:uppercase;display:flex;justify-content:space-between;align-items:center;padding:7px 28px;">
    <span>Cultural Intelligence Platform · Powered by Countercurrent</span>
    <span style="color:#fff;font-weight:700;letter-spacing:.22em;">{agency}</span>
  </div>
  <header class="masthead">
    <div class="masthead-top">
      <div class="edition"><span>{vol_no}</span><span>{today_str}</span></div>
      <div class="edition">
        <span class="live"><span class="dot"></span> Sweeping live</span>
        <span>Leadership Edition</span>
      </div>
    </div>
    <div class="clientbar"><span class="pill">Client</span> {e(client)}</div>
    <div class="title-row">
      <div class="beacon-mark">
        <span class="beam"></span><span class="lamp"></span><span class="tower"></span>
      </div>
      <h1 class="logo"><span class="the">THE</span>LIGHTHOUSE</h1>
    </div>
    <p class="tagline">{e(tagline)}</p>
  </header>

  <section class="sweep">
    <div class="cell">
      <div class="k">Signals scanned · 24h</div>
      <div class="v" id="sigcount">{sig_display}</div>
    </div>
    <div class="cell"><div class="k">Currents surfaced</div><div class="v">{sw.get("currents_surfaced","—")}</div></div>
    <div class="cell"><div class="k">Rising fast</div><div class="v" style="color:var(--rising)">{sw.get("rising_fast","—")}</div></div>
    <div class="cell"><div class="k">Needs a human</div><div class="v" style="color:var(--beacon)">{sw.get("needs_human","—")}</div></div>
    <div class="cell"><div class="k">Sources active</div><div class="sources-line">{src_pills}</div></div>
  </section>

  <div class="controls">
    <div class="chips">
      <button class="chip active">All currents</button>
      {chips_html}
    </div>
    <div class="section-eyebrow">▲ Today's strongest current</div>
  </div>

  <div class="grid">
    <main>
      <article class="lead">
        <div class="meta">
          <span class="tag-lead">Lead Current</span>
          <span>{topic_str}</span>
          <span>Relevance: <b>{e(lead.get("relevance","—"))}</b></span>
          <span class="momentum {_mclass(ld)}">{_marrow(ld)} {e(lead.get("momentum_pct",""))}/{e(lead.get("momentum_period",""))}</span>
        </div>
        <h2>{e(lead.get("title",""))}</h2>
        <p class="dek">{e(lead.get("dek",""))}</p>
        <div class="lead-body">
          <div>
            <div class="pullquote">
              &ldquo;{e(lead.get("pullquote",""))}&rdquo;
              <cite>— {e(lead.get("pullquote_cite",""))}</cite>
            </div>
            {render_signal_stack(lead.get("signal_stack",[]))}
          </div>
          <aside class="counter">
            <div class="lbl">◐ The Countercurrent</div>
            <h4>{e(lead.get("countercurrent_title",""))}</h4>
            <p>{e(lead.get("countercurrent_body",""))}</p>
            <div class="act">
              <button class="primary">Brief the team →</button>
              <button>Save</button>
            </div>
          </aside>
        </div>
      </article>

      <div class="more-eyebrow">
        <span class="section-eyebrow">More currents worth watching</span>
      </div>
      <div class="cards">{cards_html}</div>
    </main>

    <aside class="rail">
      <div class="panel">
        <h5>Share Of Voice <span class="cnt">7d</span></h5>
        <div class="brandrow">
          <div class="av" style="background:#0e9aa7">H</div>
          <div><div class="bn">Heinz Cream of Tomato <span class="ours">OURS</span></div><div class="bi">Can · flagship</div></div>
          <div class="stat"><div class="pct up">▲ 41%</div><div class="sub">Conversation</div></div>
        </div>
        <div class="brandrow">
          <div class="av" style="background:#cf2b29">H</div>
          <div><div class="bn">Heinz Soup of the Day <span class="ours">OURS</span></div><div class="bi">Pouch · convenience</div></div>
          <div class="stat"><div class="pct up">▲ 63%</div><div class="sub">Conversation</div></div>
        </div>
        <div class="brandrow">
          <div class="av" style="background:#3a6e3a">C</div>
          <div><div class="bn">Cully &amp; Sully</div><div class="bi">Pot · competitor</div></div>
          <div class="stat"><div class="pct up">▲ 28%</div><div class="sub">Gaining</div></div>
        </div>
        <div class="brandrow">
          <div class="av" style="background:#6b4e8c">G</div>
          <div><div class="bn">New Covent Garden</div><div class="bi">Carton · competitor</div></div>
          <div class="stat"><div class="pct" style="color:var(--ink-soft)">● 2%</div><div class="sub">Flat</div></div>
        </div>
        <div class="brandrow">
          <div class="av" style="background:#a9572b">B</div>
          <div><div class="bn">Batchelors Cup-a-Soup</div><div class="bi">Sachet · competitor</div></div>
          <div class="stat"><div class="pct down">▼ 19%</div><div class="sub">Declining</div></div>
        </div>
      </div>

      <div class="panel">
        <h5>Needs A Human <span class="cnt">{len(alerts)} open</span></h5>
        {alerts_html}
      </div>

      <div class="panel">
        <h5>The 07:00 Briefing</h5>
        <div class="digest">
          <p>&ldquo;{e(content.get("briefing",""))}&rdquo;</p>
          <div class="deliver">
            <button>Send to leads</button>
            <button class="ghost">Full report</button>
          </div>
        </div>
        <div class="next">◷ Next sweep on demand</div>
      </div>
    </aside>
  </div>

  <section class="voices">
    <div class="voices-head">
      <span class="eye">● Live · Voices From The Currents</span>
      <h3>What people are actually saying</h3>
      <p>Raw signal texture from this sweep — the language, jokes and feelings real people attach to the category. Steal the language.</p>
    </div>
    <div class="voice-grid">{voices_html}</div>
  </section>

  <section class="provocations">
    <div class="prov-head">
      <span class="eye">◐ To Close · The Countercurrent</span>
      <h3>Three provocations for the room</h3>
    </div>
    <p class="prov-sub">Deliberately unfinished questions drawn from today's currents — not answers, but opening lines to push the team past the obvious. Argue with these.</p>
    <div class="prov-grid">{provs_html}</div>
    <div class="prov-foot">
      <span>Generated fresh from today's strongest currents</span>
      <div class="btns">
        <button class="primary">Send to creative team →</button>
        <button>Regenerate</button>
      </div>
    </div>
  </section>

  <footer>
    <span>The Lighthouse · Countercurrent.ai v3</span>
    <span style="color:var(--beacon);font-weight:700;letter-spacing:.14em;">{agency}</span>
    <span>Client: {e(client)} · Refreshes on demand · Human-reviewed before send</span>
  </footer>

</div>
<script>
(function() {{
  // Chip filter toggle
  document.querySelectorAll('.chip').forEach(function(c) {{
    c.addEventListener('click', function() {{
      document.querySelectorAll('.chip').forEach(function(x) {{ x.classList.remove('active'); }});
      c.classList.add('active');
    }});
  }});
  // Animate signal counter
  var el = document.getElementById('sigcount');
  var base = {sig_n};
  if (el && base > 0) {{
    setInterval(function() {{
      base += Math.floor(Math.random() * 4 + 1);
      el.textContent = base >= 1000000
        ? (base / 1000000).toFixed(2) + 'M'
        : (base / 1000).toFixed(1) + 'K';
    }}, 1800);
  }}
}})();
</script>
</body>
</html>"""


# ── Session state ──────────────────────────────────────────────────────────────

if "lh_content" not in st.session_state:
    st.session_state.lh_content = None


# ── Load data ──────────────────────────────────────────────────────────────────

signals = load_signals()


def load_last_dispatch(path: str = "data/dispatches.jsonl"):
    """Load the most recent saved dispatch from disk."""
    if not os.path.exists(path):
        return None
    last = None
    with open(path) as f:
        for line in f:
            try:
                last = json.loads(line)
            except Exception:
                pass
    if last and "full" in last:
        return last["full"]
    return None


# ── Mode: saved (free) vs live (calls Claude) ──────────────────────────────────

if not live_mode:
    # SAVED MODE — load last dispatch, zero API cost
    if st.session_state.lh_content is None:
        saved = load_last_dispatch()
        if saved:
            st.session_state.lh_content = saved
            st.sidebar.caption("Showing last saved dispatch.")
        else:
            st.session_state.lh_content = _fallback()
            st.sidebar.caption("No dispatch saved yet — switch to Live to generate.")

elif regenerate:
    # LIVE MODE — call Claude
    if not signals:
        st.session_state.lh_content = _fallback()
    else:
        with st.spinner("🗼 The Lighthouse is sweeping the currents…"):
            rag = []
            if use_pinecone and focus_topic:
                rag = semantic_search(
                    focus_topic,
                    top_k=signal_limit,
                    client_filter=client_filter or None,
                )
            content = generate(signals, rag, client_name, brief_tagline, focus_topic)
            st.session_state.lh_content = content
            save_dispatch(content, focus_topic)

content = st.session_state.lh_content


# ── Email dispatch ─────────────────────────────────────────────────────────────

if send_email_btn and email_to and content:
    html_body  = build_html(content, signals, client_name, brief_tagline)
    week_label = datetime.utcnow().strftime("Week of %d %b %Y")
    subject    = f"The Lighthouse · {client_name} · {week_label}"
    ok = send_email(email_to, subject, html_body)
    if ok:
        st.toast(f"✓ Dispatch sent to {email_to}")
    else:
        st.error("Send failed — check SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in .env")


# ── Render ─────────────────────────────────────────────────────────────────────

if content:
    final_html = build_html(content, signals, client_name, brief_tagline)
    st.components.v1.html(final_html, height=3200, scrolling=True)
else:
    st.info("No dispatch saved yet. Switch to **Live mode** in the sidebar and press **⚡ Sweep & Generate** to create the first briefing.")
