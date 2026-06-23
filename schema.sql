-- ============================================================
-- Lighthouse – Supabase schema
-- Run this once in your Supabase SQL Editor
-- ============================================================

-- ── SIGNALS (scraped raw signals) ─────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    title       TEXT,
    content     TEXT,
    source      TEXT,
    url         TEXT,
    tags        JSONB       DEFAULT '[]',
    extra       JSONB       DEFAULT '{}'   -- full original dict
);
CREATE INDEX IF NOT EXISTS signals_timestamp_idx ON signals (timestamp DESC);

-- ── DISPATCHES ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dispatches (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dispatch_id TEXT        UNIQUE,
    topic       TEXT,
    content     TEXT,                     -- lead title (for quick listing)
    full_json   JSONB                     -- complete dispatch object
);
CREATE INDEX IF NOT EXISTS dispatches_timestamp_idx ON dispatches (timestamp DESC);

-- ── CURADORIA (saved board items) ─────────────────────────
CREATE TABLE IF NOT EXISTS curadoria (
    id          TEXT        PRIMARY KEY,
    user_id     TEXT        NOT NULL,
    type        TEXT,
    title       TEXT,
    content     TEXT,
    url         TEXT,
    category    TEXT,
    saved_at    TEXT,
    folder_ids  JSONB       DEFAULT '[]'
);

-- ── PROJECT FOLDERS ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS project_folders (
    id          TEXT        PRIMARY KEY,
    name        TEXT        NOT NULL,
    created_by  TEXT,
    created_at  TEXT
);

-- ── CLIENT ACCOUNTS ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS client_accounts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username    TEXT        UNIQUE NOT NULL,
    password    TEXT        NOT NULL,
    client_label TEXT,
    perms       JSONB       DEFAULT '{}'
);

-- ── COUNTERCURRENT OVERRIDES (hand-edited dispatch content) ─
CREATE TABLE IF NOT EXISTS countercurrent_overrides (
    dispatch_id TEXT        PRIMARY KEY,
    title       TEXT,
    body        TEXT,
    edited_by   TEXT,
    edited_at   TEXT
);

-- ── SWEEP RUNS (for velocity tracking) ────────────────────
CREATE TABLE IF NOT EXISTS sweep_runs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    topic       TEXT,
    signal_count INT        DEFAULT 0,
    sources     JSONB       DEFAULT '[]'
);

-- ── TOPIC VELOCITY snapshots ──────────────────────────────
CREATE TABLE IF NOT EXISTS topic_velocity (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    sweep_run_id UUID       REFERENCES sweep_runs(id) ON DELETE CASCADE,
    topic_tag   TEXT,
    signal_count INT        DEFAULT 0,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── DISABLE Row Level Security (private internal app) ──────
ALTER TABLE signals                  DISABLE ROW LEVEL SECURITY;
ALTER TABLE dispatches               DISABLE ROW LEVEL SECURITY;
ALTER TABLE curadoria                DISABLE ROW LEVEL SECURITY;
ALTER TABLE project_folders          DISABLE ROW LEVEL SECURITY;
ALTER TABLE client_accounts          DISABLE ROW LEVEL SECURITY;
ALTER TABLE countercurrent_overrides DISABLE ROW LEVEL SECURITY;
ALTER TABLE sweep_runs               DISABLE ROW LEVEL SECURITY;
ALTER TABLE topic_velocity           DISABLE ROW LEVEL SECURITY;
