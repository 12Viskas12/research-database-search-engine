from app.db import database

KEEP = 200
ADD = (
    "INSERT INTO search_history (user_id, query, files, source, results) "
    "VALUES ($1, $2, $3, $4, $5) RETURNING id"
)
TRIM = (
    "DELETE FROM search_history WHERE user_id = $1 AND id < "
    "COALESCE((SELECT min(id) FROM (SELECT id FROM search_history "
    "WHERE user_id = $1 ORDER BY id DESC LIMIT $2) t), 0)"
)
LIST = (
    "SELECT id, query, files, source, results, at FROM search_history "
    "WHERE user_id = $1 ORDER BY id DESC LIMIT 100"
)
CLEAR = "DELETE FROM search_history WHERE user_id = $1"
MISSED_ADD = "INSERT INTO missed_queries (query, files, user_id, source) VALUES ($1, $2, $3, $4)"
MISSED_TRIM = (
    "DELETE FROM missed_queries WHERE id <= COALESCE((SELECT id FROM missed_queries "
    "ORDER BY id DESC OFFSET 999 LIMIT 1), 0)"
)
MISSED_TOP = (
    "SELECT lower(query) AS query, count(*)::int AS n, max(at) AS last FROM missed_queries "
    "GROUP BY lower(query) ORDER BY n DESC, last DESC LIMIT 50"
)
MISSED_CLEAR = "DELETE FROM missed_queries"
VALID = (
    "SELECT 1 FROM search_history WHERE id = $1 AND user_id = $2 AND query = $3 "
    "AND files = $4 AND at > now() - interval '1 hour'"
)


def scope(files):
    return ",".join(str(i) for i in sorted(set(files or [])))


async def add(user_id, query, files, source, results):
    pool = database.get_pool()
    row_id = await pool.fetchval(ADD, user_id, query, scope(files), source, results)
    await pool.execute(TRIM, user_id, KEEP)
    return row_id


async def valid(search_id, user_id, query, files):
    if not search_id:
        return False
    row = await database.get_pool().fetchval(
        VALID, search_id, user_id, query, scope(files)
    )
    return row is not None


async def items(user_id):
    return [dict(r) for r in await database.get_pool().fetch(LIST, user_id)]


async def clear(user_id):
    await database.get_pool().execute(CLEAR, user_id)


async def missed(user_id, query, files, source):
    pool = database.get_pool()
    await pool.execute(MISSED_ADD, query, scope(files), user_id, source)
    await pool.execute(MISSED_TRIM)


async def missed_top():
    return [dict(r) for r in await database.get_pool().fetch(MISSED_TOP)]


async def missed_clear():
    await database.get_pool().execute(MISSED_CLEAR)
