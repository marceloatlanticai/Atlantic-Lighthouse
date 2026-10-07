"""
session_core.py — the logic of the Session Room, kept free of Streamlit.

The room is the client-facing half of the Lighthouse: a facilitator runs a
workshop, the tool listens, and on the Atlantic side of the screen it quietly
brings up what the team curated beforehand that bears on what was just said.

Everything here is plain Python on purpose. The rest of the app can only be
checked by running it in a browser; this part can be tested on its own, and it
is the part where a mistake would be invisible in the room — a citation that
points at the wrong saved item, a transcript that double-counts, a suggestion
built on something the model invented.

DESIGN RULES, decided before any of this was written and enforced below:
  1. It listens always and shows only on demand. Nothing here interrupts.
  2. It offers EVIDENCE, never conclusions. It never says what the client
     should do — that is the facilitator's job and the agency's product.
  3. Silence is a valid answer. A reading with nothing relevant returns nothing
     rather than something stretched.
  4. It only cites what exists. Every item it raises resolves to a row the team
     actually saved; anything else is dropped before it reaches the screen.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# Clients
# ══════════════════════════════════════════════════════════════════════════════
# The pre-work Stacia and Joao asked for in the session: a short brief the client
# fills in before the meeting, so the first fifteen minutes are not spent
# working out what the meeting is about. `interests` is Patrick's idea — the
# room's own tastes, used for analogies rather than for searching.

ROOM_ROLES = (
    "CMO / marketing lead",
    "Brand or category team",
    "Social and content",
    "Innovation and product",
    "Founder or CEO",
    "Mixed room",
)

CLIENT_TEXT_FIELDS = ("name", "brand", "category", "product", "market",
                      "objective", "customer", "interests", "role", "notes")


def client_record_id(folder_id: str) -> str:
    return f"client:{folder_id}"


def normalise_client(d: Optional[dict]) -> dict:
    """A client profile with every field present and trimmed."""
    d = dict(d or {})
    out = {k: str(d.get(k) or "").strip() for k in CLIENT_TEXT_FIELDS}
    probs = d.get("problems") or []
    if isinstance(probs, str):
        probs = [p for p in re.split(r"\n+", probs)]
    out["problems"] = [str(p).strip() for p in probs if str(p).strip()][:5]
    out["folder_id"] = str(d.get("folder_id") or "").strip()
    if out["role"] and out["role"] not in ROOM_ROLES:
        out["role"] = "Mixed room"
    return out


def client_search_key(c: dict) -> str:
    """The same key the board uses to file items by search."""
    return " · ".join(p for p in (c.get("brand"), c.get("category"),
                                  c.get("product")) if p)


# ══════════════════════════════════════════════════════════════════════════════
# Sessions
# ══════════════════════════════════════════════════════════════════════════════

def session_record_id(folder_id: str, started: Optional[datetime] = None) -> str:
    t = (started or datetime.utcnow()).strftime("%Y%m%d-%H%M%S")
    return f"session:{folder_id}:{t}"


def new_session(folder_id: str, client_name: str) -> dict:
    now = datetime.utcnow()
    return {
        "id": session_record_id(folder_id, now),
        "client_id": folder_id,
        "client_name": client_name,
        "started_at": now.isoformat(timespec="seconds"),
        "status": "live",
        "chunks": [],        # what was said, in order
        "insights": [],      # what the listener raised, newest last
        "scans": [],         # background searches and where they landed
        "last_seq": -1,      # highest voice batch already taken from the mic
        "read_upto": 0,      # chunks [0, read_upto) have been read by the ear
    }


def add_chunk(session: dict, text: str, source: str = "note",
              seq: Optional[int] = None) -> bool:
    """Append something said. Returns False when it is a repeat.

    THE MICROPHONE REPEATS ITSELF, BY DESIGN. Streamlit hands a component's last
    value back on every rerun, so the same batch of speech arrives again and
    again until a newer one replaces it. Each batch carries a sequence number,
    and anything at or below the last one taken is a repeat, not new speech.
    Without this a two-hour session would transcribe its first sentence a few
    hundred times.
    """
    text = (text or "").strip()
    if not text:
        return False
    if seq is not None:
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            return False
        if seq <= int(session.get("last_seq", -1)):
            return False
        session["last_seq"] = seq
    session.setdefault("chunks", []).append({
        "t": datetime.utcnow().isoformat(timespec="seconds"),
        "source": source if source in ("voice", "note") else "note",
        "text": text,
    })
    return True


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def unread_text(session: dict) -> str:
    chunks = session.get("chunks") or []
    return " ".join(c.get("text", "") for c in chunks[int(session.get("read_upto", 0)):])


def unread_words(session: dict) -> int:
    return _words(unread_text(session))


def context_text(session: dict, max_words: int = 600) -> str:
    """The tail of the whole conversation, for the listener's sense of where we are."""
    allw = " ".join(c.get("text", "") for c in (session.get("chunks") or [])).split()
    return " ".join(allw[-max_words:])


def mark_read(session: dict) -> None:
    session["read_upto"] = len(session.get("chunks") or [])


def surfaced_ids(session: dict) -> list:
    """Board items the listener has already raised in this session."""
    seen: list = []
    for ins in session.get("insights") or []:
        for ev in ins.get("evidence") or []:
            if ev.get("item_id") and ev["item_id"] not in seen:
                seen.append(ev["item_id"])
        for i in (ins.get("connection") or {}).get("item_ids") or []:
            if i not in seen:
                seen.append(i)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# The board, narrowed to what bears on the moment
# ══════════════════════════════════════════════════════════════════════════════

_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "your", "our", "are",
    "was", "were", "have", "has", "had", "they", "them", "their", "what", "when",
    "which", "who", "about", "into", "just", "like", "really", "think", "know",
    "yeah", "okay", "right", "kind", "sort", "thing", "things", "going", "want",
    "would", "could", "should", "there", "here", "then", "than", "also", "very",
    "much", "more", "some", "maybe", "because", "being", "been", "does", "doing",
}


def tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= 4 and w not in _STOP}


def prefilter_board(items: list, text: str, k: int = 40) -> list:
    """The k saved items most likely to bear on `text`, best first.

    Cheap word overlap, only to keep the prompt short when a board grows past a
    few dozen items. It does not decide relevance — the model does that, and it
    sees every item that survives. Order is stable, so ties keep the board's own
    order (newest first) rather than shuffling between readings.
    """
    if len(items) <= k:
        return list(items)
    t = tokens(text)
    scored = []
    for n, it in enumerate(items):
        overlap = len(t & tokens(f"{it.get('title','')} {it.get('content','')}"))
        scored.append((-overlap, n, it))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [it for _o, _n, it in scored[:k]]


def board_listing(board: list, unpack=None) -> str:
    """The numbered board, as the listener reads it.

    `unpack` is db.unpack_evidence, passed in rather than imported so this
    module stays free of the database. Without it the raw content is used.
    """
    lines = []
    for n, it in enumerate(board):
        body = it.get("content", "")
        if unpack:
            try:
                body = unpack(body)[0]
            except Exception:
                pass
        body = re.sub(r"\s+", " ", body or "").strip()[:180]
        # Archive material is labelled as such, in the listing itself, so the
        # model can tell a human's choice from a machine's harvest.
        when = (f"from a scan of {it.get('saved_at','')}, not curated"
                if it.get("type") == "archive" else f"kept {it.get('saved_at','')}")
        lines.append(f"[{n}] {str(it.get('type','')).upper()} · {when} · "
                     f"\"{str(it.get('title','')).strip()[:140]}\""
                     + (f" — {body}" if body else ""))
    return "\n".join(lines)


def archive_items(briefs: list, max_briefs: int = 2, max_items: int = 14) -> list:
    """Recent briefs for the client, flattened into citable items.

    THE BOARD IS THE EDIT; THE ARCHIVE IS THE RAW MATERIAL. A client that has
    only just been set up has an empty board, and an ear with nothing to cite
    can only ever stay silent. The currents, tensions and openings of the last
    scans are real rows in the database, so they can be cited without breaking
    rule 4 — but they are typed "archive", listed after the curated items, and
    the prompt says to prefer what a human kept.
    """
    out: list = []
    for b in (briefs or [])[:max_briefs]:
        res = b.get("result") or {}
        rid = str(b.get("id") or "")
        day = str(b.get("saved_at") or "")[:10]

        def _add(kind, n, title, body):
            title = re.sub(r"\s+", " ", str(title or "")).strip()
            if title:
                out.append({"id": f"brief:{rid}:{kind}{n}", "type": "archive",
                            "title": title, "content": str(body or "").strip(),
                            "url": "", "saved_at": day, "report_id": rid})

        for n, t in enumerate((res.get("trends") or [])[:3]):
            _add("t", n, t.get("title"), t.get("summary"))
        for n, t in enumerate((res.get("tensions") or [])[:2]):
            _add("x", n, t.get("title"), t.get("open") or t.get("opening") or "")
        for n, g in enumerate((res.get("trade_vs_street") or [])[:2]):
            _add("g", n, g.get("gap"), " · ".join(p for p in (
                f"trade says {g.get('trade_says')}" if g.get("trade_says") else "",
                f"street says {g.get('street_says')}" if g.get("street_says") else "") if p))
    return out[:max_items]


def ear_material(client_items: list, board_items: list, archive: list) -> list:
    """What the ear may cite, curated first.

    The client's own material when there is any; the whole Atlantic board when
    there is not (a client set up this morning should still get readings); the
    recent archive after either.
    """
    curated = list(client_items) if client_items else list(board_items)
    seen = {it.get("id") for it in curated}
    return curated + [a for a in (archive or []) if a.get("id") not in seen]


# ══════════════════════════════════════════════════════════════════════════════
# The ear
# ══════════════════════════════════════════════════════════════════════════════

def build_ear_prompt(client: dict, new_text: str, context: str, board: list,
                     surfaced: Optional[list] = None, unpack=None,
                     mode: str = "heard") -> str:
    """The reading prompt. `mode` is "heard" (what the room just said) or
    "asked" (a question the facilitator typed to the tool, privately)."""
    c = normalise_client(client)
    probs = "\n".join(f"  - {p}" for p in c["problems"]) or "  (none given)"
    already = ", ".join(str(n) for n, it in enumerate(board)
                        if it.get("id") in (surfaced or [])) or "none"
    if mode == "asked":
        cue = ("THE FACILITATOR ASKS YOU, PRIVATELY — answer from the board, in the "
               "same JSON. \"heard\" restates what they are looking for:")
    else:
        cue = "JUST SAID (react to this):"
    return f"""You are the second listener in a client workshop run by Atlantic, a strategy and creative agency. The workshop is about finding "something they weren't looking for" — countercurrents and white space — for {c['name'] or c['brand'] or 'the client'}.

You sit on the AGENCY's side of the room. Only the facilitator sees what you write, and they glance at it between sentences. Be brief.

THE CLIENT
  Brand: {c['brand'] or '—'} · Category: {c['category'] or '—'} · Product: {c['product'] or '—'} · Market: {c['market'] or '—'}
  Who is in the room: {c['role'] or 'not stated'}
  What they came to explore: {c['objective'] or '—'}
  Problems they brought:
{probs}
  Their own tastes and references (use ONLY for analogies, never as evidence): {c['interests'] or '—'}

THE BOARD — what the agency curated before the session. Cite items ONLY by their number in brackets. Items typed ARCHIVE come from recent scans nobody curated: cite one only when nothing a human kept fits.
{board_listing(board, unpack) or '(the board is empty)'}

Items already raised this session: {already}. Prefer fresh ones unless the conversation returns to an earlier thread.

RECENT CONVERSATION (for context):
{context or '(nothing yet)'}

{cue}
{new_text}

Respond ONLY with JSON:
{{"heard": "one line — what the room is circling, in your words",
  "evidence": [{{"item": 3, "why": "how this saved item bears on what was just said"}}],
  "connection": {{"text": "one non-obvious link, phrased as an observation or a question", "items": [3, 7]}},
  "look_into": {{"category": "...", "product": "...", "reason": "why the board does not already cover this"}},
  "question": "one question the facilitator could put to the room next"}}

RULES — these are the product, not style:
- EVIDENCE, NEVER CONCLUSIONS. Never say what the client should do, launch, change or decide. The facilitator turns evidence into direction; you do not.
- Cite only numbers from the board. If nothing on the board bears on what was just said, return "evidence": [] — silence is a correct answer and a stretched one is not.
- At most 3 evidence items. At most ONE connection, and only if it is genuinely non-obvious: a link between what was said and something from a different register (what people say vs what the industry reports vs what writers argue), or between two board items the room has not put together. If you would have to reach for it, leave "connection" null.
- "look_into" only when the conversation has moved onto ground the board does not cover. It names a NEW search, by category and product. Otherwise null.
- "question" is optional. It must open the room up, not steer it to an answer.
- Write in the language the conversation is in.
- Never quote the client back to themselves at length, never flatter, never summarise the meeting so far.
LENGTH: heard ≤ 14 words · why ≤ 18 words · connection ≤ 30 words · question ≤ 20 words · reason ≤ 18 words."""


def _clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def parse_ear(obj: Optional[dict], board: list) -> Optional[dict]:
    """Validate a reading against the board. Returns None if nothing is left.

    THE ONE PLACE A HALLUCINATION COULD REACH THE ROOM, and it is closed here.
    The model cites by position; positions that do not exist are dropped, and
    every surviving citation is replaced by the saved item's own id, title and
    link — so what the facilitator sees comes from the database, never from the
    model's recollection of what it read.
    """
    if not isinstance(obj, dict):
        return None

    def _item(n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return None
        return board[n] if 0 <= n < len(board) else None

    evidence, seen = [], set()
    for ev in (obj.get("evidence") or [])[:6]:
        if not isinstance(ev, dict):
            continue
        it = _item(ev.get("item"))
        if not it or it.get("id") in seen:
            continue
        seen.add(it.get("id"))
        evidence.append({"item_id": it.get("id"), "title": _clip(it.get("title"), 160),
                         "type": it.get("type", ""), "url": it.get("url", ""),
                         "why": _clip(ev.get("why"), 160)})
        if len(evidence) >= 3:
            break

    connection = None
    con = obj.get("connection")
    if isinstance(con, dict) and str(con.get("text") or "").strip():
        items = [it for it in (_item(n) for n in (con.get("items") or [])[:4]) if it]
        connection = {"text": _clip(con.get("text"), 240),
                      "item_ids": [it.get("id") for it in items],
                      "titles": [_clip(it.get("title"), 90) for it in items]}

    look = None
    lk = obj.get("look_into")
    if isinstance(lk, dict) and (str(lk.get("category") or "").strip()
                                 or str(lk.get("product") or "").strip()):
        look = {"category": _clip(lk.get("category"), 60),
                "product": _clip(lk.get("product"), 60),
                "reason": _clip(lk.get("reason"), 160)}

    out = {"heard": _clip(obj.get("heard"), 140),
           "evidence": evidence,
           "connection": connection,
           "look_into": look,
           "question": _clip(obj.get("question"), 180)}
    if not (evidence or connection or look or out["question"]):
        return None              # nothing worth a card — and that is fine
    out["t"] = datetime.utcnow().isoformat(timespec="seconds")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Background searches
# ══════════════════════════════════════════════════════════════════════════════
# A full scan takes about four minutes. In the room that stops being a defect:
# a question at minute 20 lands at minute 24 as "while you were talking, we went
# and looked." The registry is the only thing the worker thread writes to; the
# session log is updated by the main thread when it sees a finished job, so
# there is exactly one writer for anything persisted and no lost updates.

class JobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict = {}

    KEEP_FINISHED = 3600.0   # seconds a finished, never-collected job is kept

    def start(self, session_id: str, label: str, **meta) -> str:
        jid = uuid.uuid4().hex[:10]
        with self._lock:
            # A job is collected when its session's page next looks. If that
            # page was closed, nobody ever will — so finished jobs older than
            # an hour are dropped here rather than kept for the life of the
            # server.
            now = time.time()
            for old in [k for k, j in self._jobs.items()
                        if j["finished"] and now - j["finished"] > self.KEEP_FINISHED]:
                self._jobs.pop(old, None)
            self._jobs[jid] = {"id": jid, "session_id": session_id, "label": label,
                               "status": "running", "started": time.time(),
                               "finished": None, "result": None, "error": "",
                               **meta}
        return jid

    def finish(self, jid: str, result: Optional[dict] = None, error: str = "") -> None:
        with self._lock:
            j = self._jobs.get(jid)
            if not j:
                return
            j["finished"] = time.time()
            j["status"] = "failed" if error else "done"
            j["result"] = result
            j["error"] = error

    def for_session(self, session_id: str) -> list:
        with self._lock:
            return [dict(j) for j in self._jobs.values() if j["session_id"] == session_id]

    def running(self, session_id: str, kind: Optional[str] = None) -> int:
        return sum(1 for j in self.for_session(session_id)
                   if j["status"] == "running" and (kind is None or j.get("kind") == kind))

    def is_running(self, jid: str) -> bool:
        with self._lock:
            j = self._jobs.get(jid)
            return bool(j) and j["status"] == "running"

    def known(self, jid: str) -> bool:
        """Still in the registry — running, or finished and not yet collected.
        A session log that says "running" for a job this does not know was
        interrupted: the server restarted while the thread was working."""
        with self._lock:
            return jid in self._jobs

    def pop_finished(self, session_id: str) -> list:
        """Hand over this session's finished jobs, ONCE, and forget them.

        The registry lives as long as the server process, and every reading of
        the room is a job — a two-hour session is a hundred of them. Taking a
        finished job out of here as it is moved into the session log keeps the
        registry to what is actually still running.
        """
        with self._lock:
            done = [jid for jid, j in self._jobs.items()
                    if j["session_id"] == session_id and j["status"] != "running"]
            return [self._jobs.pop(jid) for jid in done]


JOBS = JobRegistry()


def scan_summary(result: dict) -> dict:
    """The few lines of a finished background scan worth putting in the room."""
    res = result or {}
    return {
        "currents": [_clip(t.get("title"), 110) for t in (res.get("trends") or [])[:3]],
        "tension": _clip(((res.get("tensions") or [{}])[0]).get("title"), 110)
        if res.get("tensions") else "",
        "opening": _clip(((res.get("trade_vs_street") or [{}])[0]).get("gap"), 160)
        if res.get("trade_vs_street") else "",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Pacing, clocks and the notes that leave the room
# ══════════════════════════════════════════════════════════════════════════════

AUTO_READ_WORDS = 150      # about a minute of conversation
AUTO_READ_GAP = 40.0       # seconds — never two readings closer than this


def should_auto_read(unread: int, since_last: float,
                     min_words: int = AUTO_READ_WORDS,
                     min_gap: float = AUTO_READ_GAP) -> bool:
    """Enough new talk, and not too soon after the last reading."""
    return unread >= min_words and since_last >= min_gap


def _parse_iso(iso: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "").split(".")[0])
    except Exception:
        return None


def fmt_clock(iso: str, tz_name: str = "") -> str:
    """'2026-10-07T18:32:05' (UTC) → '14:32' on the team's clock."""
    d = _parse_iso(iso)
    if not d:
        return ""
    if tz_name:
        try:
            from datetime import timezone
            from zoneinfo import ZoneInfo
            d = d.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
        except Exception:
            pass                     # a bad zone name must not cost the time
    return d.strftime("%H:%M")


def duration_min(session: dict, now: Optional[datetime] = None) -> int:
    a = _parse_iso(session.get("started_at", ""))
    b = _parse_iso(session.get("ended_at", "")) or now or datetime.utcnow()
    if not a:
        return 0
    return max(0, int((b - a).total_seconds() // 60))


def word_count(session: dict) -> int:
    return sum(_words(c.get("text", "")) for c in (session.get("chunks") or []))


def session_markdown(session: dict, client: Optional[dict] = None,
                     link=None, tz_name: str = "") -> str:
    """The session as notes the team can keep: what was raised, what was
    looked into, then the transcript. `link(report_id)` turns a background
    scan into a URL; without it the scan is listed unlinked."""
    c = normalise_client(client or {})
    name = c["name"] or c["brand"] or session.get("client_name") or "Client"
    day = (_parse_iso(session.get("started_at", "")) or datetime.utcnow()).strftime("%d %b %Y")
    span = fmt_clock(session.get("started_at", ""), tz_name)
    if session.get("ended_at"):
        span += "–" + fmt_clock(session.get("ended_at", ""), tz_name)
    L = [f"# Session notes — {name}",
         f"{day} · {span} · {duration_min(session)} min · {word_count(session)} words", ""]
    if c["objective"] or c["problems"]:
        L.append("## What they came with")
        if c["objective"]:
            L.append(c["objective"])
        L += [f"- {p}" for p in c["problems"]]
        L.append("")
    ins = session.get("insights") or []
    L.append("## What the board brought up")
    if not ins:
        L.append("_Nothing was raised._")
    for i in ins:
        head = i.get("asked") and f"Asked: {i['asked']}" or i.get("heard") or "Reading"
        L.append(f"### {fmt_clock(i.get('t', ''), tz_name)} — {head}")
        for ev in i.get("evidence") or []:
            t = ev.get("title", "")
            t = f"[{t}]({ev['url']})" if ev.get("url") else t
            L.append(f"- {t}" + (f" — {ev['why']}" if ev.get("why") else ""))
        con = i.get("connection") or {}
        if con.get("text"):
            L.append(f"- **Connection:** {con['text']}")
        if i.get("question"):
            L.append(f"- **Ask the room:** {i['question']}")
        lk = i.get("look_into") or {}
        if lk:
            L.append(f"- **Worth a search:** {' · '.join(p for p in (lk.get('category'), lk.get('product')) if p)}"
                     + (f" — {lk['reason']}" if lk.get("reason") else ""))
        L.append("")
    scans = session.get("scans") or []
    if scans:
        L.append("## Looked into during the session")
        for s in scans:
            line = f"- **{s.get('label', '')}** — {s.get('status', '')}"
            if s.get("report_id") and link:
                line += f" · [open the brief]({link(s['report_id'])})"
            L.append(line)
            for cur in (s.get("summary") or {}).get("currents") or []:
                L.append(f"  - {cur}")
            if s.get("error"):
                L.append(f"  - {s['error']}")
        L.append("")
    L.append("## Transcript")
    for ch in session.get("chunks") or []:
        mark = "" if ch.get("source") == "voice" else " (note)"
        L.append(f"{fmt_clock(ch.get('t', ''), tz_name)}{mark} — {ch.get('text', '')}")
    return "\n".join(L).rstrip() + "\n"
