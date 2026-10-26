"""Asking the Lighthouse something specific.

Three pieces, all from Pat's notes of Oct 23 and the Refine prototype approved
before that:

  THE PROMPT BAR   one sentence ("Puma basketball shoes in the US, last six
                   months, against Nike and Adidas — how are women hoopers
                   reacting?") becomes the scan's settings, which the strategist
                   then reviews before running.
  MUST MENTION     the words every signal has to carry to be about this brief.
                   The Puma brief showed why: with "sneakers" as the product,
                   a Myntra ad and a kids' cartoon got in. "basketball" keeps
                   them out.
  THE QUESTION     one specific thing to read the networks for. It becomes two
                   or three extra searches (same budget), the model POINTS at
                   the posts that answer it and which way each one leans, and
                   every number in the answer is counted here, from those posts
                   — never estimated by the model.

Pure Python: no Streamlit, no network. Tested on its own (tests/trefine.py).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Optional

_W = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""the and for with from that this your our their about into over under than
then what when where which who why how are was were will would could should can may might
all any some more most less very just also only even still new best top get got its it's
people posts post brand brands product products category market""".split())


# ══════════════════════════════════════════════════════════════════════════════
# MUST MENTION
# ══════════════════════════════════════════════════════════════════════════════
def _stem(w: str) -> str:
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


def focus_items(text: str) -> list:
    """'basketball, women's hoops' → [['basketball'], ['women', 'hoops']].

    Commas (or 'or') separate alternatives; the words inside one alternative
    must ALL appear. Short words and filler are dropped."""
    out = []
    for part in re.split(r"[,;\n/]+|\s+or\s+", text or "", flags=re.I):
        part = part.lower().replace("’", "'").replace("'s", "")
        words = [w for w in _W.findall(part) if len(w) >= 3 and w not in _STOP]
        if words and words not in out:
            out.append(words)
    return out[:8]


def focus_text(items: list) -> str:
    return ", ".join(" ".join(w) for w in items or [])


def focus_hit(text: str, items: list) -> bool:
    """Does the text carry the focus? Plural-insensitive; a long word also
    counts inside a hashtag (#basketballshoes carries 'basketball')."""
    if not items:
        return True
    low = (text or "").lower()
    have = {_stem(w) for w in _W.findall(low)}
    for words in items:
        if all(_stem(w) in have or (len(w) >= 5 and w in low) for w in words):
            return True
    return False


def with_focus(query: str, items: list) -> str:
    """A search query that carries the focus — prefixed when it does not."""
    q = (query or "").strip()
    if not items or focus_hit(q, items):
        return q
    return f"{' '.join(items[0])} {q}".strip()


# ══════════════════════════════════════════════════════════════════════════════
# THE PROMPT BAR
# ══════════════════════════════════════════════════════════════════════════════
def setup_prompt(text: str, markets: list, windows: list, today: str = "") -> str:
    today = today or datetime.now(timezone.utc).strftime("%d %B %Y").lstrip("0")
    mk = ", ".join(f'"{m}"' for m in markets)
    wn = ", ".join(str(w) for w in windows)
    return f"""Turn this request into the settings of a Lighthouse scan. Today is {today}.

REQUEST: \"\"\"{(text or '')[:700]}\"\"\"

Answer ONLY with JSON:
{{"brand": "", "category": "", "product": "", "market": "", "window_months": null, "competitors": "", "focus": "", "question": ""}}

brand: the brand the brief is for, as written ("Puma"). Empty if the request names none.
category: the category it competes in, 1 to 3 words ("Basketball footwear").
product: the specific product, 1 to 3 words ("Basketball shoes").
market: exactly one of {mk}, or "" if the request does not say.
window_months: one of {wn} when the request gives a period ("last 6 months" is 6, "this year" is 12, "the past two years" is 24), otherwise null.
competitors: the competitors the request names, comma-separated. If it names none, the 3 or 4 obvious ones for this category in this market.
focus: the words every post must mention to be about this — usually the sport, occasion or audience that the product word alone does not carry ("basketball" when the product is sneakers). Comma-separated alternatives. Empty when the product already says it.
question: the one specific question the request asks of the networks ("How are women hoopers reacting to Puma's signature line?"). Empty if the request only names the subject.
Never invent a brand. Keep the user's own words where you can."""


def clean_setup(obj: dict, markets: list, windows: list) -> dict:
    """The model's answer, made safe to drop into the form: trimmed, the market
    one we have, the window one we offer, the focus in our own format."""
    obj = obj if isinstance(obj, dict) else {}

    def s(k: str, n: int) -> str:
        return re.sub(r"\s+", " ", str(obj.get(k) or "")).strip().strip('"')[:n]

    m = s("market", 40).lower()
    try:
        w = int(obj.get("window_months") or 0)
    except (TypeError, ValueError):
        w = 0
    comps = list(dict.fromkeys(c.strip() for c in re.split(r"[,;]", s("competitors", 240))
                               if c.strip()))
    return {
        "brand": s("brand", 60),
        "category": s("category", 60),
        "product": s("product", 60),
        "market": next((k for k in markets if k.lower() == m), ""),
        "window": w if w in windows else 0,
        "competitors": ", ".join(comps[:8]),
        "focus": focus_text(focus_items(s("focus", 160))),
        "question": s("question", 220),
    }


# ══════════════════════════════════════════════════════════════════════════════
# THE QUESTION
# ══════════════════════════════════════════════════════════════════════════════
def try_chips(brand: str = "", product: str = "", rival: str = "") -> list:
    """The "Try" row under the question field: (label, a question to start from)."""
    b = (brand or "").strip() or "the brand"
    p = (product or "").strip().lower() or "the product"
    r = (rival or "").strip() or "the main rival"
    return [("A launch", f"How are people reacting to {b}'s latest launch?"),
            ("A rival's move", f"What do people make of {r}'s latest move?"),
            ("A price change", f"Are people pushing back on what {p} costs now?"),
            ("One audience", f"What does Gen Z think of {b}?"),
            ("A claim", f"Do people believe what {b} says about its {p}?")]


def queries_prompt(question: str, brand: str, category: str, product: str,
                   market: str = "") -> str:
    where = f" in {market}" if market and market != "Worldwide" else ""
    return f"""A strategist wants the social networks read for ONE question about {brand or 'the brand'} ({category}, {product}){where}:
"{(question or '')[:240]}"

Write 2 or 3 short searches that would find posts answering it: the words people actually post, or a hashtag if one is obvious. Each one 2 to 6 words, and each one keeps the brand or the product in it.

Answer ONLY with JSON: {{"queries": ["...", "..."]}}"""


def clean_queries(obj: dict, limit: int = 3) -> list:
    out = []
    for q in ((obj or {}).get("queries") or []) if isinstance(obj, dict) else []:
        q = re.sub(r"\s+", " ", str(q)).strip().strip('"').strip()[:60]
        if len(q) >= 3 and q.lower() not in (x.lower() for x in out):
            out.append(q)
    return out[:limit]


LEANS = ("for", "mixed", "against")
MIN_POSTS = 6          # below this we count, but call neither side nor direction
STRONG, SOME = 0.15, 0.05


def _when(v):
    try:
        import sources as _s            # the same date reader as the window
        return _s.parse_when(v)
    except Exception:
        return None


def question_stats(batch: list, touched: list, label: Optional[Callable] = None,
                   min_posts: int = MIN_POSTS) -> dict:
    """Every number in the answer, counted from the posts the model pointed at.

    `batch` is the list of signals the model was shown, in order — the indexes
    in `touched` refer to it. Returns the share of the conversation, where it is
    said, how it leans, whether it is growing, and how strong the signal is."""
    label = label or (lambda s: str((s or {}).get("source", "") or "other"))
    total = len(batch or [])
    seen: dict = {}
    for t in touched or []:
        if not isinstance(t, dict):
            continue
        try:
            i = int(t.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < total and i not in seen:
            lean = str(t.get("lean") or "").strip().lower()
            seen[i] = lean if lean in LEANS else "mixed"
    n = len(seen)
    share = (n / total) if total else 0.0
    nets = Counter(label(batch[i]) for i in seen)
    leans = {l: sum(1 for v in seen.values() if v == l) for l in LEANS}
    # DIRECTION: the share of posts touching the question in the older half of
    # the collection against the newer half. Shares, not totals — networks that
    # only return recent posts would otherwise invent a rise.
    dated = sorted(((d, i) for i, s in enumerate(batch or [])
                    for d in [_when((s or {}).get("timestamp"))] if d), key=lambda x: x[0])
    s_old = s_new = None
    # A direction needs time to happen in: posts that all come from the same
    # fortnight cannot rise or fade, they can only be split in two.
    if len(dated) >= 8 and (dated[-1][0] - dated[0][0]).days >= 14:
        half = len(dated) // 2
        old, new = [i for _, i in dated[:half]], [i for _, i in dated[half:]]
        s_old = sum(1 for i in old if i in seen) / len(old)
        s_new = sum(1 for i in new if i in seen) / len(new)
    enough = n >= min_posts
    direction = ""
    if enough and s_old is not None:
        if s_old == 0:
            direction = "rising" if s_new > 0 else "steady"
        elif s_new >= 1.5 * s_old:
            direction = "rising"
        elif s_new <= s_old * 2 / 3:
            direction = "fading"
        else:
            direction = "steady"
    strength = ("too few" if not enough else
                "strong" if share >= STRONG else "some" if share >= SOME else "almost nothing")
    return {"n": n, "total": total, "share": round(share, 4),
            "nets": nets.most_common(), "leans": leans, "enough": enough,
            "strength": strength, "direction": direction,
            "share_old": None if s_old is None else round(s_old, 4),
            "share_new": None if s_new is None else round(s_new, 4),
            "touched": [{"i": i, "lean": l} for i, l in seen.items()]}


def pct(x: float) -> str:
    return f"{round((x or 0) * 100)}%"


def direction_line(st: dict) -> str:
    """One sentence on the direction, in the prototype's words."""
    d, a, b = st.get("direction"), st.get("share_old"), st.get("share_new")
    if not d or a is None or b is None:
        return ""
    if d == "rising":
        verb = "doubled" if a and b >= 2 * a else "grew"
        return (f"▲ Its share of the posts {verb} from the older half of the window to "
                f"the newer — {pct(a)} → {pct(b)}.")
    if d == "fading":
        return (f"▼ Its share of the posts fell from the older half of the window to the "
                f"newer — {pct(a)} → {pct(b)}.")
    return (f"■ Its share of the posts held steady across the window — "
            f"{pct(a)} → {pct(b)}.")
