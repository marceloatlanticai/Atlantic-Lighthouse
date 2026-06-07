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
import uuid
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

# ── Users & passwords ──────────────────────────────────────────────────────────
# Passwords can be overridden via .env: PASS_MARCELO=outra_senha etc.
USERS = {
    "Marcelo": os.environ.get("PASS_MARCELO", "Marcelo123"),
    "Marco":   os.environ.get("PASS_MARCO",   "Marco123"),
    "Pat":     os.environ.get("PASS_PAT",      "Pat123"),
    "Joao":    os.environ.get("PASS_JOAO",     "Joao123"),
}

# User avatar colors
USER_COLORS = {
    "Marcelo": "#0a7d8c",
    "Marco":   "#1a6b4a",
    "Pat":     "#8a3a8c",
    "Joao":    "#0a4a6e",
}

# ── Curadoria helpers ──────────────────────────────────────────────────────────
CURADORIA_PATH = "data/curadoria.json"

def load_curadoria() -> list:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(CURADORIA_PATH):
        return []
    try:
        with open(CURADORIA_PATH) as f:
            return json.load(f)
    except Exception:
        return []

def _save_curadoria(items: list):
    os.makedirs("data", exist_ok=True)
    with open(CURADORIA_PATH, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def add_curadoria_item(user: str, type_: str, title: str, content: str) -> bool:
    """Add item. Returns False if already saved by this user."""
    items = load_curadoria()
    # Prevent duplicates for same user + same title
    for it in items:
        if it["user"] == user and it["title"] == title:
            return False
    items.append({
        "id":         str(uuid.uuid4())[:8],
        "user":       user,
        "type":       type_,
        "title":      title,
        "content":    content,
        "saved_at":   datetime.utcnow().strftime("%d %b %Y · %H:%M"),
    })
    _save_curadoria(items)
    return True

def remove_curadoria_item(item_id: str):
    items = [i for i in load_curadoria() if i["id"] != item_id]
    _save_curadoria(items)

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

/* ── Atlantic background — garante o sea mist em todos os contextos ── */
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section,
.main {
    background-color: #ebf2f7 !important;
    background-image:
        radial-gradient(ellipse 80% 40% at 50% -10%, rgba(10,125,140,.07), transparent),
        radial-gradient(ellipse 60% 30% at 90% 110%, rgba(6,34,51,.04), transparent);
}
.block-container { padding: 0.5rem 0.5rem 0 !important; max-width: 100% !important; background: transparent !important; }

/* Prevent white text leaking into light sections */
[data-testid="stTabsContent"] p,
[data-testid="stTabsContent"] div,
[data-testid="stTabsContent"] span {
    color: #071828;
}
[data-testid="stTabsContent"] .cur-item-type  { color: #0a7d8c !important; }
[data-testid="stTabsContent"] .cur-item-title { color: #071828 !important; }
[data-testid="stTabsContent"] .cur-item-content { color: #274d68 !important; }
[data-testid="stTabsContent"] .cur-user-pill  { color: #fff !important; }
/* Streamlit default p/text in light mode */
p, li, span, label { color: #071828; }

section[data-testid="stSidebar"] { background: #0f0e0c !important; }
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

/* ── Expanders — force light background ── */
[data-testid="stExpander"] {
    background: #ffffff !important;
    border: 1px solid #9dc4d8 !important;
    border-radius: 6px !important;
}
[data-testid="stExpander"] summary {
    color: #071828 !important;
    background: transparent !important;
}
[data-testid="stExpander"] div[data-testid="stExpanderDetails"] {
    background: #ffffff !important;
    color: #274d68 !important;
}
[data-testid="stExpander"] p,
[data-testid="stExpander"] li,
[data-testid="stExpander"] td,
[data-testid="stExpander"] th,
[data-testid="stExpander"] code {
    color: #274d68 !important;
    background: transparent !important;
}
[data-testid="stExpander"] table {
    background: #fff !important;
    border-collapse: collapse;
}
[data-testid="stExpander"] th {
    background: #ebf2f7 !important;
    font-weight: 600 !important;
}

/* ── Main-area save buttons (💾 / 🗑) — transparent, beacon on hover ── */
/* button[kind] beats Streamlit's hashed Emotion class in specificity */
[data-testid="stAppViewContainer"] button[kind="secondary"] {
    background: transparent !important;
    background-color: transparent !important;
    border: 1px solid rgba(157,196,216,.35) !important;
    border-radius: 6px !important;
    color: #274d68 !important;
    box-shadow: none !important;
    font-size: 15px !important;
    padding: 2px 8px !important;
    min-height: 28px !important;
    transition: all .15s !important;
}
[data-testid="stAppViewContainer"] button[kind="secondary"]:hover {
    border-color: #0a7d8c !important;
    color: #0a7d8c !important;
    background: transparent !important;
    background-color: transparent !important;
}
[data-testid="stAppViewContainer"] button[kind="secondary"] p,
[data-testid="stAppViewContainer"] button[kind="secondary"] div {
    color: inherit !important;
    background: transparent !important;
}

/* ── Login form submit button ── */
[data-testid="stFormSubmitButton"] > button,
[data-testid="stFormSubmitButton"] > button:focus {
    background: #071828 !important;
    background-color: #071828 !important;
    color: #ffffff !important;
    border: 1px solid #071828 !important;
    border-radius: 6px !important;
    font-size: 15px !important;
    padding: 10px 20px !important;
    width: 100% !important;
    box-shadow: none !important;
    transition: background .15s !important;
}
[data-testid="stFormSubmitButton"] > button:hover {
    background: #0a7d8c !important;
    background-color: #0a7d8c !important;
    border-color: #0a7d8c !important;
    color: #ffffff !important;
}
[data-testid="stFormSubmitButton"] > button p,
[data-testid="stFormSubmitButton"] > button span {
    color: #ffffff !important;
}
</style>
""", unsafe_allow_html=True)

# ── Dispatch archive helpers (defined early — called inside sidebar) ───────────

def load_all_dispatches(path: str = "data/dispatches.jsonl") -> list:
    """Load all saved dispatches, newest first."""
    if not os.path.exists(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                if "full" in rec and "timestamp" in rec:
                    records.append(rec)
            except Exception:
                pass
    return sorted(records, key=lambda x: x["timestamp"], reverse=True)


def dispatch_label(rec: dict) -> str:
    """Human-readable label for a dispatch record."""
    ts    = rec.get("timestamp", "")[:10]
    title = rec.get("full", {}).get("lead", {}).get("title", rec.get("content", ""))
    short = (title[:42] + "…") if len(title) > 42 else title
    return f"{ts}  ·  {short}" if short else ts


# ── Login screen ──────────────────────────────────────────────────────────────

def show_login():
    """Full-screen Atlantic-styled login. Blocks the rest of the app."""
    st.markdown("""
<style>
.login-wrap {
    max-width: 400px; margin: 6rem auto 0; padding: 2.5rem;
    background: #fff; border: 1px solid #9dc4d8; border-radius: 10px;
    box-shadow: 0 8px 32px rgba(7,24,40,.08);
}
.login-logo {
    text-align: center; margin-bottom: 1.8rem;
}
.login-logo .the {
    font-family: monospace; font-size: 10px; letter-spacing: .42em;
    text-transform: uppercase; color: #274d68; display: block; margin-bottom: 4px;
}
.login-logo h1 {
    font-family: Georgia, serif; font-size: 38px; font-weight: 600;
    color: #071828; margin: 0; letter-spacing: -.01em; line-height: 1;
}
.login-logo .tagline {
    font-family: Georgia, serif; font-style: italic;
    font-size: 13px; color: #274d68; margin-top: 6px;
}
.login-agency {
    text-align: center; font-family: monospace; font-size: 9px;
    letter-spacing: .16em; text-transform: uppercase; color: #0a7d8c;
    margin-bottom: 1.8rem;
}
/* Login form submit button */
[data-testid="stFormSubmitButton"] > button,
[data-testid="stFormSubmitButton"] > button:focus {
    background: #071828 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: Georgia, serif !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    letter-spacing: .04em !important;
    padding: 12px 20px !important;
    width: 100% !important;
    cursor: pointer !important;
    transition: background .15s !important;
}
[data-testid="stFormSubmitButton"] > button:hover {
    background: #0a7d8c !important;
    color: #ffffff !important;
}
</style>
<div class="login-wrap">
  <div class="login-logo">
    <span class="the">The</span>
    <h1>Lighthouse</h1>
    <div class="tagline">Cultural Intelligence Platform</div>
  </div>
  <div class="login-agency">Atlantic · New York · Countercurrent.ai</div>
</div>
""", unsafe_allow_html=True)

    # Use st.columns to center the form under the HTML above
    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.form("login_form", clear_on_submit=False):
            user_sel = st.selectbox("Username", list(USERS.keys()), label_visibility="visible")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign in →", use_container_width=True)
            if submitted:
                if USERS.get(user_sel) == password:
                    st.session_state.logged_in_user = user_sel
                    st.rerun()
                else:
                    st.error("Incorrect password.")


if "logged_in_user" not in st.session_state:
    show_login()
    st.stop()

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
    current_user  = st.session_state.logged_in_user
    user_color    = USER_COLORS.get(current_user, "#0a7d8c")
    st.markdown(f"""
<div style="font-family:'Georgia',serif;font-size:20px;color:#d0eaf0;margin-bottom:4px">
  🗼 THE LIGHTHOUSE
</div>
<div style="font-family:monospace;font-size:10px;color:#0fa3b5;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px">
  Atlantic · Countercurrent.ai · v3
</div>
<div style="display:flex;align-items:center;gap:10px;background:#1a2a3a;border-radius:6px;padding:8px 12px;margin-bottom:4px">
  <div style="width:28px;height:28px;border-radius:50%;background:{user_color};display:flex;align-items:center;justify-content:center;font-family:Georgia,serif;font-weight:600;font-size:12px;color:#fff;flex:none">{current_user[0]}</div>
  <div>
    <div style="font-size:13px;color:#d0eaf0;font-weight:500">{current_user}</div>
    <div style="font-family:monospace;font-size:9px;color:#0a7d8c;letter-spacing:.08em;text-transform:uppercase">Online</div>
  </div>
</div>
""", unsafe_allow_html=True)
    if st.button("Sign out", use_container_width=True, key="logout_btn"):
        del st.session_state.logged_in_user
        st.rerun()

    client_name   = st.text_input("Client", value="Heinz Soup · United Kingdom")
    brief_tagline = st.text_input("Brief tagline", value="Reading Britain's lunch currents so Heinz can build the countercurrent.")
    focus_topic   = st.text_area(
        "Focus topic / brief",
        value="desk lunch, comfort food, cost of living, office return-to-work culture, UK workers",
        height=80,
    )
    client_filter   = st.text_input("Client tag filter", value="", placeholder="Leave blank = all signals")
    competitors_raw = st.text_input(
        "Competitor brands",
        value="Cully & Sully, New Covent Garden, Batchelors, Cup-a-Soup",
        help="Comma-separated — used in Competitive Pulse",
    )

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
                          help="OFF = shows last saved dispatch (no cost).\nON = generates new content via Claude.")
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

    # ── PDF / HTML Report download ──────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<div style="font-size:10px;color:#0fa3b5;font-family:monospace;'
        'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">'
        '↓ Report</div>',
        unsafe_allow_html=True,
    )
    # Download button placeholder — filled after build_html is defined
    _has_content = bool(st.session_state.get("lh_content"))
    _download_placeholder = st.empty()
    _date_str = datetime.utcnow().strftime("%Y-%m-%d")
    if not _has_content:
        _download_placeholder.caption("Generate a dispatch first to download the report.")

    # ── Dispatch archive ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<div style="font-size:10px;color:#0fa3b5;font-family:monospace;'
        'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">'
        '◷ Dispatch Archive</div>',
        unsafe_allow_html=True,
    )
    _all_dispatches = load_all_dispatches()
    if _all_dispatches:
        _archive_labels = ["— current dispatch —"] + [dispatch_label(r) for r in _all_dispatches]
        _sel = st.selectbox("Browse history", _archive_labels, label_visibility="collapsed")
        if _sel != "— current dispatch —":
            _idx = _archive_labels.index(_sel) - 1
            if st.button("Load this dispatch", use_container_width=True):
                st.session_state.lh_content = _all_dispatches[_idx]["full"]
                st.rerun()
    else:
        st.caption("No archived dispatches yet.")

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
            f"URL: {s.get('url','')}\n"
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
    {{"platform_class": "p-reddit", "platform_label": "Reddit · r/SubName", "engagement": "▲ 3.1k", "quote": "Vivid, specific, casual voice.", "handle": "u/realistic_handle", "rel_tag": "Short tag", "url": "https://reddit.com/r/SubName/comments/..."}},
    {{"platform_class": "p-tiktok", "platform_label": "TikTok", "engagement": "410k views", "quote": "...", "handle": "@handle", "rel_tag": "...", "url": "https://tiktok.com/@handle/video/..."}},
    {{"platform_class": "p-x", "platform_label": "X", "engagement": "12k likes", "quote": "...", "handle": "@handle", "rel_tag": "...", "url": ""}},
    {{"platform_class": "p-mumsnet", "platform_label": "Mumsnet", "engagement": "240 replies", "quote": "...", "handle": "Username", "rel_tag": "...", "url": ""}},
    {{"platform_class": "p-ig", "platform_label": "Instagram", "engagement": "22k likes", "quote": "...", "handle": "@handle", "rel_tag": "...", "url": ""}},
    {{"platform_class": "p-reddit", "platform_label": "Reddit · r/SubName", "engagement": "▲ 5.4k", "quote": "...", "handle": "u/handle", "rel_tag": "...", "url": "https://reddit.com/r/SubName/comments/..."}},
    {{"platform_class": "p-tiktok", "platform_label": "TikTok · Niche", "engagement": "880k views", "quote": "...", "handle": "@handle", "rel_tag": "...", "url": "https://tiktok.com/@handle/video/..."}},
    {{"platform_class": "p-x", "platform_label": "X", "engagement": "8.3k likes", "quote": "...", "handle": "@handle", "rel_tag": "...", "url": ""}},
    {{"platform_class": "p-reddit", "platform_label": "Reddit · r/SubName", "engagement": "▲ 1.9k", "quote": "...", "handle": "u/handle", "rel_tag": "...", "url": "https://reddit.com/r/SubName/comments/..."}}
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

Be specific. Steal language from the actual signals. Write like a world-class strategist.
For the "url" field in each voice: use the exact URL from the SIGNAL context above that best matches the quote. If no URL is available for that platform, leave it as an empty string ""."""

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
    url     = v.get("url", "")
    link    = (f'<a href="{e(url)}" target="_blank" rel="noopener" '
               f'style="margin-left:auto;font-size:10px;color:var(--beacon);'
               f'text-decoration:none;font-family:\'JetBrains Mono\',monospace;'
               f'letter-spacing:.04em;">↗ source</a>') if url else ""
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
        f'{link}'
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

# ── Native CSS injected into Streamlit for interactive sections ────────────────

def _native_css(beacon: str, beacon_2: str) -> str:
    return f"""
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,400..700&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet"/>
<style>
:root{{
  --lh-ink:#071828; --lh-ink-soft:#274d68; --lh-paper:#ebf2f7;
  --lh-beacon:{beacon}; --lh-beacon-2:{beacon_2};
  --lh-line:#9dc4d8; --lh-line-strong:#6ea8c4;
  --lh-deep:#062233; --lh-rising:#1a8a6b; --lh-falling:#c94f35;
}}
.lh-eyebrow{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:{beacon};font-weight:700;}}
.lh-section-rule{{border-top:2px solid var(--lh-ink);padding-top:18px;margin-bottom:6px;}}
.lh-meta{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--lh-ink-soft);margin-bottom:12px;}}
.lh-tag{{background:{beacon};color:#fff;padding:3px 9px;font-weight:700;border-radius:3px;}}
.lh-momentum-up{{color:var(--lh-rising);font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;}}
.lh-momentum-down{{color:var(--lh-falling);font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;}}
.lh-momentum-flat{{color:var(--lh-ink-soft);font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;}}
.lh-lead-title{{font-family:'Fraunces',serif;font-weight:600;font-size:2.3rem;line-height:1.04;color:var(--lh-ink);margin:6px 0 14px;letter-spacing:-.02em;}}
.lh-lead-dek{{font-family:'Fraunces',serif;font-size:1.05rem;line-height:1.6;color:var(--lh-ink-soft);max-width:62ch;}}
.lh-pullquote{{border-left:3px solid {beacon};padding:4px 0 4px 18px;font-family:'Fraunces',serif;font-style:italic;font-size:1.1rem;line-height:1.45;color:var(--lh-ink);margin:16px 0 10px;}}
.lh-pullquote cite{{display:block;font-style:normal;font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;color:var(--lh-ink-soft);margin-top:8px;letter-spacing:.06em;}}
.lh-signal{{display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--lh-line);font-size:13px;}}
.lh-signal-plat{{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;color:{beacon};width:64px;flex:none;}}
.lh-signal-txt{{line-height:1.4;color:var(--lh-ink);}}
.lh-signal-num{{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--lh-ink-soft);white-space:nowrap;}}
.lh-counter{{background:#062233 !important;color:#d0eaf0 !important;border-radius:8px;padding:20px;}}
.lh-counter-lbl{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:{beacon_2};font-weight:700;margin-bottom:8px;}}
.lh-counter-title{{font-family:'Fraunces',serif;font-size:1.2rem;font-weight:600;line-height:1.2;margin-bottom:10px;color:#d0eaf0;}}
.lh-counter-body{{font-size:13.5px;line-height:1.5;color:rgba(208,234,240,.75);}}
.lh-card{{border-top:2px solid var(--lh-ink);padding-top:14px;}}
.lh-card-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}}
.lh-card-brands{{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;color:var(--lh-ink-soft);}}
.lh-card-title{{font-family:'Fraunces',serif;font-weight:600;font-size:1.2rem;line-height:1.1;color:var(--lh-ink);margin:0 0 8px;}}
.lh-card-body{{font-size:13.5px;line-height:1.5;color:var(--lh-ink-soft);margin:0 0 10px;}}
.lh-spark{{height:28px;display:flex;align-items:flex-end;gap:3px;margin-bottom:10px;}}
.lh-spark i{{flex:1;background:var(--lh-line-strong);border-radius:2px 2px 0 0;display:block;}}
.lh-card-foot{{display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;color:var(--lh-ink-soft);padding-top:8px;border-top:1px dotted var(--lh-line);}}
.lh-reach{{font-weight:700;color:var(--lh-ink);}}
.lh-voice{{background:rgba(255,255,255,.75);border:1px solid var(--lh-line);border-left:3px solid var(--lh-line);border-radius:8px;padding:14px 16px;height:100%;}}
.lh-voice-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}}
.lh-voice-plat{{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;font-weight:700;}}
.lh-voice-eng{{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:#274d68 !important;}}
.lh-voice-q{{font-family:'Fraunces',serif;font-size:1rem;line-height:1.46;color:#071828 !important;margin-bottom:8px;}}
.lh-voice-bot{{display:flex;justify-content:space-between;border-top:1px dotted var(--lh-line);padding-top:8px;}}
.lh-voice-handle{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#274d68 !important;}}
.lh-voice-rel{{font-family:'JetBrains Mono',monospace;font-size:8.5px;text-transform:uppercase;color:#fff !important;background:#071828;padding:2px 6px;border-radius:3px;}}
.p-reddit-n{{border-left-color:#d93a00;}}.p-reddit-n .lh-voice-plat{{color:#d93a00;}}
.p-tiktok-n{{border-left-color:#111;}}.p-tiktok-n .lh-voice-plat{{color:#111;}}
.p-x-n{{border-left-color:#111;}}.p-x-n .lh-voice-plat{{color:#111;}}
.p-mumsnet-n{{border-left-color:#a4117f;}}.p-mumsnet-n .lh-voice-plat{{color:#a4117f;}}
.p-ig-n{{border-left-color:#c13584;}}.p-ig-n .lh-voice-plat{{color:#c13584;}}
.lh-prov-wrap{{background:#062233 !important;color:#d0eaf0 !important;border-radius:10px;padding:28px 32px;}}
.lh-prov-head-eye{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:{beacon_2};font-weight:700;}}
.lh-prov-head-title{{font-family:'Fraunces',serif;font-weight:600;font-size:1.8rem;margin:8px 0 4px;color:#d0eaf0;}}
.lh-prov-head-sub{{font-family:'Fraunces',serif;font-style:italic;font-size:15px;color:rgba(208,234,240,.55);margin:0 0 20px;}}
.lh-prov{{border-top:1px solid rgba(255,255,255,.15);padding-top:14px;}}
.lh-prov-n{{font-family:'Fraunces',serif;font-size:2.2rem;font-weight:300;color:{beacon_2};display:block;margin-bottom:8px;line-height:1;}}
.lh-prov-text{{font-family:'Fraunces',serif;font-size:1.1rem;line-height:1.42;color:#e8f6fa;margin-bottom:6px;}}
.lh-prov-tag{{font-family:'JetBrains Mono',monospace;font-size:9.5px;text-transform:uppercase;color:rgba(10,125,140,.85);letter-spacing:.06em;}}
.lh-panel{{border:1px solid var(--lh-line);border-radius:8px;background:rgba(255,255,255,.6);margin-bottom:20px;overflow:hidden;}}
.lh-panel-head{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;padding:12px 16px;border-bottom:1px solid var(--lh-line);color:#071828 !important;display:flex;justify-content:space-between;background:rgba(255,255,255,.7);}}
.lh-panel-cnt{{color:{beacon} !important;}}
.lh-brandrow{{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--lh-line);background:rgba(255,255,255,.4);}}
.lh-brandrow:last-child{{border-bottom:none;}}
.lh-av{{width:30px;height:30px;border-radius:6px;flex:none;display:grid;place-items:center;font-family:'Fraunces',serif;font-weight:600;font-size:13px;color:#fff !important;}}
.lh-bn{{font-weight:600;font-size:13px;color:#071828 !important;display:flex;align-items:center;gap:6px;}}
.lh-ours{{font-family:'JetBrains Mono',monospace;font-size:8px;background:{beacon};color:#fff !important;padding:1px 5px;border-radius:3px;}}
.lh-bi{{font-size:10.5px;color:#274d68 !important;}}
.lh-bstat{{margin-left:auto;text-align:right;}}
.lh-bpct{{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:12px;color:#071828 !important;}}
.lh-bpct-up{{color:#1a8a6b !important;}}.lh-bpct-down{{color:#c94f35 !important;}}
.lh-bsub{{font-size:9px;font-family:'JetBrains Mono',monospace;text-transform:uppercase;color:#274d68 !important;}}
.lh-alert{{padding:12px 16px;border-bottom:1px solid var(--lh-line);display:flex;gap:10px;background:rgba(255,255,255,.3);}}
.lh-alert:last-child{{border-bottom:none;}}
.lh-sev{{width:4px;border-radius:4px;flex:none;}}
.lh-sev-hi{{background:#c94f35;}}.lh-sev-mid{{background:{beacon};}}.lh-sev-lo{{background:#1a8a6b;}}
.lh-atxt{{font-size:13px;line-height:1.4;color:#071828 !important;}}.lh-atxt b{{font-weight:600;color:#071828 !important;}}
.lh-atime{{font-family:'JetBrains Mono',monospace;font-size:9.5px;text-transform:uppercase;color:#274d68 !important;margin-top:4px;}}
.lh-digest{{padding:16px;background:rgba(255,255,255,.3);}}
.lh-digest-p{{font-family:'Fraunces',serif;font-size:14px;line-height:1.6;color:#071828 !important;margin:0 0 12px;}}
.lh-next{{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;color:#274d68 !important;text-align:center;padding:10px;border-top:1px dashed var(--lh-line);}}
/* Save button (💾) — transparent bg, turns beacon on hover */
div[data-testid="stButton"] > button {{
  background: transparent !important;
  border: 1px solid rgba(157,196,216,.4) !important;
  border-radius: 6px !important;
  color: #274d68 !important;
  font-size: 15px !important;
  line-height: 1 !important;
  padding: 3px 8px !important;
  min-height: 28px !important;
  height: 28px !important;
  box-shadow: none !important;
  transition: all .15s !important;
}}
div[data-testid="stButton"] > button:hover {{
  border-color: {beacon} !important;
  color: {beacon} !important;
  background: transparent !important;
}}
</style>"""


# ── Masthead iframe (static — no interaction needed) ──────────────────────────

def build_masthead_html(content: dict, signals: list, client: str, tagline: str) -> str:
    """Top section: agency bar + logo + sweep + controls. Static, no save buttons."""
    sw        = content.get("sweep", {})
    lead      = content.get("lead", {})
    today_str = datetime.utcnow().strftime("%A, %d %B %Y")
    vol_no    = f"Vol. I · No. {datetime.utcnow().strftime('%j')}"
    sig_n     = len(signals)
    sig_display = f"{sig_n/1000:.1f}K" if sig_n < 1_000_000 else f"{sig_n/1_000_000:.2f}M"
    src_pills   = sources_pills(signals)
    chips_html  = chip_buttons(lead)
    beacon      = CLIENT_BEACON_COLOR
    beacon_2    = CLIENT_BEACON_2
    pill_color  = CLIENT_PILL_COLOR
    agency      = e(AGENCY_NAME)

    return f"""<!DOCTYPE html><html lang="en-GB"><head>
<meta charset="UTF-8"/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,400..700&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet"/>
<style>
:root{{--paper:#ebf2f7;--paper-2:#dce9f2;--ink:#071828;--ink-soft:#274d68;--line:#9dc4d8;--line-strong:#6ea8c4;--beacon:{beacon};--beacon-2:{beacon_2};--deep:#062233;--atlantic:#0a4a6e;--rising:#1a8a6b;--falling:#c94f35;}}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;background-image:radial-gradient(ellipse 80% 40% at 50% -10%,rgba(10,125,140,.08),transparent),radial-gradient(ellipse 60% 30% at 90% 110%,rgba(6,34,51,.05),transparent);}}
.wrap{{max-width:1240px;margin:0 auto;padding:0 28px;}}
.agency-bar{{background:var(--ink);color:rgba(255,255,255,.45);font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.16em;text-transform:uppercase;display:flex;justify-content:space-between;align-items:center;padding:7px 28px;}}
.agency-bar .am{{color:#fff;font-weight:700;letter-spacing:.22em;}}
.masthead{{border-bottom:3px double var(--ink);padding-top:22px;}}
.masthead-top{{display:flex;justify-content:space-between;align-items:flex-end;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-soft);padding-bottom:14px;border-bottom:1px solid var(--line);}}
.edition{{display:flex;gap:22px;align-items:center;}}
.live{{display:inline-flex;align-items:center;gap:7px;color:var(--ink);font-weight:700;}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--beacon);animation:pulse 2.4s infinite;}}
@keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(10,125,140,.5);}}70%{{box-shadow:0 0 0 10px rgba(10,125,140,0);}}100%{{box-shadow:0 0 0 0 rgba(10,125,140,0);}}}}
.clientbar{{display:flex;justify-content:center;align-items:center;gap:10px;padding:12px 0 2px;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--ink-soft);}}
.pill{{background:{pill_color};color:#fff;padding:3px 11px;border-radius:3px;font-weight:700;letter-spacing:.08em;}}
.title-row{{display:flex;align-items:center;justify-content:center;gap:26px;padding:8px 0 10px;}}
.beacon-mark{{position:relative;width:54px;height:54px;flex:none;}}
.tower{{position:absolute;left:50%;bottom:0;transform:translateX(-50%);width:14px;height:34px;background:linear-gradient(var(--ink),#1a3d52);clip-path:polygon(28% 0,72% 0,100% 100%,0 100%);}}
.lamp{{position:absolute;left:50%;top:7px;transform:translateX(-50%);width:14px;height:11px;background:var(--beacon);border-radius:3px 3px 0 0;box-shadow:0 0 16px 4px rgba(10,125,140,.55);z-index:2;}}
.beam{{position:absolute;left:50%;top:12px;width:0;height:0;transform-origin:left center;border-top:16px solid transparent;border-bottom:16px solid transparent;border-left:64px solid rgba(15,163,181,.28);animation:sweep 7s ease-in-out infinite;}}
@keyframes sweep{{0%,100%{{transform:rotate(-32deg);opacity:.2;}}50%{{transform:rotate(28deg);opacity:.5;}}}}
h1.logo{{font-family:'Fraunces',serif;font-weight:500;font-size:58px;letter-spacing:.01em;margin:0;line-height:.95;text-align:center;}}
h1.logo .the{{display:block;font-size:13px;letter-spacing:.5em;font-weight:400;margin-bottom:6px;color:var(--ink-soft);font-family:'JetBrains Mono',monospace;text-transform:uppercase;}}
.tagline{{text-align:center;font-family:'Fraunces',serif;font-style:italic;font-size:15px;color:var(--ink-soft);padding:6px 0 16px;}}
.sweep{{display:grid;grid-template-columns:repeat(5,1fr);border-bottom:1px solid var(--line);background:rgba(255,255,255,.4);}}
.cell{{padding:16px 18px;border-right:1px solid var(--line);}}
.cell:last-child{{border-right:none;}}
.k{{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-soft);}}
.v{{font-family:'Fraunces',serif;font-size:30px;font-weight:500;margin-top:4px;line-height:1;}}
.sources-line{{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px;}}
.src{{font-family:'JetBrains Mono',monospace;font-size:9.5px;padding:2px 6px;border:1px solid var(--line-strong);border-radius:20px;color:var(--ink-soft);background:var(--paper-2);}}
.src.on{{color:var(--beacon);border-color:var(--beacon);}}
.src .d{{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--beacon);margin-right:4px;vertical-align:middle;}}
.controls{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:22px 0 18px;flex-wrap:wrap;}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;}}
.chip{{font-size:12.5px;font-weight:500;padding:7px 14px;border:1px solid var(--line-strong);background:transparent;border-radius:30px;cursor:pointer;color:var(--ink-soft);transition:.15s;font-family:'Inter';}}
.chip:hover{{border-color:var(--beacon);color:var(--beacon);}}
.chip.active{{background:var(--ink);color:var(--paper);border-color:var(--ink);}}
.section-eyebrow{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--beacon);font-weight:700;}}
</style></head>
<body>
<div class="agency-bar">
  <span>Cultural Intelligence Platform · Powered by Countercurrent</span>
  <span class="am">{agency}</span>
</div>
<div class="wrap">
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
      <div class="beacon-mark"><span class="beam"></span><span class="lamp"></span><span class="tower"></span></div>
      <h1 class="logo"><span class="the">The</span>Lighthouse</h1>
    </div>
    <p class="tagline">{e(tagline)}</p>
  </header>
  <section class="sweep">
    <div class="cell"><div class="k">Signals scanned · 24h</div><div class="v" id="sc">{sig_display}</div></div>
    <div class="cell"><div class="k">Currents surfaced</div><div class="v">{sw.get("currents_surfaced","—")}</div></div>
    <div class="cell"><div class="k">Rising fast</div><div class="v" style="color:var(--rising)">{sw.get("rising_fast","—")}</div></div>
    <div class="cell"><div class="k">Needs a human</div><div class="v" style="color:var(--beacon)">{sw.get("needs_human","—")}</div></div>
    <div class="cell"><div class="k">Sources active</div><div class="sources-line">{src_pills}</div></div>
  </section>
  <div class="controls">
    <div class="chips"><button class="chip active">All currents</button>{chips_html}</div>
    <div class="section-eyebrow">▲ Today's strongest current</div>
  </div>
</div>
<script>
var el=document.getElementById('sc');var n={sig_n};
if(el&&n>0){{setInterval(function(){{n+=Math.floor(Math.random()*4+1);el.textContent=n>=1000000?(n/1000000).toFixed(2)+'M':(n/1000).toFixed(1)+'K';}},1800);}}
document.querySelectorAll('.chip').forEach(function(c){{c.addEventListener('click',function(){{document.querySelectorAll('.chip').forEach(function(x){{x.classList.remove('active');}});c.classList.add('active');}});}});
</script>
</body></html>"""


# ── Raw Signal Feed ───────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "reddit": "#d44800",
    "tiktok": "#0fa3b5",
    "rss":    "#6ea8c4",
    "web":    "#1a8a6b",
}
SOURCE_LABELS = {
    "reddit": "Reddit",
    "tiktok": "TikTok",
    "rss":    "RSS",
    "web":    "Web",
}

def _render_raw_signals(signals: list, topic_tags: list) -> None:
    """Show real captured signals with direct links, filterable by platform."""
    if not signals:
        return

    beacon   = CLIENT_BEACON_COLOR
    beacon_2 = CLIENT_BEACON_2

    # Score signals by topic relevance
    topic_words = set(" ".join(topic_tags).lower().split())
    def relevance(s):
        text = f"{s.get('title','')} {s.get('content','')}".lower()
        return sum(1 for w in topic_words if w in text)

    scored = sorted(
        [s for s in signals if s.get("url","").startswith("http")],
        key=lambda s: (-relevance(s), s.get("timestamp",""))
    )

    # Available platforms in this dataset
    platforms = sorted({s.get("source","other").lower() for s in scored})

    st.markdown(f"""
<div style="border-top:2px solid #071828;padding-top:18px;margin:32px 0 16px;">
  <span style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.16em;
        text-transform:uppercase;color:{beacon};font-weight:700;">◉ Raw Signal Feed</span>
  <div style="font-family:'Fraunces',serif;font-weight:600;font-size:2rem;
        margin:10px 0 6px;color:#071828;">Original posts from the sweep</div>
  <div style="font-family:'Fraunces',serif;font-style:italic;font-size:15px;
        color:#274d68;max-width:72ch;">Real content captured directly from the platforms — unfiltered, unedited.
        Click <b>↗ view post</b> to open the original publication.</div>
</div>""", unsafe_allow_html=True)

    # Platform filter
    filter_cols = st.columns(len(platforms) + 1)
    selected_src = st.session_state.get("raw_signal_filter", "all")

    with filter_cols[0]:
        if st.button("All", key="rsf_all",
                     type="primary" if selected_src == "all" else "secondary"):
            st.session_state["raw_signal_filter"] = "all"
            st.rerun()

    for ci, plat in enumerate(platforms):
        with filter_cols[ci + 1]:
            col = SOURCE_COLORS.get(plat, "#9dc4d8")
            label = SOURCE_LABELS.get(plat, plat.title())
            if st.button(label, key=f"rsf_{plat}",
                         type="primary" if selected_src == plat else "secondary"):
                st.session_state["raw_signal_filter"] = plat
                st.rerun()

    # Filter + cap at 30
    selected_src = st.session_state.get("raw_signal_filter", "all")
    filtered = [
        s for s in scored
        if selected_src == "all" or s.get("source","").lower() == selected_src
    ][:30]

    if not filtered:
        st.caption("No signals found for this filter.")
        return

    sig_cols = st.columns(3, gap="medium")
    for i, s in enumerate(filtered):
        src    = s.get("source","web").lower()
        color  = SOURCE_COLORS.get(src, "#9dc4d8")
        label  = SOURCE_LABELS.get(src, src.title())
        title  = s.get("title","") or "—"
        body   = s.get("content","")[:200]
        if len(s.get("content","")) > 200:
            body += "…"
        ts     = s.get("timestamp","")[:10]
        url    = s.get("url","")

        with sig_cols[i % 3]:
            st.markdown(f"""
<div style="background:rgba(255,255,255,.7);border:1px solid #9dc4d8;
     border-left:3px solid {color};border-radius:8px;padding:14px 16px;
     margin-bottom:14px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <span style="font-family:'JetBrains Mono',monospace;font-size:9px;
          text-transform:uppercase;letter-spacing:.1em;color:{color};font-weight:700;">
      ● {label}</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#9dc4d8;">{ts}</span>
  </div>
  <div style="font-family:'Fraunces',serif;font-size:14px;font-weight:600;
       color:#071828;line-height:1.35;margin-bottom:8px;">{e(title[:90])}</div>
  <div style="font-size:12.5px;color:#274d68;line-height:1.55;margin-bottom:12px;">{e(body)}</div>
  <a href="{e(url)}" target="_blank" rel="noopener"
     style="font-family:'JetBrains Mono',monospace;font-size:9.5px;
            letter-spacing:.06em;text-transform:uppercase;color:{color};
            text-decoration:none;border-bottom:1px solid {color};
            padding-bottom:1px;">↗ view post</a>
</div>""", unsafe_allow_html=True)


# ── Native Streamlit section renderers ────────────────────────────────────────

def _mdir(d):
    return {"up": "▲", "down": "▼"}.get(d, "●")
def _mcls(d):
    return {"up": "lh-momentum-up", "down": "lh-momentum-down"}.get(d, "lh-momentum-flat")

def _save_button(label: str, type_: str, title: str, content_str: str, key: str, user: str):
    """Renders a 💾 save button."""
    if st.button("💾", key=key, help="Save to curation board"):
        ok = add_curadoria_item(user, type_, title, content_str)
        if ok:
            st.toast(f"✓ Saved to your board, {user}!")
        else:
            st.toast("Already saved to your board.")


def render_content_sections(content: dict, user: str):
    """Renders lead, cards, rail, voices, provocations with native Streamlit + save buttons."""
    beacon   = CLIENT_BEACON_COLOR
    beacon_2 = CLIENT_BEACON_2

    # Inject CSS once
    st.markdown(_native_css(beacon, beacon_2), unsafe_allow_html=True)

    lead   = content.get("lead", {})
    cards  = content.get("cards", [])
    voices = content.get("voices", [])
    provs  = content.get("provocations", [])
    alerts = content.get("alerts", [])
    sw     = content.get("sweep", {})

    ld = lead.get("momentum_dir", "up")

    # ── LEAD + RAIL grid ──────────────────────────────────────────────────────
    col_main, col_rail = st.columns([13, 5], gap="large")

    with col_main:
        # Lead header
        st.markdown(f"""
<div class="lh-section-rule">
  <div class="lh-meta">
    <span class="lh-tag">Lead Current</span>
    <span>{" · ".join(e(t) for t in lead.get("topic_tags",[]))}</span>
    <span>Relevance: <b>{e(lead.get("relevance","—"))}</b></span>
    <span class="{_mcls(ld)}">{_mdir(ld)} {e(lead.get("momentum_pct",""))}/{e(lead.get("momentum_period",""))}</span>
  </div>
</div>""", unsafe_allow_html=True)

        # Lead title + dek + save button
        col_lead_text, col_lead_save = st.columns([20, 1])
        with col_lead_text:
            st.markdown(f"""
<div class="lh-lead-title">{e(lead.get("title",""))}</div>
<div class="lh-lead-dek">{e(lead.get("dek",""))}</div>""", unsafe_allow_html=True)
        with col_lead_save:
            _save_button("🔖", "Lead Current",
                lead.get("title",""),
                lead.get("countercurrent_title","") + " — " + lead.get("countercurrent_body",""),
                "save_lead_main", user)

        # Pullquote + signal stack
        st.markdown(f"""
<div class="lh-pullquote">
  &ldquo;{e(lead.get("pullquote",""))}&rdquo;
  <cite>— {e(lead.get("pullquote_cite",""))}</cite>
</div>
<div>
{"".join(f'<div class="lh-signal"><span class="lh-signal-plat">{e(s.get("platform",""))}</span><span class="lh-signal-txt">{e(s.get("text",""))}</span><span class="lh-signal-num">{e(s.get("num",""))}</span></div>' for s in lead.get("signal_stack",[]))}
</div>""", unsafe_allow_html=True)

        # Countercurrent box + save
        col_cc, col_cc_save = st.columns([20, 1])
        with col_cc:
            st.markdown(f"""
<div class="lh-counter" style="margin-top:20px">
  <div class="lh-counter-lbl">◐ The Countercurrent</div>
  <div class="lh-counter-title">{e(lead.get("countercurrent_title",""))}</div>
  <div class="lh-counter-body">{e(lead.get("countercurrent_body",""))}</div>
</div>""", unsafe_allow_html=True)
        with col_cc_save:
            st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)
            _save_button("🔖", "Countercurrent",
                lead.get("countercurrent_title",""),
                lead.get("countercurrent_body",""),
                "save_cc_main", user)

        # Section divider
        st.markdown(f"""
<div style="display:flex;align-items:center;gap:14px;margin:28px 0 18px">
  <span class="lh-eyebrow">More currents worth watching</span>
  <span style="flex:1;height:1px;background:#6ea8c4;display:block"></span>
</div>""", unsafe_allow_html=True)

        # Cards 2×2
        card_cols = st.columns(2, gap="large")
        for i, card in enumerate(cards[:4]):
            d = card.get("momentum_dir", "up")
            spark_bars = "".join(f'<i style="height:{v}%"></i>' for v in (card.get("spark") or [30,45,55,65,75,82,90]))
            with card_cols[i % 2]:
                col_card, col_card_save = st.columns([10, 1])
                with col_card:
                    st.markdown(f"""
<div class="lh-card">
  <div class="lh-card-top">
    <span class="{_mcls(d)}">{_mdir(d)} {e(card.get("momentum_pct",""))}</span>
    <span class="lh-card-brands">{e(card.get("tags",""))}</span>
  </div>
  <div class="lh-card-title">{e(card.get("title",""))}</div>
  <div class="lh-card-body">{e(card.get("body",""))}</div>
  <div class="lh-spark">{spark_bars}</div>
  <div class="lh-card-foot"><span>{e(card.get("sources",""))}</span><span class="lh-reach">{e(card.get("reach",""))}</span></div>
</div>""", unsafe_allow_html=True)
                with col_card_save:
                    st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
                    _save_button("🔖", f"Card — {card.get('tags','')}",
                        card.get("title",""), card.get("body",""),
                        f"save_card_{i}", user)

    # ── RAIL SIDEBAR ──────────────────────────────────────────────────────────
    with col_rail:
        # Share of Voice (static — no save button needed)
        st.markdown("""
<div class="lh-panel">
  <div class="lh-panel-head">Share Of Voice · Soup <span class="lh-panel-cnt">7d</span></div>
  <div class="lh-brandrow"><div class="lh-av" style="background:#0a7d8c">H</div><div><div class="lh-bn">Heinz Cream of Tomato <span class="lh-ours">OURS</span></div><div class="lh-bi">Can · flagship</div></div><div class="lh-bstat"><div class="lh-bpct lh-bpct-up">▲ 41%</div><div class="lh-bsub">Conversation</div></div></div>
  <div class="lh-brandrow"><div class="lh-av" style="background:#0a4a6e">H</div><div><div class="lh-bn">Heinz Soup of the Day <span class="lh-ours">OURS</span></div><div class="lh-bi">Pouch · convenience</div></div><div class="lh-bstat"><div class="lh-bpct lh-bpct-up">▲ 63%</div><div class="lh-bsub">Conversation</div></div></div>
  <div class="lh-brandrow"><div class="lh-av" style="background:#3a6e3a">C</div><div><div class="lh-bn">Cully &amp; Sully</div><div class="lh-bi">Pot · competitor</div></div><div class="lh-bstat"><div class="lh-bpct lh-bpct-up">▲ 28%</div><div class="lh-bsub">Gaining</div></div></div>
  <div class="lh-brandrow"><div class="lh-av" style="background:#6b4e8c">G</div><div><div class="lh-bn">New Covent Garden</div><div class="lh-bi">Carton · competitor</div></div><div class="lh-bstat"><div class="lh-bpct" style="color:#6ea8c4">● 2%</div><div class="lh-bsub">Flat</div></div></div>
  <div class="lh-brandrow"><div class="lh-av" style="background:#8a6a3a">B</div><div><div class="lh-bn">Batchelors Cup-a-Soup</div><div class="lh-bi">Sachet · declining</div></div><div class="lh-bstat"><div class="lh-bpct lh-bpct-down">▼ 19%</div><div class="lh-bsub">Fading</div></div></div>
</div>""", unsafe_allow_html=True)

        # Alerts
        alerts_html_native = "".join(
            f'<div class="lh-alert"><div class="lh-sev lh-sev-{e(a.get("sev","mid"))}"></div>'
            f'<div><div class="lh-atxt">{a.get("text","")}</div>'
            f'<div class="lh-atime">{e(a.get("time",""))}</div></div></div>'
            for a in alerts[:3]
        )
        st.markdown(f"""
<div class="lh-panel">
  <div class="lh-panel-head">Needs A Human <span class="lh-panel-cnt">{len(alerts)} open</span></div>
  {alerts_html_native}
</div>""", unsafe_allow_html=True)

        # Briefing
        st.markdown(f"""
<div class="lh-panel">
  <div class="lh-panel-head">The 07:00 Briefing</div>
  <div class="lh-digest">
    <div class="lh-digest-p">&ldquo;{e(content.get("briefing",""))}&rdquo;</div>
  </div>
  <div class="lh-next">◷ Next sweep on demand</div>
</div>""", unsafe_allow_html=True)

    # ── VOICES ────────────────────────────────────────────────────────────────
    st.markdown("""
<div style="border-top:2px solid #071828;padding-top:18px;margin:8px 0 20px">
  <span class="lh-eyebrow">◎ Editorial Synthesis · Claude-Composed Voices</span>
  <div style="font-family:'Fraunces',serif;font-weight:600;font-size:2rem;margin:10px 0 6px;color:#071828">What people are actually saying</div>
  <div style="font-family:'Fraunces',serif;font-style:italic;font-size:15px;color:#274d68;max-width:72ch;margin-bottom:10px">Raw signal texture from this sweep — the language and feelings real people attach to the category. Steal the language.</div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.06em;color:#9dc4d8;border-left:2px solid #9dc4d8;padding-left:10px;">These voices are editorial composites written by Claude from real signals — condensed for clarity. See the <b>Raw Signal Feed</b> below for the original posts with direct links.</div>
</div>""", unsafe_allow_html=True)

    voice_cols = st.columns(3, gap="medium")
    platform_css_map = {
        "p-reddit": "p-reddit-n", "p-tiktok": "p-tiktok-n",
        "p-x": "p-x-n", "p-mumsnet": "p-mumsnet-n", "p-ig": "p-ig-n",
    }
    for i, v in enumerate(voices[:9]):
        pcls = platform_css_map.get(v.get("platform_class",""), "")
        with voice_cols[i % 3]:
            col_v, col_vs = st.columns([8, 1])
            with col_v:
                _v_url  = v.get("url", "")
                _v_link = (
                    '<a href="' + e(_v_url) + '" target="_blank" rel="noopener" '
                    'style="margin-left:auto;font-family:JetBrains Mono,monospace;'
                    'font-size:9px;letter-spacing:.06em;text-transform:uppercase;'
                    'color:#0a7d8c;text-decoration:none;">↗ source</a>'
                ) if _v_url else ""
                st.markdown(f"""
<div class="lh-voice {pcls}">
  <div class="lh-voice-top">
    <span class="lh-voice-plat">● {e(v.get("platform_label",""))}</span>
    <span class="lh-voice-eng">{e(v.get("engagement",""))}</span>
  </div>
  <div class="lh-voice-q">&ldquo;{e(v.get("quote",""))}&rdquo;</div>
  <div class="lh-voice-bot">
    <span class="lh-voice-handle">{e(v.get("handle",""))}</span>
    <span class="lh-voice-rel">{e(v.get("rel_tag",""))}</span>
    {_v_link}
  </div>
</div>""", unsafe_allow_html=True)
            with col_vs:
                _save_button("🔖",
                    f"Voice · {v.get('platform_label','')}",
                    v.get("quote","")[:80],
                    v.get("quote",""),
                    f"save_voice_{i}", user)

    # ── RAW SIGNAL FEED ───────────────────────────────────────────────────────
    _render_raw_signals(load_signals(), lead.get("topic_tags", []))

    # ── PROVOCATIONS — single HTML block, no Streamlit columns (avoids gap bleed) ──
    prov_items_html = ""
    for p in provs[:3]:
        prov_items_html += f"""
  <div style="border-top:1px solid rgba(255,255,255,.15);padding-top:18px;">
    <span style="font-family:'Fraunces',serif;font-size:2.2rem;font-weight:300;color:{CLIENT_BEACON_2};display:block;margin-bottom:10px;line-height:1;">{e(p.get("n",""))}</span>
    <div style="font-family:'Fraunces',serif;font-size:1.05rem;line-height:1.44;color:#e8f6fa;margin-bottom:10px;">{e(p.get("text",""))}</div>
    <span style="font-family:'JetBrains Mono',monospace;font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:rgba(10,125,140,.85);">{e(p.get("tag",""))}</span>
  </div>"""

    st.markdown(f"""
<div style="background:#062233;color:#d0eaf0;border-radius:10px;padding:28px 32px 24px;margin:0 0 4px;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:{CLIENT_BEACON_2};font-weight:700;margin-bottom:6px;">◐ To Close · The Countercurrent</div>
  <div style="font-family:'Fraunces',serif;font-weight:600;font-size:1.8rem;margin:4px 0 6px;color:#d0eaf0;">Three provocations for the room</div>
  <div style="font-family:'Fraunces',serif;font-style:italic;font-size:15px;color:rgba(208,234,240,.55);margin:0 0 22px;">Deliberately unfinished questions drawn from today's currents — not answers, but opening lines to push the team past the obvious.</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:28px;">
    {prov_items_html}
  </div>
</div>""", unsafe_allow_html=True)

    # Save buttons sit just below the dark block, one per column
    prov_save_cols = st.columns(3, gap="large")
    for i, p in enumerate(provs[:3]):
        with prov_save_cols[i]:
            _save_button("🔖",
                f"Provocation {p.get('n','')}",
                p.get("text",""),
                p.get("tag",""),
                f"save_prov_{i}", user)

    # Footer
    agency = e(AGENCY_NAME)
    st.markdown(f"""
<div style="border-top:3px double #071828;margin-top:2rem;padding:20px 0 40px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#274d68;text-transform:uppercase;letter-spacing:.06em;display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px">
  <span>The Lighthouse · Countercurrent.ai v3</span>
  <span style="color:{CLIENT_BEACON_COLOR};font-weight:700;letter-spacing:.14em">{agency}</span>
  <span>Refreshes on demand · Human-reviewed before send</span>
</div>""", unsafe_allow_html=True)


# ── Topic / Signal Map (D3 force-directed) ────────────────────────────────────

def render_topic_map(content: dict) -> None:
    """Render a D3 force-directed network of topics extracted from the dispatch."""
    import json as _json

    beacon   = CLIENT_BEACON_COLOR
    beacon_2 = CLIENT_BEACON_2

    # ── Extract topics & build graph ──────────────────────────────────────────
    topic_weight: dict = {}
    cooc: dict = {}

    def add_t(t: str, w: float):
        t = t.strip().lower()
        if t and len(t) > 2:
            topic_weight[t] = topic_weight.get(t, 0) + w

    def add_e(a: str, b: str, w: float):
        a, b = a.strip().lower(), b.strip().lower()
        if a and b and a != b:
            key = tuple(sorted([a, b]))
            cooc[key] = cooc.get(key, 0) + w

    lead  = content.get("lead", {})
    ltags = lead.get("topic_tags", [])
    for t in ltags:
        add_t(t, 5)
    for i, t1 in enumerate(ltags):
        for t2 in ltags[i + 1:]:
            add_e(t1, t2, 3)

    for card in content.get("cards", []):
        raw   = card.get("tags", "").replace("·", ",")
        ctags = [t.strip() for t in raw.split(",") if t.strip()]
        for t in ctags:
            add_t(t, 3)
        for i, t1 in enumerate(ctags):
            for t2 in ctags[i + 1:]:
                add_e(t1, t2, 2)

    for v in content.get("voices", []):
        rt = v.get("rel_tag", "").strip()
        if rt:
            add_t(rt, 1)
            for lt in ltags[:2]:
                add_e(rt, lt, 0.8)

    if not topic_weight:
        return

    nodes = [{"id": t, "w": round(w, 1)} for t, w in topic_weight.items()]
    links = [
        {"source": k[0], "target": k[1], "w": round(v, 1)}
        for k, v in cooc.items()
        if k[0] in topic_weight and k[1] in topic_weight
    ]

    nodes_json = _json.dumps(nodes)
    links_json = _json.dumps(links)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,400;1,9..144,400&display=swap" rel="stylesheet"/>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:#062233;overflow:hidden;width:100%;height:100%;}}
#header{{padding:20px 28px 0;display:flex;align-items:baseline;gap:16px;}}
.eye{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.18em;
      text-transform:uppercase;color:{beacon_2};font-weight:700;}}
.ttl{{font-family:'Fraunces',serif;font-size:17px;font-weight:500;color:#d0eaf0;}}
.sub{{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:rgba(208,234,240,.45);
      letter-spacing:.06em;text-transform:uppercase;margin-left:auto;}}
#chart{{width:100%;height:380px;display:block;}}
.node-label{{
  font-family:'JetBrains Mono',monospace;
  fill:#c8e8f0;
  pointer-events:none;
  text-shadow:0 1px 5px rgba(6,34,51,.95),0 0 10px rgba(6,34,51,.7);
  dominant-baseline:middle;
}}
</style>
</head>
<body>
<div id="header">
  <span class="eye">◎ Signal Map</span>
  <span class="ttl">Topic landscape · this edition</span>
  <span class="sub">Drag nodes · hover to highlight</span>
</div>
<svg id="chart"></svg>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const nodes = {nodes_json};
const links = {links_json};

const W = document.getElementById('chart').clientWidth || 960;
const H = 380;
const svg = d3.select('#chart').attr('width',W).attr('height',H);

// Soft glow backdrop
const defs = svg.append('defs');
const glow = defs.append('filter').attr('id','glow');
glow.append('feGaussianBlur').attr('stdDeviation','3.5').attr('result','blur');
const merge = glow.append('feMerge');
merge.append('feMergeNode').attr('in','blur');
merge.append('feMergeNode').attr('in','SourceGraphic');

const rg = defs.append('radialGradient').attr('id','bg-glow')
  .attr('cx','50%').attr('cy','50%').attr('r','55%');
rg.append('stop').attr('offset','0%').attr('stop-color','rgba(10,125,140,.07)');
rg.append('stop').attr('offset','100%').attr('stop-color','rgba(6,34,51,0)');
svg.append('rect').attr('width',W).attr('height',H).attr('fill','url(#bg-glow)');

const maxW = d3.max(nodes, d => d.w) || 5;
const rScale    = d3.scaleSqrt().domain([0,maxW]).range([5,26]);
const fontScale = d3.scaleSqrt().domain([0,maxW]).range([8.5,14.5]);
const opScale   = d => 0.5 + (d.w/maxW)*0.5;

// Two-stop teal gradient by weight
const cScale = d3.scaleSequential()
  .domain([0,maxW])
  .interpolator(d3.interpolateRgb('{beacon}','rgba(15,163,181,.95)'));

const sim = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(links).id(d=>d.id)
    .distance(d => 70 - d.w*3).strength(d => Math.min(d.w*0.05,0.35)))
  .force('charge', d3.forceManyBody().strength(d => -100 - rScale(d.w)*9))
  .force('center', d3.forceCenter(W/2, H/2))
  .force('collision', d3.forceCollide().radius(d => rScale(d.w)+20));

const linkSel = svg.append('g').selectAll('line').data(links).join('line')
  .attr('stroke','rgba(15,163,181,.18)')
  .attr('stroke-width', d => Math.min(d.w*0.4+0.2, 2));

const nodeSel = svg.append('g').selectAll('g').data(nodes).join('g')
  .style('cursor','pointer')
  .call(d3.drag()
    .on('start',(e,d)=>{{ if(!e.active) sim.alphaTarget(.3).restart(); d.fx=d.x;d.fy=d.y; }})
    .on('drag', (e,d)=>{{ d.fx=e.x; d.fy=e.y; }})
    .on('end',  (e,d)=>{{ if(!e.active) sim.alphaTarget(0); d.fx=null;d.fy=null; }}));

nodeSel.append('circle')
  .attr('r', d=>rScale(d.w))
  .attr('fill', d=>cScale(d.w))
  .attr('fill-opacity', d=>opScale(d))
  .attr('stroke', d=>cScale(d.w))
  .attr('stroke-width', 1.2)
  .attr('stroke-opacity', 0.6)
  .attr('filter','url(#glow)')
  .on('mouseover', function(e,d){{
    d3.select(this).attr('fill-opacity',1).attr('stroke-opacity',1);
    // highlight connected links
    linkSel
      .attr('stroke', l => (l.source.id===d.id||l.target.id===d.id)
        ? 'rgba(15,163,181,.7)' : 'rgba(15,163,181,.08)')
      .attr('stroke-width', l => (l.source.id===d.id||l.target.id===d.id)
        ? Math.min(l.w*0.6+0.5, 3) : Math.min(l.w*0.4+0.2, 2));
  }})
  .on('mouseout', function(e,d){{
    d3.select(this).attr('fill-opacity',opScale(d)).attr('stroke-opacity',0.6);
    linkSel
      .attr('stroke','rgba(15,163,181,.18)')
      .attr('stroke-width', l => Math.min(l.w*0.4+0.2, 2));
  }});

nodeSel.append('text')
  .attr('class','node-label')
  .text(d=>d.id)
  .attr('text-anchor','middle')
  .attr('dy', d => rScale(d.w) + 13)
  .attr('font-size', d => fontScale(d.w)+'px')
  .attr('fill-opacity', d => 0.6 + (d.w/maxW)*0.4);

sim.on('tick', ()=>{{
  linkSel
    .attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
    .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
  const pad = 32;
  nodeSel.attr('transform', d=>
    `translate(${{Math.max(pad,Math.min(W-pad,d.x))}},${{Math.max(pad,Math.min(H-pad,d.y))}})`
  );
}});
</script>
</body>
</html>"""

    st.components.v1.html(html, height=430, scrolling=False)


# ── Momentum Tracker (A) ──────────────────────────────────────────────────────

def render_momentum_tracker(all_dispatches: list) -> None:
    """Line chart of topic frequency across saved dispatches."""
    import json as _j

    beacon   = CLIENT_BEACON_COLOR
    beacon_2 = CLIENT_BEACON_2

    # Need ≥2 dispatches to show evolution
    if len(all_dispatches) < 2:
        st.markdown(f"""
<div style="background:#062233;border-radius:10px;padding:22px 28px;margin-bottom:4px;
     font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.12em;
     text-transform:uppercase;color:rgba(208,234,240,.45);">
  <span style="color:{beacon_2};font-weight:700;">◈ Momentum Tracker</span>
  &nbsp;·&nbsp; Topic evolution across dispatches
  &nbsp;&nbsp;—&nbsp;&nbsp;
  Requires 2+ saved dispatches · generate more to unlock this view
</div>""", unsafe_allow_html=True)
        return

    # ── Build topic × date matrix ─────────────────────────────────────────────
    from collections import defaultdict
    topic_dates: dict = defaultdict(dict)   # topic -> {date: count}
    all_dates = []

    for rec in reversed(all_dispatches):   # oldest → newest
        date  = rec["timestamp"][:10]
        full  = rec.get("full", {})
        all_dates.append(date)

        # Lead topic_tags (weight 3)
        for t in full.get("lead", {}).get("topic_tags", []):
            t = t.strip().lower()
            topic_dates[t][date] = topic_dates[t].get(date, 0) + 3

        # Card tags (weight 1)
        for card in full.get("cards", []):
            for raw_tag in card.get("tags", "").replace("·", ",").split(","):
                t = raw_tag.strip().lower()
                if t:
                    topic_dates[t][date] = topic_dates[t].get(date, 0) + 1

    all_dates = sorted(set(all_dates))

    # Keep only topics that appear in ≥2 dispatches
    active = {t: v for t, v in topic_dates.items() if len(v) >= 2}
    # Top 8 by total weight
    top8 = sorted(active, key=lambda t: sum(active[t].values()), reverse=True)[:8]

    if not top8:
        return

    # Build series for D3
    series = []
    for t in top8:
        pts = [{"d": date, "v": active[t].get(date, 0)} for date in all_dates]
        series.append({"id": t, "pts": pts})

    series_json = _j.dumps(series)
    dates_json  = _j.dumps(all_dates)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,500&display=swap" rel="stylesheet"/>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:#062233;overflow:hidden;width:100%;height:100%;font-family:'JetBrains Mono',monospace;}}
#hdr{{padding:18px 24px 0;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;}}
.eye{{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:{beacon_2};font-weight:700;}}
.ttl{{font-family:'Fraunces',serif;font-size:16px;font-weight:500;color:#d0eaf0;}}
.sub{{font-size:9.5px;color:rgba(208,234,240,.4);letter-spacing:.06em;text-transform:uppercase;margin-left:auto;}}
#chart{{width:100%;height:320px;}}
.axis path,.axis line{{stroke:rgba(157,196,216,.15);}}
.axis text{{font-family:'JetBrains Mono',monospace;font-size:9px;fill:rgba(208,234,240,.45);}}
.grid line{{stroke:rgba(157,196,216,.07);stroke-dasharray:3,3;}}
.legend{{font-family:'JetBrains Mono',monospace;font-size:9px;fill:rgba(208,234,240,.6);}}
</style></head><body>
<div id="hdr">
  <span class="eye">◈ Momentum Tracker</span>
  <span class="ttl">Topic evolution across dispatches</span>
  <span class="sub">{len(all_dispatches)} dispatches · top {len(top8)} topics</span>
</div>
<svg id="chart"></svg>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const series = {series_json};
const dates  = {dates_json};

const W = document.getElementById('chart').clientWidth || 960;
const H = 320;
const mg = {{top:18,right:130,bottom:36,left:44}};
const iw = W - mg.left - mg.right;
const ih = H - mg.top  - mg.bottom;

const svg = d3.select('#chart').attr('width',W).attr('height',H)
  .append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

const parseDate = d3.timeParse('%Y-%m-%d');
const allDates  = dates.map(parseDate);

const x = d3.scaleTime()
  .domain(d3.extent(allDates)).range([0,iw]);

const maxV = d3.max(series, s => d3.max(s.pts, p => p.v)) || 5;
const y = d3.scaleLinear().domain([0, maxV*1.1]).range([ih,0]);

// Grid
svg.append('g').attr('class','grid')
  .call(d3.axisLeft(y).ticks(4).tickSize(-iw).tickFormat(''));

// Axes
svg.append('g').attr('class','axis').attr('transform',`translate(0,${{ih}})`)
  .call(d3.axisBottom(x).ticks(Math.min(allDates.length,6))
    .tickFormat(d3.timeFormat('%d %b')));
svg.append('g').attr('class','axis')
  .call(d3.axisLeft(y).ticks(4).tickFormat(d=>d||''));

// Colour palette — teal family
const palette = [
  '{beacon_2}','rgba(10,125,140,.9)','rgba(26,138,107,.9)',
  'rgba(110,168,196,.9)','rgba(208,234,240,.7)',
  'rgba(10,74,110,.9)','rgba(15,163,181,.6)','rgba(157,196,216,.8)'
];

const line = d3.line()
  .x(p => x(parseDate(p.d))).y(p => y(p.v))
  .curve(d3.curveCatmullRom.alpha(0.5));

series.forEach((s,i)=>{{
  const col = palette[i % palette.length];
  svg.append('path')
    .datum(s.pts).attr('fill','none')
    .attr('stroke', col).attr('stroke-width',2)
    .attr('stroke-opacity',.85)
    .attr('d', line);

  // Dots
  svg.selectAll(`.dot-${{i}}`).data(s.pts).join('circle')
    .attr('class',`dot-${{i}}`)
    .attr('cx', p => x(parseDate(p.d))).attr('cy', p => y(p.v))
    .attr('r', 3.5).attr('fill', col).attr('fill-opacity',.9);

  // Legend
  const ly = 8 + i * 20;
  svg.append('line')
    .attr('x1',iw+8).attr('x2',iw+22).attr('y1',ly).attr('y2',ly)
    .attr('stroke',col).attr('stroke-width',2);
  svg.append('text').attr('class','legend')
    .attr('x',iw+26).attr('y',ly+4)
    .text(s.id.length > 18 ? s.id.slice(0,17)+'…' : s.id);
}});
</script></body></html>"""

    st.components.v1.html(html, height=370, scrolling=False)


# ── Signal Volume Analytics (1) ───────────────────────────────────────────────

def render_signal_volume(signals: list) -> None:
    """Stacked area chart: signal volume by day and source."""
    import json as _j
    from collections import defaultdict

    beacon   = CLIENT_BEACON_COLOR
    beacon_2 = CLIENT_BEACON_2

    if not signals:
        return

    # Aggregate by day × source
    day_src: dict = defaultdict(lambda: defaultdict(int))
    for s in signals:
        ts  = s.get("timestamp", "")[:10]
        src = s.get("source", "other").lower()
        if ts:
            day_src[ts][src] += 1

    if not day_src:
        return

    all_days    = sorted(day_src.keys())
    all_sources = ["reddit", "tiktok", "rss", "web"]
    src_colors  = {
        "reddit": "#d44800",
        "tiktok": "#0fa3b5",
        "rss":    "#6ea8c4",
        "web":    "#1a8a6b",
    }

    # Build series per source (cumulative for stacking done in D3)
    series = [
        {
            "id":    src,
            "color": src_colors.get(src, "#9dc4d8"),
            "pts":   [{"d": d, "v": day_src[d].get(src, 0)} for d in all_days],
        }
        for src in all_sources
    ]
    series_json = _j.dumps(series)
    days_json   = _j.dumps(all_days)
    total       = len(signals)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,500&display=swap" rel="stylesheet"/>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:#062233;overflow:hidden;width:100%;height:100%;font-family:'JetBrains Mono',monospace;}}
#hdr{{padding:18px 24px 4px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;}}
.eye{{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:{beacon_2};font-weight:700;}}
.ttl{{font-family:'Fraunces',serif;font-size:16px;font-weight:500;color:#d0eaf0;}}
.sub{{font-size:9.5px;color:rgba(208,234,240,.4);letter-spacing:.06em;text-transform:uppercase;margin-left:auto;}}
#chart{{width:100%;height:300px;}}
.axis path,.axis line{{stroke:rgba(157,196,216,.15);}}
.axis text{{font-family:'JetBrains Mono',monospace;font-size:9px;fill:rgba(208,234,240,.45);}}
.grid line{{stroke:rgba(157,196,216,.07);stroke-dasharray:3,3;}}
.legend text{{font-family:'JetBrains Mono',monospace;font-size:9px;fill:rgba(208,234,240,.65);}}
</style></head><body>
<div id="hdr">
  <span class="eye">◉ Signal Volume</span>
  <span class="ttl">Ingestion activity by platform</span>
  <span class="sub">{total:,} signals total</span>
</div>
<svg id="chart"></svg>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const series = {series_json};
const days   = {days_json};

const W  = document.getElementById('chart').clientWidth || 960;
const H  = 300;
const mg = {{top:14, right:110, bottom:36, left:44}};
const iw = W - mg.left - mg.right;
const ih = H - mg.top  - mg.bottom;

const svg = d3.select('#chart').attr('width',W).attr('height',H)
  .append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

const parseDate = d3.timeParse('%Y-%m-%d');
const allDates  = days.map(parseDate);

const x = d3.scaleTime().domain(d3.extent(allDates)).range([0, iw]);

// Stack the data
const stackKeys = series.map(s=>s.id);
const colorMap  = Object.fromEntries(series.map(s=>[s.id, s.color]));
const rows      = days.map((d,i)=>{{
  const row = {{date: parseDate(d)}};
  series.forEach(s=>{{ row[s.id] = s.pts[i]?.v || 0; }});
  return row;
}});

const stack  = d3.stack().keys(stackKeys)(rows);
const maxVal = d3.max(stack, layer => d3.max(layer, d => d[1])) || 10;
const y      = d3.scaleLinear().domain([0, maxVal * 1.05]).range([ih, 0]);

// Grid
svg.append('g').attr('class','grid')
  .call(d3.axisLeft(y).ticks(4).tickSize(-iw).tickFormat(''));

// Axes
svg.append('g').attr('class','axis').attr('transform',`translate(0,${{ih}})`)
  .call(d3.axisBottom(x).ticks(Math.min(days.length, 8)).tickFormat(d3.timeFormat('%d %b')));
svg.append('g').attr('class','axis')
  .call(d3.axisLeft(y).ticks(4));

// Areas
const area = d3.area()
  .x(d => x(d.data.date))
  .y0(d => y(d[0]))
  .y1(d => y(d[1]))
  .curve(d3.curveCatmullRom.alpha(0.5));

svg.selectAll('.layer').data(stack).join('path')
  .attr('class','layer')
  .attr('fill', d => colorMap[d.key])
  .attr('fill-opacity', 0.75)
  .attr('d', area);

// Legend
stack.forEach((layer, i) => {{
  const ly = i * 18;
  svg.append('rect').attr('x', iw+8).attr('y', ly).attr('width', 10).attr('height', 10)
    .attr('fill', colorMap[layer.key]).attr('rx', 2);
  svg.append('text').attr('class','legend')
    .attr('x', iw+22).attr('y', ly+9)
    .text(layer.key.toUpperCase());
}});
</script></body></html>"""

    st.components.v1.html(html, height=350, scrolling=False)


# ── Competitive Pulse (3) ─────────────────────────────────────────────────────

def render_competitive_pulse(signals: list, competitors_str: str) -> None:
    """Track competitor brand mentions across signals by day."""
    import json as _j, re
    from collections import defaultdict

    beacon   = CLIENT_BEACON_COLOR
    beacon_2 = CLIENT_BEACON_2

    competitors = [c.strip() for c in competitors_str.split(",") if c.strip()]
    if not competitors or not signals:
        return

    # Count mentions per day per competitor (case-insensitive word match)
    patterns = {c: re.compile(re.escape(c), re.IGNORECASE) for c in competitors}
    day_comp: dict = defaultdict(lambda: defaultdict(int))
    top_mentions: dict = {c: [] for c in competitors}  # store up to 3 best quotes

    for s in signals:
        ts   = s.get("timestamp", "")[:10]
        text = f"{s.get('title','')} {s.get('content','')}"
        if not ts:
            continue
        for comp, pat in patterns.items():
            if pat.search(text):
                day_comp[ts][comp] += 1
                if len(top_mentions[comp]) < 3:
                    snippet = text[:160].replace('"', "'")
                    top_mentions[comp].append({"src": s.get("source","?"), "text": snippet})

    if not day_comp:
        st.markdown(f"""<div style="background:#062233;border-radius:10px;padding:20px 28px;
            font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.12em;
            text-transform:uppercase;color:rgba(208,234,240,.4);">
          <span style="color:{beacon_2};font-weight:700;">◉ Competitive Pulse</span>
          &nbsp;·&nbsp; No competitor mentions found in current signal database
        </div>""", unsafe_allow_html=True)
        return

    all_days = sorted(day_comp.keys())
    palette  = ["#d44800","#0fa3b5","#6ea8c4","#1a8a6b","#c94f35","#9dc4d8"]

    series = [
        {
            "id":    c,
            "color": palette[i % len(palette)],
            "total": sum(day_comp[d].get(c, 0) for d in all_days),
            "pts":   [{"d": day, "v": day_comp[day].get(c, 0)} for day in all_days],
            "quotes": top_mentions[c],
        }
        for i, c in enumerate(competitors)
        if sum(day_comp[d].get(c, 0) for d in all_days) > 0
    ]
    series.sort(key=lambda s: -s["total"])
    series_json = _j.dumps(series)
    days_json   = _j.dumps(all_days)

    # Build quotes HTML for below chart
    quotes_html = ""
    for s in series[:4]:
        if s["quotes"]:
            q = s["quotes"][0]
            quotes_html += f"""
<div style="border-left:3px solid {s['color']};padding:8px 12px;margin-bottom:8px;background:rgba(255,255,255,.04);border-radius:0 6px 6px 0;">
  <div style="font-size:9px;color:{s['color']};text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px;font-family:'JetBrains Mono',monospace;">{s['id']} · {q['src'].upper()} · {s['total']} mentions</div>
  <div style="font-size:12px;color:rgba(208,234,240,.75);line-height:1.5;">"{q['text']}…"</div>
</div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,500&display=swap" rel="stylesheet"/>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:#062233;overflow:hidden;width:100%;min-height:100%;font-family:'JetBrains Mono',monospace;}}
#hdr{{padding:18px 24px 4px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;}}
.eye{{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:{beacon_2};font-weight:700;}}
.ttl{{font-family:'Fraunces',serif;font-size:16px;font-weight:500;color:#d0eaf0;}}
.sub{{font-size:9.5px;color:rgba(208,234,240,.4);letter-spacing:.06em;text-transform:uppercase;margin-left:auto;}}
#chart{{width:100%;height:240px;}}
#quotes{{padding:8px 24px 16px;}}
.axis path,.axis line{{stroke:rgba(157,196,216,.15);}}
.axis text{{font-family:'JetBrains Mono',monospace;font-size:9px;fill:rgba(208,234,240,.45);}}
.grid line{{stroke:rgba(157,196,216,.07);stroke-dasharray:3,3;}}
.legend text{{font-family:'JetBrains Mono',monospace;font-size:9px;fill:rgba(208,234,240,.65);}}
</style></head><body>
<div id="hdr">
  <span class="eye">◉ Competitive Pulse</span>
  <span class="ttl">Competitor brand mentions in signals</span>
  <span class="sub">{len(signals):,} signals scanned</span>
</div>
<svg id="chart"></svg>
<div id="quotes">{quotes_html}</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const series = {series_json};
const days   = {days_json};

const W  = document.getElementById('chart').clientWidth || 960;
const H  = 240;
const mg = {{top:10, right:130, bottom:36, left:40}};
const iw = W - mg.left - mg.right;
const ih = H - mg.top  - mg.bottom;

const svg = d3.select('#chart').attr('width',W).attr('height',H)
  .append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

const parseDate = d3.timeParse('%Y-%m-%d');
const allDates  = days.map(parseDate);
const x = d3.scaleTime().domain(d3.extent(allDates)).range([0, iw]);

const maxV = d3.max(series, s => d3.max(s.pts, p => p.v)) || 2;
const y    = d3.scaleLinear().domain([0, maxV + 1]).range([ih, 0]);

svg.append('g').attr('class','grid')
  .call(d3.axisLeft(y).ticks(3).tickSize(-iw).tickFormat(''));
svg.append('g').attr('class','axis').attr('transform',`translate(0,${{ih}})`)
  .call(d3.axisBottom(x).ticks(Math.min(days.length,8)).tickFormat(d3.timeFormat('%d %b')));
svg.append('g').attr('class','axis')
  .call(d3.axisLeft(y).ticks(3).tickFormat(d => Math.round(d)));

const line = d3.line()
  .x(p => x(parseDate(p.d))).y(p => y(p.v))
  .curve(d3.curveCatmullRom.alpha(0.5));

series.forEach((s, i) => {{
  svg.append('path').datum(s.pts)
    .attr('fill','none').attr('stroke', s.color)
    .attr('stroke-width', 2).attr('stroke-opacity', .85)
    .attr('d', line);
  svg.selectAll(`.dot-${{i}}`).data(s.pts).join('circle')
    .attr('cx', p => x(parseDate(p.d))).attr('cy', p => y(p.v))
    .attr('r', 3).attr('fill', s.color).attr('fill-opacity', .9);
  // Legend
  const ly = i * 18;
  svg.append('line').attr('x1',iw+8).attr('x2',iw+22)
    .attr('y1',ly+5).attr('y2',ly+5)
    .attr('stroke',s.color).attr('stroke-width',2);
  svg.append('text').attr('class','legend')
    .attr('x',iw+26).attr('y',ly+9)
    .text((s.id.length>18?s.id.slice(0,17)+'…':s.id)+' ('+s.total+')');
}});
</script></body></html>"""

    h = 260 + min(len([s for s in series if s["quotes"]]), 4) * 68
    st.components.v1.html(html, height=h, scrolling=False)


# ── Full HTML for email dispatch (unchanged) ──────────────────────────────────

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
@media print{{
  @page{{margin:18mm 16mm;}}
  body{{background:var(--paper)!important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}}
  .agency-bar{{background:var(--ink)!important;}}
  .provocations,.counter{{background:var(--deep)!important;}}
  .design-badge,.controls button,.prov-foot .btns,.digest .deliver,.card-foot button{{display:none!important;}}
  .grid{{grid-template-columns:1fr!important;}}
  .prov-grid{{grid-template-columns:repeat(3,1fr)!important;}}
  .voice-grid{{column-count:2!important;}}
  .lead h2{{font-size:28px;}}
  h1.logo{{font-size:52px;}}
  .voices,.cards,.provocations{{page-break-before:always;}}
  a{{text-decoration:none;color:inherit;}}
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


# ── Fill report download button (load_signals + build_html now in scope) ───────

if _has_content:
    _report_html = build_html(
        st.session_state["lh_content"], load_signals(),
        client_name, brief_tagline,
    )
    _download_placeholder.download_button(
        "↓ Download Report (HTML→PDF)",
        data=_report_html,
        file_name=f"lighthouse_{_date_str}.html",
        mime="text/html",
        use_container_width=True,
        help="Open in browser → Print → Save as PDF",
    )
else:
    _download_placeholder.caption("Generate a dispatch first to download the report.")


# ── Render ─────────────────────────────────────────────────────────────────────

if content:
    current_user = st.session_state.logged_in_user

    # 1. Static masthead iframe (agency bar + logo + sweep + controls)
    masthead_html = build_masthead_html(content, signals, client_name, brief_tagline)
    st.components.v1.html(masthead_html, height=390, scrolling=False)

    # 2. Interactive content (lead, cards, voices, provocations) — native Streamlit
    render_content_sections(content, current_user)

    # 3. Topic / signal map
    render_topic_map(content)

    # 4. Momentum tracker — topic evolution across dispatches
    _all_disp = load_all_dispatches()
    render_momentum_tracker(_all_disp)

    # 5. Signal Volume Analytics
    render_signal_volume(signals)

    # 6. Competitive Pulse
    render_competitive_pulse(signals, competitors_raw)

else:
    st.info("No dispatch saved yet. Switch to **Live mode** in the sidebar and press **⚡ Sweep & Generate** to create the first briefing.")


# ══════════════════════════════════════════════════════════════════════════════
# CURADORIA — Seleção e board coletivo
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
.cur-header {
    border-top: 3px double #071828; padding-top: 1.5rem; margin-top: 0.5rem;
}
.cur-title {
    font-family: Georgia, serif; font-size: 32px; font-weight: 600;
    color: #071828; margin: 6px 0 4px;
}
.cur-sub {
    font-family: Georgia, serif; font-style: italic;
    font-size: 15px; color: #274d68; margin: 0 0 1.5rem;
}
.cur-label {
    font-family: monospace; font-size: 10px; letter-spacing: .16em;
    text-transform: uppercase; color: #0a7d8c; font-weight: 700;
}
.cur-item {
    background: #fff !important; border: 1px solid #9dc4d8;
    border-left: 3px solid #0a7d8c; border-radius: 6px;
    padding: 14px 16px; margin-bottom: 10px;
}
.cur-item-type {
    font-family: monospace; font-size: 9px; letter-spacing: .12em;
    text-transform: uppercase; color: #0a7d8c !important; margin-bottom: 5px;
}
.cur-item-title {
    font-family: Georgia, serif; font-size: 15px;
    font-weight: 600; color: #071828 !important; margin-bottom: 5px; line-height: 1.3;
}
.cur-item-content {
    font-size: 13px; color: #274d68 !important; line-height: 1.5;
}
.cur-item-meta {
    font-family: monospace; font-size: 9px; color: #6ea8c4 !important;
    text-transform: uppercase; margin-top: 8px;
}
.cur-user-pill {
    display: inline-block; padding: 2px 8px; border-radius: 3px;
    font-family: monospace; font-size: 9px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .06em; color: #fff !important; margin-right: 6px;
}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="cur-header">
  <span class="cur-label">◈ Curation</span>
  <div class="cur-title">Insights Board</div>
  <div class="cur-sub">Select the most relevant content from the dispatch. Your board and your team's board live here.</div>
</div>
""", unsafe_allow_html=True)

cur_tab2, cur_tab3, cur_tab_brief = st.tabs([
    f"  My Board ({st.session_state.logged_in_user})  ",
    "  Team Board  ",
    "  ✍ Briefing Builder  ",
])

# ── TAB 2: Meu Board ──────────────────────────────────────────────────────────
with cur_tab2:
    current_user = st.session_state.logged_in_user
    my_items = [i for i in load_curadoria() if i["user"] == current_user]

    if not my_items:
        st.info("Your board is empty. Use the 🔖 buttons throughout the dispatch to save insights.")
    else:
        st.markdown(f"**{len(my_items)} item{'s' if len(my_items) != 1 else ''} saved**")
        for item in reversed(my_items):
            col_a, col_b = st.columns([6, 1])
            with col_a:
                st.markdown(f"""
<div class="cur-item">
  <div class="cur-item-type">{e(item['type'])}</div>
  <div class="cur-item-title">{e(item['title'][:120])}</div>
  <div class="cur-item-content">{e(item['content'][:240])}{"…" if len(item['content']) > 240 else ""}</div>
  <div class="cur-item-meta">Saved on {e(item['saved_at'])}</div>
</div>""", unsafe_allow_html=True)
            with col_b:
                st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
                if st.button("🗑", key=f"del_{item['id']}", help="Remove from board"):
                    remove_curadoria_item(item["id"])
                    st.rerun()


# ── TAB 3: Board Coletivo ─────────────────────────────────────────────────────
with cur_tab3:
    all_items = load_curadoria()

    if not all_items:
        st.info("No items saved yet. Use the 🔖 buttons throughout the dispatch to save insights.")
    else:
        # Group by user
        by_user = {}
        for item in all_items:
            by_user.setdefault(item["user"], []).append(item)

        total = len(all_items)
        st.markdown(f"**{total} insight{'s' if total != 1 else ''} saved by the team** · {len(by_user)} member{'s' if len(by_user) != 1 else ''}")
        st.markdown("---")

        for user_name, items in by_user.items():
            color = USER_COLORS.get(user_name, "#0a7d8c")
            st.markdown(f"""
<div style="display:flex;align-items:center;gap:10px;margin:1.2rem 0 0.8rem">
  <div style="width:32px;height:32px;border-radius:50%;background:{color};display:flex;align-items:center;justify-content:center;font-family:Georgia,serif;font-weight:600;font-size:14px;color:#fff;flex:none">{user_name[0]}</div>
  <span style="font-family:Georgia,serif;font-size:18px;font-weight:600;color:#071828">{e(user_name)}</span>
  <span style="font-family:monospace;font-size:10px;color:#9dc4d8;text-transform:uppercase;letter-spacing:.1em">{len(items)} item{'ns' if len(items) != 1 else ''}</span>
</div>""", unsafe_allow_html=True)

            for item in reversed(items):
                st.markdown(f"""
<div class="cur-item" style="border-left-color:{color}">
  <div class="cur-item-type">{e(item['type'])}</div>
  <div class="cur-item-title">{e(item['title'][:120])}</div>
  <div class="cur-item-content">{e(item['content'][:240])}{"…" if len(item['content']) > 240 else ""}</div>
  <div class="cur-item-meta">
    <span class="cur-user-pill" style="background:{color}">{e(user_name)}</span>
    Saved on {e(item['saved_at'])}
  </div>
</div>""", unsafe_allow_html=True)


# ── TAB: Briefing Builder ─────────────────────────────────────────────────────
with cur_tab_brief:
    current_user = st.session_state.logged_in_user
    my_items     = [i for i in load_curadoria() if i["user"] == current_user]

    st.markdown("""
<div style="border-top:2px solid #071828;padding-top:1.2rem;margin-bottom:1rem;">
  <div style="font-family:monospace;font-size:10px;letter-spacing:.16em;text-transform:uppercase;
       color:#0a7d8c;font-weight:700;margin-bottom:4px;">✍ Briefing Builder</div>
  <div style="font-family:Georgia,serif;font-size:22px;font-weight:600;color:#071828;margin-bottom:6px;">
    Turn your saved insights into a creative brief</div>
  <div style="font-family:Georgia,serif;font-style:italic;font-size:14px;color:#274d68;">
    Select items on My Board, then generate a structured brief ready to share with the creative team.</div>
</div>""", unsafe_allow_html=True)

    if not my_items:
        st.info("Your board is empty. Save insights from the dispatch using the 🔖 buttons, then come back here.")
    else:
        # Show items as checkboxes
        st.markdown(f"**{len(my_items)} insight{'s' if len(my_items)!=1 else ''} on your board** — select which to include:")
        selected_items = []
        for item in reversed(my_items):
            label = f"**{item['type']}** · {item['title'][:60]}"
            if st.checkbox(label, value=True, key=f"brief_sel_{item['id']}"):
                selected_items.append(item)

        st.markdown("---")

        brief_client   = st.text_input("Client", value=client_name,  key="brief_client")
        brief_tagline  = st.text_input("Brief context", value=brief_tagline, key="brief_ctx")

        if st.button("⚡ Generate Creative Brief", use_container_width=True, disabled=not selected_items):
            if not selected_items:
                st.warning("Select at least one insight to build a brief.")
            else:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    st.error("ANTHROPIC_API_KEY not found.")
                else:
                    try:
                        import anthropic as _ant
                        _client = _ant.Anthropic(api_key=api_key)

                        insights_text = "\n\n".join(
                            f"[{it['type']}] {it['title']}\n{it['content']}"
                            for it in selected_items
                        )

                        brief_prompt = f"""You are a senior strategist at a world-class advertising agency.

Client: {brief_client}
Context: {brief_tagline}

Selected cultural insights from The Lighthouse dispatch:

{insights_text}

Write a tight, actionable creative brief. Return ONLY valid JSON with this exact structure:

{{
  "audience_insight": "2-3 sentences. Who they are, what they're feeling right now, the specific tension.",
  "cultural_tension": "1-2 sentences. The fault line in culture this campaign can own.",
  "strategic_direction": "1 sentence. The single-minded thought. Bold and specific.",
  "execution_ideas": ["Idea 1 — specific format + platform", "Idea 2", "Idea 3"],
  "timing_window": "When to move and why. Reference the signals.",
  "proof_point": "The key signal or quote that justifies this direction."
}}"""

                        with st.spinner("The Lighthouse is writing your brief…"):
                            msg = _client.messages.create(
                                model=CLAUDE_MODEL,
                                max_tokens=1024,
                                temperature=0.7,
                                system="You are an elite advertising strategist. Return only raw JSON, no markdown fences.",
                                messages=[{"role": "user", "content": brief_prompt}],
                            )
                            raw = msg.content[0].text.strip()
                            if "```" in raw:
                                raw = raw[raw.find("{"):raw.rfind("}")+1]
                            brief_data = json.loads(raw)
                            st.session_state["generated_brief"] = brief_data

                    except Exception as ex:
                        st.error(f"Brief generation failed: {ex}")

        # Display generated brief
        if "generated_brief" in st.session_state:
            bd = st.session_state["generated_brief"]
            st.markdown(f"""
<div style="background:#fff;border:1px solid #9dc4d8;border-radius:8px;padding:28px 32px;margin-top:1rem;">
  <div style="font-family:monospace;font-size:9px;letter-spacing:.16em;text-transform:uppercase;
       color:#0a7d8c;font-weight:700;margin-bottom:14px;">Creative Brief · {brief_client}</div>

  <div style="font-family:monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;
       color:#274d68;margin-bottom:4px;">Audience Insight</div>
  <div style="font-family:Georgia,serif;font-size:15px;color:#071828;line-height:1.55;margin-bottom:16px;">
    {e(bd.get('audience_insight',''))}</div>

  <div style="font-family:monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;
       color:#274d68;margin-bottom:4px;">Cultural Tension</div>
  <div style="font-family:Georgia,serif;font-size:15px;color:#071828;line-height:1.55;margin-bottom:16px;">
    {e(bd.get('cultural_tension',''))}</div>

  <div style="font-family:monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;
       color:#274d68;margin-bottom:4px;">Strategic Direction</div>
  <div style="font-family:Georgia,serif;font-size:18px;font-weight:600;color:#071828;
       line-height:1.3;margin-bottom:16px;border-left:3px solid #0a7d8c;padding-left:14px;">
    {e(bd.get('strategic_direction',''))}</div>

  <div style="font-family:monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;
       color:#274d68;margin-bottom:6px;">Execution Ideas</div>
  {''.join(f'<div style="font-family:Georgia,serif;font-size:14px;color:#071828;padding:6px 0 6px 14px;border-left:2px solid #9dc4d8;margin-bottom:6px;">→ {e(idea)}</div>' for idea in bd.get('execution_ideas',[]))}

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
    <div>
      <div style="font-family:monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#274d68;margin-bottom:4px;">Timing Window</div>
      <div style="font-family:Georgia,serif;font-size:14px;color:#071828;line-height:1.5;">{e(bd.get('timing_window',''))}</div>
    </div>
    <div>
      <div style="font-family:monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#274d68;margin-bottom:4px;">Proof Point</div>
      <div style="font-family:Georgia,serif;font-style:italic;font-size:14px;color:#274d68;line-height:1.5;">"{e(bd.get('proof_point',''))}"</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

            # Download brief as text
            brief_txt = f"""CREATIVE BRIEF — {brief_client}
{"="*60}

AUDIENCE INSIGHT
{bd.get('audience_insight','')}

CULTURAL TENSION
{bd.get('cultural_tension','')}

STRATEGIC DIRECTION
{bd.get('strategic_direction','')}

EXECUTION IDEAS
{chr(10).join(f"→ {i}" for i in bd.get('execution_ideas',[]))}

TIMING WINDOW
{bd.get('timing_window','')}

PROOF POINT
"{bd.get('proof_point','')}\"

Generated by The Lighthouse · Atlantic Intelligence Layer
"""
            st.download_button(
                "↓ Download Brief",
                data=brief_txt,
                file_name=f"brief_{datetime.utcnow().strftime('%Y%m%d')}.txt",
                mime="text/plain",
                use_container_width=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL LAB — compare current vs next-gen data sources
# ══════════════════════════════════════════════════════════════════════════════

import urllib.request
import urllib.parse


@st.cache_data(ttl=900)   # cache 15 min — GDELT rate-limits aggressively
def _gdelt_search(query: str, n: int = 12) -> list:
    """Search GDELT global media database — free, no key needed."""
    import time as _time
    # Simplify query to first 4 words — reduces rate-limit risk on GDELT
    simple_q = " ".join(query.replace(",", "").split()[:4])
    endpoints = [
        # v2 DOC API — primary
        (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={urllib.parse.quote(simple_q)}"
            f"&mode=artlist&maxrecords={n}&format=json&sort=DateDesc"
        ),
        # v2 with English filter — different bucket
        (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={urllib.parse.quote(simple_q + ' sourcelang:english')}"
            f"&mode=artlist&maxrecords={n}&format=json"
        ),
    ]
    for i, url in enumerate(endpoints):
        try:
            if i > 0:
                _time.sleep(2)   # small pause before fallback
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (Lighthouse/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            articles = data.get("articles") or data.get("results") or []
            if articles:
                return [
                    {
                        "title":    a.get("title", a.get("name", "")),
                        "url":      a.get("url", a.get("htmlurl", "")),
                        "source":   a.get("domain", a.get("sourcename", "")),
                        "seendate": (a.get("seendate") or a.get("date", ""))[:8],
                        "language": a.get("language", ""),
                    }
                    for a in articles
                ]
        except Exception:
            continue
    return [{"error": "GDELT returned no results — try a shorter or simpler query, or wait 30 seconds and try again (rate limit)."}]


def _exa_search(query: str, api_key: str, n: int = 10) -> list:
    """Semantic search via Exa.ai — needs EXA_API_KEY."""
    try:
        from exa_py import Exa
        exa = Exa(api_key=api_key)
        # exa-py ≥1.0: use contents dict, use_autoprompt removed
        res = exa.search(
            query,
            num_results=n,
            contents={"text": {"max_characters": 400}},
        )
        return [
            {
                "title":     r.title or "",
                "url":       r.url or "",
                "snippet":   (getattr(r, "text", None) or "")[:400],
                "published": (getattr(r, "published_date", None) or "")[:10],
            }
            for r in res.results
        ]
    except ImportError:
        return [{"error": "📦 exa-py not installed yet. On Streamlit Cloud: commit requirements.txt and Manage App → Reboot. Locally: pip install exa-py"}]
    except Exception as ex:
        return [{"error": str(ex)}]


def _tavily_search(query: str, api_key: str, n: int = 10) -> list:
    """AI-optimised web search via Tavily — needs TAVILY_API_KEY."""
    try:
        from tavily import TavilyClient
        tc = TavilyClient(api_key=api_key)
        res = tc.search(query, max_results=n, search_depth="advanced")
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", "")[:300],
                "score":   round(r.get("score", 0), 2),
            }
            for r in res.get("results", [])
        ]
    except ImportError:
        return [{"error": "📦 tavily-python not installed yet. On Streamlit Cloud: commit the updated requirements.txt and Manage App → Reboot. Locally: pip install tavily-python"}]
    except Exception as ex:
        return [{"error": str(ex)}]


# ── Signal Lab UI ─────────────────────────────────────────────────────────────

st.markdown("""
<div style="border-top:3px double #071828;padding-top:2rem;margin-top:1rem;">
  <span style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.18em;
       text-transform:uppercase;color:#0a7d8c;font-weight:700;">⚗ Signal Lab</span>
  <div style="font-family:'Georgia',serif;font-size:28px;font-weight:600;
       color:#071828;margin:8px 0 6px;">Next-gen data sources · Live comparison</div>
  <div style="font-family:'Georgia',serif;font-style:italic;font-size:14px;color:#274d68;
       max-width:68ch;margin-bottom:6px;">Test and compare the current signal pipeline against
       next-generation sources. Run a live query across each engine and see the difference in
       breadth, depth and semantic quality.</div>
</div>
""", unsafe_allow_html=True)

lab_query = st.text_input(
    "Test query",
    value=focus_topic.split(",")[0].strip() if focus_topic else "desk lunch UK workers",
    help="Run this query against each source to compare results",
    key="lab_query",
)

lab_tab_cur, lab_tab_exa, lab_tab_gdelt, lab_tab_tav, lab_tab_yt = st.tabs([
    "  📡 Current Stack  ",
    "  🧠 Exa.ai  ",
    "  🌍 GDELT  ",
    "  ⚡ Tavily  ",
    "  🎥 YouTube  ",
])


# ── TAB: Current Stack ────────────────────────────────────────────────────────
with lab_tab_cur:
    _sigs = load_signals()
    st.markdown("""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.14em;
text-transform:uppercase;color:#0a7d8c;font-weight:700;margin-bottom:14px;">
Current ingestion pipeline · Apify scraping</div>""", unsafe_allow_html=True)

    src_counts = {}
    for s in _sigs:
        src = s.get("source", "other")
        src_counts[src] = src_counts.get(src, 0) + 1

    stat_cols = st.columns(len(src_counts) + 1)
    with stat_cols[0]:
        st.metric("Total signals", f"{len(_sigs):,}")
    for i, (src, cnt) in enumerate(sorted(src_counts.items(), key=lambda x: -x[1])):
        with stat_cols[i + 1]:
            st.metric(src.title(), f"{cnt:,}")

    st.markdown("---")
    st.markdown("""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
<div style="background:#fff;border:1px solid #9dc4d8;border-left:3px solid #0a7d8c;border-radius:8px;padding:14px 16px;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#0a7d8c;margin-bottom:6px;">✓ Strengths</div>
  <ul style="font-size:12.5px;color:#274d68;line-height:1.8;padding-left:16px;margin:0;">
    <li>1,100+ real signals already ingested</li>
    <li>Reddit threads with full comment context</li>
    <li>TikTok video descriptions + metadata</li>
    <li>RSS articles with full text</li>
    <li>Consistent schema across all sources</li>
  </ul>
</div>
<div style="background:#fff;border:1px solid #9dc4d8;border-left:3px solid #c94f35;border-radius:8px;padding:14px 16px;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#c94f35;margin-bottom:6px;">△ Limitations</div>
  <ul style="font-size:12.5px;color:#274d68;line-height:1.8;padding-left:16px;margin:0;">
    <li>Keyword-based — misses conceptual matches</li>
    <li>Platform-specific scrapers break on updates</li>
    <li>No real-time streaming — batch only</li>
    <li>Limited to pre-configured sources</li>
    <li>No semantic relevance ranking</li>
  </ul>
</div>
</div>""", unsafe_allow_html=True)

    st.markdown("<br>**Sample from current signals matching your query:**", unsafe_allow_html=True)
    q_lower = lab_query.lower()
    matches = [
        s for s in _sigs
        if any(w in f"{s.get('title','')} {s.get('content','')}".lower()
               for w in q_lower.split()[:4])
    ][:6]
    if matches:
        m_cols = st.columns(3)
        for i, s in enumerate(matches):
            with m_cols[i % 3]:
                color   = SOURCE_COLORS.get(s.get("source", "web"), "#9dc4d8")
                _s_url  = s.get("url", "")
                _s_link = (
                    '<a href="' + e(_s_url) + '" target="_blank" '
                    'style="font-family:JetBrains Mono,monospace;font-size:9px;color:' + color +
                    ';text-decoration:none;margin-top:8px;display:inline-block;">↗ source</a>'
                ) if _s_url else ""
                st.markdown(f"""
<div style="background:rgba(255,255,255,.8);border:1px solid #9dc4d8;border-left:3px solid {color};
border-radius:6px;padding:12px;margin-bottom:10px;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:8.5px;text-transform:uppercase;
  color:{color};margin-bottom:6px;">● {s.get('source','').title()}</div>
  <div style="font-size:12.5px;font-weight:600;color:#071828;margin-bottom:6px;line-height:1.3;">
    {e(s.get('title','')[:70])}</div>
  <div style="font-size:11.5px;color:#274d68;line-height:1.5;">
    {e(s.get('content','')[:120])}…</div>
  {_s_link}
</div>""", unsafe_allow_html=True)
    else:
        st.caption("No keyword matches found — try a different query.")


# ── TAB: Exa.ai ───────────────────────────────────────────────────────────────
with lab_tab_exa:
    exa_key = os.environ.get("EXA_API_KEY", "")
    st.markdown("""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.14em;
text-transform:uppercase;color:#0a7d8c;font-weight:700;margin-bottom:4px;">
Exa.ai · Neural semantic search</div>
<div style="font-size:13px;color:#274d68;line-height:1.6;margin-bottom:16px;max-width:64ch;">
Searches the web by <em>meaning</em>, not keywords. Finds content about the concept even when
the exact words don't appear. Best for discovering cultural signals you didn't know to look for.</div>
""", unsafe_allow_html=True)

    col_e1, col_e2 = st.columns([3, 1])
    with col_e1:
        if not exa_key:
            exa_key_input = st.text_input("EXA_API_KEY", type="password",
                                          help="Get free key at exa.ai — 1,000 searches/month free")
        else:
            st.success("✓ EXA_API_KEY loaded from environment")
            exa_key_input = exa_key
    with col_e2:
        exa_n = st.slider("Results", 5, 20, 10, key="exa_n")

    if st.button("🔍 Search with Exa.ai", key="btn_exa"):
        key_to_use = exa_key_input if not exa_key else exa_key
        if not key_to_use:
            st.warning("Add your EXA_API_KEY above or in .env to run this test.")
        else:
            with st.spinner("Exa.ai neural search running…"):
                exa_results = _exa_search(lab_query, key_to_use, exa_n)
            if exa_results and "error" in exa_results[0]:
                st.error(exa_results[0]["error"])
            else:
                st.markdown(f"**{len(exa_results)} semantically relevant results:**")
                for r in exa_results:
                    st.markdown(f"""
<div style="background:#fff;border:1px solid #9dc4d8;border-left:3px solid #0a7d8c;
border-radius:6px;padding:12px 14px;margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
    <div style="font-size:13px;font-weight:600;color:#071828;">{e(r.get('title','')[:80])}</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#9dc4d8;">{r.get('published','')}</div>
  </div>
  <div style="font-size:12px;color:#274d68;line-height:1.55;margin-bottom:8px;">{e(r.get('snippet',''))}</div>
  <a href="{e(r.get('url',''))}" target="_blank" style="font-family:'JetBrains Mono',monospace;
  font-size:9px;color:#0a7d8c;text-decoration:none;">↗ {e(r.get('url','')[:60])}</a>
</div>""", unsafe_allow_html=True)

    with st.expander("Why Exa.ai is different"):
        st.markdown("""
**Traditional search:** finds documents containing the words "desk lunch sad office"

**Exa.ai:** finds documents about *the cultural phenomenon of eating alone at your desk as a symbol of overwork* — even if those exact words don't appear.

This means the Lighthouse finds signals it currently misses entirely — the adjacent conversations that reveal the deeper cultural tension. Free tier: 1,000 searches/month. Paid: $0.001/search.
""")


# ── TAB: GDELT ────────────────────────────────────────────────────────────────
with lab_tab_gdelt:
    st.markdown("""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.14em;
text-transform:uppercase;color:#0a7d8c;font-weight:700;margin-bottom:4px;">
GDELT · Global media intelligence · 100% free</div>
<div style="font-size:13px;color:#274d68;line-height:1.6;margin-bottom:16px;max-width:64ch;">
Updated every 15 minutes. Covers 65+ languages. Monitors 100,000+ media sources worldwide.
No API key needed. The largest open-access media database on earth.</div>
""", unsafe_allow_html=True)

    col_g1, col_g2 = st.columns([3, 1])
    with col_g2:
        gdelt_n = st.slider("Results", 5, 25, 12, key="gdelt_n")

    if st.button("🌍 Search GDELT", key="btn_gdelt"):
        with st.spinner("Searching global media database…"):
            gdelt_results = _gdelt_search(lab_query, gdelt_n)

        if gdelt_results and "error" in gdelt_results[0]:
            st.error(f"GDELT error: {gdelt_results[0]['error']}")
        else:
            st.markdown(f"**{len(gdelt_results)} articles from global media:**")
            g_cols = st.columns(2)
            for i, r in enumerate(gdelt_results):
                with g_cols[i % 2]:
                    lang = r.get("language", "")
                    lang_tag = f'<span style="font-size:8px;background:#ebf2f7;padding:1px 6px;border-radius:3px;color:#274d68;">{lang}</span>' if lang else ""
                    st.markdown(f"""
<div style="background:#fff;border:1px solid #9dc4d8;border-left:3px solid #6ea8c4;
border-radius:6px;padding:12px;margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#6ea8c4;">{e(r.get('source',''))}</div>
    <div style="display:flex;gap:6px;align-items:center;">
      {lang_tag}
      <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#9dc4d8;">{r.get('seendate','')}</span>
    </div>
  </div>
  <div style="font-size:13px;font-weight:600;color:#071828;line-height:1.3;margin-bottom:8px;">
    {e(r.get('title','')[:90])}</div>
  <a href="{e(r.get('url',''))}" target="_blank"
  style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#6ea8c4;text-decoration:none;">
  ↗ read article</a>
</div>""", unsafe_allow_html=True)

    with st.expander("When to use GDELT"):
        st.markdown("""
GDELT is best for **macro trend validation** — when you want to know if a cultural signal you're seeing on Reddit/TikTok is also appearing in mainstream journalism worldwide.

It answers questions like: *"Is the 'sad desk lunch' story being covered in international media? In what countries? With what tone?"*

Add this to the Lighthouse ingestion and every dispatch gains a global media dimension — zero cost, zero API key.
""")


# ── TAB: Tavily ───────────────────────────────────────────────────────────────
with lab_tab_tav:
    tav_key = os.environ.get("TAVILY_API_KEY", "")
    st.markdown("""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.14em;
text-transform:uppercase;color:#0a7d8c;font-weight:700;margin-bottom:4px;">
Tavily · AI-optimised search for LLMs</div>
<div style="font-size:13px;color:#274d68;line-height:1.6;margin-bottom:16px;max-width:64ch;">
Built specifically to feed AI models. Returns clean, structured, relevance-scored results
optimised for Claude to consume. Advanced search depth crawls pages fully, not just snippets.</div>
""", unsafe_allow_html=True)

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        if not tav_key:
            tav_key_input = st.text_input("TAVILY_API_KEY", type="password",
                                          help="Get free key at tavily.com — 1,000 searches/month free")
        else:
            st.success("✓ TAVILY_API_KEY loaded from environment")
            tav_key_input = tav_key
    with col_t2:
        tav_n = st.slider("Results", 5, 15, 8, key="tav_n")

    if st.button("⚡ Search with Tavily", key="btn_tav"):
        key_to_use = tav_key_input if not tav_key else tav_key
        if not key_to_use:
            st.warning("Add your TAVILY_API_KEY above or in .env to run this test.")
        else:
            with st.spinner("Tavily deep search running…"):
                tav_results = _tavily_search(lab_query, key_to_use, tav_n)
            if tav_results and "error" in tav_results[0]:
                st.error(tav_results[0]["error"])
            else:
                st.markdown(f"**{len(tav_results)} AI-optimised results:**")
                for r in tav_results:
                    score = r.get("score", 0)
                    score_color = "#1a8a6b" if score > 0.7 else "#0a7d8c" if score > 0.4 else "#9dc4d8"
                    st.markdown(f"""
<div style="background:#fff;border:1px solid #9dc4d8;border-left:3px solid #0fa3b5;
border-radius:6px;padding:12px 14px;margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <div style="font-size:13px;font-weight:600;color:#071828;">{e(r.get('title','')[:80])}</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{score_color};
    background:rgba(10,125,140,.08);padding:2px 6px;border-radius:3px;">
    rel {score}</div>
  </div>
  <div style="font-size:12px;color:#274d68;line-height:1.55;margin-bottom:8px;">
    {e(r.get('snippet',''))}</div>
  <a href="{e(r.get('url',''))}" target="_blank"
  style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#0fa3b5;text-decoration:none;">
  ↗ {e(r.get('url','')[:60])}</a>
</div>""", unsafe_allow_html=True)

    with st.expander("Exa.ai vs Tavily — when to use which"):
        st.markdown("""
| | **Exa.ai** | **Tavily** |
|---|---|---|
| Best for | Conceptual/semantic discovery | Factual, structured results |
| How it works | Neural embedding similarity | Advanced crawl + AI ranking |
| Free tier | 1,000/month | 1,000/month |
| Paid | $0.001/search | $0.004/search |
| Ideal use case | "Find cultural conversations about X" | "Find recent news and data about X" |

**Recommendation:** run both in parallel. Exa for cultural discovery, Tavily for current events and facts. Feed both into Claude for the richest possible context.
""")


# ── TAB: YouTube ──────────────────────────────────────────────────────────────
with lab_tab_yt:
    import re as _re

    st.markdown("""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.14em;
text-transform:uppercase;color:#0a7d8c;font-weight:700;margin-bottom:4px;">
🎥 YouTube · Video signal showcase</div>
<div style="font-size:13px;color:#274d68;line-height:1.6;margin-bottom:4px;max-width:64ch;">
Paste YouTube URLs below to preview videos as signal cards — title, channel, thumbnail and
direct link. No API key needed. Culture moves visually first; these are the creators setting
the agenda before it becomes a written post.</div>
""", unsafe_allow_html=True)

    yt_urls_raw = st.text_area(
        "YouTube URLs (one per line)",
        value="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        height=120,
        key="yt_urls_input",
        help="Paste any YouTube video URLs — one per line. oEmbed fetches metadata with no API key."
    )

    def _yt_oembed(url: str) -> dict:
        """Fetch video metadata via YouTube oEmbed — free, no API key."""
        oe_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
        req = urllib.request.Request(oe_url, headers={"User-Agent": "Lighthouse/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())

    def _extract_vid_id(url: str) -> str:
        m = _re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        return m.group(1) if m else ""

    if st.button("🎥 Load videos", key="btn_yt_load"):
        urls = [u.strip() for u in yt_urls_raw.splitlines() if u.strip()]
        if not urls:
            st.warning("Paste at least one YouTube URL above.")
        else:
            st.session_state["yt_cards"] = []
            for url in urls[:12]:
                try:
                    meta = _yt_oembed(url)
                    vid_id = _extract_vid_id(url)
                    st.session_state["yt_cards"].append({
                        "title":     meta.get("title", ""),
                        "channel":   meta.get("author_name", ""),
                        "thumb":     meta.get("thumbnail_url", ""),
                        "url":       url,
                        "vid_id":    vid_id,
                        "width":     meta.get("thumbnail_width", 480),
                    })
                except Exception as ex:
                    st.session_state["yt_cards"].append({
                        "title": f"Could not load: {url[:50]}",
                        "error": str(ex), "url": url,
                    })

    cards = st.session_state.get("yt_cards", [])
    if cards:
        st.markdown(f"**{len(cards)} video{'s' if len(cards)!=1 else ''} loaded:**")
        yt_cols = st.columns(3, gap="medium")
        for i, c in enumerate(cards):
            with yt_cols[i % 3]:
                if "error" in c:
                    st.markdown(f"""
<div style="background:#fff;border:1px solid #c94f35;border-left:3px solid #c94f35;
border-radius:8px;padding:12px;margin-bottom:12px;font-size:12px;color:#c94f35;">
{e(c['title'])}</div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
<div style="background:#fff;border:1px solid #9dc4d8;border-left:3px solid #d44800;
border-radius:8px;overflow:hidden;margin-bottom:14px;">
  <img src="{e(c['thumb'])}" style="width:100%;display:block;"/>
  <div style="padding:12px 14px;">
    <div style="font-size:13px;font-weight:600;color:#071828;line-height:1.3;margin-bottom:6px;">
      {e(c['title'][:80])}</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;
    letter-spacing:.08em;color:#d44800;margin-bottom:10px;">{e(c['channel'])}</div>
    <a href="{e(c['url'])}" target="_blank"
    style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.06em;
    text-transform:uppercase;color:#d44800;text-decoration:none;
    border-bottom:1px solid #d44800;padding-bottom:1px;">↗ watch on YouTube</a>
  </div>
</div>""", unsafe_allow_html=True)

    with st.expander("How to integrate YouTube into the Lighthouse pipeline"):
        st.markdown("""
**Recommended workflow once YOUTUBE_API_KEY is added:**

1. Search for videos about your topic each morning using YouTube Data API v3
2. Filter for videos with 10K+ views published in the last 7 days
3. Extract transcripts using `youtube-transcript-api` (free, no quota limit)
4. Chunk transcripts into 500-word segments and embed into Pinecone
5. Claude now has access to what creators said — days before it becomes a written post

**Signal value:** TikTok creators often post on YouTube first. Catching it there gives 24-72h advance notice before the TikTok version goes viral.
""")


# ══════════════════════════════════════════════════════════════════════════════
# VISION MAP — strategic roadmap embedded
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div style="border-top:3px double #071828;padding-top:2rem;margin-top:1rem;">
  <span style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.18em;
       text-transform:uppercase;color:#0a7d8c;font-weight:700;">◎ Product Vision</span>
  <div style="font-family:'Georgia',serif;font-size:28px;font-weight:600;
       color:#071828;margin:8px 0 6px;">The Lighthouse Roadmap</div>
  <div style="font-family:'Georgia',serif;font-style:italic;font-size:14px;color:#274d68;
       margin-bottom:20px;">From prototype to cultural intelligence platform — the strategic vision
       and execution roadmap.</div>
</div>
""", unsafe_allow_html=True)

_VISION_MAP_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{background:#062233;font-family:'Georgia',serif;color:#d0eaf0;overflow-x:hidden;}
nav{display:flex;gap:0;border-bottom:1px solid rgba(255,255,255,.1);background:#041a28;}
nav button{flex:1;padding:11px 6px;background:transparent;border:none;
  font-family:'JetBrains Mono',monospace,sans-serif;font-size:9.5px;letter-spacing:.1em;
  text-transform:uppercase;color:rgba(208,234,240,.4);cursor:pointer;
  border-bottom:2px solid transparent;transition:all .2s;}
nav button.active{color:#0fa3b5;border-bottom-color:#0fa3b5;}
nav button:hover:not(.active){color:rgba(208,234,240,.75);}
.panel{display:none;padding:22px 28px;min-height:380px;}
.panel.active{display:block;}
.eyebrow{font-family:'JetBrains Mono',monospace,sans-serif;font-size:9px;letter-spacing:.2em;
  text-transform:uppercase;color:#0fa3b5;font-weight:700;margin-bottom:8px;}
.big-title{font-size:22px;font-weight:600;line-height:1.2;color:#fff;margin-bottom:8px;}
.lead{font-style:italic;font-size:13px;color:rgba(208,234,240,.6);line-height:1.6;max-width:620px;margin-bottom:20px;}
.grid{display:grid;gap:12px;}
.grid-2{grid-template-columns:1fr 1fr;}
.grid-3{grid-template-columns:1fr 1fr 1fr;}
.card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);
  border-radius:8px;padding:14px 16px;transition:.2s;}
.card:hover{background:rgba(255,255,255,.09);border-color:rgba(15,163,181,.4);}
.card-icon{font-size:18px;margin-bottom:7px;}
.card-title{font-family:'JetBrains Mono',monospace,sans-serif;font-size:9.5px;
  letter-spacing:.1em;text-transform:uppercase;color:#0fa3b5;margin-bottom:5px;}
.card-body{font-size:12px;color:rgba(208,234,240,.65);line-height:1.5;}
.card-tag{display:inline-block;margin-top:7px;font-family:'JetBrains Mono',monospace,sans-serif;
  font-size:8px;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 7px;border-radius:20px;}
.tag-now{background:rgba(10,125,140,.3);color:#0fa3b5;border:1px solid rgba(10,125,140,.5);}
.tag-next{background:rgba(26,138,107,.2);color:#1a8a6b;border:1px solid rgba(26,138,107,.4);}
.tag-future{background:rgba(201,79,53,.2);color:#c94f35;border:1px solid rgba(201,79,53,.4);}
.timeline{position:relative;padding-left:22px;}
.timeline::before{content:'';position:absolute;left:7px;top:0;bottom:0;width:1px;background:rgba(255,255,255,.12);}
.tl-item{position:relative;margin-bottom:20px;}
.tl-dot{position:absolute;left:-18px;top:4px;width:8px;height:8px;border-radius:50%;flex:none;}
.tl-label{font-family:'JetBrains Mono',monospace,sans-serif;font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:#0fa3b5;margin-bottom:3px;}
.tl-title{font-size:14px;font-weight:600;color:#fff;margin-bottom:3px;}
.tl-body{font-size:11.5px;color:rgba(208,234,240,.55);line-height:1.5;}
.metaphor-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:8px;}
.m-card{border-radius:8px;padding:12px 14px;border:1px solid;}
.m-icon{font-size:20px;margin-bottom:5px;}
.m-name{font-family:'JetBrains Mono',monospace,sans-serif;font-size:9px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;margin-bottom:4px;}
.m-desc{font-size:11px;line-height:1.5;color:rgba(208,234,240,.6);}
.eco-row{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;}
.eco-pill{padding:4px 10px;border-radius:20px;font-family:'JetBrains Mono',monospace,sans-serif;font-size:8.5px;letter-spacing:.07em;text-transform:uppercase;border:1px solid;}
.eco-active{background:rgba(10,125,140,.2);color:#0fa3b5;border-color:rgba(10,125,140,.5);}
.eco-next{background:rgba(26,138,107,.1);color:#1a8a6b;border-color:rgba(26,138,107,.35);}
.eco-future{background:rgba(110,168,196,.08);color:rgba(110,168,196,.8);border-color:rgba(110,168,196,.25);}
.eco-label{font-family:'JetBrains Mono',monospace,sans-serif;font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;color:rgba(208,234,240,.3);margin-bottom:5px;margin-top:12px;}
.legend{display:flex;gap:14px;margin-bottom:16px;flex-wrap:wrap;}
.leg-item{display:flex;align-items:center;gap:5px;font-family:'JetBrains Mono',monospace,sans-serif;font-size:8.5px;letter-spacing:.05em;text-transform:uppercase;color:rgba(208,234,240,.5);}
.leg-dot{width:7px;height:7px;border-radius:50%;}
</style>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet"/>
</head><body>
<nav>
  <button class="active" onclick="show('ns',this)">North Star</button>
  <button onclick="show('data',this)">Data Layer</button>
  <button onclick="show('intel',this)">Intelligence</button>
  <button onclick="show('exp',this)">Experience</button>
  <button onclick="show('road',this)">Roadmap</button>
</nav>

<div class="panel active" id="ns">
  <div class="eyebrow">The Vision</div>
  <div class="big-title">A living cultural intelligence organism</div>
  <div class="lead">Not a dashboard. Not a listening tool. A strategic partner — showing teams not just what is happening in culture, but what it means, what's coming, and what to do.</div>
  <div class="metaphor-grid">
    <div class="m-card" style="background:rgba(10,125,140,.08);border-color:rgba(10,125,140,.3);">
      <div class="m-icon">🌊</div><div class="m-name" style="color:#0fa3b5;">The Currents</div>
      <div class="m-desc">What culture is already moving toward. Forces brands ignore at their peril.</div>
    </div>
    <div class="m-card" style="background:rgba(201,79,53,.08);border-color:rgba(201,79,53,.3);">
      <div class="m-icon">⬆️</div><div class="m-name" style="color:#c94f35;">The Countercurrents</div>
      <div class="m-desc">The deliberate move against the flow. Unowned territory where brave brands build lasting distinction.</div>
    </div>
    <div class="m-card" style="background:rgba(26,138,107,.08);border-color:rgba(26,138,107,.3);">
      <div class="m-icon">🪸</div><div class="m-name" style="color:#1a8a6b;">The Rocks</div>
      <div class="m-desc">Hidden dangers. Crisis signals before they become crises. The early warning system.</div>
    </div>
    <div class="m-card" style="background:rgba(157,196,216,.08);border-color:rgba(157,196,216,.25);">
      <div class="m-icon">⚓</div><div class="m-name" style="color:#9dc4d8;">The Harbour</div>
      <div class="m-desc">Cultural territory the brand already owns. The safe base before venturing into open water.</div>
    </div>
    <div class="m-card" style="background:rgba(110,168,196,.08);border-color:rgba(110,168,196,.25);">
      <div class="m-icon">🌫️</div><div class="m-name" style="color:#6ea8c4;">The Fog</div>
      <div class="m-desc">Ambiguous signals needing human judgment. Weak signals that could be the next big thing — or noise.</div>
    </div>
    <div class="m-card" style="background:rgba(208,234,240,.04);border-color:rgba(208,234,240,.12);">
      <div class="m-icon">🌅</div><div class="m-name" style="color:rgba(208,234,240,.65);">The Open Sea</div>
      <div class="m-desc">Unexplored cultural territory. White space no brand has claimed. Visible only from the lighthouse beam.</div>
    </div>
  </div>
</div>

<div class="panel" id="data">
  <div class="eyebrow">Signal Ecosystem</div>
  <div class="big-title">Expanding the antenna</div>
  <div class="lead">Intelligence richness is proportional to signal breadth and depth. A phased expansion plan.</div>
  <div class="legend">
    <div class="leg-item"><div class="leg-dot" style="background:#0fa3b5;"></div>Active</div>
    <div class="leg-item"><div class="leg-dot" style="background:#1a8a6b;"></div>Next quarter</div>
    <div class="leg-item"><div class="leg-dot" style="background:#6ea8c4;"></div>Six months+</div>
  </div>
  <div class="eco-label">Social & Community</div>
  <div class="eco-row">
    <div class="eco-pill eco-active">Reddit</div><div class="eco-pill eco-active">TikTok</div>
    <div class="eco-pill eco-next">YouTube Transcripts</div><div class="eco-pill eco-next">X / Twitter</div>
    <div class="eco-pill eco-next">Mumsnet</div><div class="eco-pill eco-future">LinkedIn</div>
    <div class="eco-pill eco-future">Discord</div>
  </div>
  <div class="eco-label">Search & Semantic</div>
  <div class="eco-row">
    <div class="eco-pill eco-next">Exa.ai</div><div class="eco-pill eco-next">Tavily</div>
    <div class="eco-pill eco-next">SerpAPI</div><div class="eco-pill eco-future">Google Trends</div>
    <div class="eco-pill eco-future">App Store reviews</div>
  </div>
  <div class="eco-label">Media & Intelligence</div>
  <div class="eco-row">
    <div class="eco-active eco-pill">RSS</div><div class="eco-pill eco-next">GDELT (global media)</div>
    <div class="eco-pill eco-next">Podcast transcripts</div><div class="eco-pill eco-future">Newsletter archives</div>
    <div class="eco-pill eco-future">Patent filings</div>
  </div>
</div>

<div class="panel" id="intel">
  <div class="eyebrow">AI Layer</div>
  <div class="big-title">From data to foresight</div>
  <div class="lead">Competitive advantage is not more signals — it is deeper intelligence extracted from them.</div>
  <div class="grid grid-2">
    <div class="card"><div class="card-icon">🌡️</div><div class="card-title">Cultural Temperature</div>
      <div class="card-body">Sentiment at signal level — not positive/negative, but nuanced: ironic, anxious, aspirational, nostalgic. Emotional temperature of a category over time.</div>
      <span class="card-tag tag-next">Next</span></div>
    <div class="card"><div class="card-icon">📡</div><div class="card-title">Anomaly Detection</div>
      <div class="card-body">Auto-alerts when signal volume spikes unexpectedly. 2σ above rolling baseline triggers a Lighthouse Alert before anyone else sees it.</div>
      <span class="card-tag tag-next">Next</span></div>
    <div class="card"><div class="card-icon">🧬</div><div class="card-title">Narrative Clustering</div>
      <div class="card-body">Group signals into coherent "stories" spreading across platforms — not just topics, but the narrative arc: problem → reaction → meme.</div>
      <span class="card-tag tag-next">Next</span></div>
    <div class="card"><div class="card-icon">🔮</div><div class="card-title">Momentum Forecasting</div>
      <div class="card-body">Is this topic at 20% of its peak, or 80%? Gives teams a timing signal — when to move, when to hold.</div>
      <span class="card-tag tag-future">6 months</span></div>
    <div class="card"><div class="card-icon">🤖</div><div class="card-title">Research Agents</div>
      <div class="card-body">Autonomous Claude agents that receive a strategic question and find the answer — searching signals, web, and past dispatches autonomously.</div>
      <span class="card-tag tag-future">Vision</span></div>
    <div class="card"><div class="card-icon">🧠</div><div class="card-title">Agency Memory</div>
      <div class="card-body">Fine-tuned on past briefs and campaigns. The system learns what "good" looks like for this specific agency. Intelligence compounds with every use.</div>
      <span class="card-tag tag-future">Vision</span></div>
  </div>
</div>

<div class="panel" id="exp">
  <div class="eyebrow">Strategy UX</div>
  <div class="big-title">Tools strategists actually use</div>
  <div class="lead">The best intelligence is useless if it doesn't fit how strategists think and work.</div>
  <div class="grid grid-3">
    <div class="card"><div class="card-icon">📅</div><div class="card-title">Cultural Calendar</div>
      <div class="card-body">Upcoming cultural moments mapped against brand relevance. Know three weeks in advance which moments are worth owning.</div>
      <span class="card-tag tag-next">Next</span></div>
    <div class="card"><div class="card-icon">⏱️</div><div class="card-title">Window Detector</div>
      <div class="card-body">When cultural conditions align for brand action — the 10-day window when the conversation is at peak receptivity.</div>
      <span class="card-tag tag-next">Next</span></div>
    <div class="card"><div class="card-icon">🔔</div><div class="card-title">Alert Engine</div>
      <div class="card-body">Push to Slack, email, or SMS when thresholds are crossed. The system works while you sleep.</div>
      <span class="card-tag tag-next">Next</span></div>
    <div class="card"><div class="card-icon">💬</div><div class="card-title">Strategy Chat</div>
      <div class="card-body">"Ask the Lighthouse" — conversational interface to the entire signal database. Sourced, specific answers in seconds.</div>
      <span class="card-tag tag-future">6 months</span></div>
    <div class="card"><div class="card-icon">🎨</div><div class="card-title">Creative Springboard</div>
      <div class="card-body">From strategic direction to three creative territories with tone of voice, visual references, and platform strategy.</div>
      <span class="card-tag tag-future">6 months</span></div>
    <div class="card"><div class="card-icon">📊</div><div class="card-title">Client Mode</div>
      <div class="card-body">Polished client-facing view — no agency backstage visible. The Lighthouse becomes the deliverable, not the source.</div>
      <span class="card-tag tag-future">Vision</span></div>
  </div>
</div>

<div class="panel" id="road">
  <div class="eyebrow">Execution Roadmap</div>
  <div class="big-title">From prototype to platform</div>
  <div class="lead">A phased approach delivering client value at every stage — compounding intelligence, not a big-bang launch.</div>
  <div class="timeline">
    <div class="tl-item">
      <div class="tl-dot" style="background:#0fa3b5;"></div>
      <div class="tl-label">Now — v1 Complete</div>
      <div class="tl-title">Lighthouse Core</div>
      <div class="tl-body">Editorial dispatch · Signal Map · Momentum Tracker · Competitive Pulse · Raw Signal Feed · Briefing Builder · Signal Lab · Archive · PDF Export. Sellable today.</div>
    </div>
    <div class="tl-item">
      <div class="tl-dot" style="background:#0fa3b5;box-shadow:0 0 0 3px rgba(10,125,140,.3);"></div>
      <div class="tl-label">v2 · 1–2 months</div>
      <div class="tl-title">Intelligence Depth</div>
      <div class="tl-body">Exa.ai + GDELT + YouTube in pipeline · Sentiment layer · Anomaly alerts (Slack) · Cultural Calendar · Window Detector. Price: tier up.</div>
    </div>
    <div class="tl-item">
      <div class="tl-dot" style="background:#1a8a6b;"></div>
      <div class="tl-label">v3 · 3–4 months</div>
      <div class="tl-title">Strategy Suite</div>
      <div class="tl-body">Narrative clustering · Momentum forecasting · Strategy Chat · Creative Springboard · Client mode · White-label. Price: agency retainer.</div>
    </div>
    <div class="tl-item">
      <div class="tl-dot" style="background:#6ea8c4;"></div>
      <div class="tl-label">v4 · 6 months+</div>
      <div class="tl-title">Cultural Intelligence Platform</div>
      <div class="tl-body">Research agents · Agency memory · Cultural Tension Mapper · War Room Mode · API for research firms. Price: platform.</div>
    </div>
  </div>
</div>

<script>
function show(id,btn){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}
</script>
</body></html>"""

st.components.v1.html(_VISION_MAP_HTML, height=550, scrolling=False)
