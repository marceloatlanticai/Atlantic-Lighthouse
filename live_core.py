"""
live_core.py — the logic of the Live Session, kept free of Streamlit.

The live session is the meeting itself, run on one screen that the team and
the client both look at: before it, the client answers ten questions on a link
of their own; Lighthouse digs four parts (Company, Competition, Customer,
Climate) and the team cuts what is weak; in the room, people keep, star, tweak
and kill currents while Lighthouse listens and picks what the room keeps
coming back to; the selects become countercurrent territories, and the
territories a leave-behind with its own link.

Plain Python on purpose, like session_core.py next to it: this is where a
mistake would be invisible in the room — a pick the room never made, a quote
put in the wrong mouth, an answer saved over somebody else's.

RULES, decided with the prototype and enforced below:
  1. A strong topic is COUNTED, not guessed. The model only says which current
     a line is about; how strong that makes it is arithmetic done here — how
     many people, how many mentions, whether somebody came back to it.
  2. People decide. A human decision is never overridden, an undone pick is
     never made again, and disagreement is only ever flagged.
  3. The facilitator's own words never count as strength.
  4. Everything cited exists: every piece of evidence is a post, an article or
     a figure that was collected, or a line somebody said in the room.
  5. The client's link opens their own answers and nothing else.
"""
from __future__ import annotations

import html
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Optional

# ══════════════════════════════════════════════════════════════════════════════
# The intake — the client's ten questions, on a link of their own
# ══════════════════════════════════════════════════════════════════════════════
# From the session plan. (question, hint, short label for the team's screens).
QUESTIONS = (
    ("What's the business goal for the next 12 months?", "One or two sentences.", "The goal"),
    ("From a marketing perspective, what's the problem as you see it?",
     "The marketing problem, not just the business one.", "The marketing problem"),
    ("What does your brand deliver that no one else can?", "", "What only they deliver"),
    ("What have you tried, and why didn't it work?", "", "What they tried"),
    ("Who do you watch? Who do you want to beat?", "Names, separated by commas.", "Who they watch"),
    ("Who is your customer, and who are the customers you want?", "", "Their customer"),
    ("Three things you're curious about right now.", "One per line.", "What they are curious about"),
    ("Where does your gut disagree with what your category believes?", "", "Where the gut disagrees"),
    ("A brand, video or TikTok you love from outside your category.", "A name or a link.", "What they love"),
    ("Who will be in the room?", "Names and roles.", "Who will be in the room"),
)
N_Q = len(QUESTIONS)
Q_GOAL, Q_PROBLEM, Q_UNIQUE, Q_TRIED, Q_RIVALS, Q_CUSTOMER, Q_CURIOUS, Q_GUT, Q_LOVE, Q_ROOM = range(N_Q)
MULTI = {Q_CURIOUS, Q_ROOM}               # questions answered one item per line
ANSWER_MAX = 2000
# The six answers the session's opening screen shows, in this order.
CARDS = ((Q_GOAL, "The goal"), (Q_PROBLEM, "The marketing problem"), (Q_CURIOUS, "What they are curious about"),
         (Q_RIVALS, "Who they watch"), (Q_GUT, "Where the gut disagrees"), (Q_UNIQUE, "What only they deliver"))

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def clip(s, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def new_token() -> str:
    """An unguessable link key: 144 random bits, URL-safe, 24 characters.

    THE TOKEN IS THE ONLY LOCK on the client's link — there is no password, by
    design (Marcelo, 28 Oct: the client opens it without one). So it is long
    enough that guessing one is not a strategy, and the route that reads it
    accepts nothing that does not look like one."""
    return secrets.token_urlsafe(18)


def valid_token(t) -> bool:
    return isinstance(t, str) and bool(_TOKEN_RE.match(t))


def intake_record_id(token: str) -> str:
    return f"intake:{token}"


def new_intake(live_id: str, client_name: str, brand: str = "", now: Optional[str] = None) -> dict:
    return {"kind": "intake", "live_id": live_id, "client_name": clip(client_name, 80),
            "brand": clip(brand, 80), "answers": [""] * N_Q, "status": "open",
            "created_at": now or now_iso(), "updated_at": "", "submitted_at": "",
            "applied": [], "edits": {}}


def intake_defaults(rec: Optional[dict]) -> dict:
    rec = rec if isinstance(rec, dict) else {}
    a = rec.get("answers")
    a = [str(x or "") for x in a] if isinstance(a, list) else []
    rec["answers"] = (a + [""] * N_Q)[:N_Q]
    rec.setdefault("status", "open")
    rec.setdefault("applied", [])
    rec.setdefault("edits", {})
    rec.setdefault("submitted_at", "")
    rec.setdefault("updated_at", "")
    return rec


def clean_answer(text) -> str:
    """Trimmed, control characters out, blank lines squeezed, at most 2,000 chars."""
    s = _CTRL.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:ANSWER_MAX]


def intake_open(rec: Optional[dict]) -> bool:
    return isinstance(rec, dict) and rec.get("kind") == "intake" and rec.get("status") == "open"


def intake_apply(rec: dict, value, now: Optional[str] = None) -> dict:
    """What the client's form sent: {"items": [{"u": id, "i": question, "x": text}],
    "done": id}. Returns {"changed": n, "done": bool, "closed": bool, "acked": n}
    — `acked` counts ids seen for the first time: the record must be saved even
    when nothing changed, or the form would keep resending them.

    EACH ANSWER IS APPLIED ONCE, BY ITS OWN ID. A component hands its last value
    back on every rerun, and the team may have edited an answer since — so a
    resent value must never be applied again, or a stale answer would quietly
    overwrite the team's correction. The form gives every answer it sends a
    random id; the ids already applied are kept on the record (the last 300),
    which also works across two tabs and a reload, where a counter would not."""
    out = {"changed": 0, "done": False, "closed": False, "acked": 0}
    intake_defaults(rec)
    if rec.get("status") != "open":
        out["closed"] = True
        return out
    if not isinstance(value, dict):
        return out
    applied = [str(x) for x in rec.get("applied") or []]
    seen = set(applied)
    items = value.get("items") if isinstance(value.get("items"), list) else []
    when = now or now_iso()
    for it in items[:60]:
        if not isinstance(it, dict):
            continue
        u = re.sub(r"[^A-Za-z0-9_-]", "", str(it.get("u") or ""))[:40]
        if not u or u in seen:
            continue
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        seen.add(u)
        applied.append(u)
        out["acked"] += 1
        if not 0 <= i < N_Q:
            continue
        x = clean_answer(it.get("x"))
        if x != rec["answers"][i]:
            rec["answers"][i] = x
            rec["edits"][str(i)] = "client"
            out["changed"] += 1
    d = re.sub(r"[^A-Za-z0-9_-]", "", str(value.get("done") or ""))[:40]
    if d and d not in seen:
        applied.append(d)
        out["acked"] += 1
        if not rec.get("submitted_at"):
            rec["submitted_at"] = when
            out["done"] = True
    rec["applied"] = applied[-300:]
    if out["changed"] or out["done"]:
        rec["updated_at"] = when
    return out


def intake_set(rec: dict, i, text, by: str, now: Optional[str] = None) -> bool:
    """The team corrects or completes an answer. Returns True when it changed."""
    intake_defaults(rec)
    try:
        i = int(i)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < N_Q:
        return False
    x = clean_answer(text)
    if x == rec["answers"][i]:
        return False
    rec["answers"][i] = x
    rec["edits"][str(i)] = clip(by, 40) or "team"
    rec["updated_at"] = now or now_iso()
    return True


def intake_progress(rec: Optional[dict]) -> tuple:
    a = intake_defaults(dict(rec or {}))["answers"]
    return sum(1 for x in a if x.strip()), N_Q


def intake_public_args(rec: dict) -> dict:
    """Everything the client's form is given — and nothing else: no ids of other
    records, no names of the team, no notes."""
    intake_defaults(rec)
    return {"client": rec.get("client_name") or rec.get("brand") or "",
            "questions": [{"q": q, "h": h, "multi": i in MULTI} for i, (q, h, _l) in enumerate(QUESTIONS)],
            "answers": list(rec["answers"]), "status": rec.get("status", "open"),
            "submitted": bool(rec.get("submitted_at")), "applied": list(rec.get("applied") or [])[-120:]}


def answer_lines(text: str, n: int = 0) -> list:
    out = [clip(re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", x), 240)
           for x in str(text or "").split("\n")]
    out = [x for x in out if x]
    return out[:n] if n else out


def rivals_from(answers: list) -> str:
    """'TikTok, Instagram and Lemon8' → 'TikTok, Instagram, Lemon8'."""
    raw = str((answers or [""] * N_Q)[Q_RIVALS] or "")
    parts = re.split(r"[,;\n/]|\band\b|&", raw)
    seen, out = set(), []
    for p in parts:
        p = clip(re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", p), 40).strip(" .")
        if len(p) >= 2 and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return ", ".join(out[:8])


def curiosities_from(answers: list) -> list:
    return answer_lines((answers or [""] * N_Q)[Q_CURIOUS], 3)


# ══════════════════════════════════════════════════════════════════════════════
# The session
# ══════════════════════════════════════════════════════════════════════════════

SECTIONS = (
    {"key": "Company", "head": "Company currents", "min": 15,
     "q": "Mission, marketing history, product and the challenge in front of it.",
     "lens": "the brand itself — its mission, marketing history, product and the challenge in "
             "front of it, as the evidence shows people see it"},
    {"key": "Competition", "head": "Competition currents", "min": 15,
     "q": "What competitors do, and what is moving in the wider industry.",
     "lens": "what the competitors do and what is moving in the wider industry"},
    {"key": "Customer", "head": "Customer currents", "min": 15,
     "q": "What customers are dealing with, and the barriers they face.",
     "lens": "what customers are dealing with — their barriers, needs and voices"},
    {"key": "Climate", "head": "Climate currents", "min": 15,
     "q": "Macro forces, and what is happening in culture right now.",
     "lens": "macro forces — the economy, culture, what is happening right now"},
)
N_SEC = len(SECTIONS)
ROS = ((10, "Intro"), (15, "Company"), (15, "Competition"), (15, "Customer"), (5, "Break"),
       (15, "Climate"), (5, "Selects"), (30, "Countercurrent"), (10, "Next steps"))
SCREENS = ("setup", "sec", "selects", "terr", "brief")
DECISIONS = ("keep", "star", "kill")
MAX_CURRENTS = 14            # per part, everything included — the screen has to stay readable
TITLE_MAX, BODY_MAX = 120, 420


def live_record_id(folder_id: str, now: Optional[datetime] = None) -> str:
    t = (now or datetime.utcnow()).strftime("%Y%m%d-%H%M%S")
    return f"live:{folder_id}:{t}"


def new_live(folder_id: str, client: dict, user: str, token: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.utcnow()
    c = client or {}
    sess = {
        "id": live_record_id(folder_id, now), "kind": "live",
        "client_id": folder_id, "client_name": clip(c.get("name") or c.get("brand") or "", 80),
        "created_at": now.isoformat(timespec="seconds"), "created_by": clip(user, 40),
        "started_at": now.isoformat(timespec="seconds"),     # the room's clock; moves at Go live
        "status": "prep", "intake_token": token,
        "setup": {}, "dig": {}, "sections": [], "cid_n": 0,
    }
    return live_defaults(sess)


def live_defaults(sess: dict) -> dict:
    """Every field present — older records and half-written ones included."""
    sess.setdefault("status", "prep")
    sess.setdefault("setup", {})
    sess.setdefault("dig", {})
    secs = sess.get("sections") if isinstance(sess.get("sections"), list) else []
    for i, base in enumerate(SECTIONS):
        if i >= len(secs) or not isinstance(secs[i], dict):
            secs = secs[:i] + [{}] + secs[i + 1:]
        s = secs[i]
        s["key"] = base["key"]
        s.setdefault("currents", [])
        s.setdefault("status", "todo")
    sess["sections"] = secs[:N_SEC]
    for k in ("dec", "tweak", "human", "ai", "sugg", "locked", "flag", "talk", "last_topic",
              "newt", "reads", "chat", "sec_start"):
        if not isinstance(sess.get(k), dict):
            sess[k] = {}
    for k in ("sec_marks",):
        if not isinstance(sess.get(k), list):
            sess[k] = []
    sess.setdefault("cid_n", 0)
    sess.setdefault("mode", "auto")
    sess.setdefault("screen", "setup")
    sess.setdefault("sec", 0)
    sess.setdefault("label_upto", 0)
    sess.setdefault("label_fail", 0)
    sess.setdefault("live_ack", -1)
    sess.setdefault("went_live", None)
    sess.setdefault("terr", {"status": "none", "round": 0, "items": [], "err": ""})
    sess.setdefault("leave", {})
    sess.setdefault("lang", "")
    sess.setdefault("engine", "")
    # the session room's fields: the microphone, the people, the voices
    sess.setdefault("chunks", [])
    sess.setdefault("last_seq", -1)
    sess.setdefault("people", [])
    sess.setdefault("voices", {})
    sess.setdefault("taps", [])
    sess.setdefault("intro_on", False)
    sess.setdefault("intro_win", [])
    sess.setdefault("voice_mode", "")
    sess.setdefault("assign", {})
    return sess


def _new_cid(sess: dict) -> str:
    sess["cid_n"] = int(sess.get("cid_n") or 0) + 1
    return f"c{sess['cid_n']}"


def setup_defaults(client: dict, answers: list, markets=(), default_market: str = "",
                   window: int = 12) -> dict:
    """What Lighthouse is pointed at, before the team adjusts it: the client's
    profile for the subject, the intake for the rivals and the question."""
    c = client or {}
    cur = curiosities_from(answers)
    mk = c.get("market") if c.get("market") in (markets or ()) else default_market
    return {"brand": clip(c.get("brand") or c.get("name") or "", 60),
            "category": clip(c.get("category"), 60), "product": clip(c.get("product"), 60),
            "market": mk or "", "competitors": rivals_from(answers), "window": int(window or 12),
            "focus": "", "question": cur[0] if cur else ""}


# ── Evidence ─────────────────────────────────────────────────────────────────

_NET = {"reddit": "Reddit", "tiktok": "TikTok", "instagram": "Instagram", "twitter": "X",
        "youtube": "YouTube", "web": "Web", "gdelt": "News", "hacker_news": "Hacker News",
        "rss": "News", "db": "Archive", "trade": "Trade press", "letter": "Newsletter",
        "figure": "Figure", "room": "The room", "pinterest": "Pinterest",
        "pinterest trends": "Pinterest Trends"}


def net_label(src: str) -> str:
    s = str(src or "").lower()
    return _NET.get(s, clip(src, 24) or "Web")


def plain(s) -> str:
    """Source text as words: X and the news hand over '&amp;' and '&#39;' already
    escaped — read as markup they come out as '&a…' once a title is cut."""
    t = str(s or "")
    for _ in range(2):              # some arrive escaped twice
        u = html.unescape(t)
        if u == t:
            break
        t = u
    return t


def _ev_from_signal(s: dict, kind: str = "post") -> dict:
    return {"ti": clip(plain(s.get("title") or s.get("content") or ""), 140),
            "url": str(s.get("url") or "")[:500] if str(s.get("url") or "").startswith(("http://", "https://")) else "",
            "src": clip(s.get("source") or kind, 30), "d": str(s.get("timestamp") or s.get("date") or "")[:10],
            "k": kind}


def evidence_line(ev: list) -> str:
    """'4 posts · Reddit, TikTok · 1 article · 1 figure' — what a current stands on."""
    if not ev:
        return ""
    posts = [e for e in ev if e.get("k") == "post"]
    arts = [e for e in ev if e.get("k") == "trade"]
    figs = [e for e in ev if e.get("k") == "figure"]
    room = [e for e in ev if e.get("k") == "room"]
    bits = []
    if posts:
        nets = list(dict.fromkeys(net_label(e.get("src")) for e in posts))
        bits.append(f"{len(posts)} post{'s' if len(posts) != 1 else ''} · {', '.join(nets[:3])}")
    if arts:
        bits.append(f"{len(arts)} article{'s' if len(arts) != 1 else ''}")
    if figs:
        bits.append(f"{len(figs)} figure{'s' if len(figs) != 1 else ''}")
    if room:
        bits.append("said in the room")
    return " · ".join(bits)


# ── The dig: four parts, each through its own lens ───────────────────────────

def interleave(items: list, cap: int = 160) -> list:
    """One of each network in turn, up to `cap`. A scan returns its posts
    source by source, so cutting the list at 160 would hand the model all of
    Reddit and none of TikTok; taken in turns, every network makes the cut."""
    groups: dict = {}
    for s in items or []:
        if isinstance(s, dict):
            groups.setdefault(str(s.get("source") or ""), []).append(s)
    out, lists = [], list(groups.values())
    i = 0
    while len(out) < cap and any(i < len(g) for g in lists):
        for g in lists:
            if i < len(g) and len(out) < cap:
                out.append(g[i])
        i += 1
    return out


def listing(items: list, prefix: str, n_content: int = 220, cap: int = 160) -> str:
    rows = []
    for j, s in enumerate((items or [])[:cap]):
        rows.append(f"[{prefix}{j}] {net_label(s.get('source'))} · {str(s.get('timestamp') or s.get('date') or '')[:10] or 'undated'}"
                    f" · {clip(s.get('title'), 110)}\n{clip(s.get('content'), n_content)}")
    return "\n\n".join(rows)


def figures_listing(figs: list) -> str:
    rows = []
    for j, f in enumerate((figs or [])[:10]):
        rows.append(f"[F{j}] {clip(f.get('figure'), 20)} — {clip(f.get('claim'), 160)} "
                    f"({clip(f.get('source'), 40)}, {str(f.get('date') or '')[:10]})")
    return "\n".join(rows)


def _answers_block(answers: list) -> str:
    rows = []
    for i, (q, _h, label) in enumerate(QUESTIONS):
        a = clip((answers or [""] * N_Q)[i] if i < len(answers or []) else "", 500)
        if a:
            rows.append(f"- {label}: {a}")
    return "\n".join(rows) or "- (the client has not answered the intake yet)"


def dig_prompt(setup: dict, answers: list, signals: list, trade: list, figures: list,
               today: str, only: Optional[int] = None, avoid: Optional[list] = None) -> str:
    """The four lenses over one scan's evidence — or, with `only`, one part again
    (Re-dig), never repeating `avoid`."""
    st = setup or {}
    brand = st.get("brand") or "the brand"
    subject = " · ".join(p for p in (st.get("category"), st.get("product")) if p) or "its category"
    comps = st.get("competitors") or "its competitors"
    parts = [SECTIONS[only]] if only is not None else list(SECTIONS)
    lenses = "\n".join(f"- {p['key']} — {p['lens']}." .replace("the competitors", f"the competitors ({comps})")
                       for p in parts)
    keep = "\n".join(f"- {clip(t, 120)}" for t in (avoid or []) if t)
    n = "3 or 4" if only is None else "3"
    return f"""You are preparing a two-hour live workshop with {brand} ({subject}, {st.get('market') or 'their market'}). Today is {today}.

WHAT THE CLIENT TOLD US BEFORE THE SESSION:
{_answers_block(answers)}

Write the currents for {'each of the four parts' if only is None else 'this part'} of the session, each through its own lens:
{lenses}

{n} currents per part. A current is something MOVING that the evidence shows — not a topic. For each:
- "title": an argument with a point of view, at most 8 words (not a description, not a question)
- "body": two sentences, at most 40 words: what is happening, and why it matters for {brand}
- the evidence it stands on, as indexes from the lists below: "s" for posts [S#], "t" for trade articles [T#], "f" for figures [F#]. At least one index; never invent one; a current the evidence does not support is not written.
Never repeat a current across parts{', and never repeat or reword any of these:' if keep else '.'}
{keep}
Prefer currents that bear on what the client said they want, fear or are curious about. Plain words; no consultancy language.

POSTS:
{listing(signals, 'S') or '(none)'}

TRADE PRESS:
{listing(trade, 'T', 200, 40) or '(none)'}

FIGURES (checked against their sources):
{figures_listing(figures) or '(none)'}

Answer only with JSON: {{"sections": [{{"key": "{parts[0]['key']}", "currents": [{{"title": "…", "body": "…", "s": [0, 4], "t": [1], "f": []}}]}}]}}"""


def _idx_list(v, n: int) -> list:
    out = []
    for x in (v if isinstance(v, list) else []):
        try:
            j = int(str(x).lstrip("STFstf"))
        except (TypeError, ValueError):
            continue
        if 0 <= j < n and j not in out:
            out.append(j)
    return out


def parse_dig(obj, signals: list, trade: list, figures: list, only: Optional[int] = None,
              avoid: Optional[list] = None) -> list:
    """[[current, …] per part] — each current with its evidence resolved to what
    was really collected. A current left with no evidence is dropped, and so is
    a title already used (in another part, or in `avoid`)."""
    keys = {p["key"].lower(): i for i, p in enumerate(SECTIONS)}
    out = [[] for _ in SECTIONS]
    seen = {clip(t, 120).lower() for t in (avoid or []) if t}
    rows = (obj or {}).get("sections") if isinstance(obj, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        i = keys.get(str(r.get("key") or "").strip().lower())
        if i is None or (only is not None and i != only):
            continue
        for c in (r.get("currents") if isinstance(r.get("currents"), list) else [])[:6]:
            if not isinstance(c, dict):
                continue
            t, b = clip(c.get("title"), TITLE_MAX), clip(c.get("body"), BODY_MAX)
            if not t or t.lower() in seen:
                continue
            ev = ([_ev_from_signal(signals[j], "post") for j in _idx_list(c.get("s"), len(signals or []))] +
                  [dict(_ev_from_signal(trade[j], "trade"), src=clip((trade[j] or {}).get("source") or "trade", 30))
                   for j in _idx_list(c.get("t"), len(trade or []))] +
                  [{"ti": clip(f"{(figures[j] or {}).get('figure', '')} — {(figures[j] or {}).get('claim', '')}", 160),
                    "url": str((figures[j] or {}).get("url") or "")[:500], "src": clip((figures[j] or {}).get("source"), 30),
                    "d": str((figures[j] or {}).get("date") or "")[:10], "k": "figure"}
                   for j in _idx_list(c.get("f"), len(figures or []))])
            if not ev:
                continue
            seen.add(t.lower())
            out[i].append({"t": t, "b": b, "ev": ev[:8]})
            if len(out[i]) >= 4:
                break
    return out


def apply_dig(sess: dict, parts: list, only: Optional[int] = None, report_id: str = "",
              now: Optional[str] = None) -> int:
    """Put what the dig wrote on the four parts. A full dig REPLACES the dug
    currents (the room's own and the asked ones stay); a part dug again replaces
    only that part's. Decisions on currents that are gone are dropped.
    Returns how many currents were written."""
    live_defaults(sess)
    when = now or now_iso()
    n = 0
    for i, cur in enumerate(parts or []):
        if i >= N_SEC or (only is not None and i != only):
            continue
        sec = sess["sections"][i]
        gone = [c["id"] for c in sec["currents"] if c.get("src") == "dig"]
        sec["currents"] = [c for c in sec["currents"] if c.get("src") != "dig"]
        for k in ("dec", "tweak", "human", "ai", "sugg", "locked", "flag"):
            for cid in gone:
                sess[k].pop(cid, None)
        for c in cur or []:
            sec["currents"].append({"id": _new_cid(sess), "t": c["t"], "b": c.get("b", ""),
                                    "ev": c.get("ev") or [], "src": "dig", "cut": False, "at": when})
            n += 1
        sec["status"] = "done" if cur else "empty"
        sec["dug_at"] = when
    if report_id:
        sess["dig"]["report_id"] = report_id
    return n


# ── Currents and decisions ───────────────────────────────────────────────────

def all_currents(sess: dict, sec: int, include_cut: bool = False) -> list:
    try:
        cur = sess["sections"][int(sec)]["currents"]
    except (KeyError, IndexError, TypeError, ValueError):
        return []
    return [c for c in cur if include_cut or not c.get("cut")]


def find_current(sess: dict, cid: str) -> tuple:
    for i, s in enumerate(sess.get("sections") or []):
        for c in s.get("currents") or []:
            if c.get("id") == cid:
                return i, c
    return -1, None


def title_of(sess: dict, c: dict) -> str:
    return (sess.get("tweak") or {}).get(c.get("id"), "") or c.get("t", "")


def decide(sess: dict, cid: str, d: str) -> bool:
    """A person's decision: Keep, Star, Kill — or the same again to clear it.
    Whatever Lighthouse had picked or suggested gives way, for good."""
    i, c = find_current(sess, cid)
    if not c:
        return False
    d = d if d in DECISIONS else ""
    sess["dec"][cid] = "" if sess["dec"].get(cid) == d else d
    sess["human"][cid] = True
    sess["ai"].pop(cid, None)
    sess["sugg"].pop(cid, None)
    return True


def set_decision(sess: dict, cid: str, d: str) -> bool:
    """Like decide, without the toggle — 'Take it out' on the selects."""
    i, c = find_current(sess, cid)
    if not c:
        return False
    sess["dec"][cid] = d if d in DECISIONS else ""
    sess["human"][cid] = True
    sess["ai"].pop(cid, None)
    sess["sugg"].pop(cid, None)
    return True


def tweak(sess: dict, cid: str, text: str) -> bool:
    """Rewritten on the spot. A tweaked current is a kept one, by a person."""
    i, c = find_current(sess, cid)
    t = clip(text, TITLE_MAX)
    if not c or not t:
        return False
    sess["tweak"][cid] = "" if t == c.get("t") else t
    if not sess["dec"].get(cid) or sess["dec"][cid] == "kill":
        sess["dec"][cid] = "keep"
    sess["human"][cid] = True
    sess["ai"].pop(cid, None)
    sess["sugg"].pop(cid, None)
    return True


def add_current(sess: dict, sec: int, title: str, src: str = "room", body: str = "",
                ev: Optional[list] = None, q: str = "", keep: bool = True,
                now: Optional[str] = None) -> str:
    """A current the data did not find: the room's own (kept at once, by a
    person), or one Lighthouse dug for the room's question (left undecided)."""
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    t = clip(title, TITLE_MAX)
    if not t or not 0 <= sec < N_SEC:
        return ""
    live_defaults(sess)
    cur = sess["sections"][sec]["currents"]
    if len(cur) >= MAX_CURRENTS + 6:
        return ""
    cid = _new_cid(sess)
    cur.append({"id": cid, "t": t, "b": clip(body, BODY_MAX), "ev": list(ev or [])[:8],
                "src": src if src in ("room", "team", "ask", "talk", "dig") else "room",
                "cut": False, "q": clip(q, 200), "at": now or now_iso()})
    if keep:
        sess["dec"][cid] = "keep"
        sess["human"][cid] = True
    return cid


def cut(sess: dict, cid: str, on: bool = True) -> bool:
    """Before the meeting: the team takes a weak current off the screen (it can
    be put back). Cut currents never reach the room or the listener."""
    i, c = find_current(sess, cid)
    if not c:
        return False
    c["cut"] = bool(on)
    return True


def selects(sess: dict) -> list:
    out = []
    for i, s in enumerate(sess.get("sections") or []):
        for c in s.get("currents") or []:
            d = (sess.get("dec") or {}).get(c["id"], "")
            if not c.get("cut") and d in ("keep", "star"):
                out.append({"id": c["id"], "sec": i, "t": title_of(sess, c), "b": c.get("b", ""),
                            "star": d == "star", "ai": bool((sess.get("ai") or {}).get(c["id"])),
                            "src": c.get("src", ""), "ev": c.get("ev") or []})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Listening: what the room keeps coming back to
# ══════════════════════════════════════════════════════════════════════════════
# Every ~30 seconds the lines said since the last reading go to the fast model,
# which says only WHICH current each line is about (or a new topic, or none,
# and whether the speaker pushed back). Everything else is counted here.

READ_GAP = 25.0           # seconds between two readings, at least
READ_MIN_LINES = 2        # countable lines needed for a reading on the clock
READ_MAX_LINES = 6        # …or this many, whatever the clock says
LINE_SETTLE = 3.0         # a line younger than this may still get its speaker (a late tap)
CONTEXT_LINES = 4         # already-read lines sent along so the model knows where we are


def is_fac(p: Optional[dict]) -> bool:
    """The Atlantic side of the table: the person running the laptop ('You'),
    or anyone marked as team. Their words set the context and never count."""
    return bool(p and (p.get("you") or p.get("fac")))


def line_key(n: int, j: int) -> str:
    return f"{n}.{j}"


def keyed_lines(lines: list) -> list:
    """session_core.session_lines with a stable key per line: chunk.run."""
    out, last_n, j = [], None, 0
    for l in lines or []:
        n = l.get("n")
        j = j + 1 if n == last_n else 0
        last_n = n
        out.append(dict(l, k=line_key(n, j)))
    return out


def sec_at(sess: dict, n: int) -> int:
    """The part on screen when chunk n was said: -1 off the four parts."""
    cur = -1
    for m in sess.get("sec_marks") or []:
        try:
            at, s = int(m[0]), int(m[1])
        except (TypeError, ValueError, IndexError):
            continue
        if at <= n:
            cur = s
        else:
            break
    return cur


def mark_screen(sess: dict, screen: str, sec: int) -> None:
    """Note where the meeting is, against the transcript: from chunk n on, the
    part (or -1) and the screen — so every line can be put under the part, or
    the screen, it was said on."""
    n = len(sess.get("chunks") or [])
    s = sec if screen == "sec" else -1
    scr = screen if screen in SCREENS else "setup"
    marks = sess.setdefault("sec_marks", [])
    last = marks[-1] if marks else None
    if last and last[1] == s and (len(last) < 3 or last[2] == scr):
        return
    if last and last[0] == n:
        marks[-1] = [n, s, scr]
    else:
        marks.append([n, s, scr])


_SCREEN_LABEL = {"setup": "Opening", "selects": "The selects", "terr": "Countercurrent",
                 "brief": "The leave-behind"}


def part_at(sess: dict, n: int) -> str:
    """'Company' · 'Opening' · 'The selects' … — what was on screen when chunk n was said."""
    lab = "Opening"
    for m in sess.get("sec_marks") or []:
        try:
            at, sec = int(m[0]), int(m[1])
        except (TypeError, ValueError, IndexError):
            continue
        if at > n:
            break
        if 0 <= sec < N_SEC:
            lab = SECTIONS[sec]["key"]
        else:
            lab = _SCREEN_LABEL.get(m[2] if len(m) > 2 else "", "Between the parts")
    return lab


# ── Every interaction, as it happens ─────────────────────────────────────────
# The final report tells the meeting back in order — every decision, rewrite,
# question, pick and change of part, with its time — so each one is written
# down the moment it is applied. Times are UTC like everything else here.

LOG_MAX = 4000


def log_event(sess: dict, k: str, when: Optional[str] = None, **data) -> None:
    lg = sess.setdefault("log", [])
    ev = {"t": when or now_iso(), "k": k}
    for kk, v in data.items():
        if v not in (None, "", [], {}):
            ev[kk] = v
    # A note typed in a territory is one event, however many pauses it took.
    if k == "tnote" and lg and lg[-1].get("k") == "tnote" and lg[-1].get("id") == ev.get("id"):
        lg[-1] = ev
    else:
        lg.append(ev)
    if len(lg) > LOG_MAX:
        del lg[: len(lg) - LOG_MAX]


def utc_ts(iso) -> Optional[float]:
    """Epoch seconds of one of our timestamps. They are written with utcnow()
    and carry no zone, so they are read as UTC — never as the server's local
    time, which would age every line by the server's offset."""
    try:
        d = datetime.fromisoformat(str(iso)[:19])
    except (TypeError, ValueError):
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def _chunk_age(sess: dict, n: int, now_t: float) -> float:
    try:
        t = utc_ts(sess["chunks"][n].get("t", ""))
    except (IndexError, KeyError, TypeError, AttributeError):
        t = None
    return 1e9 if t is None else now_t - t


def label_batch(sess: dict, lines: list, people: dict, now_t: Optional[float] = None,
                force: bool = False, last_t: float = 0.0) -> Optional[dict]:
    """The next lines to read, all from one part, or None when it is not time.

    Returns {sec, todo: [lines to label], ctx: [lines for context], upto}.
    `people` maps person id → person dict; `lines` are keyed_lines."""
    now_t = time.time() if now_t is None else now_t
    upto = int(sess.get("label_upto") or 0)
    fresh = [l for l in lines if l.get("n", -1) >= upto and not l.get("note")
             and _chunk_age(sess, l["n"], now_t) >= (0 if force else LINE_SETTLE)]
    if not fresh:
        return None
    sec = sec_at(sess, fresh[0]["n"])
    group = []
    for l in fresh:
        if sec_at(sess, l["n"]) != sec:
            break
        group.append(l)
    new_upto = max(l["n"] for l in group) + 1
    # all runs of the last chunk travel together
    group = [l for l in fresh if l["n"] < new_upto]
    if sec < 0:
        # Said off the four parts (the opening, the selects…): nothing to count.
        return {"sec": -1, "todo": [], "ctx": [], "upto": new_upto}
    countable = [l for l in group if not is_fac(people.get(l.get("w")))]
    words = sum(len(str(l.get("x", "")).split()) for l in countable)
    since = now_t - float(last_t or 0)
    # A lone line after a pause is read too, a little later: the last word on a
    # topic is often the one that makes it strong.
    due = force or len(countable) >= READ_MAX_LINES or words >= 120 or \
        (len(countable) >= READ_MIN_LINES and since >= READ_GAP) or \
        (len(countable) >= 1 and since >= 2 * READ_GAP)
    if not due:
        return None
    before = [l for l in lines if l.get("n", -1) < upto and sec_at(sess, l["n"]) == sec][-CONTEXT_LINES:]
    return {"sec": sec, "todo": group, "ctx": before, "upto": new_upto}


def _who(people: dict, w: str, labels: dict) -> str:
    p = people.get(w)
    lab = labels.get(w) or ("" if not p else (p.get("name") or ""))
    role = (p or {}).get("role", "")
    if is_fac(p):
        role = (role + " · " if role else "") + "facilitator"
    return f"{lab or 'Someone'}{f' ({role})' if role else ''}"


def label_prompt(sess: dict, batch: dict, people: dict, labels: dict) -> tuple:
    """(prompt, {line id in the prompt: line key})."""
    sec = batch["sec"]
    part = SECTIONS[sec]
    # Killed currents stay on the list: a line about one is still about it, and
    # without it the model would file that line as a "new" topic.
    cur = all_currents(sess, sec)
    rows = "\n".join(f"[{c['id']}] {title_of(sess, c)} — {clip(c.get('b'), 160)}" for c in cur)
    known = (sess.get("newt") or {}).get(str(sec)) or {}
    on_screen = {c["id"] for c in cur}
    newrows = "\n".join(f"[new:{k}] {v.get('t', '')}" for k, v in known.items()
                        if f"n{sec}-{k}" not in on_screen)
    ids = {}
    ctx = []
    for l in batch.get("ctx") or []:
        ctx.append(f"   {_who(people, l.get('w'), labels)}: {clip(l.get('x'), 300)}")
    todo = []
    for j, l in enumerate(batch.get("todo") or []):
        lid = f"L{j + 1}"
        ids[lid] = l["k"]
        todo.append(f"[{lid}] {_who(people, l.get('w'), labels)}: {clip(l.get('x'), 400)}")
    return f"""You are listening to a client workshop. The room is discussing the "{part['head']}" part ({part['q']}).

THE CURRENTS ON SCREEN:
{rows or '(none)'}

TOPICS THE ROOM ALREADY RAISED THAT NO CURRENT COVERS:
{newrows or '(none)'}
{('JUST BEFORE (context only, do not label):' + chr(10) + chr(10).join(ctx) + chr(10)) if ctx else ''}
LINES TO LABEL (speaker, then words — transcribed by a machine):
{chr(10).join(todo)}

For each line, say which current it is about: its id (like "{cur[0]['id'] if cur else 'c1'}"); or a topic the room is discussing that no current covers, as "new:<short-key>" (reuse a key above when it is the same topic); or null when it is about nothing on screen — small talk, logistics, a question with no view. Be strict: a line is about a current only when it clearly talks about that idea, not when it shares a word with it.
Set "against": true only when the speaker disagrees with or pushes back on that current.
For each NEW key you use for the first time, give a "title" (an argument, at most 8 words) and a "body" (one sentence on what the room is saying).

Answer only with JSON: {{"lines": [{{"id": "L1", "topic": "c3", "against": false}}], "new": [{{"key": "short-key", "title": "…", "body": "…"}}]}}""", ids


def _key(s) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(s or "").lower()).strip("-")[:24]


def parse_labels(obj, ids: dict, sess: dict, sec: int) -> dict:
    """{"lines": {line key: {"topic": cid or None, "against": bool}}, "new": {key: {t, b}}}.
    Only ids that were sent, only currents that exist, only new topics that come
    with a title (now or from before)."""
    out = {"lines": {}, "new": {}}
    if not isinstance(obj, dict):
        return out
    cids = {c["id"] for c in all_currents(sess, sec)}
    known = (sess.get("newt") or {}).get(str(sec)) or {}
    for r in obj.get("new") if isinstance(obj.get("new"), list) else []:
        if not isinstance(r, dict):
            continue
        k = _key(r.get("key"))
        t = clip(r.get("title"), TITLE_MAX)
        if k and t and k not in known:
            out["new"][k] = {"t": t, "b": clip(r.get("body"), BODY_MAX)}
    for r in obj.get("lines") if isinstance(obj.get("lines"), list) else []:
        if not isinstance(r, dict):
            continue
        lk = ids.get(str(r.get("id") or "").strip())
        if not lk:
            continue
        top = r.get("topic")
        cid = None
        if isinstance(top, str) and top.strip():
            top = top.strip()
            if top in cids:
                cid = top
            elif top.lower().startswith("new:"):
                k = _key(top[4:])
                if k in known or k in out["new"]:
                    cid = f"n{sec}-{k}"
        out["lines"][lk] = {"topic": cid, "against": bool(r.get("against")) and cid is not None}
    return out


def apply_labels(sess: dict, sec: int, parsed: dict, todo: list, people: dict) -> int:
    """Count what the model labelled. Returns how many lines counted."""
    live_defaults(sess)
    s = str(sec)
    talk = sess["talk"].setdefault(s, {})
    newt = sess["newt"].setdefault(s, {})
    for k, v in (parsed.get("new") or {}).items():
        newt.setdefault(k, v)
    counted = 0
    for l in todo or []:
        lab = (parsed.get("lines") or {}).get(l.get("k"))
        if not lab or not lab.get("topic") or l.get("note"):
            continue
        cid = lab["topic"]
        fac = is_fac(people.get(l.get("w")))
        # THE FACILITATOR'S WORDS ARE KEPT BUT NEVER COUNTED. Kept, because
        # someone is often marked as the Atlantic side only after they have
        # spoken: topic_stats leaves out whoever is marked NOW, so marking them
        # late still takes their lines out of every count.
        if lab.get("against"):
            if not fac:
                sess["flag"][cid] = {"k": l["k"], "w": l.get("w", ""), "x": clip(l.get("x"), 220)}
        else:
            st = talk.setdefault(cid, {"ks": [], "ret": False})
            if l["k"] not in st["ks"]:
                if not fac and st["ks"] and sess["last_topic"].get(s) not in (None, cid):
                    st["ret"] = True                  # somebody came back to it
                st["ks"].append(l["k"])
                counted += 0 if fac else 1
        if not fac:
            sess["last_topic"][s] = cid
    return counted


def topic_stats(sess: dict, sec: int, cid: str, by_key: dict, people: dict) -> Optional[dict]:
    """How strong a topic is NOW: mentions, the people behind them, what they
    said — the facilitator's lines left out, whoever is marked as such today."""
    st = ((sess.get("talk") or {}).get(str(sec)) or {}).get(cid)
    if not st or not st.get("ks"):
        return None
    who, quotes = [], []
    for k in st["ks"]:
        l = by_key.get(k)
        if not l:
            continue
        w = l.get("w") or ""
        if is_fac(people.get(w)):
            continue
        if w and w not in who:
            who.append(w)
        quotes.append({"w": w, "x": clip(l.get("x"), 220), "k": k})
    if not quotes:
        return None
    return {"m": len(quotes), "who": who, "quotes": quotes, "ret": bool(st.get("ret"))}


def level(st: Optional[dict]) -> str:
    """Two people (or one coming back to it) = Keep; three people, or a third
    mention after coming back with two people talking = Star."""
    if not st:
        return ""
    sp, m, ret = len(st.get("who") or []), int(st.get("m") or 0), bool(st.get("ret"))
    if sp >= 3 or (m >= 3 and ret and sp >= 2):
        return "star"
    if (sp >= 2 and m >= 2) or (m >= 2 and ret):
        return "keep"
    return ""


def reading(sess: dict, sec: int, by_key: dict, people: dict, labels: dict,
            now: Optional[str] = None, flagged_before: Optional[set] = None) -> dict:
    """After the lines are counted: what is strong enough now. New topics that
    made it become currents 'from the conversation'; Lighthouse picks (AI
    selects) or proposes (AI suggests) — never over a person's decision, never
    a current it was told to leave alone. Returns the reading for the log."""
    live_defaults(sess)
    s = str(sec)
    picked, flagged = [], []
    newt = sess["newt"].get(s) or {}
    for cid in list((sess["talk"].get(s) or {}).keys()):
        st = topic_stats(sess, sec, cid, by_key, people)
        lv = level(st)
        if not lv:
            continue
        i, c = find_current(sess, cid)
        if not c and cid.startswith(f"n{sec}-"):
            k = cid[len(f"n{sec}-"):]
            nt = newt.get(k)
            if not nt:
                continue
            cur = sess["sections"][sec]["currents"]
            c = {"id": cid, "t": nt["t"], "b": nt.get("b", ""), "ev": [], "src": "talk",
                 "cut": False, "at": now or now_iso()}
            cur.append(c)
            log_event(sess, "new_topic", now, screen="sec", sec=sec, id=cid, title=c["t"],
                      who=list(st["who"]), m=st["m"])
        if not c or c.get("cut"):
            continue
        if sess["human"].get(cid) or sess["locked"].get(cid):
            continue
        have = (sess["dec"].get(cid) if sess["ai"].get(cid) else "") or (sess["sugg"].get(cid) or {}).get("lv", "")
        if have == lv or (have == "star" and lv == "keep"):
            continue
        mark = {"lv": lv, "who": list(st["who"]), "m": st["m"]}
        if sess.get("mode") == "suggest":
            sess["sugg"][cid] = mark
        else:
            sess["dec"][cid] = lv
            sess["ai"][cid] = mark
        log_event(sess, "ai", now, screen="sec", sec=sec, id=cid, d=lv, title=title_of(sess, c),
                  who=list(st["who"]), m=st["m"], mode=sess.get("mode", "auto"), ret=bool(st.get("ret")))
        picked.append({"lv": lv, "t": title_of(sess, c)})
    seen = flagged_before if flagged_before is not None else set(sess.get("flag_seen") or [])
    for cid in list(sess["flag"].keys()):
        i, c = find_current(sess, cid)
        if c and i == sec and cid not in seen:
            seen.add(cid)
            flagged.append(title_of(sess, c))
            fl = sess["flag"].get(cid) or {}
            log_event(sess, "flag", now, screen="sec", sec=sec, id=cid, title=title_of(sess, c),
                      w=fl.get("w", ""), text=fl.get("x", ""))
    sess["flag_seen"] = sorted(seen)
    reads = sess["reads"].setdefault(s, [])
    entry = {"t": now or now_iso(), "n": len(reads) + 1, "picked": picked, "flagged": flagged,
             "mode": sess.get("mode", "auto")}
    reads.append(entry)
    if len(reads) > 40:
        del reads[: len(reads) - 40]
    return entry


def undo_ai(sess: dict, cid: str) -> bool:
    if not sess["ai"].get(cid):
        return False
    sess["dec"][cid] = ""
    sess["ai"].pop(cid, None)
    sess["locked"][cid] = True
    return True


def confirm_sugg(sess: dict, cid: str) -> bool:
    g = sess["sugg"].get(cid)
    if not g:
        return False
    sess["dec"][cid] = g.get("lv") or "keep"
    sess["ai"][cid] = g
    sess["sugg"].pop(cid, None)
    return True


def dismiss_sugg(sess: dict, cid: str) -> bool:
    if not sess["sugg"].pop(cid, None):
        return False
    sess["locked"][cid] = True
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Ask Lighthouse — one sentence from the room becomes a current
# ══════════════════════════════════════════════════════════════════════════════

def ask_prompt(sess: dict, sec: int, q: str, cand: list, today: str, back: str = "") -> str:
    """`back` = an existing current's title: find evidence FOR it instead."""
    part = SECTIONS[sec]
    st = sess.get("setup") or {}
    brand = st.get("brand") or sess.get("client_name") or "the brand"
    have = "\n".join(f"- {title_of(sess, c)}" for c in all_currents(sess, sec))
    if back:
        ask = (f'The room added this current on its own: "{back}". Find the posts below that really '
               f'back it. If none does, answer exactly {{"none": "one sentence saying why"}}.')
        fmt = '{"signal_indexes": [0, 3], "body": "two sentences on what the posts show"}'
    else:
        ask = (f'Somebody in the room asked: "{q}". Answer it with ONE current built only from the '
               f'posts below that are really about it — through this part\'s lens: {part["lens"]}. '
               f'If none is, answer exactly {{"none": "one sentence saying what is missing"}}.')
        fmt = '{"title": "an argument, at most 8 words", "body": "two sentences, at most 40 words", "signal_indexes": [0, 3]}'
    return f"""You are Lighthouse, in a live workshop with {brand}. Today is {today}. The part on screen: {part['head']}.

Currents already on screen — never repeat or reword them:
{have or '- (none)'}

{ask}

POSTS:
{listing(cand, '', 240, 120) or '(none)'}

Answer only with JSON: {fmt}"""


def parse_ask(obj, cand: list, back: bool = False) -> dict:
    """{"none": why} · {"t", "b", "ev"} — evidence resolved to real posts, at least one."""
    if not isinstance(obj, dict):
        return {"none": "Lighthouse did not answer — try again."}
    if obj.get("none"):
        return {"none": clip(obj["none"], 240)}
    ev = [_ev_from_signal(cand[j], "post") for j in _idx_list(obj.get("signal_indexes"), len(cand or []))][:6]
    if not ev:
        return {"none": "None of what was collected is really about it."}
    if back:
        return {"b": clip(obj.get("body"), BODY_MAX), "ev": ev}
    t = clip(obj.get("title"), TITLE_MAX)
    if not t:
        return {"none": "Lighthouse did not answer — try again."}
    return {"t": t, "b": clip(obj.get("body"), BODY_MAX), "ev": ev}


# ══════════════════════════════════════════════════════════════════════════════
# Countercurrents — the gaps between what the room kept
# ══════════════════════════════════════════════════════════════════════════════

MIN_SELECTS = 4


def terr_prompt(sess: dict, answers: list, sels: list, today: str, people: dict, labels: dict,
                by_key: dict) -> str:
    st = sess.get("setup") or {}
    brand = st.get("brand") or sess.get("client_name") or "the brand"
    rows = []
    for j, c in enumerate(sels):
        stt = topic_stats(sess, c["sec"], c["id"], by_key, people)
        said = ""
        if stt and stt["quotes"]:
            said = " · In the room: " + " / ".join(f'"{clip(q["x"], 140)}"' for q in stt["quotes"][-2:])
        rows.append(f"[{j}] {SECTIONS[c['sec']]['key']}{' · STARRED' if c['star'] else ''} — {c['t']}"
                    f"{(': ' + clip(c['b'], 200)) if c.get('b') else ''}{said}")
    terr = sess.get("terr") or {}
    keep = [t for t in terr.get("items") or [] if t.get("ripe")]
    notes = [t for t in terr.get("items") or [] if (t.get("notes") or "").strip() and not t.get("ripe")]
    extra = ""
    if keep:
        extra += ("\nTHE ROOM MARKED THESE RIPE — they stay as they are; write the others around them:\n" +
                  "\n".join(f"- {t['t']} ({t['a']} / {t['b']})" for t in keep))
    if notes:
        extra += ("\nTHE ROOM'S NOTES ON THE LAST ROUND — use them:\n" +
                  "\n".join(f"- On \"{t['t']}\": {clip(t['notes'], 300)}" for t in notes))
    want = max(1, 4 - len(keep))
    return f"""You are Lighthouse, at the end of a live workshop with {brand}. Today is {today}.

WHAT THE CLIENT TOLD US:
- The goal: {clip((answers or [''] * N_Q)[Q_GOAL], 400) or '—'}
- The marketing problem: {clip((answers or [''] * N_Q)[Q_PROBLEM], 400) or '—'}
- What only they deliver: {clip((answers or [''] * N_Q)[Q_UNIQUE], 300) or '—'}
- Where their gut disagrees with the category: {clip((answers or [''] * N_Q)[Q_GUT], 300) or '—'}

WHAT THE ROOM KEPT (the selects; starred ones carry more weight):
{chr(10).join(rows)}
{extra}

Find {want} countercurrent territor{'y' if want == 1 else 'ies'}: where {brand} could go that nobody else is going. Each one sits in the GAP between two currents the room kept — a tension with two sides that are both true. For each:
- "title": the territory, at most 7 words, an idea a creative team could run with — a line with a point of view, in sentence case. Never "X vs. Y": the tension goes in "a" and "b", the title is where the brand goes
- "a": side A of the tension, one line
- "b": side B, one line, starting with "…" (it answers side A)
- "why": two sentences, at most 40 words: why the brand can own it, in plain words
- "from": the indexes of the selects it is built from (two or more)
No territory may repeat one marked ripe. Plain words; no consultancy language.

Answer only with JSON: {{"territories": [{{"title": "…", "a": "…", "b": "…", "why": "…", "from": [0, 4]}}]}}"""


def parse_terr(obj, sels: list) -> list:
    out = []
    rows = (obj or {}).get("territories") if isinstance(obj, dict) else None
    seen = set()
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        t = clip(r.get("title"), 90)
        frm = [sels[j]["id"] for j in _idx_list(r.get("from"), len(sels or []))]
        if not t or t.lower() in seen or len(frm) < 2:
            continue
        seen.add(t.lower())
        out.append({"t": t, "a": clip(r.get("a"), 200), "b": clip(r.get("b"), 200),
                    "why": clip(r.get("why"), 360), "from": frm[:6]})
        if len(out) >= 5:
            break
    return out


def apply_terr(sess: dict, found: list, now: Optional[str] = None) -> int:
    """The new round: ripe territories stay (with their notes); the rest is
    replaced — and kept in the history, with the notes the room wrote on them,
    because the final report tells every round, not only the last."""
    terr = sess.setdefault("terr", {"status": "none", "round": 0, "items": [], "err": ""})
    old = list(terr.get("items") or [])
    keep = [t for t in old if t.get("ripe")]
    gone = [t for t in old if not t.get("ripe")]
    if old:
        hist = terr.setdefault("history", [])
        hist.append({"round": int(terr.get("round") or 0), "at": terr.get("at", ""),
                     "items": [dict(t) for t in old], "replaced": [t.get("id") for t in gone]})
        del hist[:-12]
    n0 = int(terr.get("n") or 0)
    items = list(keep)
    for t in found or []:
        n0 += 1
        items.append(dict(t, id=f"t{n0}", ripe=False, notes=""))
    terr.update(items=items[:6], n=n0, status="done", err="", at=now or now_iso(),
                round=int(terr.get("round") or 0) + 1)
    log_event(sess, "terr_done", now, screen="terr", sec=int(sess.get("sec") or 0),
              n=len(found or []), kept=len(keep), round=terr["round"])
    return len(found or [])


# ══════════════════════════════════════════════════════════════════════════════
# The leave-behind
# ══════════════════════════════════════════════════════════════════════════════

def leave_record_id(token: str) -> str:
    return f"leave:{token}"


def _e(s) -> str:
    # "$" too: on the shared page Streamlit's Markdown would read "$5 … $9" as maths.
    return html.escape(str(s or ""), quote=True).replace("$", "&#36;")


def leave_doc(sess: dict, answers: list, people: dict, labels: dict, by_key: dict,
              brief_url: str = "", when: Optional[str] = None) -> dict:
    """Everything the leave-behind says, from what the room decided — no model
    call, nothing written that was not said, kept or found."""
    terr = sorted((sess.get("terr") or {}).get("items") or [], key=lambda t: not t.get("ripe"))
    sels = selects(sess)
    evid = []
    for c in sels:
        stt = topic_stats(sess, c["sec"], c["id"], by_key, people)
        quotes = []
        for q in (stt or {}).get("quotes", [])[:2]:
            p = people.get(q["w"]) or {}
            quotes.append({"who": labels.get(q["w"]) or "Someone in the room", "role": p.get("role", ""),
                           "x": q["x"]})
        evid.append({"t": c["t"], "sec": SECTIONS[c["sec"]]["key"], "star": c["star"],
                     "src": c["src"], "ev": [e for e in c["ev"] if e.get("url")][:3],
                     "evline": evidence_line(c["ev"]), "quotes": quotes})
    titles = {c["id"]: c["t"] for c in sels}
    return {"client": sess.get("client_name", ""), "brand": (sess.get("setup") or {}).get("brand", ""),
            "date": when or now_iso(),
            "goal": (answers or [""] * N_Q)[Q_GOAL], "problem": (answers or [""] * N_Q)[Q_PROBLEM],
            "territories": [{"t": t["t"], "a": t.get("a", ""), "b": t.get("b", ""), "why": t.get("why", ""),
                             "ripe": bool(t.get("ripe")), "notes": t.get("notes", ""),
                             "from": [titles[x] for x in t.get("from") or [] if x in titles]} for t in terr],
            "evidence": evid, "brief_url": brief_url}


def _fmt_day(iso: str) -> str:
    try:
        d = datetime.fromisoformat(str(iso)[:19])
        return f"{d.day} {d.strftime('%B %Y')}"
    except Exception:
        return str(iso or "")[:10]


# ── The final report: the leave-behind, then the whole session ───────────────
# The leave-behind stays the first page. Under it, the session in full: what
# the client told us before, what Lighthouse looked for, every part with every
# current and what happened to it (and who decided), what else the room talked
# about, every question put to Lighthouse, every round of territories, every
# interaction with its time, and the transcript. Nothing in it is written by a
# model — it is the record, told back. The transcript and the timeline can
# each be left out (sess["leave_opts"]), for a copy that travels further.

REPORT_OPTS = ("transcript", "timeline")
_RECORDED = {"auto": "Voices told apart by AssemblyAI (EU servers)",
             "tap": "Chrome speech recognition; speakers tapped by the facilitator"}
_OUTCOME = {"keep": "Kept", "star": "Starred", "kill": "Killed"}
_SRC_LABEL = {"talk": "From the conversation", "room": "Added by the room", "team": "Added by Atlantic",
              "ask": "Asked by the room", "dig": "Dug by Lighthouse"}


def recorded_with(sess: dict) -> str:
    """How the room was heard, read from the lines themselves — the setting
    can change later (a server without the key falls back to Chrome)."""
    voice = [c for c in sess.get("chunks") or [] if isinstance(c, dict) and c.get("source") == "voice"]
    if not voice:
        return ""
    told_apart = sum(1 for c in voice if c.get("spk") or c.get("ep"))
    if told_apart == len(voice):
        return _RECORDED["auto"]
    if not told_apart:
        return _RECORDED["tap"]
    return _RECORDED["auto"] + "; part of it with " + _RECORDED["tap"][0].lower() + _RECORDED["tap"][1:]


def report_opts(sess: dict, opts: Optional[dict] = None) -> dict:
    """What goes in beyond the record itself — both, unless switched off."""
    o = {k: True for k in REPORT_OPTS}
    src = opts if isinstance(opts, dict) else (sess or {}).get("leave_opts")
    for k, v in (src if isinstance(src, dict) else {}).items():
        if k in o:
            o[k] = bool(v)
    return o


def _local(iso, tz_name: str = "") -> Optional[datetime]:
    """One of our UTC times, on the team's clock (DISPLAY_TZ) when given."""
    try:
        d = datetime.fromisoformat(str(iso or "").replace("Z", "")[:19])
    except (TypeError, ValueError):
        return None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            d = d.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
        except Exception:
            pass                        # a bad zone name must not cost the time
    return d


def fmt_clock(iso, tz_name: str = "") -> str:
    d = _local(iso, tz_name)
    return d.strftime("%H:%M") if d else ""


def fmt_zone(iso, tz_name: str = "") -> str:
    """'EST', 'EDT', 'BRT'… — or 'UTC' when the team has not set its clock."""
    d = _local(iso, tz_name) if tz_name else None
    z = d.strftime("%Z") if d is not None and d.tzinfo else ""
    return z or ("UTC" if not tz_name else tz_name)


def fmt_day(iso, tz_name: str = "") -> str:
    d = _local(iso, tz_name)
    return f"{d.day} {d.strftime('%B %Y')}" if d else ""


def _plural(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def report_labels(people: dict, labels: dict) -> dict:
    """Names for a reader who was not there: 'You' is the facilitator."""
    out = {}
    for pid, p in (people or {}).items():
        lab = (labels or {}).get(pid) or ""
        if (p or {}).get("you") and not (p or {}).get("name"):
            lab = "The facilitator"
        out[pid] = lab or "Unnamed voice"
    return out


def _names(ids, labels: dict) -> str:
    return ", ".join(labels.get(w) or "someone" for w in ids or [])


def _where(ev: dict) -> str:
    """The part (or screen) an interaction happened on."""
    if ev.get("screen") == "sec":
        try:
            return SECTIONS[max(0, min(N_SEC - 1, int(ev.get("sec") or 0)))]["key"]
        except (TypeError, ValueError):
            return ""
    return _SCREEN_LABEL.get(ev.get("screen", ""), "")


def time_on_parts(sess: dict, until: Optional[str] = None) -> dict:
    """Seconds spent on each part and screen, from the moves in the log —
    counted from the moment the session went live."""
    evs = sorted((e for e in sess.get("log") or [] if e.get("k") in ("go", "golive", "end")),
                 key=lambda e: str(e.get("t", "")))
    first = next((j for j, e in enumerate(evs) if e.get("k") == "golive"), None)
    if first is not None:
        evs = evs[first:]
    spent: dict = {}
    cur, since = None, None
    for e in evs:
        t = utc_ts(e.get("t"))
        if t is None:
            continue
        if cur and since is not None:
            spent[cur] = spent.get(cur, 0.0) + max(0.0, t - since)
        if e.get("k") == "end":
            cur, since = None, None
            continue
        cur, since = _where(e) or "Opening", t
    u = utc_ts(until) if until else None
    if cur and since is not None and u and u > since:
        spent[cur] = spent.get(cur, 0.0) + (u - since)
    return spent


def _mins(sec: Optional[float]) -> str:
    if not sec or sec < 20:
        return ""
    return f"{max(1, int(round(sec / 60)))} min"


def event_text(ev: dict, labels: dict) -> str:
    """One interaction, as a sentence."""
    k, t = ev.get("k", ""), ev.get("title", "")
    q = lambda x: f"“{x}”"
    if k == "go":
        if ev.get("screen") == "sec":
            return f"Moved to {SECTIONS[max(0, min(N_SEC - 1, int(ev.get('sec') or 0)))]['head']}"
        return {"setup": "Back to the opening", "selects": "Opened the selects",
                "terr": "Opened the countercurrents", "brief": "Opened the leave-behind"}.get(
            ev.get("screen", ""), "Moved on")
    if k in ("decide", "set"):
        d = ev.get("d", "")
        if not d:
            return f"Took {q(t)} out of the selects" if k == "set" else f"Cleared the decision on {q(t)}"
        return {"keep": f"Kept {q(t)}", "star": f"Starred {q(t)}", "kill": f"Killed {q(t)}"}.get(d, q(t))
    if k == "tweak":
        return f"Rewrote {q(ev.get('frm', ''))} as {q(t)}"
    if k == "add":
        return f"Added a current: {q(t)}"
    if k == "ask":
        return f"Asked Lighthouse: {q(ev.get('q', ''))}"
    if k == "ask_done":
        return f"Lighthouse answered {q(ev.get('q', ''))} with a new current: {q(t)}"
    if k == "ask_none":
        return f"Lighthouse found nothing for {q(ev.get('q', ''))}" + (f" — {ev['note']}" if ev.get("note") else "")
    if k == "back":
        return (f"Lighthouse found {_plural(int(ev.get('n') or 0), 'post')} behind {q(t)}" if ev.get("n")
                else f"Nothing Lighthouse collected backs {q(t)} yet")
    if k == "ai":
        lv = "★ Star" if ev.get("d") == "star" else "✓ Keep"
        verb = "suggested" if ev.get("mode") == "suggest" else "picked"
        return (f"Lighthouse {verb} {lv} for {q(t)}, from the conversation — {_names(ev.get('who'), labels)}; "
                f"{_plural(int(ev.get('m') or 0), 'mention')}{'; the room came back to it' if ev.get('ret') else ''}")
    if k == "new_topic":
        return f"A topic from the conversation became a current: {q(t)} — {_names(ev.get('who'), labels)}"
    if k == "flag":
        return f"{q(t)} was contested — {labels.get(ev.get('w')) or 'someone'}: {q(ev.get('text', ''))}"
    if k == "undo":
        return f"Undid Lighthouse's pick of {q(t)}"
    if k == "confirm":
        return f"Confirmed Lighthouse's suggestion on {q(t)}"
    if k == "dismiss":
        return f"Dismissed Lighthouse's suggestion on {q(t)}"
    if k == "mode":
        return "Lighthouse set to suggest only" if ev.get("m") == "suggest" else "Lighthouse set to pick on its own"
    if k == "read":
        return "Asked Lighthouse to read the room now"
    if k == "terr":
        return ("Asked for the countercurrents again, with the room's notes" if ev.get("again")
                else f"Asked for the countercurrents, from {_plural(int(ev.get('n') or 0), 'select')}")
    if k == "terr_done":
        kept = int(ev.get("kept") or 0)
        return (f"Lighthouse found {_plural(int(ev.get('n') or 0), 'territory', 'territories')} — round "
                f"{ev.get('round', 1)}{f', {kept} ripe kept' if kept else ''}")
    if k == "terr_fail":
        return "Lighthouse could not find territories" + (f" — {ev['note']}" if ev.get("note") else "")
    if k == "ripe":
        return f"Marked {q(t)} ripe" if ev.get("on") else f"Unmarked {q(t)} as ripe"
    if k == "tnote":
        return f"Note on {q(t)}: {q(ev.get('text', ''))}"
    if k == "leave":
        return "Saved the leave-behind to its link"
    if k == "consent":
        return "Told the room the conversation is transcribed"
    if k == "golive":
        return "The session started"
    if k == "end":
        return "The session ended"
    if k == "intro":
        return "The round of introductions started" if ev.get("on") else "The round of introductions ended"
    if k == "name":
        return f"A voice was named: {ev.get('name', '')}" + (f", {ev['role']}" if ev.get("role") else "")
    if k == "fac":
        who = labels.get(ev.get("id")) or ev.get("name") or "A person"
        return (f"{who} marked as Atlantic — their words are not counted" if ev.get("on")
                else f"{who} no longer marked as Atlantic")
    if k == "merge":
        return "Two voices joined into one person"
    if k == "person_add":
        return "A person was added"
    if k == "person_del":
        return "A person was removed"
    if k == "lang":
        return f"Language set to {ev.get('lang', '')}"
    if k == "engine":
        return ("Voices: tapped by the facilitator (Chrome)" if ev.get("engine") == "tap"
                else "Voices: told apart (AssemblyAI)")
    return k


def transcript_rows(sess: dict, lines: list, people: dict, labels: dict, tz_name: str = "") -> list:
    """Every line, under the part it was said in, with its time and speaker."""
    out = []
    for l in lines or []:
        p = (people or {}).get(l.get("w")) or {}
        note = bool(l.get("note"))
        out.append({"t": fmt_clock(l.get("t", ""), tz_name), "part": part_at(sess, int(l.get("n") or 0)),
                    "who": "Typed note" if note else (labels.get(l.get("w")) or "Unidentified voice"),
                    "role": "" if note else p.get("role", ""), "atlantic": (not note) and is_fac(p),
                    "note": note, "intro": bool(l.get("intro")), "x": str(l.get("x") or "").strip()})
    return [r for r in out if r["x"]]


def _decided_how(sess: dict, cid: str, labels: dict, by_log: dict) -> str:
    d = (sess.get("dec") or {}).get(cid, "")
    ai = (sess.get("ai") or {}).get(cid)
    if d and ai:
        basis = f"{_names(ai.get('who'), labels)} · {_plural(int(ai.get('m') or 0), 'mention')}"
        if "confirm" in by_log.get(cid, ()):
            return f"Suggested by Lighthouse from the conversation, confirmed by the room — {basis}"
        return f"Picked by Lighthouse from the conversation — {basis}"
    if d and (sess.get("human") or {}).get(cid):
        return "Decided by the room"
    if "undo" in by_log.get(cid, ()):
        return "Lighthouse picked it; the room undid the pick"
    if "dismiss" in by_log.get(cid, ()):
        return "Lighthouse suggested it; the room dismissed the suggestion"
    if (sess.get("locked") or {}).get(cid):
        return "Lighthouse's pick or suggestion was turned down by the room"
    g = (sess.get("sugg") or {}).get(cid)
    if g:
        return f"Lighthouse suggested {'★ Star' if g.get('lv') == 'star' else '✓ Keep'} — not confirmed"
    return ""


def _quotes(stt: Optional[dict], people: dict, labels: dict) -> list:
    return [{"who": labels.get(q.get("w")) or "Someone in the room",
             "role": ((people or {}).get(q.get("w")) or {}).get("role", ""), "x": q.get("x", "")}
            for q in (stt or {}).get("quotes", [])]


def report_doc(sess: dict, answers: list, lines: list, people: dict, labels: dict,
               brief_url: str = "", when: Optional[str] = None, tz_name: str = "",
               opts: Optional[dict] = None) -> dict:
    """The leave-behind (leave_doc) with the whole session under "full".
    `lines` are keyed_lines; `labels` person id → name; `tz_name` the team's
    clock. Everything here is what was said, kept, found or done."""
    labels = report_labels(people, labels)
    by_key = {l["k"]: l for l in lines or [] if l.get("k")}
    doc = leave_doc(sess, answers, people, labels, by_key, brief_url=brief_url, when=when)
    o = report_opts(sess, opts)
    log = sorted([e for e in sess.get("log") or [] if isinstance(e, dict)], key=lambda e: str(e.get("t", "")))
    by_log: dict = {}
    for e in log:
        if e.get("id"):
            by_log.setdefault(e["id"], set()).add(e.get("k"))
    clock = lambda iso: fmt_clock(iso, tz_name)
    spoken = [l for l in lines or [] if not l.get("note") and str(l.get("x") or "").strip()]
    start = sess.get("went_live") or sess.get("started_at") or ""
    end = sess.get("ended_at") or (spoken[-1].get("t") if spoken else "") or when or now_iso()
    t0, t1 = utc_ts(start), utc_ts(end)
    spent = time_on_parts(sess, until=end)

    # the room: everyone who spoke or was named, with the role they gave
    said_by = {l.get("w") for l in spoken}
    room = [{"name": labels.get(pid, ""), "role": p.get("role", ""), "atlantic": is_fac(p)}
            for pid, p in (people or {}).items() if pid in said_by or p.get("name")]

    parts, n_dec = [], {"keep": 0, "star": 0, "kill": 0, "": 0}
    for i, base in enumerate(SECTIONS):
        curs, on_screen = [], set()
        for c in all_currents(sess, i):
            cid = c["id"]
            on_screen.add(cid)
            d = (sess.get("dec") or {}).get(cid, "")
            n_dec[d if d in n_dec else ""] += 1
            stt = topic_stats(sess, i, cid, by_key, people)
            fl = (sess.get("flag") or {}).get(cid)
            title = title_of(sess, c)
            curs.append({"t": title, "was": c.get("t", "") if title != c.get("t", "") else "",
                         "b": c.get("b", ""), "src": c.get("src") or "dig", "q": c.get("q", ""),
                         "outcome": _OUTCOME.get(d, "Not decided"), "d": d,
                         "how": _decided_how(sess, cid, labels, by_log),
                         "ev": [e for e in c.get("ev") or [] if e.get("url")][:8],
                         "evline": evidence_line(c.get("ev") or []),
                         "talk": ({"m": stt["m"], "n": len(stt["who"]), "ret": stt["ret"]} if stt else None),
                         "quotes": _quotes(stt, people, labels),
                         "contested": ({"who": labels.get(fl.get("w")) or "Someone", "x": fl.get("x", "")}
                                       if fl else None)})
        # what the room talked about that never became a current
        other = []
        for k, nt in ((sess.get("newt") or {}).get(str(i)) or {}).items():
            tid = f"n{i}-{k}"
            if tid in on_screen:
                continue
            stt = topic_stats(sess, i, tid, by_key, people)
            if stt:
                other.append({"t": nt.get("t", ""), "m": stt["m"], "n": len(stt["who"]),
                              "quotes": _quotes(stt, people, labels)})
        asks = [{"t": clock(a.get("at", "")), "q": a.get("q", ""), "status": a.get("status", ""),
                 "note": a.get("note", "")} for a in (sess.get("chat") or {}).get(str(i)) or []]
        reads = []
        for r in (sess.get("reads") or {}).get(str(i)) or []:
            bits = []
            if r.get("picked"):
                bits.append(("suggested " if r.get("mode") == "suggest" else "picked ")
                            + " · ".join(("★ " if p.get("lv") == "star" else "✓ ") + str(p.get("t", ""))
                                         for p in r["picked"]))
            if r.get("flagged"):
                bits.append("contested: " + " · ".join(str(x) for x in r["flagged"]))
            reads.append({"t": clock(r.get("t", "")),
                          "text": r.get("err") or ("; ".join(bits) if bits else "nothing strong enough yet")})
        st0 = (sess.get("sec_start") or {}).get(str(i))
        parts.append({"key": base["key"], "head": base["head"], "q": base["q"],
                      "started": clock(st0) if st0 else "", "time": _mins(spent.get(base["key"])),
                      "currents": curs, "other": other, "asks": asks, "reads": reads})

    sels = [{"t": c["t"], "part": SECTIONS[c["sec"]]["key"], "star": c["star"]} for c in selects(sess)]
    terr = sess.get("terr") or {}

    def _terr_items(items, replaced=()):
        return [{"t": x.get("t", ""), "a": x.get("a", ""), "b": x.get("b", ""), "why": x.get("why", ""),
                 "ripe": bool(x.get("ripe")), "notes": x.get("notes", ""),
                 "replaced": x.get("id") in replaced} for x in items or []]
    rounds = [{"round": h.get("round"), "t": clock(h.get("at", "")),
               "items": _terr_items(h.get("items"), set(h.get("replaced") or []))}
              for h in terr.get("history") or []]
    if terr.get("items"):
        rounds.append({"round": terr.get("round"), "t": clock(terr.get("at", "")), "final": True,
                       "items": _terr_items(terr.get("items"))})

    timeline = ([{"t": clock(e.get("t", "")), "part": _where(e), "text": event_text(e, labels)}
                 for e in log] if o["timeline"] else [])
    transcript = transcript_rows(sess, lines, people, labels, tz_name) if o["transcript"] else []
    st, dig = sess.get("setup") or {}, sess.get("dig") or {}
    order = ["Opening"] + [b["key"] for b in SECTIONS] + ["The selects", "Countercurrent", "The leave-behind"]
    time_line = " · ".join(f"{k} {_mins(v)}" for k, v in sorted(
        spent.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99)) if _mins(v))
    asks_all = [a for p_ in parts for a in p_["asks"]]
    doc["day"] = fmt_day(start or when or now_iso(), tz_name)
    doc["full"] = {
        "opts": o,
        "overview": {
            "day": doc["day"], "start": clock(start), "end": clock(end) if sess.get("ended_at") else "",
            "zone": fmt_zone(start or when or now_iso(), tz_name),
            "minutes": int(round((t1 - t0) / 60)) if (t0 and t1 and t1 >= t0) else None,
            "ended": bool(sess.get("ended_at")),
            "recorded": recorded_with(sess),
            "lang": sess.get("lang", ""), "consent": clock(sess.get("consent")) if sess.get("consent") else "",
            "lines": len(spoken), "words": sum(len(str(l.get("x", "")).split()) for l in spoken),
            "notes": sum(1 for l in lines or [] if l.get("note")),
            "kept": n_dec["keep"] + n_dec["star"], "starred": n_dec["star"], "killed": n_dec["kill"],
            "open": n_dec[""], "picks": sum(1 for e in log if e.get("k") == "ai"),
            "topics": sum(1 for e in log if e.get("k") == "new_topic"),
            "asks": len(asks_all), "answered": sum(1 for a in asks_all if a["status"] == "done"),
            "rounds": len(rounds), "events": len(log), "time": time_line},
        "room": room,
        "intake": [{"label": lab, "q": qq, "a": (answers or [])[j] if j < len(answers or []) else ""}
                   for j, (qq, _h, lab) in enumerate(QUESTIONS)],
        "setup": {k: st.get(k) for k in ("brand", "category", "product", "market", "window", "competitors",
                                         "focus", "question") if st.get(k)},
        "dig": {"day": fmt_day(dig.get("at", ""), tz_name) if dig.get("at") else "",
                "posts": int(dig.get("n") or 0), "articles": int(dig.get("n_trade") or 0),
                "figures": int(dig.get("n_figs") or 0), "pins": int(dig.get("n_pins") or 0)},
        "parts": parts, "selects": sels, "rounds": rounds, "timeline": timeline, "transcript": transcript,
        "made": fmt_day(when or now_iso(), tz_name) + " " + clock(when or now_iso()),
    }
    return doc


def tension(a, b) -> str:
    """Side A and side B as one thought. Side B is written to start with "…"
    (it answers A): "tired of performing… but still want a room" — and after
    a full stop, a new sentence, not "flavors. …Shoppers"."""
    a, b = str(a or "").strip(), str(b or "").strip()
    if not b.startswith(("…", "...")):
        return f"{a} {b}".strip()
    b = b.lstrip(".…").lstrip()
    if not a or not b:
        return (a or b).strip()
    if a.endswith(("…", "...")):
        return f"{a} {b}"
    if a.endswith((".", "!", "?")):
        return f"{a} {b[:1].upper()}{b[1:]}"
    return f"{a}… {b}"


def _x(s) -> str:
    """Text for the report: escaped, its line breaks kept as <br> — a blank
    line must never reach the page, where Markdown would end the HTML."""
    return re.sub(r"(?:\r?\n\s*)+", "<br>", _e(str(s or "").strip()))


def _full_html(f: dict, brief_url: str = "") -> str:
    """The session in full, under the leave-behind. One line of HTML; every
    piece of text escaped."""
    ov = f.get("overview") or {}
    o = f.get("opts") or {}
    toc, out = [], []

    def sec_open(anchor, label, head="", quiet="", entry=""):
        toc.append((anchor, entry or head or label))
        return (f'<section class="lb-part" id="{anchor}"><div class="lb-lbl">{_x(label)}</div>'
                + (f'<div class="lb-h2" role="heading" aria-level="2">{_x(head)}</div>' if head else "")
                + (f'<p class="lb-quiet">{_x(quiet)}</p>' if quiet else ""))

    # who was there
    room = f.get("room") or []
    if room:
        out.append(sec_open("lb-room", "In the room")
                   + '<ul class="lb-people">' + "".join(
                       f'<li><b>{_x(p.get("name") or "Unnamed voice")}</b>'
                       + ('<i>Atlantic</i>' if p.get("atlantic") else "")
                       + (f'<span>{_x(p["role"])}</span>' if p.get("role") else "") + "</li>" for p in room)
                   + "</ul></section>")
    # what the client said before
    qa = [x for x in f.get("intake") or [] if str(x.get("a") or "").strip()]
    out.append(sec_open("lb-intake", "Before the session", "What the client told us",
                        f"{len(qa)} of {len(f.get('intake') or [])} questions answered on the client's link."
                        if qa else "The client's questions were not answered before the session.")
               + "".join(f'<div class="lb-qa"><div class="lb-q">{_x(x["q"])}</div><p>{_x(x["a"])}</p></div>'
                         for x in qa) + "</section>")
    # what Lighthouse looked for
    stp, dg = f.get("setup") or {}, f.get("dig") or {}
    if stp or dg.get("posts"):
        rows = [("Brand", stp.get("brand")), ("Category", stp.get("category")), ("Product", stp.get("product")),
                ("Market", stp.get("market")),
                ("Looked back", f"{stp['window']} months" if stp.get("window") else ""),
                ("Competitors", stp.get("competitors")), ("Must mention", stp.get("focus")),
                ("The question", stp.get("question"))]
        dug = " · ".join(x for x in (f"Dug on {dg['day']}" if dg.get("day") else "",
                                     _plural(dg["posts"], "post") if dg.get("posts") else "",
                                     _plural(dg["articles"], "article") if dg.get("articles") else "",
                                     _plural(dg["figures"], "figure") if dg.get("figures") else "",
                                     _plural(dg["pins"], "Pinterest search", "Pinterest searches")
                                     if dg.get("pins") else "") if x)
        out.append(sec_open("lb-looked", "Before the session", "What Lighthouse looked for", dug)
                   + '<div class="lb-facts">' + "".join(
                       f'<div><b>{_x(k)}</b><span>{_x(v)}</span></div>' for k, v in rows if v) + "</div>"
                   + (f'<p class="lb-quiet"><a href="{_e(brief_url)}" target="_blank" rel="noopener">'
                      f'The full Lighthouse brief behind the session ↗</a></p>' if brief_url else "")
                   + "</section>")
    # the four parts
    for j, p in enumerate(f.get("parts") or []):
        meta = " · ".join(x for x in (f"started {p['started']}" if p.get("started") else "", p.get("time", ""))
                          if x)
        h = [sec_open(f"lb-part-{j}", f"Part {j + 1} of 4 · {p['key']}" + (f" · {meta}" if meta else ""),
                      p["head"], p.get("q", ""), entry=p["head"] + (f" · {p['time']}" if p.get("time") else ""))]
        if not p.get("currents"):
            h.append('<p class="lb-quiet">No current was on screen in this part.</p>')
        for c in p.get("currents") or []:
            links = " · ".join(f'<a href="{_e(e["url"])}" target="_blank" rel="noopener">{_x(clip(plain(e.get("ti")), 70))} ↗</a>'
                               for e in c.get("ev") or [])
            tk = c.get("talk")
            h.append(
                f'<div class="lb-cur o-{_e(c.get("d") or "open")}">'
                f'<div class="lb-cur-h"><span class="lb-out">{_x(c["outcome"])}</span>'
                f'<span class="lb-src">{_x(_SRC_LABEL.get(c.get("src"), "Dug by Lighthouse"))}'
                + (f' · “{_x(c["q"])}”' if c.get("q") else "") + "</span></div>"
                f'<div class="lb-cur-t">{_x(c["t"])}</div>'
                + (f'<div class="lb-was">Rewritten in the room. It was: “{_x(c["was"])}”</div>' if c.get("was") else "")
                + (f'<p>{_x(c["b"])}</p>' if c.get("b") else "")
                + (f'<div class="lb-how">{_x(c["how"])}</div>' if c.get("how") else "")
                + (f'<div class="lb-evl">{_x(c.get("evline"))}' + (f"<br>{links}" if links else "") + "</div>"
                   if (links or c.get("evline")) else "")
                + (f'<div class="lb-talk">In the room · {_plural(tk["m"], "mention")} · '
                   f'{_plural(tk["n"], "person", "people")}{" · came back to it" if tk.get("ret") else ""}</div>'
                   if tk else "")
                + "".join(f'<div class="lb-said"><b>{_x(x["who"])}</b>' + (f", {_x(x['role'])}" if x.get("role") else "")
                          + f': “{_x(x["x"])}”</div>' for x in c.get("quotes") or [])
                + (f'<div class="lb-contest"><b>Contested</b> — {_x(c["contested"]["who"])}: “{_x(c["contested"]["x"])}”</div>'
                   if c.get("contested") else "") + "</div>")
        if p.get("other"):
            h.append('<div class="lb-sub">Also talked about — not enough to become a current</div>'
                     + "".join(f'<div class="lb-cur o-other"><div class="lb-cur-t sm">{_x(x["t"])}</div>'
                               f'<div class="lb-talk">{_plural(x["m"], "mention")} · {_plural(x["n"], "person", "people")}</div>'
                               + "".join(f'<div class="lb-said"><b>{_x(y["who"])}</b>'
                                         + (f", {_x(y['role'])}" if y.get("role") else "")
                                         + f': “{_x(y["x"])}”</div>' for y in x.get("quotes") or [])
                               + "</div>" for x in p["other"]))
        if p.get("asks"):
            h.append('<div class="lb-sub">Questions put to Lighthouse</div><ul class="lb-list">' + "".join(
                f'<li><span class="lb-time">{_x(a["t"])}</span>“{_x(a["q"])}” — '
                + ({"done": f"a new current: “{_x(a['note'])}”", "running": "still looking when the record was made"}
                   .get(a.get("status"), _x(a.get("note") or "nothing found"))) + "</li>" for a in p["asks"]) + "</ul>")
        if p.get("reads"):
            h.append('<div class="lb-sub">Lighthouse listening — each reading of the room</div><ul class="lb-list">'
                     + "".join(f'<li><span class="lb-time">{_x(r["t"])}</span>{_x(r["text"])}</li>' for r in p["reads"])
                     + "</ul>")
        out.append("".join(h) + "</section>")
    # the selects
    sels = f.get("selects") or []
    out.append(sec_open("lb-selects", "The selects", "What the room kept",
                        f"{_plural(len(sels), 'current')} kept across the four parts"
                        + (f", {sum(1 for s in sels if s.get('star'))} starred." if sels else "."))
               + ('<ol class="lb-list lb-ol">' + "".join(
                   f'<li>{"★ " if s.get("star") else ""}{_x(s["t"])} <span class="lb-sec">{_x(s["part"])}</span></li>'
                   for s in sels) + "</ol>" if sels else "") + "</section>")
    # every round of territories
    rounds = f.get("rounds") or []
    if rounds:
        h = [sec_open("lb-rounds", "Countercurrent", "The territories, round by round",
                      "Every round Lighthouse wrote, with the room's notes — ripe ones stayed when it looked again.")]
        for r in rounds:
            h.append(f'<div class="lb-sub">Round {_x(r.get("round"))}' + (f' · {_x(r["t"])}' if r.get("t") else "")
                     + (" · the final round" if r.get("final") else "") + "</div>")
            for x in r.get("items") or []:
                h.append(f'<div class="lb-cur o-terr{" ripe" if x.get("ripe") else ""}">'
                         f'<div class="lb-cur-h"><span class="lb-out">{"★ Ripe" if x.get("ripe") else ("Replaced" if x.get("replaced") else "Territory")}</span></div>'
                         f'<div class="lb-cur-t">{_x(x["t"])}</div>'
                         f'<p><b>The tension:</b> {_x(tension(x.get("a"), x.get("b")))}</p>'
                         + (f'<p>{_x(x["why"])}</p>' if x.get("why") else "")
                         + (f'<div class="lb-said"><b>Notes from the room</b>: {_x(x["notes"])}</div>' if x.get("notes") else "")
                         + "</div>")
        out.append("".join(h) + "</section>")
    # every interaction
    tl = f.get("timeline") or []
    if tl:
        out.append(sec_open("lb-timeline", "Every interaction, in order", "",
                            "Every decision, rewrite, question, pick and move, with the time it happened"
                            + (f" ({ov['zone']})." if ov.get("zone") else "."),
                            entry=f"Every interaction, in order · {len(tl)}")
                   + '<table class="lb-tl"><tbody>' + "".join(
                       f'<tr><td class="lb-time">{_x(x["t"])}</td><td class="lb-tpart">{_x(x.get("part"))}</td>'
                       f'<td>{_x(x["text"])}</td></tr>' for x in tl) + "</tbody></table></section>")
    # the transcript
    tx = f.get("transcript") or []
    if tx:
        rows, last = [], None
        for x in tx:
            if x.get("part") != last:
                rows.append(f'<tr class="lb-txh"><td colspan="3">{_x(x.get("part"))}</td></tr>')
                last = x.get("part")
            cls = " note" if x.get("note") else (" atl" if x.get("atlantic") else "")
            who = _x(x["who"]) + (f'<span>{_x(x["role"])}</span>' if x.get("role") else "")
            rows.append(f'<tr class="lb-txr{cls}"><td class="lb-time">{_x(x["t"])}</td><td class="lb-who">{who}</td>'
                        f'<td>{_x(x["x"])}{" <em>introductions</em>" if x.get("intro") else ""}</td></tr>')
        out.append(sec_open("lb-transcript", "The full transcript", "", entry=f"The full transcript · {_plural(len(tx), 'line')}", quiet=
                            (f"{_plural(len(tx), 'line')}, transcribed by machine as the session happened"
                            + (f", with the room's consent (given at {ov['consent']})" if ov.get("consent") else "")
                            + (f". Times in {ov['zone']}" if ov.get("zone") else "")
                            + ". Names as the room gave them; a machine mishears, so check a quote before using it."))
                   + '<table class="lb-tx"><tbody>' + "".join(rows) + "</tbody></table></section>")

    # the band on top: the session at a glance, and the contents
    facts = [("Date", ov.get("day")),
             ("Time", " – ".join(x for x in (ov.get("start"), ov.get("end")) if x)
              + (f" {ov['zone']}" if ov.get("zone") else "")
              + ("" if ov.get("ended") else " (not ended)") if ov.get("start") else ""),
             ("Length", f"{ov['minutes']} min" if ov.get("minutes") is not None else ""),
             ("Recorded", ov.get("recorded") + (f" · {ov['lang']}" if ov.get("lang") else "") if ov.get("recorded") else ""),
             ("Said", f"{_plural(ov.get('lines', 0), 'line')} · {ov.get('words', 0):,} words"
              + (f" · {_plural(ov['notes'], 'typed note')}" if ov.get("notes") else "")),
             ("Decided", f"{ov.get('kept', 0)} kept ({ov.get('starred', 0)} starred) · {ov.get('killed', 0)} killed"
              + (f" · {ov['open']} left open" if ov.get("open") else "")),
             ("Lighthouse", f"{_plural(ov.get('picks', 0), 'pick')} from the conversation · "
              f"{_plural(ov.get('topics', 0), 'new topic')} · {ov.get('answered', 0)} of "
              f"{_plural(ov.get('asks', 0), 'question')} answered"),
             ("Countercurrent", _plural(ov.get("rounds", 0), "round")),
             ("Time on each part", ov.get("time"))]
    band = ('<section class="lb-band" id="lb-full"><div class="lb-lbl">The final report · the session in full</div>'
            '<div class="lb-h2" role="heading" aria-level="2">Everything that happened in the room</div>'
            '<p>The record of the session, told back — what was said, kept, found and done. Nothing below was '
            'written by a model.</p><div class="lb-facts">' + "".join(
                f'<div><b>{_x(k)}</b><span>{_x(v)}</span></div>' for k, v in facts if v) + "</div>"
            '<ol class="lb-toc">' + "".join(f'<li><a href="#{a}">{_x(lab)}</a></li>' for a, lab in toc)
            + "</ol></section>")
    left = [k for k in REPORT_OPTS if o and not o.get(k)]
    tail = (f'<p class="lb-quiet lb-end">Made by Lighthouse · {_x(f.get("made", ""))}'
            + (" · this copy leaves out " + " and ".join({"transcript": "the transcript",
                                                          "timeline": "the timeline"}[k] for k in left) if left else "")
            + "</p>")
    return '<div class="lb-full">' + band + "".join(out) + tail + "</div>"


def full_html(doc: dict) -> str:
    """The session in full on its own — the session screen shows it under the
    leave-behind when asked. Carries its own styles."""
    if not isinstance((doc or {}).get("full"), dict):
        return ""
    return (f'<style>{LEAVE_CSS}</style><div class="lb-doc">'
            f'{_full_html(doc["full"], doc.get("brief_url", ""))}</div>')


def report_counts(doc: dict) -> dict:
    """What the two switches would leave out: lines of transcript, interactions."""
    ov = ((doc or {}).get("full") or {}).get("overview") or {}
    return {"lines": int(ov.get("lines") or 0) + int(ov.get("notes") or 0), "events": int(ov.get("events") or 0)}


def transcript_text(sess: dict, lines: list, people: dict, labels: dict, tz_name: str = "") -> str:
    """The transcript as plain text — for the team to keep, search or paste."""
    labels = report_labels(people, labels)
    start = sess.get("went_live") or sess.get("started_at") or ""
    head = [f"{sess.get('client_name') or 'Live session'} — Lighthouse live session",
            " · ".join(x for x in (fmt_day(start, tz_name),
                                   " – ".join(y for y in (fmt_clock(start, tz_name),
                                                          fmt_clock(sess.get("ended_at"), tz_name)) if y)
                                   + (" " + fmt_zone(start, tz_name) if start else ""),
                                   recorded_with(sess)) if x),
            "Transcribed by machine as the session happened. Names as the room gave them."]
    out, last = head, None
    for x in transcript_rows(sess, lines, people, labels, tz_name):
        if x["part"] != last:
            out += ["", f"== {x['part']} ==", ""]
            last = x["part"]
        who = x["who"] + (f" ({x['role']})" if x.get("role") else "") + (" [Atlantic]" if x.get("atlantic") else "")
        said = re.sub(r"\s+", " ", x["x"])
        out.append(f"[{x['t']}] {who}: {said}")
    return "\n".join(out).strip() + "\n"


def leave_html(doc: dict, font_css: str = "", standalone: bool = True,
               print_on_open: bool = False, with_full: bool = True) -> str:
    """The leave-behind as a page — the same markup on the shared link, in the
    PDF and on the session screen. Everything inserted is escaped.
    `print_on_open`: the downloaded file opens the print dialog by itself
    (Print → Save as PDF), like the brief's export. A report_doc carries the
    whole session under it (`with_full=False` leaves it out)."""
    name = doc.get("client") or doc.get("brand") or "The client"
    terr = doc.get("territories") or []
    t_html = []
    for t in terr:
        frm = "".join(f"<li>{_e(x)}</li>" for x in t.get("from") or [])
        t_html.append(
            f'<div class="lb-t{" ripe" if t.get("ripe") else ""}"><div class="lb-h2" role="heading" aria-level="2">{"★ " if t.get("ripe") else ""}{_e(t["t"])}</div>'
            f'<p><b>The tension:</b> {_e(tension(t.get("a"), t.get("b")))}</p>'
            f'<p>{_e(t.get("why"))}</p>'
            + (f'<p class="lb-room"><b>From the room:</b> {_e(t["notes"])}</p>' if t.get("notes") else "")
            + (f'<div class="lb-from">Built from<ul>{frm}</ul></div>' if frm else "") + "</div>")
    ev_html = []
    for c in doc.get("evidence") or []:
        links = " · ".join(f'<a href="{_e(e["url"])}" target="_blank" rel="noopener">{_e(clip(plain(e.get("ti")), 70))} ↗</a>'
                           for e in c.get("ev") or [])
        src = ("raised in the room" if c.get("src") == "talk" else
               "added by the room" if c.get("src") == "room" and not c.get("ev") else
               "added by Atlantic" if c.get("src") == "team" and not c.get("ev") else
               _e(c.get("evline")) or "—")
        q = "<br>".join(f'<i>In the room:</i> {_e(x["who"])}{(", " + _e(x["role"])) if x.get("role") else ""}: “{_e(x["x"])}”'
                        for x in c.get("quotes") or [])
        ev_html.append(f'<li><b>{"★ " if c.get("star") else ""}{_e(c["t"])}</b> <span class="lb-sec">{_e(c["sec"])}</span>'
                       f' — {src}{("<br>" + links) if links else ""}{("<br>" + q) if q else ""}</li>')
    body = f"""<article class="lb-doc">
<div class="lb-lbl">Leave-behind · Lighthouse live session</div>
<div class="lb-h1" role="heading" aria-level="1">{_e(name)}: the brief we built together</div>
<p class="lb-quiet">{_e(doc.get("day") or _fmt_day(doc.get("date")))} · Atlantic New York</p>
<section class="lb-part"><div class="lb-lbl">The business challenge</div><p>{_e(doc.get("goal")) or "—"}</p></section>
<section class="lb-part"><div class="lb-lbl">The marketing challenge underneath it</div><p>{_e(doc.get("problem")) or "—"}</p></section>
<section class="lb-part"><div class="lb-lbl">The territories</div>{"".join(t_html) or "<p>No territories yet.</p>"}</section>
<section class="lb-part"><div class="lb-lbl">The evidence — from Lighthouse and from the room</div><ul class="lb-ev">{"".join(ev_html) or "<li>No selects yet.</li>"}</ul></section>
<section class="lb-part"><div class="lb-lbl">Next</div><p>The strategic rigour and the creative development — the work after the hypothesis.</p>
{f'<p class="lb-quiet"><a href="{_e(doc["brief_url"])}" target="_blank" rel="noopener">The full Lighthouse brief behind this session ↗</a></p>' if doc.get("brief_url") else ""}</section>{_full_html(doc["full"], doc.get("brief_url", "")) if with_full and isinstance(doc.get("full"), dict) else ""}
</article>"""
    css = LEAVE_CSS
    if not standalone:
        return f"<style>{css}</style>{body}"
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(name)} · {"Final report" if with_full and doc.get("full") else "Leave-behind"} · Lighthouse</title><style>{font_css}{css}'
            f'body{{margin:0;padding:48px max(28px,calc((100% - 860px)/2)) 64px;background:#fff}}'
            f'@media print{{body{{padding:0}}}}</style></head><body>{body}'
            + ('<script>window.addEventListener("load",function(){setTimeout(function(){window.print()},400)})</script>'
               if print_on_open else '') + '</body></html>')


LEAVE_CSS = """
.lb-doc{font-family:'Telegraf','Space Grotesk','Helvetica Neue',Helvetica,Arial,sans-serif;color:#000;max-width:860px;-webkit-font-smoothing:antialiased}
.lb-doc .lb-lbl{font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:700;color:#0000ff}
.lb-doc .lb-h1{font-size:52px;font-weight:700;letter-spacing:-.03em;line-height:1.02;margin:12px 0 16px;color:#000}
.lb-doc .lb-h2{font-size:24px;font-weight:700;letter-spacing:-.01em;line-height:1.2;margin:22px 0 8px;color:#000}
.lb-doc p,.lb-doc li,.lb-doc div{font-family:inherit}
.lb-doc .lb-part{border-top:3px solid #000;padding-top:16px;margin-top:30px}
.lb-doc p{font-size:15px;line-height:1.55;color:#222;margin:6px 0}
.lb-doc .lb-quiet{font-size:12.5px;color:#666}
.lb-doc .lb-room{border-left:3px solid #0000ff;padding-left:10px}
.lb-doc .lb-from{font-size:12px;color:#666;margin-top:6px}
.lb-doc .lb-from ul{margin:4px 0 0 18px;padding:0}
.lb-doc ul.lb-ev{margin:8px 0 0 18px;padding:0;font-size:14px;line-height:1.7;color:#222}
.lb-doc ul.lb-ev li{margin-bottom:8px}
.lb-doc .lb-sec{font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:#0000ff;margin-left:4px}
.lb-doc a{color:#0000ff}
@media (max-width:820px){.lb-doc .lb-h1{font-size:34px}}
.lb-doc .lb-full{margin-top:56px}
.lb-doc .lb-band{background:#0000ff;color:#fff;padding:30px 30px 26px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.lb-doc .lb-band .lb-lbl{color:#fff}
.lb-doc .lb-band .lb-h2{color:#fff;font-size:40px;letter-spacing:-.025em;line-height:1.04;margin:12px 0 10px}
.lb-doc .lb-band p{color:#fff;opacity:.92}
.lb-doc .lb-facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));border-top:1.5px solid #000;margin-top:14px}
.lb-doc .lb-band .lb-facts{border-top-color:#fff}
.lb-doc .lb-facts>div{padding:9px 14px 9px 0;border-bottom:1px solid rgba(0,0,0,.14)}
.lb-doc .lb-band .lb-facts>div{border-bottom-color:rgba(255,255,255,.4)}
.lb-doc .lb-facts b{display:block;font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:#0000ff;margin-bottom:3px}
.lb-doc .lb-band .lb-facts b{color:#fff;opacity:.85}
.lb-doc .lb-facts span{font-size:14px;line-height:1.4}
.lb-doc ol.lb-toc{columns:2;column-gap:28px;margin:18px 0 0;padding:0 0 0 20px;font-size:13.5px;line-height:1.9}
.lb-doc ol.lb-toc a{color:#fff;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.55)}
.lb-doc ul.lb-people{list-style:none;margin:10px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:0}
.lb-doc ul.lb-people li{padding:9px 12px 9px 0;border-bottom:1px solid rgba(0,0,0,.14);font-size:14px}
.lb-doc ul.lb-people span{display:block;font-size:12.5px;color:#666}
.lb-doc ul.lb-people i{display:inline-block;font-style:normal;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:#0000ff;margin-left:6px}
.lb-doc .lb-qa{margin:14px 0 0}
.lb-doc .lb-q{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:#000}
.lb-doc .lb-cur{border-top:1.5px solid #000;padding:12px 0 14px;margin-top:12px;break-inside:avoid}
.lb-doc .lb-cur-h{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.lb-doc .lb-out{font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;padding:3px 8px;border:1.5px solid #000;border-radius:999px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.lb-doc .o-keep .lb-out{background:#000;color:#fff}
.lb-doc .o-star .lb-out,.lb-doc .o-terr.ripe .lb-out{background:#0000ff;border-color:#0000ff;color:#fff}
.lb-doc .o-kill .lb-out{border-color:#e00000;color:#e00000}
.lb-doc .o-kill .lb-cur-t{text-decoration:line-through;text-decoration-thickness:1.5px;color:#555}
.lb-doc .o-open .lb-out,.lb-doc .o-terr .lb-out{color:#666;border-color:#bbb}
.lb-doc .lb-src{font-size:11.5px;color:#666}
.lb-doc .lb-cur-t{font-size:19px;font-weight:700;letter-spacing:-.01em;line-height:1.25;margin:8px 0 4px}
.lb-doc .lb-cur-t.sm{font-size:15.5px;margin-top:0}
.lb-doc .o-other{border-top-width:1px;border-top-color:rgba(0,0,0,.25)}
.lb-doc .lb-was{font-size:12.5px;color:#666;font-style:italic;margin-bottom:4px}
.lb-doc .lb-how{font-size:12.5px;color:#0000ff;font-weight:700;margin-top:6px}
.lb-doc .lb-evl{font-size:12.5px;color:#444;line-height:1.6;margin-top:6px}
.lb-doc .lb-talk{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;color:#000;margin-top:8px}
.lb-doc .lb-said{font-size:13.5px;line-height:1.5;color:#222;border-left:3px solid #0000ff;padding:2px 0 2px 10px;margin-top:6px}
.lb-doc .lb-contest{font-size:13.5px;line-height:1.5;color:#222;border-left:3px solid #000;padding:2px 0 2px 10px;margin-top:6px}
.lb-doc .lb-sub{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:#0000ff;margin:22px 0 4px}
.lb-doc ul.lb-list,.lb-doc ol.lb-list{margin:6px 0 0 18px;padding:0;font-size:13.5px;line-height:1.6;color:#222}
.lb-doc ul.lb-list li,.lb-doc ol.lb-list li{margin-bottom:5px}
.lb-doc .lb-time{font-variant-numeric:tabular-nums;color:#666;font-size:12px;margin-right:8px;white-space:nowrap}
.lb-doc table.lb-tl,.lb-doc table.lb-tx{width:100%;border-collapse:collapse;border:0;margin:10px 0 0;font-size:13px;line-height:1.5;background:transparent}
.lb-doc table.lb-tl tr,.lb-doc table.lb-tx tr{border:0;background:transparent}
.lb-doc table.lb-tl td,.lb-doc table.lb-tx td{padding:5px 10px 5px 0;border:0;border-bottom:1px solid rgba(0,0,0,.1);vertical-align:top;background:transparent}
.lb-doc table.lb-tl tr,.lb-doc table.lb-tx tr{break-inside:avoid}
.lb-doc td.lb-time{width:46px}
.lb-doc td.lb-tpart{width:120px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;color:#0000ff;padding-top:7px}
.lb-doc td.lb-who{width:150px;font-weight:700}
.lb-doc td.lb-who span{display:block;font-weight:400;font-size:11.5px;color:#666}
.lb-doc tr.lb-txh td{border:0;border-bottom:1.5px solid #000;padding-top:18px;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:#0000ff}
.lb-doc tr.lb-txr.atl td.lb-who{color:#0000ff}
.lb-doc tr.lb-txr.note td{color:#666;font-style:italic}
.lb-doc tr.lb-txr em{font-style:normal;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:#999;margin-left:6px}
.lb-doc .lb-end{margin-top:34px;border-top:1.5px solid #000;padding-top:10px}
@media (max-width:820px){.lb-doc ol.lb-toc{columns:1}.lb-doc .lb-band .lb-h2{font-size:30px}.lb-doc td.lb-who{width:96px}.lb-doc td.lb-tpart{display:none}}
@media print{.lb-doc .lb-full{break-before:page;margin-top:0}.lb-doc .lb-part{break-inside:auto}.lb-doc .lb-sub,.lb-doc .lb-lbl{break-after:avoid}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# The session screen — what it is given, and what it sends back
# ══════════════════════════════════════════════════════════════════════════════

def live_apply(sess: dict, value, now: Optional[str] = None) -> list:
    """Apply the session screen's pending actions, once each, in order.

    Same protocol as the session room's panel: every action is numbered and the
    screen keeps it until the app acknowledges it (live_ack), because a
    component holds one value at a time and two clicks can land between two
    reruns. Returns the EFFECTS the app must carry out — the ones that need the
    model or the database: ("ask", sec, qid) ("back", cid) ("terr",) ("leave",)
    ("read",) ("people",) ("golive",) ("end",) ("prep",) ("lang",) ("engine",)
    ("pdf",) ("full",) ("txt",) — the final report's files, sent to the screen once —
    ("who", message) — names, taps and the round of introductions (apply_who).
    """
    live_defaults(sess)
    msgs = (value or {}).get("msgs") if isinstance(value, dict) else None
    if not isinstance(msgs, list):
        return []
    ack = int(sess.get("live_ack", -1))
    fresh = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        try:
            s = int(m.get("seq"))
        except (TypeError, ValueError):
            continue
        if s > ack:
            fresh.append((s, m))
    effects: list = []
    when = now or now_iso()

    def eff(x):
        if x not in effects:
            effects.append(x)
    def tt(cid):
        i_, c_ = find_current(sess, cid)
        return title_of(sess, c_) if c_ else ""

    def where():
        return {"screen": sess.get("screen", "setup"), "sec": int(sess.get("sec") or 0)}

    def lg(k, **data):
        log_event(sess, k, when, **dict(where(), **data))
    for s, m in sorted(fresh, key=lambda x: x[0]):
        t = str(m.get("type") or "")
        cid = str(m.get("id") or "")
        if t == "go":
            scr = str(m.get("screen") or "")
            if scr in SCREENS:
                try:
                    sec = max(0, min(N_SEC - 1, int(m.get("sec", sess.get("sec", 0)))))
                except (TypeError, ValueError):
                    sec = int(sess.get("sec") or 0)
                left = sess.get("screen") == "sec" and (scr != "sec" or sec != sess.get("sec"))
                moved = scr != sess.get("screen") or (scr == "sec" and sec != sess.get("sec"))
                sess["screen"], sess["sec"] = scr, sec
                if scr == "sec" and not sess["sec_start"].get(str(sec)):
                    sess["sec_start"][str(sec)] = when
                mark_screen(sess, scr, sec)
                if moved:
                    lg("go")
                if left:
                    eff(("read",))           # what was said in the part just left is read now
        elif t == "decide":
            if decide(sess, cid, str(m.get("d") or "")):
                lg("decide", id=cid, d=sess["dec"].get(cid, ""), title=tt(cid))
        elif t == "set":
            if set_decision(sess, cid, str(m.get("d") or "")):
                lg("set", id=cid, d=sess["dec"].get(cid, ""), title=tt(cid))
        elif t == "tweak":
            before = tt(cid)
            if tweak(sess, cid, m.get("text")):
                lg("tweak", id=cid, frm=before, title=tt(cid))
        elif t == "add":
            new = add_current(sess, m.get("sec", sess.get("sec", 0)), m.get("text"), "room",
                              body="Added in the session.", now=when)
            if new:
                lg("add", id=new, title=tt(new))
                eff(("back", new))
        elif t == "ask":
            q = clip(m.get("q"), 300)
            try:
                sec = max(0, min(N_SEC - 1, int(m.get("sec", sess.get("sec", 0)))))
            except (TypeError, ValueError):
                sec = 0
            if q:
                ch = sess["chat"].setdefault(str(sec), [])
                ch.append({"id": f"q{s}", "q": q, "status": "running", "note": "", "cid": "", "at": when})
                del ch[:-12]
                lg("ask", q=q, part=SECTIONS[sec]["key"])
                eff(("ask", sec, f"q{s}"))
        elif t == "undo":
            if undo_ai(sess, cid):
                lg("undo", id=cid, title=tt(cid))
        elif t == "confirm":
            lv_ = (sess["sugg"].get(cid) or {}).get("lv", "")
            if confirm_sugg(sess, cid):
                lg("confirm", id=cid, d=lv_, title=tt(cid))
        elif t == "dismiss":
            if dismiss_sugg(sess, cid):
                lg("dismiss", id=cid, title=tt(cid))
        elif t == "mode":
            new_m = "suggest" if m.get("m") == "suggest" else "auto"
            if new_m != sess.get("mode"):
                sess["mode"] = new_m
                lg("mode", m=new_m)
        elif t == "read":
            lg("read")
            eff(("read",))
        elif t == "terr":
            if len(selects(sess)) >= MIN_SELECTS and (sess.get("terr") or {}).get("status") != "running":
                sess["terr"]["status"] = "running"
                sess["terr"]["err"] = ""
                lg("terr", n=len(selects(sess)), again=bool((sess.get("terr") or {}).get("items")))
                eff(("terr",))
        elif t == "ripe":
            for it in sess["terr"].get("items") or []:
                if it.get("id") == cid:
                    it["ripe"] = bool(m.get("on"))
                    lg("ripe", id=cid, on=it["ripe"], title=it.get("t", ""))
        elif t == "tnote":
            for it in sess["terr"].get("items") or []:
                if it.get("id") == cid:
                    it["notes"] = clean_answer(m.get("text"))[:600]
                    lg("tnote", id=cid, text=clip(it["notes"], 300), title=it.get("t", ""))
        elif t == "leave":
            lg("leave")
            eff(("leave",))
        elif t == "pdf":
            eff(("pdf",))
        elif t == "full":
            eff(("full",))
        elif t == "txt":
            eff(("txt",))
        elif t == "leave_opt":
            k_ = str(m.get("k") or "")
            if k_ in ("transcript", "timeline"):
                sess.setdefault("leave_opts", {})[k_] = bool(m.get("on"))
        elif t == "consent":
            if not sess.get("consent"):
                sess["consent"] = when
                lg("consent")
        elif t == "golive":
            if not sess.get("went_live"):
                sess["went_live"] = when
                sess["started_at"] = when
                sess["status"] = "live"
                lg("golive")
                eff(("golive",))
        elif t == "end":
            sess["status"] = "ended"
            sess["ended_at"] = when
            lg("end")
            eff(("end",))
        elif t == "prep":
            eff(("prep",))
        elif t == "lang":
            sess["lang"] = clip(m.get("lang"), 8)
            lg("lang", lang=sess["lang"])
            eff(("lang",))
        elif t == "engine":
            sess["engine"] = "tap" if m.get("engine") == "tap" else "auto"
            lg("engine", engine=sess["engine"])
            eff(("engine",))
        elif t == "fac":
            for p in sess.get("people") or []:
                if p.get("id") == cid:
                    p["fac"] = not p.get("fac")
                    lg("fac", id=cid, on=p["fac"], name=p.get("name", ""))
                    eff(("people",))
        elif t in ("tap", "person_add", "name", "merge", "you", "person_del", "assign", "intro"):
            # who is who — session_core's own vocabulary, applied there. Taps
            # are the facilitator's pointing, many a minute: not interactions.
            if t == "intro":
                lg("intro", on=bool(m.get("on")))
            elif t == "name":
                lg("name", id=cid, name=clip(m.get("name"), 60), role=clip(m.get("role"), 60))
            elif t in ("merge", "person_add", "person_del"):
                lg(t, id=cid)
            eff(("who", m))
        sess["live_ack"] = s
    return effects


def apply_who(sess: dict, m: dict) -> tuple:
    """Who is who, in session_core's own vocabulary — the same names, taps,
    merges and round of introductions as the session room. Returns
    (changed, intro) where intro is True/False when the round opened/closed."""
    import session_core as _sc
    _sc.people_defaults(sess)
    t = str(m.get("type") or "")
    pid = str(m.get("id") or "")
    if t == "tap":
        return _sc.add_tap(sess, m.get("at"), m.get("who")), None
    if t == "person_add":
        p = _sc.new_person(sess, "tap")
        if p and m.get("tap"):
            _sc.add_tap(sess, m.get("at"), p["id"])
        if p and m.get("assign_n") is not None:
            _sc.assign_line(sess, m.get("assign_n"), p["id"])
        return bool(p), None
    if t == "assign":
        return _sc.assign_line(sess, m.get("n"), m.get("who")), None
    if t == "name":
        return bool(_sc.name_person(sess, pid, m.get("name"), m.get("role"))), None
    if t == "merge":
        fac = any(p.get("fac") for p in sess.get("people") or [] if p.get("id") == pid)
        done = _sc.merge_people(sess, pid, str(m.get("into") or ""))
        if done and fac:
            for p in sess.get("people") or []:
                if p.get("id") == str(m.get("into") or ""):
                    p["fac"] = True
        return done, None
    if t == "you":
        return _sc.set_you(sess, pid), None
    if t == "person_del":
        return _sc.remove_person(sess, pid), None
    if t == "intro":
        on = bool(m.get("on"))
        try:
            at = int(float(m.get("at")))
        except (TypeError, ValueError):
            at = int(time.time() * 1000)
        wins = sess["intro_win"]
        if on and not sess.get("intro_on"):
            sess["intro_on"] = True
            wins.append([at, None])
            return True, True
        if not on and sess.get("intro_on"):
            sess["intro_on"] = False
            if wins and isinstance(wins[-1], list) and len(wins[-1]) == 2 and wins[-1][1] is None:
                wins[-1][1] = max(at, int(wins[-1][0] or at))
            return True, False
    return False, None


def _ago(iso: str, now_t: float) -> Optional[int]:
    t = utc_ts(iso)
    return None if t is None else max(0, int(now_t - t))


def live_state(sess: dict, intake: Optional[dict], lines: list, people_view: list,
               people: dict, labels: dict, now_t: Optional[float] = None, listen: Optional[dict] = None,
               leave: Optional[dict] = None, running: Optional[dict] = None, brief_url: str = "",
               client_meta: str = "") -> dict:
    """Everything the session screen draws, as one JSON-ready dict."""
    live_defaults(sess)
    now_t = time.time() if now_t is None else now_t
    answers = intake_defaults(dict(intake or {}))["answers"]
    by_key = {l["k"]: l for l in lines}
    secs = []
    for i, base in enumerate(SECTIONS):
        s = sess["sections"][i]
        cur = []
        for c in all_currents(sess, i):
            cid = c["id"]
            stt = topic_stats(sess, i, cid, by_key, people)
            ai, sg, fl = sess["ai"].get(cid), sess["sugg"].get(cid), sess["flag"].get(cid)
            ev = list(c.get("ev") or [])
            said = [{"who": labels.get(q["w"], "") or "Someone", "x": q["x"]} for q in (stt or {}).get("quotes", [])[-2:]]
            cur.append({
                "id": cid, "t": title_of(sess, c), "t0": c.get("t", ""), "b": c.get("b", ""),
                "src": c.get("src", "dig"), "q": c.get("q", ""), "looking": bool(c.get("looking")),
                "ev": [{"ti": plain(e.get("ti", "")), "url": e.get("url", ""), "src": net_label(e.get("src")),
                        "d": e.get("d", ""), "k": e.get("k", "")} for e in ev[:6]],
                "evline": evidence_line(ev) or ("the room · " + ", ".join(dict.fromkeys(x["who"] for x in said))
                                                if c.get("src") == "talk" and said else ""),
                "dec": sess["dec"].get(cid, ""),
                "ai": ({"who": [labels.get(w, "") or "Someone" for w in ai.get("who") or []], "m": ai.get("m", 0)}
                       if ai and sess["dec"].get(cid) else None),
                "sugg": ({"lv": sg.get("lv"), "who": [labels.get(w, "") or "Someone" for w in sg.get("who") or []],
                          "m": sg.get("m", 0)} if sg and not sess["dec"].get(cid) else None),
                "flag": ({"who": labels.get(fl.get("w"), "") or "Someone", "x": fl.get("x", "")} if fl else None),
                "said": said,
                "talk": ({"m": stt["m"], "n": len(stt["who"]), "ret": stt["ret"]} if stt else None),
                "locked": bool(sess["locked"].get(cid)),
            })
        st0 = sess["sec_start"].get(str(i))
        secs.append({"key": base["key"], "head": base["head"], "q": base["q"], "min": base["min"],
                     "status": s.get("status", "todo"), "dug_at": s.get("dug_at", ""),
                     "elapsed": _ago(st0, now_t) if st0 else None, "currents": cur,
                     "chat": list(sess["chat"].get(str(i)) or [])[-6:],
                     "reads": list(reversed((sess["reads"].get(str(i)) or [])[-8:]))})
    # the transcript of the part on screen (or of the opening), newest last
    on = sess.get("sec", 0) if sess.get("screen") == "sec" else -1
    tx = [l for l in lines if sec_at(sess, l["n"]) == on][-40:]
    tlines = [{"k": l["k"], "who": labels.get(l.get("w"), "") or ("Note" if l.get("note") else "…"),
               "role": (people.get(l.get("w")) or {}).get("role", ""),
               "fac": is_fac(people.get(l.get("w"))), "x": l.get("x", ""), "w": l.get("w", "")} for l in tx]
    terr = sess.get("terr") or {}
    sel = selects(sess)
    sel_titles = {c["id"]: c["t"] for c in sel}
    st = sess.get("setup") or {}
    return {
        "v": 1, "ack": int(sess.get("live_ack", -1)),
        "screen": sess.get("screen", "setup"), "sec": int(sess.get("sec", 0)),
        "client": {"name": sess.get("client_name", ""), "brand": st.get("brand", ""), "meta": client_meta},
        "status": sess.get("status", "prep"), "went_live": bool(sess.get("went_live")),
        "elapsed": _ago(sess.get("went_live"), now_t) if sess.get("went_live") else None,
        "ros": [list(r) for r in ROS],
        "cards": [{"l": lab, "x": answers[i]} for i, lab in CARDS if answers[i].strip()],
        "room_names": answers[Q_ROOM], "curious": curiosities_from(answers),
        "sections": secs, "mode": sess.get("mode", "auto"),
        "selects": [{"id": c["id"], "sec": c["sec"], "t": c["t"], "star": c["star"], "ai": c["ai"]} for c in sel],
        "min_selects": MIN_SELECTS,
        "terr": {"status": terr.get("status", "none"), "round": int(terr.get("round") or 0),
                 "err": terr.get("err", ""),
                 "items": [{"id": t.get("id", ""), "t": t["t"], "a": t.get("a", ""), "b": t.get("b", ""),
                            "why": t.get("why", ""), "ripe": bool(t.get("ripe")), "notes": t.get("notes", ""),
                            "from": [sel_titles.get(x) or "" for x in t.get("from") or [] if sel_titles.get(x)]}
                           for t in terr.get("items") or []]},
        "lines": tlines, "people": people_view or [], "voice_mode": sess.get("voice_mode", ""),
        "consent": bool(sess.get("consent")), "intro": {"on": bool(sess.get("intro_on"))},
        "listen": listen or {}, "leave": leave or {}, "running": running or {},
        "brief_url": brief_url,
    }
