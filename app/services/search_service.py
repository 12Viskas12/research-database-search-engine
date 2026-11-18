import asyncio
import random

from app.db import database
from app.services import compression_service

FTS_SQL = """
SELECT r.id, r.file_id, r.data
FROM records r, websearch_to_tsquery('simple', $1) q
WHERE r.tsv @@ q
ORDER BY ts_rank(r.tsv, q) DESC, r.id
LIMIT $2 OFFSET $3
"""

LIKE_SQL = """
SELECT id, file_id, data
FROM records
WHERE search_text ILIKE $1
ORDER BY id
LIMIT $2 OFFSET $3
"""


LUCKY_COUNTS = """
SELECT
    COALESCE(sum(rows_count) FILTER (WHERE NOT packed AND status = 'done'), 0)::bigint AS live,
    COALESCE(sum(rows_count) FILTER (WHERE packed), 0)::bigint AS packed
FROM files
"""

LUCKY_LIVE = """
SELECT id, file_id, data FROM records
WHERE id >= (SELECT floor(random() * COALESCE(max(id), 0))::bigint + 1 FROM records)
ORDER BY id LIMIT 1
"""

LUCKY_LIVE_FIRST = "SELECT id, file_id, data FROM records ORDER BY id LIMIT 1"

LUCKY_BLOCK = """
SELECT file_id, block_no, codec, payload FROM blocks
ORDER BY random() LIMIT 1
"""


def _like_pattern(query):
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def search(query, limit=20, offset=0):
    query = query.strip()
    if not query:
        return []
    need = offset + limit
    async with database.get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            rows = await conn.fetch(FTS_SQL, query, need, 0)
            if not rows:
                rows = await conn.fetch(LIKE_SQL, _like_pattern(query), need, 0)
            items = [dict(r) for r in rows]
            if len(items) < need:
                items += await compression_service.search_packed(
                    conn, query, need - len(items)
                )
    return items[offset : offset + limit]


async def lucky():
    pool = database.get_pool()
    counts = await pool.fetchrow(LUCKY_COUNTS)
    total = counts["live"] + counts["packed"]
    if total <= 0:
        return None
    if random.random() * total < counts["live"]:
        row = await pool.fetchrow(LUCKY_LIVE) or await pool.fetchrow(LUCKY_LIVE_FIRST)
        if row:
            return dict(row)
    block = await pool.fetchrow(LUCKY_BLOCK)
    if block is None:
        return None
    rows = await asyncio.to_thread(
        compression_service.decode_block, block["payload"], block["codec"]
    )
    if not rows:
        return None
    index = random.randrange(len(rows))
    return {
        "id": f"{block['file_id']}:{block['block_no']}:{index}",
        "file_id": block["file_id"],
        "data": rows[index],
    }
