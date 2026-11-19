from app.db import database

INSERT = (
    "INSERT INTO audit_log (actor_id, actor_name, action, details) VALUES ($1, $2, $3, $4)"
)
LIST = (
    "SELECT id, at, actor_id, actor_name, action, details FROM audit_log "
    "WHERE ($1::bigint IS NULL OR id < $1) "
    "AND ($2::text IS NULL OR action = $2) "
    "AND ($3::text IS NULL OR actor_name ILIKE $3) "
    "ORDER BY id DESC LIMIT $4"
)
ACTIONS = "SELECT DISTINCT action FROM audit_log ORDER BY action"


async def log(actor, action, **details):
    try:
        await database.get_pool().execute(
            INSERT,
            actor["id"] if actor else None,
            actor["username"] if actor else details.pop("name", None),
            action,
            details or None,
        )
    except Exception:
        pass


def like(value):
    value = (value or "").strip()
    if not value:
        return None
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def entries(before=None, action=None, actor=None, limit=50):
    rows = await database.get_pool().fetch(
        LIST, before, action or None, like(actor), limit + 1
    )
    items = [dict(r) for r in rows[:limit]]
    return {"items": items, "more": len(rows) > limit}


async def actions():
    return [r["action"] for r in await database.get_pool().fetch(ACTIONS)]
