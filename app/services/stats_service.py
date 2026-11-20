from app.db import database

ROLES = "SELECT role, count(*)::int AS n FROM users GROUP BY role"
BLOCKED = "SELECT count(*)::int FROM users WHERE blocked"
FILES = (
    "SELECT count(*)::int AS files, "
    "count(*) FILTER (WHERE packed)::int AS packed, "
    "COALESCE(sum(rows_count) FILTER (WHERE status = 'done'), 0)::bigint AS records "
    "FROM files"
)
DB_SIZE = "SELECT pg_database_size(current_database())::bigint"
PER_DAY = (
    "SELECT d::date AS day, COALESCE(s.searches, 0)::int AS searches "
    "FROM generate_series((now() AT TIME ZONE 'UTC')::date - 29, "
    "(now() AT TIME ZONE 'UTC')::date, interval '1 day') d "
    "LEFT JOIN stats_daily s ON s.day = d::date ORDER BY d"
)
TOP_QUERIES = (
    "SELECT lower(query) AS query, count(*)::int AS n FROM search_history "
    "WHERE at > now() - interval '30 days' GROUP BY lower(query) "
    "ORDER BY n DESC, query LIMIT 10"
)
TOP_USERS = (
    "SELECT u.username, COALESCE(sum(s.count), 0)::int AS total FROM users u "
    "LEFT JOIN search_usage s ON s.user_id = u.id GROUP BY u.id "
    "HAVING COALESCE(sum(s.count), 0) > 0 ORDER BY total DESC, u.username LIMIT 10"
)


async def stats():
    pool = database.get_pool()
    roles = {r["role"]: r["n"] for r in await pool.fetch(ROLES)}
    files = dict(await pool.fetchrow(FILES))
    per_day = [dict(r) for r in await pool.fetch(PER_DAY)]
    return {
        "roles": roles,
        "blocked": await pool.fetchval(BLOCKED),
        "files": files,
        "db_bytes": await pool.fetchval(DB_SIZE),
        "per_day": per_day,
        "searches_30d": sum(r["searches"] for r in per_day),
        "searches_today": per_day[-1]["searches"] if per_day else 0,
        "top_queries": [dict(r) for r in await pool.fetch(TOP_QUERIES)],
        "top_users": [dict(r) for r in await pool.fetch(TOP_USERS)],
    }
