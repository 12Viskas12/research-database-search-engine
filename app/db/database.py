import json

import asyncpg

from app.core.config import settings
from app.db.db_models import MIGRATIONS

_pool = None


def _dump(value):
    return json.dumps(value, default=str, ensure_ascii=False)


async def _init_conn(conn):
    await conn.set_type_codec(
        "jsonb", encoder=_dump, decoder=json.loads, schema="pg_catalog"
    )


async def init_pool():
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=10, init=_init_conn
    )
    async with _pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(7351)")
        try:
            await migrate(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(7351)")
    return _pool


async def migrate(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
    for version, name, sql in MIGRATIONS:
        if version in done:
            continue
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                version,
                name,
            )


def get_pool():
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def create_file(name, path="", sha256=None):
    return await _pool.fetchval(
        "INSERT INTO files (name, path, sha256) VALUES ($1, $2, $3) RETURNING id",
        name,
        path,
        sha256,
    )


async def find_duplicate(sha256):
    row = await _pool.fetchrow(
        "SELECT id, name FROM files WHERE sha256 = $1 "
        "AND status NOT IN ('failed', 'deleting') ORDER BY id LIMIT 1",
        sha256,
    )
    return dict(row) if row else None


async def get_file(file_id):
    row = await _pool.fetchrow("SELECT * FROM files WHERE id = $1", file_id)
    return dict(row) if row else None


async def list_files():
    rows = await _pool.fetch(
        "SELECT id, name, status, rows_count, progress, packed, raw_bytes, "
        "packed_bytes, error, created_at FROM files ORDER BY id DESC"
    )
    return [dict(r) for r in rows]


async def set_file_status(file_id, status, rows_count=None, error=None):
    await _pool.execute(
        "UPDATE files SET status = $2::text, rows_count = COALESCE($3, rows_count), "
        "error = $4, "
        "progress = CASE WHEN $2::text = 'done' THEN 100 "
        "WHEN $2::text IN ('processing', 'packing', 'unpacking', 'pending') THEN 0 "
        "ELSE progress END "
        "WHERE id = $1",
        file_id,
        status,
        rows_count,
        error,
    )


async def set_file_progress(file_id, progress):
    await _pool.execute(
        "UPDATE files SET progress = $2 WHERE id = $1", file_id, progress
    )
