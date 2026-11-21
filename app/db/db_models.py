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

ALTER TABLE files ADD COLUMN IF NOT EXISTS packed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE files ADD COLUMN IF NOT EXISTS codec TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS raw_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS packed_bytes BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS blocks (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    block_no INTEGER NOT NULL,
    rows_count INTEGER NOT NULL,
    raw_size INTEGER NOT NULL,
    codec TEXT NOT NULL,
    bloom BYTEA NOT NULL,
    payload BYTEA NOT NULL,
    PRIMARY KEY (file_id, block_no)
);

ALTER TABLE blocks ALTER COLUMN bloom SET STORAGE EXTERNAL;
ALTER TABLE blocks ALTER COLUMN payload SET STORAGE EXTERNAL;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    pass_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'vip', 'admin')),
    tg_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS users_username_idx ON users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS users_tg_idx ON users (tg_id) WHERE tg_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    id SERIAL PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('user', 'vip', 'admin')),
    tg_id BIGINT,
    note TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS access_requests (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT NOT NULL,
    tg_username TEXT,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    invite_id INTEGER REFERENCES invites(id) ON DELETE SET NULL,
    notified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS requests_pending_idx ON access_requests (tg_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS search_usage (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS role_until TIMESTAMPTZ;
ALTER TABLE invites ADD COLUMN IF NOT EXISTS role_days INTEGER;
ALTER TABLE access_requests ADD COLUMN IF NOT EXISTS admin_notified BOOLEAN NOT NULL DEFAULT FALSE;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS vocab (
    word TEXT PRIMARY KEY,
    freq INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS vocab_trgm_idx ON vocab USING GIN (word gin_trgm_ops);
CREATE INDEX IF NOT EXISTS records_trgm_idx ON records USING GIN (search_text gin_trgm_ops);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id INTEGER,
    actor_name TEXT,
    action TEXT NOT NULL,
    details JSONB
);

CREATE INDEX IF NOT EXISTS audit_action_idx ON audit_log (action, id DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS search_history (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    files TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'web',
    results INTEGER NOT NULL DEFAULT 0,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS history_user_idx ON search_history (user_id, id DESC);

CREATE TABLE IF NOT EXISTS tg_links (
    code TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);
"""

FEATURES = """
ALTER TABLE files ADD COLUMN IF NOT EXISTS sha256 TEXT;
CREATE INDEX IF NOT EXISTS files_sha_idx ON files (sha256) WHERE sha256 IS NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS stats_daily (
    day DATE PRIMARY KEY,
    searches INTEGER NOT NULL DEFAULT 0
);
"""

MIGRATIONS = [
    (1, "baseline", SCHEMA),
    (2, "hash, blocking, stats", FEATURES),
]
