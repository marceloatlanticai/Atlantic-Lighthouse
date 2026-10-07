"""
db.py — Persistence layer for The Lighthouse.

Priority: Supabase (PostgreSQL) when SUPABASE_URL + SUPABASE_KEY are set
          in .streamlit/secrets.toml or environment variables.
Fallback: JSON/JSONL files in data/ (for local dev without Supabase).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

# ── Supabase client (lazy singleton) ──────────────────────────────────────────

_supabase_client = None
_supabase_checked = False


def _get_sb():
    """Return Supabase client, or None if not configured."""
    global _supabase_client, _supabase_checked
    if _supabase_checked:
        return _supabase_client
    _supabase_checked = True

    url = ""
    key = ""
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_KEY", "")
    except Exception:
        pass
    if not url:
        url = os.environ.get("SUPABASE_URL", "")
    if not key:
        key = os.environ.get("SUPABASE_KEY", "")

    if not url or not key:
        return None

    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
    except Exception as exc:
        print(f"[db] Supabase init failed: {exc}")
        _supabase_client = None

    return _supabase_client


def use_supabase() -> bool:
    """True when a Supabase client is available."""
    return _get_sb() is not None


# ── File paths (fallback) ─────────────────────────────────────────────────────

_SIGNALS_FILE     = "data/signals.jsonl"
_DISPATCHES_FILE  = "data/dispatches.jsonl"
_CURADORIA_FILE   = "data/curadoria.json"
_FOLDERS_FILE     = "data/project_folders.json"
_ACCOUNTS_FILE    = "data/client_access.json"
_OVERRIDES_FILE   = "data/countercurrent_overrides.json"


def _mkdir():
    os.makedirs("data", exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def load_signals(limit: int = 200) -> list:
    """Return up to `limit` signals, newest first."""
    sb = _get_sb()
    if sb:
        try:
            res = (
                sb.table("signals")
                .select("*")
                .order("timestamp", desc=True)
                .limit(limit)
                .execute()
            )
            signals = []
            for row in res.data:
                # Reconstruct original dict from extra + top-level columns
                sig = row.get("extra") or {}
                # Ensure indexed fields are present (they may differ from extra)
                for k in ("timestamp", "title", "content", "source", "url"):
                    if row.get(k):
                        sig[k] = row[k]
                # Hoist thumbnail from raw_meta so s.get("thumbnail") works everywhere
                if not sig.get("thumbnail"):
                    sig["thumbnail"] = (sig.get("raw_meta") or {}).get("thumbnail", "")
                signals.append(sig)
            return signals
        except Exception as exc:
            print(f"[db] load_signals Supabase error: {exc}")

    # ── file fallback ──
    if not os.path.exists(_SIGNALS_FILE):
        return []
    signals = []
    with open(_SIGNALS_FILE) as f:
        for line in f:
            try:
                signals.append(json.loads(line))
            except Exception:
                pass
    signals.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return signals[:limit]


def save_signal(signal: dict):
    """Append a single signal."""
    sb = _get_sb()
    if sb:
        try:
            sb.table("signals").insert({
                "timestamp": signal.get("timestamp", datetime.utcnow().isoformat()),
                "title":     signal.get("title", ""),
                "content":   signal.get("content", ""),
                "source":    signal.get("source", ""),
                "url":       signal.get("url", ""),
                "tags":      signal.get("tags", []),
                "extra":     signal,
            }).execute()
            return
        except Exception as exc:
            print(f"[db] save_signal Supabase error: {exc}")

    # ── file fallback ──
    _mkdir()
    with open(_SIGNALS_FILE, "a") as f:
        f.write(json.dumps(signal, ensure_ascii=False) + "\n")


def bulk_save_signals(signals: list):
    """Insert many signals at once (more efficient than looping save_signal)."""
    if not signals:
        return
    sb = _get_sb()
    if sb:
        try:
            rows = [{
                "timestamp": s.get("timestamp", datetime.utcnow().isoformat()),
                "title":     s.get("title", ""),
                "content":   s.get("content", ""),
                "source":    s.get("source", ""),
                "url":       s.get("url", ""),
                "tags":      s.get("tags", []),
                "extra":     s,
            } for s in signals]
            # Batch in chunks of 500 (Supabase limit)
            for i in range(0, len(rows), 500):
                sb.table("signals").insert(rows[i:i+500]).execute()
            return
        except Exception as exc:
            print(f"[db] bulk_save_signals Supabase error: {exc}")

    # ── file fallback ──
    _mkdir()
    with open(_SIGNALS_FILE, "a") as f:
        for s in signals:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHES
# ══════════════════════════════════════════════════════════════════════════════

# ── The archive read, memoised ───────────────────────────────────────────────
# THIS FUNCTION IS CALLED FOUR TIMES PER PAGE RENDER, and each call downloaded
# every dispatch ever saved, in full.
#
# It was tolerable while a brief stored 80 signals. Raising that to 240 — so the
# shared link would show the same posts as the PDF — tripled the payload of
# every one of those four downloads at once, and the page got noticeably slower
# on EVERY render, not only on a scan. The fix for one problem paid for itself
# with another, which is the second time that has happened this week.
#
# A plain time-based memo rather than @st.cache_data: cached Streamlit functions
# have no script context inside a worker thread and blow up there, a trap this
# codebase has now been bitten by three times. This one is just a dict and a
# lock, so it is safe from anywhere.
_DISPATCH_CACHE: dict = {"at": 0.0, "rows": None}
_DISPATCH_TTL = 45.0          # seconds
_DISPATCH_LOCK = threading.Lock()


def invalidate_dispatch_cache() -> None:
    """Drop the memo — call right after saving, so a new brief appears at once."""
    with _DISPATCH_LOCK:
        _DISPATCH_CACHE["rows"] = None
        _DISPATCH_CACHE["at"] = 0.0


def load_all_dispatches(limit: int = 150) -> list:
    """Load dispatches, newest first. Memoised for a few seconds.

    Client profiles and session logs share this table (see upsert_record) but
    are NOT dispatches, and they are filtered out here so no older caller ever
    meets one. That is not hypothetical: the per-client Dispatch loader returns
    the newest row without an _overview flag and assumes "Heinz" when no client
    is set — a fresh session log would have been served as Heinz's current
    Dispatch. Records are read through load_records / load_record instead.
    """
    import time as _time
    with _DISPATCH_LOCK:
        _rows = _DISPATCH_CACHE["rows"]
        if _rows is not None and (_time.time() - _DISPATCH_CACHE["at"]) < _DISPATCH_TTL:
            return _rows
    rows = [r for r in _load_all_dispatches_uncached(limit)
            if not (r.get("full") or {}).get("_record")]
    with _DISPATCH_LOCK:
        _DISPATCH_CACHE["rows"] = rows
        _DISPATCH_CACHE["at"] = _time.time()
    return rows


def _load_all_dispatches_uncached(limit: int = 150) -> list:
    """Load all dispatches, newest first."""
    sb = _get_sb()
    if sb:
        try:
            def _query(skip_records: bool):
                q = sb.table("dispatches").select("*")
                if skip_records:
                    # Client profiles and session logs live in this table too,
                    # and a session log carries its whole transcript. Left in,
                    # every Archive load would download every meeting ever
                    # transcribed, only to throw them away. The NULL branch
                    # keeps any old row written without a topic.
                    q = q.or_("topic.is.null,topic.not.in.(__client__,__session__)")
                # There was no limit at all. The Archive shows 40 and nothing
                # else reads further back, so every row beyond this was being
                # downloaded and parsed for nobody.
                return q.order("timestamp", desc=True).limit(limit).execute()
            try:
                res = _query(True)
            except Exception as _fexc:
                # The filter is an optimisation, never a reason for an empty
                # Archive: if the server rejects it, ask the old way and let
                # load_all_dispatches drop the records in Python.
                print(f"[db] record filter rejected, loading unfiltered: {_fexc}")
                res = _query(False)
            records = []
            for row in res.data:
                full_data = row.get("full_json") or {}
                # full_json may come back as a string if it was json.dumps'd before insert
                if isinstance(full_data, str):
                    try:
                        full_data = json.loads(full_data)
                    except Exception:
                        full_data = {}
                rec = {
                    "timestamp":   row.get("timestamp", ""),
                    "dispatch_id": row.get("dispatch_id", ""),
                    "topic":       row.get("topic", ""),
                    "content":     row.get("content", ""),
                    "full":        full_data,
                }
                if rec["timestamp"]:
                    records.append(rec)
            return records
        except Exception as exc:
            print(f"[db] load_all_dispatches Supabase error: {exc}")

    # ── file fallback ──
    if not os.path.exists(_DISPATCHES_FILE):
        return []
    records = []
    with open(_DISPATCHES_FILE) as f:
        for line in f:
            try:
                rec = json.loads(line)
                if "full" in rec and "timestamp" in rec:
                    records.append(rec)
            except Exception:
                pass
    return sorted(records, key=lambda x: x["timestamp"], reverse=True)


def save_dispatch(content: dict, topic: str):
    """Save a generated dispatch. Mutates content to embed dispatch_id."""
    dispatch_id = str(uuid.uuid4())[:12]
    content["_dispatch_id"] = dispatch_id
    record = {
        "timestamp":   datetime.utcnow().isoformat(),
        "dispatch_id": dispatch_id,
        "topic":       topic,
        "content":     content.get("lead", {}).get("title", ""),
        "full":        content,
    }

    sb = _get_sb()
    if sb:
        try:
            sb.table("dispatches").insert({
                "timestamp":   record["timestamp"],
                "dispatch_id": record["dispatch_id"],
                "topic":       record["topic"],
                "content":     record["content"],
                "full_json":   record["full"],
            }).execute()
            return
        except Exception as exc:
            print(f"[db] save_dispatch Supabase error: {exc}")

    # ── file fallback ──
    _mkdir()
    with open(_DISPATCHES_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# RECORDS — client profiles and session logs, kept in the dispatches table
# ══════════════════════════════════════════════════════════════════════════════
# WHY THIS TABLE AND NOT A NEW ONE. A new table means someone running SQL against
# the live database before any of this can be tried. `dispatches` already has a
# JSONB column and — crucially — `dispatch_id` is UNIQUE, so a record can be
# UPDATED in place by its id instead of piling up a new row on every change. A
# session log changes every minute of a meeting; appending would have meant
# hundreds of rows per session.
#
# Every record carries `_record: True` in its JSON, which is what keeps it out
# of load_all_dispatches and therefore out of every older screen.

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


_UPSERT_MINIMAL: dict = {}      # {"ok": False} once the client is found not to support it


def upsert_record(record_id: str, topic: str, data: dict, label: str = "") -> bool:
    """Create or replace a record by id. Returns True on success."""
    if not record_id:
        return False
    full = dict(data or {})
    full["_record"] = True
    full["_record_id"] = record_id
    row = {"timestamp": _now_iso(), "dispatch_id": record_id, "topic": topic,
           "content": (label or record_id)[:200], "full_json": full}
    sb = _get_sb()
    if sb:
        try:
            q = sb.table("dispatches")
            # A live session log is rewritten every few seconds and grows to
            # ~100 KB by the end of a long meeting. By default the server sends
            # the whole row back after every write, for nobody: "minimal"
            # skips that. Older clients without the option use the default.
            if _UPSERT_MINIMAL.get("ok", True):
                try:
                    from postgrest.types import ReturnMethod
                    q.upsert(row, on_conflict="dispatch_id",
                             returning=ReturnMethod.minimal).execute()
                    return True
                except (ImportError, TypeError) as _mexc:
                    _UPSERT_MINIMAL["ok"] = False
                    print(f"[db] upsert without returning=minimal ({_mexc})")
            sb.table("dispatches").upsert(row, on_conflict="dispatch_id").execute()
            return True
        except Exception as exc:
            print(f"[db] upsert_record Supabase error: {exc}")
    # ── file fallback: rewrite the jsonl with the record replaced ──
    try:
        _mkdir()
        lines = []
        if os.path.exists(_DISPATCHES_FILE):
            with open(_DISPATCHES_FILE) as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("dispatch_id") != record_id:
                        lines.append(rec)
        lines.append({"timestamp": row["timestamp"], "dispatch_id": record_id,
                      "topic": topic, "content": row["content"], "full": full})
        with open(_DISPATCHES_FILE, "w") as f:
            for rec in lines:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        print(f"[db] upsert_record file error: {exc}")
        return False


def _record_from_row(row: dict) -> dict:
    full = row.get("full_json") if "full_json" in row else row.get("full")
    if isinstance(full, str):
        try:
            full = json.loads(full)
        except Exception:
            full = {}
    return dict(full or {}, _updated=row.get("timestamp", ""))


def load_records(topic: str, limit: int = 200, id_prefix: str = "") -> list:
    """All records of one kind, most recently updated first.

    `id_prefix` narrows by record id — "session:<client>:" asks for one client's
    sessions only. Without it, listing a client's past sessions would download
    every transcript of every client just to keep a few of them.
    """
    sb = _get_sb()
    if sb:
        try:
            q = sb.table("dispatches").select("*").eq("topic", topic)
            if id_prefix:
                q = q.like("dispatch_id", id_prefix + "%")
            res = q.order("timestamp", desc=True).limit(limit).execute()
            return [_record_from_row(r) for r in (res.data or [])]
        except Exception as exc:
            print(f"[db] load_records Supabase error: {exc}")
    out = []
    if os.path.exists(_DISPATCHES_FILE):
        latest: dict = {}
        with open(_DISPATCHES_FILE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("topic") == topic and str(rec.get("dispatch_id", "")).startswith(id_prefix):
                    latest[rec.get("dispatch_id")] = rec      # last write wins
        out = [_record_from_row(r) for r in latest.values()]
    return sorted(out, key=lambda r: r.get("_updated", ""), reverse=True)[:limit]


def load_record(record_id: str) -> Optional[dict]:
    """One record by id, or None."""
    if not record_id:
        return None
    sb = _get_sb()
    if sb:
        try:
            res = (sb.table("dispatches").select("*")
                   .eq("dispatch_id", record_id).limit(1).execute())
            rows = res.data or []
            return _record_from_row(rows[0]) if rows else None
        except Exception as exc:
            print(f"[db] load_record Supabase error: {exc}")
    if os.path.exists(_DISPATCHES_FILE):
        found = None
        with open(_DISPATCHES_FILE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("dispatch_id") == record_id:
                    found = rec          # last write wins
        return _record_from_row(found) if found else None
    return None


def delete_record(record_id: str) -> None:
    sb = _get_sb()
    if sb:
        try:
            sb.table("dispatches").delete().eq("dispatch_id", record_id).execute()
            return
        except Exception as exc:
            print(f"[db] delete_record Supabase error: {exc}")
    if os.path.exists(_DISPATCHES_FILE):
        keep = []
        with open(_DISPATCHES_FILE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("dispatch_id") != record_id:
                    keep.append(rec)
        with open(_DISPATCHES_FILE, "w") as f:
            for rec in keep:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_last_dispatch() -> Optional[dict]:
    """Return the most recent dispatch record, or None."""
    dispatches = load_all_dispatches()
    return dispatches[0] if dispatches else None


# ══════════════════════════════════════════════════════════════════════════════
# CURADORIA (saved board items)
# ══════════════════════════════════════════════════════════════════════════════

def load_curadoria() -> list:
    sb = _get_sb()
    if sb:
        try:
            res = sb.table("curadoria").select("*").execute()
            items = []
            for row in res.data:
                items.append({
                    "id":         row["id"],
                    "user":       row.get("user_id", ""),
                    "type":       row.get("type", ""),
                    "title":      row.get("title", ""),
                    "content":    row.get("content", ""),
                    "url":        row.get("url", ""),
                    "category":   row.get("category", ""),
                    "saved_at":   row.get("saved_at", ""),
                    "folder_ids": row.get("folder_ids") or [],
                })
            return items
        except Exception as exc:
            print(f"[db] load_curadoria Supabase error: {exc}")

    # ── file fallback ──
    if not os.path.exists(_CURADORIA_FILE):
        return []
    try:
        with open(_CURADORIA_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_curadoria(items: list):
    """Internal: write full curadoria list to file (fallback only)."""
    _mkdir()
    with open(_CURADORIA_FILE, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ── Evidence, stored inside `content` ────────────────────────────────────────
# A SAVED HEADLINE THAT CANNOT BE DEFENDED IS WORTHLESS.
# The whole point of curating over days or weeks is to walk into a room and say
# "this kept coming back, and here is what it came back from". That needs the
# posts, not just the claim — so every saved item carries its sources with it.
#
# They go in `content` behind a marker rather than in a new column, because a
# schema change means someone running SQL against the live database before any
# of this can be tried. The marker keeps the row readable in the Supabase table
# editor, which a JSON blob would not.
_EVIDENCE_MARK = "\n\n⟦sources⟧\n"


def pack_evidence(summary: str, sources: list) -> str:
    """Body text plus its sources, as one readable string."""
    lines = []
    for s in (sources or [])[:8]:
        label = str(s.get("label") or s.get("source") or "").strip()
        title = str(s.get("title") or "").strip().replace("\n", " ")[:120]
        url = str(s.get("url") or "").strip()
        lines.append(" · ".join(p for p in (label, title, url) if p))
    if not lines:
        return summary or ""
    return (summary or "") + _EVIDENCE_MARK + "\n".join(lines)


def unpack_evidence(content: str) -> tuple:
    """(summary, [source lines]) — the inverse of pack_evidence."""
    txt = content or ""
    if _EVIDENCE_MARK not in txt:
        return txt, []
    head, _, tail = txt.partition(_EVIDENCE_MARK)
    return head, [l for l in tail.split("\n") if l.strip()]


def add_curadoria_item(user: str, type_: str, title: str, content: str,
                       url: str = "", category: str = "",
                       folder_ids: Optional[list] = None) -> bool:
    """Add item. Returns False if already saved by this user.

    `category` carries the search this came from — brand, category, product —
    so a board assembled over three weeks can still say where each item was
    found. Both columns already exist in the table and were simply never
    written to.
    """
    items = load_curadoria()
    for it in items:
        if it["user"] == user and it["title"] == title:
            return False

    item_id  = str(uuid.uuid4())[:8]
    saved_at = datetime.utcnow().strftime("%d %b %Y · %H:%M")

    sb = _get_sb()
    if sb:
        try:
            sb.table("curadoria").insert({
                "id":         item_id,
                "user_id":    user,
                "type":       type_,
                "title":      title,
                "content":    content,
                "url":        url,
                "category":   category,
                "saved_at":   saved_at,
                "folder_ids": list(folder_ids or []),
            }).execute()
            return True
        except Exception as exc:
            print(f"[db] add_curadoria_item Supabase error: {exc}")

    # ── file fallback ──
    items.append({
        "id":         item_id,
        "user":       user,
        "type":       type_,
        "title":      title,
        "content":    content,
        "url":        url,
        "category":   category,
        "saved_at":   saved_at,
        "folder_ids": list(folder_ids or []),
    })
    _save_curadoria(items)
    return True


def remove_curadoria_item(item_id: str):
    sb = _get_sb()
    if sb:
        try:
            sb.table("curadoria").delete().eq("id", item_id).execute()
            return
        except Exception as exc:
            print(f"[db] remove_curadoria_item Supabase error: {exc}")

    # ── file fallback ──
    items = [i for i in load_curadoria() if i["id"] != item_id]
    _save_curadoria(items)


def set_item_folders(item_id: str, folder_ids: list):
    sb = _get_sb()
    if sb:
        try:
            sb.table("curadoria").update({"folder_ids": folder_ids}).eq("id", item_id).execute()
            return
        except Exception as exc:
            print(f"[db] set_item_folders Supabase error: {exc}")

    # ── file fallback ──
    items = load_curadoria()
    for it in items:
        if it["id"] == item_id:
            it["folder_ids"] = folder_ids
    _save_curadoria(items)


def add_url_current_to_curadoria(item: dict) -> dict:
    """Save a pre-built curadoria item (used by add_url_current in app.py)."""
    sb = _get_sb()
    if sb:
        try:
            sb.table("curadoria").insert({
                "id":         item["id"],
                "user_id":    item["user"],
                "type":       item.get("type", ""),
                "title":      item.get("title", ""),
                "content":    item.get("content", ""),
                "url":        item.get("url", ""),
                "category":   item.get("category", ""),
                "saved_at":   item.get("saved_at", ""),
                "folder_ids": item.get("folder_ids", []),
            }).execute()
            return item
        except Exception as exc:
            print(f"[db] add_url_current_to_curadoria Supabase error: {exc}")

    # ── file fallback ──
    items = load_curadoria()
    items.append(item)
    _save_curadoria(items)
    return item


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT FOLDERS
# ══════════════════════════════════════════════════════════════════════════════

def load_project_folders() -> list:
    sb = _get_sb()
    if sb:
        try:
            res = sb.table("project_folders").select("*").execute()
            return [
                {
                    "id":         row["id"],
                    "name":       row.get("name", ""),
                    "created_by": row.get("created_by", ""),
                    "created_at": row.get("created_at", ""),
                }
                for row in res.data
            ]
        except Exception as exc:
            print(f"[db] load_project_folders Supabase error: {exc}")

    # ── file fallback ──
    if not os.path.exists(_FOLDERS_FILE):
        return []
    try:
        with open(_FOLDERS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_project_folders(folders: list):
    _mkdir()
    with open(_FOLDERS_FILE, "w") as f:
        json.dump(folders, f, ensure_ascii=False, indent=2)


def create_project_folder(name: str, user: str) -> Optional[dict]:
    """Returns the new folder dict, or None if name is empty/duplicate."""
    name = (name or "").strip()
    if not name:
        return None
    folders = load_project_folders()
    if any(f["name"].lower() == name.lower() for f in folders):
        return None

    folder = {
        "id":         str(uuid.uuid4())[:8],
        "name":       name,
        "created_by": user,
        "created_at": datetime.utcnow().strftime("%d %b %Y · %H:%M"),
    }

    sb = _get_sb()
    if sb:
        try:
            sb.table("project_folders").insert(folder).execute()
            return folder
        except Exception as exc:
            print(f"[db] create_project_folder Supabase error: {exc}")

    # ── file fallback ──
    folders.append(folder)
    _save_project_folders(folders)
    return folder


def delete_project_folder(folder_id: str):
    sb = _get_sb()
    if sb:
        try:
            sb.table("project_folders").delete().eq("id", folder_id).execute()
            # Detach from curadoria items
            items = load_curadoria()
            for it in items:
                fids = it.get("folder_ids") or []
                if folder_id in fids:
                    new_fids = [x for x in fids if x != folder_id]
                    set_item_folders(it["id"], new_fids)
            return
        except Exception as exc:
            print(f"[db] delete_project_folder Supabase error: {exc}")

    # ── file fallback ──
    folders = [f for f in load_project_folders() if f["id"] != folder_id]
    _save_project_folders(folders)
    items = load_curadoria()
    changed = False
    for it in items:
        fids = it.get("folder_ids", [])
        if folder_id in fids:
            it["folder_ids"] = [x for x in fids if x != folder_id]
            changed = True
    if changed:
        _save_curadoria(items)


# ══════════════════════════════════════════════════════════════════════════════
# CLIENT ACCOUNTS
# ══════════════════════════════════════════════════════════════════════════════

def load_client_accounts() -> list:
    sb = _get_sb()
    if sb:
        try:
            res = sb.table("client_accounts").select("*").execute()
            return [
                {
                    "username":      row["username"],
                    "password":      row.get("password", ""),
                    "client_label":  row.get("client_label", row["username"]),
                    "perms":         row.get("perms") or {},
                }
                for row in res.data
            ]
        except Exception as exc:
            print(f"[db] load_client_accounts Supabase error: {exc}")

    # ── file fallback ──
    if not os.path.exists(_ACCOUNTS_FILE):
        return []
    try:
        with open(_ACCOUNTS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_client_accounts(accounts: list):
    _mkdir()
    with open(_ACCOUNTS_FILE, "w") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def create_client_account(username: str, password: str, label: str) -> bool:
    username = (username or "").strip()
    password = (password or "").strip()
    if not username or not password:
        return False
    if any(a["username"].lower() == username.lower() for a in load_client_accounts()):
        return False

    perms_defaults = {
        "competitive_pulse": False,
        "topic_map":         False,
        "momentum":          False,
        "signal_volume":     False,
    }

    sb = _get_sb()
    if sb:
        try:
            sb.table("client_accounts").insert({
                "username":      username,
                "password":      password,
                "client_label":  (label or username).strip(),
                "perms":         perms_defaults,
            }).execute()
            return True
        except Exception as exc:
            print(f"[db] create_client_account Supabase error: {exc}")

    # ── file fallback ──
    accounts = load_client_accounts()
    accounts.append({
        "username":      username,
        "password":      password,
        "client_label":  (label or username).strip(),
        "perms":         dict(perms_defaults),
    })
    _save_client_accounts(accounts)
    return True


def delete_client_account(username: str):
    sb = _get_sb()
    if sb:
        try:
            sb.table("client_accounts").delete().eq("username", username).execute()
            return
        except Exception as exc:
            print(f"[db] delete_client_account Supabase error: {exc}")

    accounts = [a for a in load_client_accounts() if a["username"] != username]
    _save_client_accounts(accounts)


def update_client_perms(username: str, perms: dict):
    sb = _get_sb()
    if sb:
        try:
            sb.table("client_accounts").update({"perms": perms}).eq("username", username).execute()
            return
        except Exception as exc:
            print(f"[db] update_client_perms Supabase error: {exc}")

    accounts = load_client_accounts()
    for a in accounts:
        if a["username"] == username:
            a["perms"] = perms
    _save_client_accounts(accounts)


def authenticate_client(username: str, password: str) -> Optional[dict]:
    for a in load_client_accounts():
        if a["username"] == username and a.get("password") == password:
            return a
    return None


# ══════════════════════════════════════════════════════════════════════════════
# COUNTERCURRENT OVERRIDES
# ══════════════════════════════════════════════════════════════════════════════

def load_countercurrent_overrides() -> dict:
    sb = _get_sb()
    if sb:
        try:
            res = sb.table("countercurrent_overrides").select("*").execute()
            return {
                row["dispatch_id"]: {
                    "title":     row.get("title", ""),
                    "body":      row.get("body", ""),
                    "edited_by": row.get("edited_by", ""),
                    "edited_at": row.get("edited_at", ""),
                }
                for row in res.data
            }
        except Exception as exc:
            print(f"[db] load_countercurrent_overrides Supabase error: {exc}")

    # ── file fallback ──
    if not os.path.exists(_OVERRIDES_FILE):
        return {}
    try:
        with open(_OVERRIDES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_countercurrent_override(dispatch_id: str, title: str, body: str, user: str):
    edited_at = datetime.utcnow().strftime("%d %b %Y · %H:%M")
    sb = _get_sb()
    if sb:
        try:
            sb.table("countercurrent_overrides").upsert({
                "dispatch_id": dispatch_id,
                "title":       title,
                "body":        body,
                "edited_by":   user,
                "edited_at":   edited_at,
            }).execute()
            return
        except Exception as exc:
            print(f"[db] save_countercurrent_override Supabase error: {exc}")

    # ── file fallback ──
    overrides = load_countercurrent_overrides()
    overrides[dispatch_id] = {
        "title":     title,
        "body":      body,
        "edited_by": user,
        "edited_at": edited_at,
    }
    _mkdir()
    with open(_OVERRIDES_FILE, "w") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)


def clear_countercurrent_override(dispatch_id: str):
    sb = _get_sb()
    if sb:
        try:
            sb.table("countercurrent_overrides").delete().eq("dispatch_id", dispatch_id).execute()
            return
        except Exception as exc:
            print(f"[db] clear_countercurrent_override Supabase error: {exc}")

    # ── file fallback ──
    overrides = load_countercurrent_overrides()
    if dispatch_id in overrides:
        del overrides[dispatch_id]
        _mkdir()
        with open(_OVERRIDES_FILE, "w") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# SWEEP RUNS & VELOCITY TRACKING
# ══════════════════════════════════════════════════════════════════════════════

def record_sweep_run(topic: str, signal_count: int, sources: list) -> Optional[str]:
    """Save a sweep run and return its UUID (for velocity snapshots)."""
    sb = _get_sb()
    if sb:
        try:
            res = sb.table("sweep_runs").insert({
                "topic":        topic,
                "signal_count": signal_count,
                "sources":      sources,
            }).execute()
            return res.data[0]["id"] if res.data else None
        except Exception as exc:
            print(f"[db] record_sweep_run Supabase error: {exc}")
    return None


def record_topic_velocity(sweep_run_id: str, snapshots: list[dict]):
    """snapshots = [{"topic_tag": str, "signal_count": int}, ...]"""
    if not sweep_run_id or not snapshots:
        return
    sb = _get_sb()
    if sb:
        try:
            rows = [
                {
                    "sweep_run_id": sweep_run_id,
                    "topic_tag":    s["topic_tag"],
                    "signal_count": s["signal_count"],
                }
                for s in snapshots
            ]
            sb.table("topic_velocity").insert(rows).execute()
        except Exception as exc:
            print(f"[db] record_topic_velocity Supabase error: {exc}")


def load_velocity_history(topic_tag: str, limit: int = 20) -> list:
    """Return velocity snapshots for a topic (newest first)."""
    sb = _get_sb()
    if sb:
        try:
            res = (
                sb.table("topic_velocity")
                .select("signal_count, snapshot_at")
                .eq("topic_tag", topic_tag)
                .order("snapshot_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            print(f"[db] load_velocity_history Supabase error: {exc}")
    return []


def load_sweep_runs(limit: int = 30) -> list:
    """Return recent sweep runs, newest first."""
    sb = _get_sb()
    if sb:
        try:
            res = (
                sb.table("sweep_runs")
                .select("*")
                .order("run_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            print(f"[db] load_sweep_runs Supabase error: {exc}")
    return []


# ══════════════════════════════════════════════════════════════════════════════
# MIGRATION UTILITY — run once to push existing file data into Supabase
# ══════════════════════════════════════════════════════════════════════════════

def migrate_files_to_supabase() -> dict:
    """
    Read existing JSON/JSONL files and push them into Supabase.
    Returns a dict with counts per table.
    Call this once from a migration script or an admin button in the app.
    """
    if not use_supabase():
        raise RuntimeError("Supabase not configured – set SUPABASE_URL and SUPABASE_KEY.")

    counts = {}

    # signals
    if os.path.exists(_SIGNALS_FILE):
        sigs = []
        with open(_SIGNALS_FILE) as f:
            for line in f:
                try:
                    sigs.append(json.loads(line))
                except Exception:
                    pass
        bulk_save_signals(sigs)
        counts["signals"] = len(sigs)

    # dispatches
    if os.path.exists(_DISPATCHES_FILE):
        sb = _get_sb()
        recs = []
        with open(_DISPATCHES_FILE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if "full" in rec and "timestamp" in rec:
                        recs.append(rec)
                except Exception:
                    pass
        for rec in recs:
            try:
                sb.table("dispatches").upsert({
                    "timestamp":   rec["timestamp"],
                    "dispatch_id": rec.get("dispatch_id", str(uuid.uuid4())[:12]),
                    "topic":       rec.get("topic", ""),
                    "content":     rec.get("content", ""),
                    "full_json":   rec.get("full", {}),
                }).execute()
            except Exception:
                pass
        counts["dispatches"] = len(recs)

    # curadoria
    if os.path.exists(_CURADORIA_FILE):
        try:
            with open(_CURADORIA_FILE) as f:
                items = json.load(f)
        except Exception:
            items = []
        sb = _get_sb()
        for it in items:
            try:
                sb.table("curadoria").upsert({
                    "id":         it["id"],
                    "user_id":    it.get("user", ""),
                    "type":       it.get("type", ""),
                    "title":      it.get("title", ""),
                    "content":    it.get("content", ""),
                    "url":        it.get("url", ""),
                    "category":   it.get("category", ""),
                    "saved_at":   it.get("saved_at", ""),
                    "folder_ids": it.get("folder_ids", []),
                }).execute()
            except Exception:
                pass
        counts["curadoria"] = len(items)

    # project_folders
    if os.path.exists(_FOLDERS_FILE):
        try:
            with open(_FOLDERS_FILE) as f:
                folders = json.load(f)
        except Exception:
            folders = []
        sb = _get_sb()
        for fld in folders:
            try:
                sb.table("project_folders").upsert(fld).execute()
            except Exception:
                pass
        counts["project_folders"] = len(folders)

    # client_accounts
    if os.path.exists(_ACCOUNTS_FILE):
        try:
            with open(_ACCOUNTS_FILE) as f:
                accounts = json.load(f)
        except Exception:
            accounts = []
        sb = _get_sb()
        for acc in accounts:
            try:
                sb.table("client_accounts").upsert({
                    "username":     acc["username"],
                    "password":     acc.get("password", ""),
                    "client_label": acc.get("client_label", acc["username"]),
                    "perms":        acc.get("perms", {}),
                }).execute()
            except Exception:
                pass
        counts["client_accounts"] = len(accounts)

    # countercurrent_overrides
    if os.path.exists(_OVERRIDES_FILE):
        try:
            with open(_OVERRIDES_FILE) as f:
                overrides = json.load(f)
        except Exception:
            overrides = {}
        sb = _get_sb()
        for did, ov in overrides.items():
            try:
                sb.table("countercurrent_overrides").upsert({
                    "dispatch_id": did,
                    "title":       ov.get("title", ""),
                    "body":        ov.get("body", ""),
                    "edited_by":   ov.get("edited_by", ""),
                    "edited_at":   ov.get("edited_at", ""),
                }).execute()
            except Exception:
                pass
        counts["countercurrent_overrides"] = len(overrides)

    return counts
