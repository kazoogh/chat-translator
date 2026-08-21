CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON message_history(created_at DESC, message_id DESC);

CREATE INDEX IF NOT EXISTS idx_history_profile_created
    ON message_history(profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS window_geometry (
    display_id TEXT PRIMARY KEY CHECK (length(display_id) BETWEEN 1 AND 200),
    x INTEGER NOT NULL CHECK (x BETWEEN -100000 AND 100000),
    y INTEGER NOT NULL CHECK (y BETWEEN -100000 AND 100000),
    width INTEGER NOT NULL CHECK (width BETWEEN 100 AND 50000),
    height INTEGER NOT NULL CHECK (height BETWEEN 100 AND 50000),
    maximized INTEGER NOT NULL CHECK (maximized IN (0, 1)),
    updated_at TEXT NOT NULL
);
