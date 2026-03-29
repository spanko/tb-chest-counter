-- ============================================================================
-- TB Chest Counter — PostgreSQL Schema (multi-clan)
-- All tables partitioned by clan_id for multi-tenant isolation.
-- Run after initial deployment: psql -h <fqdn> -U tbadmin -d tbchests -f schema.sql
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Clans registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clans (
    clan_id         TEXT PRIMARY KEY,          -- e.g., 'for-main'
    clan_name       TEXT NOT NULL,             -- e.g., 'FOR'
    kingdom         INTEGER NOT NULL,
    scan_interval_h INTEGER NOT NULL DEFAULT 4,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Clan roster (known members for fuzzy matching)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clan_members (
    id              SERIAL PRIMARY KEY,
    clan_id         TEXT NOT NULL REFERENCES clans(clan_id),
    player_name     TEXT NOT NULL,
    aliases         TEXT[] DEFAULT '{}',        -- Known OCR misreads / alt names
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(clan_id, player_name)
);

CREATE INDEX idx_members_clan ON clan_members(clan_id) WHERE is_active;

-- ---------------------------------------------------------------------------
-- Scan runs — one row per scanner job execution
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scan_runs (
    run_id          SERIAL PRIMARY KEY,
    clan_id         TEXT NOT NULL REFERENCES clans(clan_id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed
    pages_scanned   INTEGER DEFAULT 0,
    chests_found    INTEGER DEFAULT 0,
    chests_new      INTEGER DEFAULT 0,
    error_message   TEXT,
    vision_model    TEXT,                      -- Which Claude model was used
    vision_cost_usd NUMERIC(8,4) DEFAULT 0    -- Approximate API cost
);

CREATE INDEX idx_runs_clan ON scan_runs(clan_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- Chest gifts — the core data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chests (
    id              SERIAL PRIMARY KEY,
    clan_id         TEXT NOT NULL REFERENCES clans(clan_id),
    run_id          INTEGER REFERENCES scan_runs(run_id),
    player_name     TEXT NOT NULL,
    player_name_raw TEXT,                      -- Original OCR/Vision text before fuzzy match
    chest_type      TEXT NOT NULL,
    chest_type_raw  TEXT,                      -- Original before normalization
    source          TEXT,                      -- e.g., 'crypt', 'citadel', 'event'
    points          INTEGER NOT NULL DEFAULT 1,
    confidence      NUMERIC(4,3),             -- 0.000-1.000 from Claude Vision
    verified        BOOLEAN DEFAULT FALSE,     -- True if Sonnet-verified
    time_remaining  TEXT,                      -- e.g., '12h 30m' from screenshot
    screenshot_ref  TEXT,                      -- Path/key to original screenshot
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dedup_hash      TEXT,                      -- For deduplication
    UNIQUE(clan_id, dedup_hash)
);

CREATE INDEX idx_chests_clan_time ON chests(clan_id, scanned_at DESC);
CREATE INDEX idx_chests_player ON chests(clan_id, player_name, scanned_at DESC);
CREATE INDEX idx_chests_dedup ON chests(clan_id, dedup_hash);

-- ---------------------------------------------------------------------------
-- Chest type definitions — point values and aliases
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chest_types (
    chest_type      TEXT PRIMARY KEY,
    points          INTEGER NOT NULL DEFAULT 1,
    category        TEXT,                      -- 'common', 'rare', 'epic', 'legendary', 'mythic'
    aliases         TEXT[] DEFAULT '{}'
);

-- Seed default chest types
INSERT INTO chest_types (chest_type, points, category, aliases) VALUES
    ('Common Chest',              1,   'common',    '{"basic chest"}'),
    ('Uncommon Chest',            2,   'uncommon',  '{"green chest"}'),
    ('Rare Chest',                5,   'rare',      '{"blue chest"}'),
    ('Epic Chest',                15,  'epic',      '{"purple chest"}'),
    ('Legendary Chest',           50,  'legendary', '{"gold chest","golden chest"}'),
    ('Mythic Chest',              100, 'mythic',    '{"red chest"}'),
    ('Sand Chest',                3,   'crypt',     '{}'),
    ('Stone Chest',               5,   'crypt',     '{}'),
    ('Barbarian Chest',           8,   'crypt',     '{}'),
    ('Forgotten Chest',           10,  'crypt',     '{}'),
    ('Gnome Workshop Chest',      12,  'crypt',     '{}'),
    ('Elven Citadel Chest',       15,  'citadel',   '{}'),
    ('Rare Chest of Warlords',    8,   'warlord',   '{"rare warlord"}'),
    ('Epic Chest of Warlords',    25,  'warlord',   '{"epic warlord"}'),
    ('Legendary Chest of Warlords', 75, 'warlord',  '{"legendary warlord"}'),
    ('Rare Chest of Champions',   8,   'champion',  '{"rare champion"}'),
    ('Epic Chest of Champions',   25,  'champion',  '{"epic champion"}'),
    ('Legendary Chest of Champions', 75, 'champion', '{"legendary champion"}'),
    ('Clan Gift',                 1,   'gift',      '{"gift"}')
ON CONFLICT (chest_type) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Views — leaderboards and aggregations
-- ---------------------------------------------------------------------------

-- Per-clan leaderboard (last 7 days)
CREATE OR REPLACE VIEW v_leaderboard_7d AS
SELECT
    c.clan_id,
    cl.clan_name,
    c.player_name,
    COUNT(*)            AS chest_count,
    SUM(c.points)       AS total_points,
    COUNT(DISTINCT DATE(c.scanned_at)) AS active_days,
    MAX(c.scanned_at)   AS last_seen
FROM chests c
JOIN clans cl ON cl.clan_id = c.clan_id
WHERE c.scanned_at > NOW() - INTERVAL '7 days'
GROUP BY c.clan_id, cl.clan_name, c.player_name
ORDER BY c.clan_id, total_points DESC;

-- Cross-clan summary (FOR ecosystem totals)
CREATE OR REPLACE VIEW v_clan_summary AS
SELECT
    c.clan_id,
    cl.clan_name,
    COUNT(*)            AS total_chests_7d,
    SUM(c.points)       AS total_points_7d,
    COUNT(DISTINCT c.player_name) AS active_players,
    MAX(c.scanned_at)   AS last_scan
FROM chests c
JOIN clans cl ON cl.clan_id = c.clan_id
WHERE c.scanned_at > NOW() - INTERVAL '7 days'
GROUP BY c.clan_id, cl.clan_name
ORDER BY total_points_7d DESC;

-- ---------------------------------------------------------------------------
-- Clan settings — weekly targets and configuration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clan_settings (
    clan_id             TEXT PRIMARY KEY REFERENCES clans(clan_id),
    weekly_chest_target INTEGER DEFAULT 30,           -- Min chests per member per week
    weekly_point_target INTEGER DEFAULT 100,          -- Min points per member per week
    target_type         TEXT DEFAULT 'chests',        -- 'chests', 'points', or 'both'
    week_start_day      INTEGER DEFAULT 1,            -- 1=Monday, 0=Sunday
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Player chest type breakdown
CREATE OR REPLACE VIEW v_player_breakdown AS
SELECT
    c.clan_id,
    c.player_name,
    c.chest_type,
    ct.category,
    COUNT(*)        AS count,
    SUM(c.points)   AS points
FROM chests c
LEFT JOIN chest_types ct ON ct.chest_type = c.chest_type
WHERE c.scanned_at > NOW() - INTERVAL '7 days'
GROUP BY c.clan_id, c.player_name, c.chest_type, ct.category
ORDER BY c.clan_id, c.player_name, points DESC;
