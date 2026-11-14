import json

import asyncpg

from app.core.config import settings
from app.db.db_models import SCHEMA

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
            await conn.execute(SCHEMA)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(7351)")
    return _pool


def get_pool():
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def create_file(name, path):
    return await _pool.fetchval(
        "INSERT INTO files (name, path) VALUES ($1, $2) RETURNING id", name, path
    )


async def get_file(file_id):
    row = await _pool.fetchrow("SELECT * FROM files WHERE id = $1", file_id)
    return dict(row) if row else None


async def list_files():
    rows = await _pool.fetch(
        "SELECT id, name, status, rows_count, progress, error, created_at "
        "FROM files ORDER BY id DESC"
    )
    return [dict(r) for r in rows]


async def set_file_status(file_id, status, rows_count=None, error=None):
    await _pool.execute(
        "UPDATE files SET status = $2::text, rows_count = COALESCE($3, rows_count), "
        "error = $4, "
        "progress = CASE WHEN $2::text = 'done' THEN 100 "
        "WHEN $2::text = 'processing' THEN 0 ELSE progress END "
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
