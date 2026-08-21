ALTER TABLE glossary_candidates ADD COLUMN display_alias TEXT NOT NULL DEFAULT '';
ALTER TABLE glossary_candidates ADD COLUMN category TEXT NOT NULL DEFAULT 'learned';
ALTER TABLE glossary_candidates ADD COLUMN reason TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS privacy_secrets (
    name TEXT PRIMARY KEY,
    key_bytes BLOB NOT NULL CHECK (length(key_bytes) >= 32),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS glossary_evidence (
    candidate_id TEXT NOT NULL REFERENCES glossary_candidates(candidate_id) ON DELETE CASCADE,
    message_key TEXT NOT NULL,
    speaker_key TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    ocr_stability REAL NOT NULL CHECK (ocr_stability >= 0 AND ocr_stability <= 1),
    observed_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, message_key)
);

ALTER TABLE installed_models ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0
    CHECK (size_bytes >= 0);
ALTER TABLE installed_models ADD COLUMN active INTEGER NOT NULL DEFAULT 0
    CHECK (active IN (0, 1));

CREATE INDEX IF NOT EXISTS idx_evidence_candidate
    ON glossary_evidence(candidate_id, observed_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_profile_alias
    ON glossary_candidates(profile_id, observed_text);
