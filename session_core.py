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
from datetime import datetime, timedelta
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
        # the session panel (HUD)
        "table": None,       # the question on the table: {q, src, t}
        "table_hist": [],    # every question that was put there
        "queue": [],         # questions waiting their turn
        "phase": 0,          # index into PHASES
        "quest_at": [],      # per client problem: when it was first touched
        "auto": True,        # read the room as the talk goes
        "hud_ack": -1,       # highest panel action already applied
        "went_live": None,   # when Go live was pressed; until then the room sees the opening
    }


def add_chunk(session: dict, text: str, source: str = "note",
              seq: Optional[int] = None, spk: str = "", parts: Optional[list] = None,
              t0=None, t1=None, ep: str = "", turn=None) -> bool:
    """Append something said. Returns False when it is a repeat.

    THE MICROPHONE REPEATS ITSELF, BY DESIGN. Streamlit hands a component's last
    value back on every rerun, so the same batch of speech arrives again and
    again until a newer one replaces it. Each batch carries a sequence number,
    and anything at or below the last one taken is a repeat, not new speech.
    Without this a two-hour session would transcribe its first sentence a few
    hundred times.

    Who said it travels with the line but is never decided here (see "Who is
    speaking" below): `spk` is the voice the transcription service heard,
    `parts` are the pieces of speech with their browser times, for the taps.
    """
    clean = None
    if isinstance(parts, list) and parts:
        clean = []
        for pt in parts[:80]:
            if not isinstance(pt, dict):
                continue
            x = str(pt.get("x") or "").strip()
            if x:
                clean.append({"x": x[:4000], "t0": _ms(pt.get("t0")), "t1": _ms(pt.get("t1"))})
        if not text and clean:
            text = " ".join(p["x"] for p in clean)
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
    ch = {"t": datetime.utcnow().isoformat(timespec="seconds"),
          "source": source if source in ("voice", "note") else "note",
          "text": text}
    if ch["source"] == "voice":
        if spk:
            ch["spk"] = str(spk)[:40]
            voice_person(session, ch["spk"])        # a new voice shows up at once, unnamed
        if clean:
            ch["parts"] = clean
        if _ms(t0):
            ch["t0"] = _ms(t0)
        if _ms(t1):
            ch["t1"] = _ms(t1)
        if _ep(ep):
            ch["ep"] = _ep(ep)
        if _seqno(turn) is not None:
            ch["turn"] = _seqno(turn)
    session.setdefault("chunks", []).append(ch)
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
# Who is speaking
# ══════════════════════════════════════════════════════════════════════════════
# Two ways to put a name on what was said, decided by what the server holds:
#
#   AUTO — with an AssemblyAI key, the transcription service tells the voices
#   apart and labels every turn "A", "B"… A label means something only inside
#   one connection to the service (a reconnect starts again at "A"), so a voice
#   is kept as "<connection>:<label>" and mapped here to a PERSON. When two
#   voices turn out to be one person, the facilitator merges them.
#
#   TAP — free: Chrome transcribes, and the facilitator taps who is speaking
#   (keys 1–9 on the panel). Taps and speech carry the same browser clock;
#   each piece of speech goes to whoever was tapped when it BEGAN — allowing
#   two seconds for the tap to land after a new voice starts, but never a tap
#   that came after the piece had ended (that tap is for the next speaker).
#
# NOTHING ABOUT A VOICE IS KEPT — no recording, no voiceprint. The service
# tells voices apart inside one connection and forgets them; this file keeps
# the text, a label per line and the names the room gave itself.
#
# WHO SAID A LINE IS ALWAYS WORKED OUT, NEVER WRITTEN ON IT. A line keeps the
# raw voice it was heard in, or the times of its pieces; the person behind it
# comes from the current map and taps, every time. So a merge, a late tap or a
# label the service revises later fixes every earlier line at once.

MAX_PEOPLE = 24            # a runaway split must not flood the screen
TAP_LAG_MS = 2000          # a tap may land this long after the new voice starts
INTRO_WORDS = 60           # an introduction is read from a person's first words
NOW_SECONDS = 8            # "speaking now" lasts this long after their last line
_NO_LABEL = {"", "PENDING", "UNKNOWN", "NONE", "NULL"}


def _ms(x) -> Optional[int]:
    """A browser timestamp in ms, or None."""
    try:
        v = int(float(x))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _seqno(x) -> Optional[int]:
    """A sequence or turn number (0 is valid), or None."""
    try:
        v = int(x)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def _ep(x) -> str:
    """A connection id, made safe to use inside a key."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(x or ""))[:24]


def _fold(s) -> str:
    """Lowercase, accents and punctuation off: 'João-Lima' → 'joao lima'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _tag(n) -> str:
    """1 → A, 26 → Z, 27 → AA: the letter an unnamed voice is shown with. It is
    given once and never moves, so 'Voice C' stays C after others are merged."""
    try:
        n = max(1, int(n))
    except (TypeError, ValueError):
        n = 1
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def people_defaults(session: dict) -> dict:
    """Session logs from before names existed lack these fields."""
    session.setdefault("people", [])        # [{id, n, name, role, you, src, by}]
    session.setdefault("voices", {})        # "<connection>:<label>" → person id
    session.setdefault("taps", [])          # [[browser ms, person id or ""]], in order
    session.setdefault("intro_on", False)   # the round of introductions is on screen
    session.setdefault("intro_win", [])     # [[from ms, to ms or None]] — when it was
    session.setdefault("voice_mode", "")    # "auto" (service) · "tap" (facilitator)
    session.setdefault("people_notes", {})  # person id → what they cared about (after)
    session.setdefault("quest_by", [])      # per client problem: who said it (raised_by)
    session.setdefault("assign", {})        # chunk index (str) → person id, set by hand
    if not isinstance(session.get("people_n"), int):
        session["people_n"] = max([int(p.get("n") or 0) for p in session["people"]] + [0])
    return session


def person(session: dict, pid) -> Optional[dict]:
    for p in session.get("people") or []:
        if p.get("id") == pid:
            return p
    return None


def new_person(session: dict, src: str = "voice") -> Optional[dict]:
    people_defaults(session)
    if len(session["people"]) >= MAX_PEOPLE:
        return None
    session["people_n"] = int(session.get("people_n") or 0) + 1
    n = session["people_n"]
    p = {"id": f"p{n}", "n": n, "name": "", "role": "", "you": False,
         "src": src if src in ("voice", "tap") else "voice", "by": ""}
    session["people"].append(p)
    return p


def person_label(p: Optional[dict], short: bool = False) -> str:
    """'Ana Souza' · 'Ana' (short) · 'You' (the facilitator, short) · 'Voice C'."""
    if not p:
        return ""
    if p.get("you") and (short or not p.get("name")):
        return "You"
    if p.get("name"):
        return p["name"].split()[0] if short else p["name"]
    return f"Voice {_tag(p.get('n'))}"


def voice_key(ep, label) -> str:
    """'<connection>:<label>', or "" for a turn the service could not place yet."""
    label = str(label or "").strip().upper()[:8]
    ep = _ep(ep)
    if label in _NO_LABEL or not ep:
        return ""
    return f"{ep}:{label}"


def voice_person(session: dict, vkey: str, create: bool = True) -> str:
    """The person behind a voice. A voice heard for the first time becomes a new
    person with no name, shown as 'Voice C' until someone says who it is."""
    if not vkey:
        return ""
    people_defaults(session)
    pid = session["voices"].get(vkey)
    if pid and person(session, pid):
        return pid
    if not create:
        return ""
    p = new_person(session, "voice")
    if not p:
        return ""
    session["voices"][vkey] = p["id"]
    return p["id"]


def _tap_index(session: dict) -> tuple:
    taps = []
    for t in session.get("taps") or []:
        if isinstance(t, (list, tuple)) and len(t) == 2 and _ms(t[0]):
            taps.append((_ms(t[0]), str(t[1] or "")))
    taps.sort(key=lambda x: x[0])
    return [t[0] for t in taps], [t[1] for t in taps]


def _who_at(idx: tuple, t_ms: Optional[int]) -> str:
    import bisect
    keys, whos = idx
    if not keys or not t_ms:
        return ""
    i = bisect.bisect_right(keys, t_ms) - 1
    return whos[i] if i >= 0 else ""


def _first_tap_in(idx: tuple, a: Optional[int], b: Optional[int]) -> str:
    """The first person tapped while a piece was being said — for a piece that
    began before anyone was tapped (the facilitator pressed a moment late)."""
    import bisect
    keys, whos = idx
    if not keys or not a or not b:
        return ""
    i = bisect.bisect_left(keys, a)
    while i < len(keys) and keys[i] <= b:
        if whos[i]:
            return whos[i]
        i += 1
    return ""


def _in_intro(wins: list, t0: Optional[int], t1: Optional[int] = None) -> bool:
    """Was this said during a round of introductions? It must start inside the
    round (a second and a half of grace: someone may begin as the facilitator
    opens it) and end inside it too — a line still going when the round was
    closed is the meeting starting, not an introduction."""
    if not t0:
        return False
    for w in wins or []:
        if not isinstance(w, (list, tuple)) or not w:
            continue
        a, b = _ms(w[0]), (_ms(w[1]) if len(w) > 1 else None)
        if a and t0 >= a - 1500 and (b is None or (t0 <= b and (not t1 or t1 <= b + 1500))):
            return True
    return False


def session_lines(session: dict, first: int = 0) -> list:
    """Every line said, in order, with WHO said it — the one place that works it out.

    A line heard by the service names its voice; a line from Chrome carries the
    times of its pieces, which the taps divide between people; a typed note has
    neither. Each line: {n (chunk), t, x, w (person id or ""), note, intro, t0}."""
    people_defaults(session)
    chunks = session.get("chunks") or []
    voices = session.get("voices") or {}
    known = {p.get("id") for p in session.get("people") or []}
    idx = _tap_index(session)
    wins = session.get("intro_win") or []
    hand = session.get("assign") or {}
    out = []
    for n in range(max(0, first), len(chunks)):
        ch = chunks[n]
        voice = ch.get("source") == "voice"
        base = {"n": n, "t": ch.get("t", ""), "note": not voice}
        if not voice:
            out.append(dict(base, x=ch.get("text", ""), w="", intro=False, t0=None))
            continue
        if hand.get(str(n)) in known:
            # Said who it was by hand: that wins over taps and voices, for the
            # whole line. (The intro flag still comes from the clock.)
            a = _ms(ch.get("t0")) or _ms(((ch.get("parts") or [{}])[0]).get("t0"))
            b = _ms(ch.get("t1")) or _ms(((ch.get("parts") or [{}])[-1]).get("t1"))
            out.append(dict(base, x=ch.get("text", ""), w=hand[str(n)], intro=_in_intro(wins, a, b), t0=a))
            continue
        if ch.get("spk") or ch.get("ep"):
            w = voices.get(ch.get("spk") or "", "")
            out.append(dict(base, x=ch.get("text", ""), w=w if w in known else "",
                            intro=_in_intro(wins, _ms(ch.get("t0")), _ms(ch.get("t1"))), t0=_ms(ch.get("t0"))))
            continue
        pieces = ch.get("parts") or [{"x": ch.get("text", ""), "t0": ch.get("t0"), "t1": ch.get("t1")}]
        run = None
        for pt in pieces:
            x = str(pt.get("x") or "").strip()
            if not x:
                continue
            a, b = _ms(pt.get("t0")), _ms(pt.get("t1"))
            at = min(a + TAP_LAG_MS, b) if (a and b) else ((a + TAP_LAG_MS) if a else b)
            w = _who_at(idx, at) or _first_tap_in(idx, a, b)
            w = w if w in known else ""
            intro = _in_intro(wins, a or b, b)
            if run is not None and run["w"] == w and run["intro"] == intro:
                run["x"] += " " + x
            else:
                run = dict(base, x=x, w=w, intro=intro, t0=a)
                out.append(run)
        if run is None:
            out.append(dict(base, x=ch.get("text", ""), w="", intro=False, t0=None))
    return out


def airtime(lines: list) -> dict:
    """Words each person said — introductions and typed notes left out."""
    w: dict = {}
    for l in lines or []:
        if l.get("note") or l.get("intro") or not l.get("w"):
            continue
        w[l["w"]] = w.get(l["w"], 0) + _words(l.get("x", ""))
    return w


def shares100(values: list) -> list:
    """Whole percentages that add up to exactly 100 (largest remainder)."""
    vals = [max(0, v or 0) for v in values or []]
    tot = sum(vals)
    if tot <= 0:
        return [0] * len(vals)
    raw = [100.0 * v / tot for v in vals]
    out = [int(r) for r in raw]
    left = 100 - sum(out)
    for i in sorted(range(len(raw)), key=lambda i: (-(raw[i] - out[i]), i))[:left]:
        out[i] += 1
    return out


def _stem(w: str) -> str:
    for suf in ("ing", "ers", "ies", "ed", "es", "er", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _toks(text: str) -> set:
    return {_stem(w) for w in tokens(_fold(text))}


def raised_by(session: dict, text: str, lines: Optional[list] = None, window: int = 14) -> str:
    """WHO SAID IT — the person whose recent line shares the most words with a
    client problem ('boycotting' meets 'boycott'), or "" when nobody clearly
    did. Not 'who was speaking when the box was ticked': a reading ticks boxes
    for the last minute of talk, and the notes must not hand one person's
    point to another."""
    want = _toks(text)
    if not want:
        return ""
    need = 1 if len(want) <= 3 else 2
    lines = session_lines(session) if lines is None else lines
    recent = [l for l in lines if l.get("w") and not l.get("note")][-window:]
    best, best_n = "", need - 1
    for l in recent:                      # oldest to newest: a tie goes to the latest
        n = len(want & _toks(l.get("x", "")))
        if n >= best_n and n >= need:
            best, best_n = l["w"], n
    return best


def last_speaker(session: dict) -> str:
    """Who is speaking now: the last tap when the facilitator tags, otherwise
    whoever said the last line the service placed."""
    if session.get("voice_mode") == "tap":
        idx = _tap_index(session)
        if idx[1]:
            return idx[1][-1] if person(session, idx[1][-1]) else ""
    chunks = session.get("chunks") or []
    for n in range(len(chunks) - 1, max(-1, len(chunks) - 25), -1):
        if chunks[n].get("source") != "voice":
            continue
        for l in reversed(session_lines(session, first=n)):
            if l.get("w") and not l.get("note"):
                return l["w"]
    return ""


def intro_texts(session: dict, lines: Optional[list] = None) -> dict:
    """What each person said in the round of introductions — their first words."""
    lines = session_lines(session) if lines is None else lines
    out: dict = {}
    for l in lines:
        if l.get("intro") and l.get("w") and not l.get("note"):
            have = out.get(l["w"], "")
            if _words(have) < INTRO_WORDS:
                out[l["w"]] = (have + " " + l.get("x", "")).strip()
    return {k: " ".join(v.split()[:INTRO_WORDS]) for k, v in out.items()}


def intro_todo(session: dict, texts: dict) -> dict:
    """Introductions worth reading (again): there is something new in them and
    nobody has typed that person's name by hand."""
    tried = session.get("_intro_tried") or {}
    todo = {}
    for pid, text in (texts or {}).items():
        p = person(session, pid)
        if not p or p.get("by") == "typed" or _words(text) < 2:
            continue
        if _words(text) > int(tried.get(pid, 0)):
            todo[pid] = text
    return todo


def build_intro_prompt(entries: dict) -> str:
    rows = "\n".join(f'[{pid}] "{_clip(text, 600)}"' for pid, text in entries.items())
    return ("These are people in a client workshop introducing themselves, one entry per person, "
            "transcribed by a machine — a name may be spelt the way it sounded.\n\n"
            f"{rows}\n\n"
            "For each entry give the person's NAME and ROLE as they said them. Copy the name "
            "from the entry, exactly as written there; never supply a name that is not in it. "
            "The role is short — a job title or what they do, six words at most, in the "
            "language they used. Use null for anything not said. If an entry is not an "
            "introduction at all, both are null.\n\n"
            'Answer only with JSON: {"people": [{"id": "p1", "name": "Ana Souza", "role": "CMO"}]}')


def parse_intro(obj, entries: dict) -> dict:
    """{person id: {name, role}} — and only names that really are in their words.
    A name the model supplied from nowhere is dropped: the card then asks for it."""
    out: dict = {}
    rows = obj.get("people") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("id") or "")
        if pid not in entries:
            continue
        name, role = _clip(r.get("name"), 60), _clip(r.get("role"), 60)
        name = "" if name.lower() in ("null", "none", "unknown", "n/a") else name
        role = "" if role.lower() in ("null", "none", "unknown", "n/a") else role
        if name:
            said = f" {_fold(entries[pid])} "
            toks = [t for t in _fold(name).split() if len(t) >= 2]
            if not toks or any(f" {t} " not in said for t in toks):
                name = ""
        if name or role:
            out[pid] = {"name": name, "role": role}
    return out


def apply_intro(session: dict, found: dict) -> list:
    """Put the names read from the introductions on their people — never over a
    name somebody typed. Returns the ids that changed."""
    changed = []
    for pid, v in (found or {}).items():
        p = person(session, pid)
        if not p or p.get("by") == "typed":
            continue
        if v.get("name") and v["name"] != p.get("name"):
            twin = next((q for q in session.get("people") or [] if q is not p and q.get("name")
                         and _fold(q["name"]) == _fold(v["name"])), None)
            if twin:                       # introduced twice (a reconnect): one person
                merge_people(session, pid, twin["id"])
                changed.append(twin["id"])
                continue
            p["name"], p["by"] = v["name"], "intro"
            changed.append(pid)
        if v.get("role") and v["role"] != p.get("role"):
            p["role"] = v["role"]
            if pid not in changed:
                changed.append(pid)
    return changed


def merge_people(session: dict, src_id: str, dst_id: str) -> bool:
    """Two entries, one person: every voice, tap and touch of `src` goes to `dst`."""
    if not src_id or src_id == dst_id:
        return False
    a, b = person(session, src_id), person(session, dst_id)
    if not a or not b:
        return False
    for k, v in list((session.get("voices") or {}).items()):
        if v == src_id:
            session["voices"][k] = dst_id
    session["taps"] = [[t[0], dst_id if t[1] == src_id else t[1]] for t in session.get("taps") or []
                       if isinstance(t, (list, tuple)) and len(t) == 2]
    session["quest_by"] = [dst_id if x == src_id else x for x in session.get("quest_by") or []]
    session["assign"] = {k: (dst_id if v == src_id else v) for k, v in (session.get("assign") or {}).items()}
    if not b.get("name") and a.get("name"):
        b["name"], b["role"], b["by"] = a["name"], a.get("role", ""), a.get("by", "")
    elif not b.get("role") and a.get("role"):
        b["role"] = a["role"]
    if a.get("you"):
        b["you"] = True
    notes = session.get("people_notes") or {}
    notes.pop(src_id, None)
    notes.pop(dst_id, None)              # rewritten from the merged lines next time
    session["people"] = [p for p in session.get("people") or [] if p.get("id") != src_id]
    return True


def name_person(session: dict, pid: str, name: str, role: str = "") -> str:
    """Name someone by hand. Typing the name of someone already in the room means
    it is them, so the two are merged. Returns the id that carries the name."""
    p = person(session, pid)
    if not p:
        return ""
    name, role = _clip(name, 60), _clip(role, 60)
    if name:
        twin = next((q for q in session.get("people") or [] if q is not p and q.get("name")
                     and _fold(q["name"]) == _fold(name)), None)
        if twin:
            merge_people(session, pid, twin["id"])
            if role:
                twin["role"] = role
            return twin["id"]
    p["name"], p["role"] = name, role
    p["by"] = "typed" if name else ""
    return pid


def set_you(session: dict, pid: str) -> bool:
    """Mark the facilitator ('You') — one person at most; again to unmark."""
    p = person(session, pid)
    if not p:
        return False
    on = not p.get("you")
    for q in session.get("people") or []:
        q["you"] = False
    p["you"] = on
    return True


def remove_person(session: dict, pid: str) -> bool:
    """Take out someone who never said a word (a tap too many)."""
    if not person(session, pid) or any(l.get("w") == pid for l in session_lines(session)):
        return False
    session["voices"] = {k: v for k, v in (session.get("voices") or {}).items() if v != pid}
    session["taps"] = [[t[0], "" if t[1] == pid else t[1]] for t in session.get("taps") or []
                       if isinstance(t, (list, tuple)) and len(t) == 2]
    session["assign"] = {k: v for k, v in (session.get("assign") or {}).items() if v != pid}
    session["people"] = [p for p in session.get("people") or [] if p.get("id") != pid]
    return True


def assign_line(session: dict, n, who: str) -> bool:
    """Say by hand who said line n (a chunk) — or "" to undo it."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return False
    chunks = session.get("chunks") or []
    if not 0 <= n < len(chunks) or chunks[n].get("source") != "voice":
        return False
    who = str(who or "")
    if who and not person(session, who):
        return False
    a = session.setdefault("assign", {})
    if who:
        a[str(n)] = who
    else:
        a.pop(str(n), None)
    return True


def add_tap(session: dict, at, who: str) -> bool:
    import bisect
    at = _ms(at)
    who = str(who or "")
    if not at or (who and not person(session, who)):
        return False
    taps = session.setdefault("taps", [])
    bisect.insort(taps, [at, who])
    if len(taps) > 8000:
        del taps[:len(taps) - 8000]
    return True


def revise_speakers(session: dict, ep, revs) -> int:
    """The service's second thoughts: after more audio it relabels earlier turns
    (and always once more when the connection closes). Returns lines changed."""
    ep = _ep(ep)
    if not ep or not isinstance(revs, list):
        return 0
    want = {}
    for r in revs:
        if isinstance(r, (list, tuple)) and len(r) == 2:
            t, lab = r
        elif isinstance(r, dict):
            t, lab = r.get("turn_order", r.get("turn")), r.get("speaker_label", r.get("spk"))
        else:
            continue
        t = _seqno(t)
        if t is not None:
            want[t] = voice_key(ep, lab)
    n = 0
    for ch in session.get("chunks") or []:
        if ch.get("ep") == ep and ch.get("turn") in want and ch.get("spk", "") != want[ch["turn"]]:
            ch["spk"] = want[ch["turn"]]
            if ch["spk"]:
                voice_person(session, ch["spk"])
            n += 1
    return n


def take_mic(session: dict, value) -> int:
    """Apply what the microphone sent — every item numbered above the last one
    taken, once each, in order. Returns how many lines were added.

    The microphone keeps an outbox and resends whatever was not acknowledged
    yet (same principle as the panel's actions), so two pieces of speech that
    land between two reruns are both kept. The old one-batch-at-a-time value
    ({seq, text}) is still understood."""
    people_defaults(session)
    if not isinstance(value, dict):
        return 0
    items = value.get("items")
    if items is None and "text" in value:
        items = [dict(value, kind="talk")]
    if not isinstance(items, list):
        return 0
    fresh = []
    for it in items:
        if isinstance(it, dict) and _seqno(it.get("seq")) is not None:
            fresh.append((_seqno(it["seq"]), it))
    added = 0
    for s, it in sorted(fresh, key=lambda x: x[0]):
        if s <= int(session.get("last_seq", -1)):
            continue
        kind = it.get("kind") or "talk"
        if kind == "rev":
            revise_speakers(session, it.get("ep"), it.get("revs"))
        elif kind == "turn":
            if add_chunk(session, str(it.get("text") or ""), "voice",
                         spk=voice_key(it.get("ep"), it.get("spk")), t0=it.get("t0"),
                         t1=it.get("t1"), ep=it.get("ep"), turn=it.get("turn")):
                added += 1
        else:
            parts = [p for p in it.get("parts") or [] if isinstance(p, dict)] \
                if isinstance(it.get("parts"), list) else []
            if add_chunk(session, str(it.get("text") or ""), "voice", parts=parts or None,
                         t0=it.get("t0") or (parts[0].get("t0") if parts else None),
                         t1=it.get("t1") or (parts[-1].get("t1") if parts else None)):
                added += 1
        session["last_seq"] = s
    return added


def people_lines(session: dict, lines: Optional[list] = None, min_words: int = 30) -> dict:
    """{person id: everything they said} — introductions and notes left out —
    for the people who said enough to be summed up."""
    lines = session_lines(session) if lines is None else lines
    out: dict = {}
    for l in lines:
        if l.get("w") and not l.get("note") and not l.get("intro"):
            out[l["w"]] = (out.get(l["w"], "") + " " + l.get("x", "")).strip()
    return {k: v[-7000:] for k, v in out.items() if _words(v) >= min_words}


def build_people_prompt(client: dict, entries: dict, labels: dict) -> str:
    c = normalise_client(client or {})
    rows = "\n\n".join(f"[{pid}] {labels.get(pid, pid)}:\n\"{text}\"" for pid, text in entries.items())
    return (f"A client workshop with {c['name'] or c['brand'] or 'a client'} has ended. Below is "
            "everything each person said, one entry per person, transcribed by a machine.\n\n"
            f"{rows}\n\n"
            "For each person, write what THEY cared about or pushed for in the meeting — at most "
            "two points, each under 18 words, in their own terms. Only from their own words: no "
            "advice, no judgement, nothing they did not say. If there is too little to tell, give "
            "an empty list.\n\n"
            'Answer only with JSON: {"people": [{"id": "p1", "cared": ["…", "…"]}]}')


def parse_people_notes(obj, entries: dict) -> dict:
    out: dict = {}
    rows = obj.get("people") if isinstance(obj, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or str(r.get("id") or "") not in entries:
            continue
        cared = [_clip(x, 170) for x in (r.get("cared") or []) if isinstance(x, str) and x.strip()][:2]
        out[str(r["id"])] = cared
    return out


def people_view(session: dict, lines: Optional[list] = None, pending=()) -> list:
    """The people worth showing, in the order they joined, with their share of
    the talk and where they stand in the round of introductions:
    joined (named) · listen (being read) · ask (no name heard) · wait (not spoken)."""
    people_defaults(session)
    lines = session_lines(session) if lines is None else lines
    at = airtime(lines)
    texts = intro_texts(session, lines)
    tried = session.get("_intro_tried") or {}
    vis = [p for p in session["people"]
           if p.get("name") or p.get("you") or at.get(p["id"]) or texts.get(p["id"]) or p.get("src") == "tap"]
    pct = shares100([at.get(p["id"], 0) for p in vis])
    out = []
    for i, p in enumerate(vis):
        tx = texts.get(p["id"], "")
        if p.get("name") or p.get("you"):
            state = "joined"
        elif not tx:
            state = "wait"
        elif p["id"] in pending or _words(tx) > int(tried.get(p["id"], 0)):
            state = "listen"
        else:
            state = "ask"
        out.append({"id": p["id"], "tag": _tag(p.get("n")), "name": p.get("name", ""),
                    "role": p.get("role", ""), "you": bool(p.get("you")),
                    "short": person_label(p, True), "label": person_label(p),
                    "words": at.get(p["id"], 0), "pct": pct[i], "state": state,
                    "heard": _clip(tx, 220), "src": p.get("src", "voice")})
    return out


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
    probs = "\n".join(f"  [P{n}] {p}" for n, p in enumerate(c["problems"], 1)) or "  (none given)"
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
  "question": "one question the facilitator could put to the room next",
  "touched": [1]}}

RULES — these are the product, not style:
- EVIDENCE, NEVER CONCLUSIONS. Never say what the client should do, launch, change or decide. The facilitator turns evidence into direction; you do not.
- Cite only numbers from the board. If nothing on the board bears on what was just said, return "evidence": [] — silence is a correct answer and a stretched one is not.
- At most 3 evidence items. At most ONE connection, and only if it is genuinely non-obvious: a link between what was said and something from a different register (what people say vs what the industry reports vs what writers argue), or between two board items the room has not put together. If you would have to reach for it, leave "connection" null.
- "look_into" only when the conversation has moved onto ground the board does not cover. It names a NEW search, by category and product. Otherwise null.
- "question" is optional. It must open the room up, not steer it to an answer.
- "touched" lists the numbers of the problems they brought (P1, P2…) that what was just said is about, directly or in substance. [] when none.
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


def parse_touched(obj: Optional[dict], n_problems: int) -> list:
    """The client problems a reading says were just discussed, as 0-based
    indexes. Numbers that do not exist are dropped — same rule as citations."""
    if not isinstance(obj, dict) or n_problems <= 0:
        return []
    out = set()
    for v in obj.get("touched") or []:
        try:
            n = int(str(v).strip().lstrip("Pp"))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= n_problems:
            out.add(n - 1)
    return sorted(out)


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


# ══════════════════════════════════════════════════════════════════════════════
# Memory that outlives a rerun
# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT RUNS app.py AFRESH ON EVERY RERUN, IN A NEW MODULE. A dict kept in a
# global there is a new, empty dict each time — and a background thread that
# finishes later writes its answer into the old module, where nobody looks any
# more. That is how the news race kept starting three fetches at once and
# losing the one that came back. An imported module is loaded once per server
# process, so anything that must survive a rerun is kept here (like JOBS).

SHARED: dict = {}
_SHARED_LOCK = threading.Lock()


def shared(name: str, factory):
    """One object per server process, made by `factory` the first time."""
    with _SHARED_LOCK:
        if name not in SHARED:
            SHARED[name] = factory()
        return SHARED[name]


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
    people_defaults(session)
    lines = session_lines(session)
    ppl = sorted(people_view(session, lines), key=lambda p: -p["words"])
    ppl = [p for p in ppl if p["name"] or p["you"] or p["words"]]
    label = {p["id"]: p["label"] for p in people_view(session, lines)}
    if ppl:
        L.append("## Who was in the room")
        for p in ppl:
            who = p["name"] or p["label"]
            extra = [x for x in (p["role"], "facilitator" if p["you"] else "",
                                 f"{p['pct']}% of the talk" if p["words"] else "") if x]
            L.append(f"- **{who}**" + (" — " + " · ".join(extra) if extra else ""))
        L.append("")
        notes = session.get("people_notes") or {}
        cared = [(p, notes.get(p["id"])) for p in ppl if notes.get(p["id"])]
        if cared:
            L.append("## What each person cared about")
            for p, bullets in cared:
                L.append(f"### {p['name'] or p['label']}")
                L += [f"- {b}" for b in bullets]
                L.append("")
    if c["objective"] or c["problems"]:
        L.append("## What they came with")
        if c["objective"]:
            L.append(c["objective"])
        qa, qb = list(session.get("quest_at") or []), list(session.get("quest_by") or [])
        for i, p in enumerate(c["problems"]):
            by = label.get(qb[i], "") if i < len(qb) and i < len(qa) and qa[i] else ""
            L.append(f"- {p}" + (f" — raised by {by}" if by else ""))
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
    # One paragraph per turn of speech: lines in a row from the same person are
    # joined, with the time they started. Lines nobody was put on read as before.
    prev_w = None
    for l in lines:
        clock = fmt_clock(l.get("t", ""), tz_name)
        if l["note"]:
            L.append(f"{clock} (note) — {l['x']}")
            prev_w = None
        elif l["w"]:
            if prev_w == l["w"]:          # the line above is theirs: same paragraph
                L[-1] += " " + l["x"]
            else:
                L.append(f"{clock} **{label.get(l['w'], '')}:** {l['x']}")
            prev_w = l["w"]
        else:
            L.append(f"{clock} — {l['x']}")
            prev_w = None
    return "\n".join(L).rstrip() + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# The session panel (HUD)
# ══════════════════════════════════════════════════════════════════════════════
# The live room is one full-screen panel drawn by a component in the browser.
# Python owns the state; the panel only sends ACTIONS ("put this on the table",
# "look into that") and draws whatever state it is handed back.
#
# EVERY ACTION IS NUMBERED, AND NOTHING IS LOST OR DONE TWICE. A component has
# one value at a time, and Streamlit may drop a rerun when two arrive close
# together. So the panel keeps an outbox and always sends ALL actions not yet
# acknowledged; Python applies those numbered above the last one it applied,
# records that number, and hands it back so the panel can empty its outbox.
# Same principle as the microphone's batches, for the same reason.

PHASES = ("01 Open", "02 Evidence", "03 Provoke", "04 Converge")

TYPE_LABELS = {"current": "Current", "voice": "Voice", "trade": "Trade",
               "argument": "Argument", "gap": "Opening", "provocation": "Provocation",
               "archive": "From a scan"}


def hud_defaults(session: dict) -> dict:
    """Session logs written before the panel existed lack its fields."""
    session.setdefault("table", None)
    session.setdefault("table_hist", [])
    session.setdefault("queue", [])
    session.setdefault("phase", 0)
    session.setdefault("quest_at", [])
    session.setdefault("auto", True)
    session.setdefault("hud_ack", -1)
    # Logs from before the opening existed were live from their first second.
    session.setdefault("went_live", session.get("started_at") if (session.get("chunks") or session.get("insights")) else None)
    people_defaults(session)
    return session


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def put_on_table(session: dict, q: str, src: str = "", when: Optional[str] = None) -> bool:
    q = _clip(q, 300)
    if not q:
        return False
    when = when or _now_iso()
    session["table"] = {"q": q, "src": _clip(src, 80), "t": when}
    hist = session.setdefault("table_hist", [])
    if not hist or hist[-1].get("q") != q:
        hist.append({"q": q, "src": _clip(src, 80), "t": when})
    session["queue"] = [x for x in session.get("queue") or [] if x != q]
    return True


def touch_problem(session: dict, i: int, on: bool = True, when: Optional[str] = None,
                  n_problems: int = 0, by: Optional[str] = None, text: str = "") -> bool:
    """Mark a client problem as discussed (or undo it). Keeps the FIRST time —
    and, given the problem's words, who said them (see raised_by)."""
    try:
        i = int(i)
    except (TypeError, ValueError):
        return False
    n = max(n_problems, i + 1)
    if i < 0 or (n_problems and i >= n_problems):
        return False
    q = list(session.get("quest_at") or [])
    q += [None] * (n - len(q))
    qb = list(session.get("quest_by") or [])
    qb += [""] * (n - len(qb))
    if on:
        if q[i]:
            return False
        q[i] = when or _now_iso()
        qb[i] = by if by is not None else (raised_by(session, text) if text else "")
    else:
        if not q[i]:
            return False
        q[i] = None
        qb[i] = ""
    session["quest_at"] = q
    session["quest_by"] = qb
    return True


def hud_apply(session: dict, value, n_problems: int = 0,
              now: Optional[str] = None, problems: Optional[list] = None) -> list:
    """Apply the panel's pending actions, once each, in order.

    Returns the EFFECTS the app must carry out — the ones that need the model,
    a scan or a page change: ("read",) ("ask", text) ("note", text)
    ("look", category, product, reason) ("end",) ("setup",) ("golive",)
    ("people",) when names changed and the log should be saved now,
    ("chart_raw", key, line index, points, scope) when the panel fetched a news line itself.
    Everything that is only state is done here — including who is who:
    tap {who, at} · person_add {at, tap, assign_n} · name {id, name, role} ·
    merge {id, into} · you {id} · person_del {id} · assign {n, who} · intro {on, at}.
    """
    hud_defaults(session)
    msgs = (value or {}).get("msgs") if isinstance(value, dict) else None
    if not isinstance(msgs, list):
        return []
    ack = int(session.get("hud_ack", -1))
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
    for s, m in sorted(fresh, key=lambda x: x[0]):
        t = str(m.get("type") or "")
        when = now or _now_iso()
        if t == "table":
            put_on_table(session, m.get("q"), m.get("src") or "Put on the table", when)
        elif t == "queue":
            q = _clip(m.get("q"), 300)
            if q and q not in session["queue"] and (session.get("table") or {}).get("q") != q:
                session["queue"] = (session["queue"] + [q])[-8:]
        elif t == "unqueue":
            q = _clip(m.get("q"), 300)
            session["queue"] = [x for x in session["queue"] if x != q]
        elif t == "next":
            if session["queue"]:
                put_on_table(session, session["queue"][0], "From the queue", when)
        elif t == "phase":
            try:
                p = int(m.get("i"))
            except (TypeError, ValueError):
                p = -1
            if 0 <= p < len(PHASES):
                session["phase"] = p
        elif t == "quest":
            try:
                txt = (problems or [])[int(m.get("i"))] if 0 <= int(m.get("i")) < len(problems or []) else ""
            except (TypeError, ValueError):
                txt = ""
            touch_problem(session, m.get("i"), bool(m.get("on", True)), when, n_problems, text=txt)
        elif t == "auto":
            session["auto"] = bool(m.get("on"))
        elif t == "golive":
            # THE SESSION STARTS WHEN THE ROOM GOES LIVE, not when the opening
            # went up on the screen: the clock and the log's start move to now —
            # unless something was already said or read, which would then sit
            # before the start of its own session.
            if not session.get("went_live"):
                session["went_live"] = when
                if not session.get("chunks") and not session.get("insights"):
                    session["started_at"] = when
                effects.append(("golive",))
        elif t in ("read", "end", "setup"):
            effects.append((t,))
        elif t in ("ask", "note"):
            txt = str(m.get("text") or "").strip()[:600]
            if txt:
                effects.append((t, txt))
        elif t == "look":
            cat, prod = _clip(m.get("category"), 60), _clip(m.get("product"), 60)
            if cat or prod:
                effects.append(("look", cat, prod, _clip(m.get("reason"), 160)))
        # ── who is who ──
        elif t == "tap":
            add_tap(session, m.get("at"), m.get("who"))
        elif t == "person_add":
            p = new_person(session, "tap")
            if p and m.get("tap"):
                add_tap(session, m.get("at"), p["id"])
            if p and m.get("assign_n") is not None:
                assign_line(session, m.get("assign_n"), p["id"])
            if p and ("people",) not in effects:
                effects.append(("people",))
        elif t == "chart_raw":
            # One news line fetched by the panel itself, in the browser; the
            # app checks every point before keeping it.
            try:
                i = int(m.get("i"))
            except (TypeError, ValueError):
                i = -1
            if i >= 0 and isinstance(m.get("line"), list):
                effects.append(("chart_raw", str(m.get("key") or "")[:600], i, m.get("line"),
                                str(m.get("scope") or "")[:12]))
        elif t == "assign":
            if assign_line(session, m.get("n"), m.get("who")) and ("people",) not in effects:
                effects.append(("people",))
        elif t in ("name", "merge", "you", "person_del"):
            pid = str(m.get("id") or "")
            done = (name_person(session, pid, m.get("name"), m.get("role")) if t == "name"
                    else merge_people(session, pid, str(m.get("into") or "")) if t == "merge"
                    else set_you(session, pid) if t == "you"
                    else remove_person(session, pid))
            if done and ("people",) not in effects:
                effects.append(("people",))
        elif t == "intro":
            on, at = bool(m.get("on")), _ms(m.get("at")) or int(time.time() * 1000)
            wins = session["intro_win"]
            if on and not session.get("intro_on"):
                session["intro_on"] = True
                wins.append([at, None])
                effects.append(("intro", True))
            elif not on and session.get("intro_on"):
                session["intro_on"] = False
                if wins and isinstance(wins[-1], list) and len(wins[-1]) == 2 and wins[-1][1] is None:
                    wins[-1][1] = max(at, _ms(wins[-1][0]) or at)
                effects.append(("intro", False))
        session["hud_ack"] = s
    return effects


def _norm_phrase(s: str) -> str:
    s = str(s or "").lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"^[\W_]+|[\W_]+$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def cliche_counts(chunks: list, phrases: list) -> list:
    """How many times each off-the-table phrase was said in the room.

    Whole words only ("indulgent" does not count inside "indulgently"), case
    and punctuation ignored, hyphen and space interchangeable ("purpose-driven"
    and "purpose driven" are the same slip), "&" read as "and"."""
    text = " " + " ".join(str(c.get("text", "")).lower().replace("&", " and ").replace("’", "'")
                          for c in (chunks or [])) + " "
    out = []
    for p in phrases or []:
        w = _norm_phrase(p)
        if not w:
            out.append(0)
            continue
        parts = [re.escape(x) for x in re.split(r"[\s-]+", w) if x]
        pat = r"(?<![\w'-])" + r"[\s-]+".join(parts) + r"(?![\w-])"
        out.append(len(re.findall(pat, text)))
    return out


def _elapsed(start_iso: str, now_iso: str) -> int:
    a, b = _parse_iso(start_iso), _parse_iso(now_iso)
    return max(0, int((b - a).total_seconds())) if a and b else 0


def hud_state(session: dict, client: dict, brief: Optional[dict] = None,
              now: Optional[str] = None, tz_name: str = "", reading_now: bool = False,
              scan_paused: bool = False, report_url=None, scan_eta: int = 210,
              chart: Optional[dict] = None, intro_pending=()) -> dict:
    """Everything the panel draws, as one JSON-ready dict.

    `brief` carries the tiles that come from the latest brief for the client —
    currents (with ages and heat), voices, tensions, starters, clichés — built
    by the app, because finding that brief needs the archive. `intro_pending`
    are the people whose introduction the model is reading right now."""
    hud_defaults(session)
    now = now or _now_iso()
    c = normalise_client(client or {})
    clk = lambda iso: fmt_clock(iso, tz_name)
    chunks = session.get("chunks") or []
    upto = int(session.get("read_upto", 0))
    all_lines = session_lines(session)
    lines = [{"t": clk(l["t"]), "x": l["x"], "note": l["note"], "unread": l["n"] >= upto,
              "w": l["w"], "intro": bool(l.get("intro")), "n": l["n"]} for l in all_lines[-40:]]
    now_who = ""
    for l in reversed(all_lines[-6:]):
        if l["note"]:
            continue
        if l["w"] and _elapsed(l["t"], now) <= NOW_SECONDS:
            now_who = l["w"]
        break
    taps = _tap_index(session)[1]
    readings = []
    for i in (session.get("insights") or [])[-8:]:
        lk = i.get("look_into") or None
        readings.append({
            "t": clk(i.get("t", "")), "asked": i.get("asked", ""), "heard": i.get("heard", ""),
            "ev": [{"ti": e.get("title", ""), "ty": TYPE_LABELS.get(str(e.get("type", "")),
                                                                   str(e.get("type", ""))[:18]),
                    "url": e.get("url", ""), "why": e.get("why", "")} for e in i.get("evidence") or []],
            "conn": (i.get("connection") or {}).get("text", ""),
            "ask": i.get("question", ""),
            "look": ({"w": " · ".join(p for p in (lk.get("category"), lk.get("product")) if p),
                      "cat": lk.get("category", ""), "prod": lk.get("product", ""),
                      "r": lk.get("reason", "")} if lk else None)})
    q_at = list(session.get("quest_at") or [])
    quest = [{"t": p, "at": clk(q_at[n]) if n < len(q_at) and q_at[n] else ""}
             for n, p in enumerate(c["problems"])]
    scans = []
    for s in session.get("scans") or []:
        el = _elapsed(s.get("started_at", ""), now)
        sm = s.get("summary") or {}
        scans.append({"id": s.get("id", ""), "w": s.get("label", ""), "status": s.get("status", ""),
                      "el": el, "pct": min(97, int(100 * el / max(1, scan_eta))),
                      "end": clk(s.get("finished_at", "")), "cur": sm.get("currents") or [],
                      "ten": sm.get("tension", ""), "gap": sm.get("opening", ""),
                      "url": report_url(s["report_id"]) if (report_url and s.get("report_id")) else "",
                      "err": s.get("error", "")})
    b = brief or {}
    cl = b.get("cliches") or []
    counts = cliche_counts(chunks, [x.get("w", "") for x in cl])
    table = session.get("table") or {}
    ear_note = ""
    if session.get("_ear_error"):
        ear_note = "error"
    elif session.get("_quiet_at"):
        ear_note = "quiet"
    return {
        "v": 1, "ack": int(session.get("hud_ack", -1)),
        "client": {"name": c["name"] or c["brand"] or session.get("client_name", ""),
                   "meta": " · ".join(p for p in (c["category"], c["product"], c["market"]) if p),
                   "cat": c["category"], "prod": c["product"]},
        "elapsed": _elapsed(session.get("started_at", ""), now), "status": session.get("status", ""),
        "phase": int(session.get("phase", 0)), "phases": list(PHASES),
        "table": ({"q": table.get("q", ""), "src": table.get("src", ""), "t": clk(table.get("t", ""))}
                  if table.get("q") else None),
        "hist": [{"q": h.get("q", ""), "src": h.get("src", ""), "t": clk(h.get("t", ""))}
                 for h in (session.get("table_hist") or [])[-12:]],
        "queue": list(session.get("queue") or [])[:8],
        "lines": lines, "n_lines": len(all_lines), "words": word_count(session),
        "people": people_view(session, all_lines, pending=set(intro_pending or ())),
        "voice_mode": session.get("voice_mode") or "",
        "tap_who": taps[-1] if taps else "", "now_who": now_who,
        "intro": {"on": bool(session.get("intro_on")), "n": len(session.get("intro_win") or [])},
        "readings": readings, "reading_now": bool(reading_now), "auto": bool(session.get("auto", True)),
        "ear_note": ear_note, "ear_err": str(session.get("_ear_error") or "")[:160],
        "quiet_at": clk(session.get("_quiet_at", "")) if session.get("_quiet_at") else "",
        "quest": quest, "scans": scans, "scan_paused": bool(scan_paused),
        "currents": b.get("currents") or [], "voices": b.get("voices") or [],
        "tensions": b.get("tensions") or [], "starters": b.get("starters") or [],
        "cliches": [dict(x, n=counts[i]) for i, x in enumerate(cl)],
        "brief_label": b.get("label", ""), "brief_url": b.get("url", ""),
        "objective": c.get("objective", ""),
        "went_live": bool(session.get("went_live")),
        "chart": chart if isinstance(chart, dict) and chart.get("status") else {"status": "none"},
        "stats": {"readings": len(session.get("insights") or []),
                  "evidence": sum(len(i.get("evidence") or []) for i in session.get("insights") or []),
                  "searches": len(session.get("scans") or []), "words": word_count(session)},
        "tz": tz_name,
    }


# ══════════════════════════════════════════════════════════════════════════════
# The race chart — news attention per current, day by day
# ══════════════════════════════════════════════════════════════════════════════
# The lines come from GDELT (see ingestion.gdelt_timeline): how many articles a
# day matched each current, as a seven-day average, over three months. The
# panel draws them; the arithmetic lives here too so it can be tested, and so
# the app knows which current rose before asking GDELT what drove its spike.

CHART_DAYS = 90
QUIET_TOTAL = 30.0      # articles across all currents and days below which there is no chart


def chart_analysis(values: list) -> dict:
    """Who leads, when they took the lead, who rose, who fell.

    leader      the current with the largest share of the three on the last day
    took_lead   the day index its current lead began (None if it led throughout)
    change30    average daily articles, last 30 days against the 30 before, -1..+inf
    riser       the current with the largest change30, if it is at least +20%
    peaks       per current, its highest day in the last 60 and the fall since
    faller      of the others, the one furthest below its peak, if 25% or more
    """
    empty = {"leader": -1, "took_lead": None, "riser": -1, "faller": -1, "change30": [], "peaks": []}
    if not values or any(not isinstance(v, list) for v in values):
        return empty
    n = min(len(v) for v in values)
    if n < 2:
        return empty
    shares = []
    for i in range(n):
        tot = sum(float(v[i]) for v in values)
        shares.append([100.0 * float(v[i]) / tot if tot > 0 else 0.0 for v in values])
    lead = [max(range(len(r)), key=lambda k: r[k]) for r in shares]
    leader, took = lead[-1], None
    for i in range(n - 1, 0, -1):
        if lead[i - 1] != leader:
            took = i
            break

    def mean(a):
        return sum(a) / len(a) if a else 0.0
    change = []
    for v in values:
        now, before = mean(v[n - 30:n]), mean(v[max(0, n - 60):max(0, n - 30)])
        change.append(now / before - 1 if before > 0 else 0.0)
    riser = -1
    for k, c in enumerate(change):
        if c >= 0.2 and (riser < 0 or c > change[riser]):
            riser = k
    peaks = []
    for v in values:
        b = max(0, n - 60)
        for j in range(b, n):
            if v[j] > v[b]:
                b = j
        peaks.append({"i": b, "v": float(v[b]),
                      "drop": (float(v[n - 1]) / float(v[b]) - 1) if v[b] > 0 else 0.0})
    faller = -1
    for k, p in enumerate(peaks):
        if k != riser and p["drop"] <= -0.25 and (faller < 0 or p["drop"] < peaks[faller]["drop"]):
            faller = k
    return {"leader": leader, "took_lead": took, "riser": riser, "faller": faller,
            "change30": [round(c, 4) for c in change], "peaks": peaks}


def chart_partial(series: list, titles: list, scans: Optional[list] = None,
                  queries: Optional[list] = None, scope: str = "", days: int = CHART_DAYS) -> dict:
    """The race with the lines GDELT did return, when at least two did.

    A missing line is LEFT OUT, never drawn as zero: the race becomes one
    between the currents that have news lines, and says which one is missing
    (`missing`). `cur_idx` maps each drawn line back to its current, so the
    panel puts the right summary, heat and scan dots on it."""
    have = [i for i, s in enumerate(series or []) if s is not None]
    if len(have) < 2 or len(have) == len(series or []):
        return chart_payload(series, titles, scans=scans, queries=queries, scope=scope, days=days)
    pos = {old: new for new, old in enumerate(have)}
    sc_ = [{"date": x.get("date", ""), "seen": [pos[int(k)] for k in (x.get("seen") or [])
                                               if str(k).lstrip("-").isdigit() and int(k) in pos]}
           for x in (scans or [])]
    out = chart_payload([series[i] for i in have], [titles[i] if i < len(titles) else "" for i in have],
                        scans=sc_, queries=[(queries or [])[i] if i < len(queries or []) else "" for i in have],
                        scope=scope, days=days)
    out["cur_idx"] = have
    out["missing"] = [titles[i] for i in range(len(series)) if i not in pos and i < len(titles)]
    return out


def _fill_holes(row: list) -> list:
    """None runs filled on the straight line between the known days around them
    (held flat at either end, where there is only one side)."""
    out = list(row)
    known = [i for i, x in enumerate(out) if x is not None]
    if not known:
        return [0.0] * len(out)
    for i in range(len(out)):
        if out[i] is not None:
            continue
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k > i), default=None)
        if left is None:
            out[i] = out[right]
        elif right is None:
            out[i] = out[left]
        else:
            out[i] = out[left] + (out[right] - out[left]) * (i - left) / (right - left)
    return out


def chart_payload(series: list, titles: list, scans: Optional[list] = None,
                  queries: Optional[list] = None, scope: str = "", days: int = CHART_DAYS) -> dict:
    """GDELT's timelines, put on one daily axis and judged.

    `series` holds one [(YYYY-MM-DD, articles)] list per current, or None where
    GDELT failed. A failed line is not drawn as zero — that would show silence
    where there was an error — so any failure fails the chart. Too little news
    across all three is "quiet": the panel says so instead of drawing noise.
    `scans` are our own: [{"date", "seen": [current indexes]}], drawn as dots."""
    titles = [str(t or "") for t in (titles or [])]
    base = {"titles": titles, "queries": list(queries or []), "scope": scope}
    if not series or any(s is None for s in series):
        return dict(base, status="failed")
    have = [{str(d)[:10]: max(0.0, float(v or 0)) for d, v in s if d} for s in series]
    dates = sorted({d for m in have for d in m})
    if not dates:
        return dict(base, status="quiet", total=0)
    try:
        end = datetime.strptime(dates[-1], "%Y-%m-%d")
        first = max(datetime.strptime(dates[0], "%Y-%m-%d"), end - timedelta(days=days - 1))
    except ValueError:
        return dict(base, status="failed")
    # THE AXIS IS WHAT GDELT ACTUALLY COVERS, not a calendar. Its archive has
    # holes — whole days with nothing at all, when it was down. A hole is not
    # silence: drawn as zero it would show every current crashing on the same
    # day. A day no line has is filled in between its neighbours; a day only
    # some lines have is a real zero for the others; and the axis starts on
    # GDELT's first day rather than padding the front with zeros.
    axis = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end - first).days + 1)]
    known = set(dates)
    values = []
    for m in have:
        row = [m.get(d, 0.0) if d in known else None for d in axis]
        values.append([round(x, 2) for x in _fill_holes(row)])
    total = sum(sum(v) for v in values)
    out = dict(base, dates=axis, values=values, total=round(total),
               holes=sum(1 for d in axis if d not in known))
    if total < QUIET_TOTAL or len(axis) < 14:
        out["status"] = "quiet"
        return out
    an = chart_analysis(values)
    out.update(status="ok", leader=an["leader"], took_lead=an["took_lead"], riser=an["riser"],
               faller=an["faller"])
    out["scans"] = [{"date": str(x.get("date", ""))[:10],
                     "seen": sorted({int(k) for k in (x.get("seen") or [])
                                     if str(k).lstrip("-").isdigit() and 0 <= int(k) < len(values)})}
                    for x in (scans or []) if axis[0] <= str(x.get("date", ""))[:10] <= axis[-1]]
    if an["riser"] >= 0:
        pk = an["peaks"][an["riser"]]["i"]
        out["spike"] = {"i": pk, "date": axis[pk], "from": axis[max(0, pk - 6)]}
    return out

