import os

from app.core import metrics
from app.core.config import settings
from app.core.redis_client import get_redis
from app.db import database

USERS = "SELECT role, count(*)::int AS n FROM users GROUP BY role"
BLOCKED = "SELECT count(*)::int FROM users WHERE blocked"
FILES = "SELECT status, count(*)::int AS n FROM files GROUP BY status"
TOTALS = (
    "SELECT COALESCE(sum(rows_count) FILTER (WHERE status = 'done'), 0)::bigint AS records, "
    "count(*) FILTER (WHERE packed)::int AS packed, "
    "COALESCE(sum(packed_bytes) FILTER (WHERE packed), 0)::bigint AS packed_bytes "
    "FROM files"
)
SEARCHES = "SELECT COALESCE(sum(searches), 0)::bigint FROM stats_daily"
TODAY = (
    "SELECT COALESCE(sum(searches), 0)::int FROM stats_daily "
    "WHERE day = (now() AT TIME ZONE 'UTC')::date"
)
MISSED = "SELECT count(*)::bigint FROM missed_queries"
HIDDEN = "SELECT count(*)::bigint FROM records WHERE hidden"
SESSIONS = "SELECT count(*)::int FROM sessions WHERE expires_at > now()"
DB_SIZE = "SELECT pg_database_size(current_database())::bigint"
REQUESTS = "SELECT count(*)::int FROM access_requests WHERE status = 'pending'"


async def safe(coro, default=0):
    try:
        return await coro
    except Exception:
        return default


async def collect():
    pool = database.get_pool()
    out = metrics.render_http()

    out += metrics.head("viskas_up", "gauge", "Dependency state")
    out.append(metrics.line("viskas_up", 1 if await safe(pool.fetchval("SELECT 1")) else 0, target="postgres"))
    queue = 0
    redis_ok = 0
    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = 1
        queue = await redis.zcard("arq:queue")
    except Exception:
        pass
    out.append(metrics.line("viskas_up", redis_ok, target="redis"))

    out += metrics.head("viskas_queue_jobs", "gauge", "Jobs waiting in the queue")
    out.append(metrics.line("viskas_queue_jobs", queue))

    out += metrics.head("viskas_users", "gauge", "Users by role")
    for row in await safe(pool.fetch(USERS), []):
        out.append(metrics.line("viskas_users", row["n"], role=row["role"]))
    out += metrics.head("viskas_users_blocked", "gauge", "Blocked users")
    out.append(metrics.line("viskas_users_blocked", await safe(pool.fetchval(BLOCKED))))
    out += metrics.head("viskas_sessions_active", "gauge", "Active sessions")
    out.append(metrics.line("viskas_sessions_active", await safe(pool.fetchval(SESSIONS))))
    out += metrics.head("viskas_access_requests_pending", "gauge", "Pending access requests")
    out.append(metrics.line("viskas_access_requests_pending", await safe(pool.fetchval(REQUESTS))))

    out += metrics.head("viskas_files", "gauge", "Files by status")
    for row in await safe(pool.fetch(FILES), []):
        out.append(metrics.line("viskas_files", row["n"], status=row["status"]))
    totals = await safe(pool.fetchrow(TOTALS), None)
    out += metrics.head("viskas_records", "gauge", "Records in done files")
    out.append(metrics.line("viskas_records", totals["records"] if totals else 0))
    out += metrics.head("viskas_files_packed", "gauge", "Packed files")
    out.append(metrics.line("viskas_files_packed", totals["packed"] if totals else 0))
    out += metrics.head("viskas_records_hidden", "gauge", "Hidden records")
    out.append(metrics.line("viskas_records_hidden", await safe(pool.fetchval(HIDDEN))))

    out += metrics.head("viskas_searches_total", "counter", "Searches made")
    out.append(metrics.line("viskas_searches_total", await safe(pool.fetchval(SEARCHES))))
    out += metrics.head("viskas_searches_today", "gauge", "Searches today (UTC)")
    out.append(metrics.line("viskas_searches_today", await safe(pool.fetchval(TODAY))))
    out += metrics.head("viskas_missed_queries_total", "counter", "Searches without results")
    out.append(metrics.line("viskas_missed_queries_total", await safe(pool.fetchval(MISSED))))

    out += metrics.head("viskas_database_bytes", "gauge", "Database size")
    out.append(metrics.line("viskas_database_bytes", await safe(pool.fetchval(DB_SIZE))))

    newest = 0
    base = settings.backup_dir
    try:
        for entry in os.scandir(base):
            if entry.is_file() and entry.name.endswith(".sql.gz"):
                newest = max(newest, entry.stat().st_mtime)
    except OSError:
        pass
    out += metrics.head("viskas_last_backup_timestamp_seconds", "gauge", "Newest backup time")
    out.append(metrics.line("viskas_last_backup_timestamp_seconds", int(newest)))
    return "\n".join(out) + "\n"
