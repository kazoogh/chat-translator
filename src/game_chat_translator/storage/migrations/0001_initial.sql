CREATE TABLE IF NOT EXISTS calibrations (
    calibration_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    layout_id TEXT NOT NULL,
    monitor_id TEXT NOT NULL,
    client_width INTEGER NOT NULL CHECK (client_width > 0),
    client_height INTEGER NOT NULL CHECK (client_height > 0),
    dpi INTEGER NOT NULL CHECK (dpi > 0),
    game_ui_scale REAL,
    normalized_x REAL NOT NULL CHECK (normalized_x >= 0 AND normalized_x <= 1),
    normalized_y REAL NOT NULL CHECK (normalized_y >= 0 AND normalized_y <= 1),
    normalized_width REAL NOT NULL CHECK (normalized_width > 0 AND normalized_width <= 1),
    normalized_height REAL NOT NULL CHECK (normalized_height > 0 AND normalized_height <= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, layout_id, monitor_id, client_width, client_height, dpi, game_ui_scale)
);

CREATE TABLE IF NOT EXISTS learned_terms (
    learned_term_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    canonical_term TEXT NOT NULL,
    language TEXT NOT NULL,
    category TEXT,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, alias, language)
);

CREATE TABLE IF NOT EXISTS glossary_candidates (
    candidate_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    observed_text TEXT NOT NULL,
    proposed_canonical_term TEXT NOT NULL,
    language TEXT NOT NULL,
    evidence_count INTEGER NOT NULL CHECK (evidence_count > 0),
    context_hash TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'rejected', 'blocked')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(profile_id, observed_text, language)
);

CREATE TABLE IF NOT EXISTS installed_models (
    model_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    license_id TEXT NOT NULL,
    health_state TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS profile_overrides (
    profile_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    override_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_history (
    message_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_expires_at ON message_history(expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON glossary_candidates(profile_id, status);

