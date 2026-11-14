SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    rows_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE files ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS records (
    id BIGSERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    data JSONB NOT NULL,
    search_text TEXT NOT NULL DEFAULT '',
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED
);

CREATE INDEX IF NOT EXISTS records_tsv_idx ON records USING GIN (tsv);
CREATE INDEX IF NOT EXISTS records_file_idx ON records (file_id);
"""
