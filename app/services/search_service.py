from app.db import database

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
    pool = database.get_pool()
    rows = await pool.fetch(FTS_SQL, query, limit, offset)
    if not rows:
        rows = await pool.fetch(LIKE_SQL, _like_pattern(query), limit, offset)
    return [dict(r) for r in rows]
