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
