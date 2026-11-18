import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time

import asyncpg

from app.core.config import settings
from app.db import database

ROLES = ("user", "vip", "admin")
REQUEST_ROLES = ("user", "vip")
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
UNLIMITED = 2**31 - 1
RANKS = (
    (0, "Новичок"),
    (10, "Следопыт"),
    (50, "Сыщик"),
    (200, "Детектив"),
    (1000, "Шерлок"),
)
WINDOW = 600
MAX_FAILS = 8
ATTEMPTS = {}

TODAY_SQL = "(now() AT TIME ZONE 'UTC')::date"
CREATE_USER = (
    "INSERT INTO users (username, pass_hash, role, tg_id) VALUES ($1, $2, $3, $4) "
    "RETURNING id, username, role, tg_id"
)
UPSERT_ADMIN = (
    "INSERT INTO users (username, pass_hash, role) VALUES ($1, $2, 'admin') "
    "ON CONFLICT (lower(username)) DO UPDATE SET role = 'admin' "
    "RETURNING id, (xmax = 0) AS created"
)
USER_BY_NAME = (
    "SELECT id, username, pass_hash, role, tg_id FROM users WHERE lower(username) = lower($1)"
)
USER_BY_SESSION = (
    "SELECT u.id, u.username, u.role, u.tg_id FROM sessions s JOIN users u ON u.id = s.user_id "
    "WHERE s.token_hash = $1 AND s.expires_at > now()"
)
USER_BY_TG = "SELECT id, username, role, tg_id FROM users WHERE tg_id = $1"
NEW_SESSION = (
    "INSERT INTO sessions (token_hash, user_id, expires_at) "
    "VALUES ($1, $2, now() + make_interval(days => $3))"
)
DROP_SESSION = "DELETE FROM sessions WHERE token_hash = $1"
DROP_EXPIRED = "DELETE FROM sessions WHERE expires_at < now()"
CLAIM_INVITE = (
    "UPDATE invites SET used_at = now() WHERE token = $1 AND used_at IS NULL "
    "AND expires_at > now() RETURNING id, role, tg_id"
)
LINK_INVITE = "UPDATE invites SET used_by = $2 WHERE id = $1"
NEW_INVITE = (
    "INSERT INTO invites (token, role, tg_id, note, created_by, expires_at) "
    "VALUES ($1, $2, $3, $4, $5, now() + make_interval(hours => $6)) "
    "RETURNING id, token, role, expires_at"
)
LIST_INVITES = (
    "SELECT i.id, i.token, i.role, i.tg_id, i.note, i.created_at, i.expires_at, i.used_at, "
    "u.username AS used_by_name FROM invites i LEFT JOIN users u ON u.id = i.used_by "
    "ORDER BY i.id DESC LIMIT 100"
)
DELETE_INVITE = "DELETE FROM invites WHERE id = $1 AND used_at IS NULL RETURNING id"
BUMP = (
    f"INSERT INTO search_usage (user_id, day, count) VALUES ($1, {TODAY_SQL}, 1) "
    "ON CONFLICT (user_id, day) DO UPDATE SET count = search_usage.count + 1 "
    "WHERE search_usage.count < $2 RETURNING count"
)
USED_TODAY = (
    "SELECT COALESCE((SELECT count FROM search_usage "
    f"WHERE user_id = $1 AND day = {TODAY_SQL}), 0)"
)
USED_TOTAL = "SELECT COALESCE(sum(count), 0)::int FROM search_usage WHERE user_id = $1"
NEW_REQUEST = (
    "INSERT INTO access_requests (tg_id, tg_username, message) VALUES ($1, $2, $3) "
    "ON CONFLICT (tg_id) WHERE status = 'pending' DO NOTHING RETURNING id"
)
LAST_REQUEST = (
    "SELECT r.id, r.status, r.created_at, i.token, i.role, i.expires_at, i.used_at "
    "FROM access_requests r LEFT JOIN invites i ON i.id = r.invite_id "
    "WHERE r.tg_id = $1 ORDER BY r.id DESC LIMIT 1"
)
LIST_REQUESTS = (
    "SELECT id, tg_id, tg_username, message, status, created_at, decided_at "
    "FROM access_requests ORDER BY (status = 'pending') DESC, id DESC LIMIT 100"
)
GET_REQUEST = "SELECT id, tg_id, tg_username, status FROM access_requests WHERE id = $1 FOR UPDATE"
DECIDE = (
    "UPDATE access_requests SET status = $2, invite_id = $3, decided_at = now() WHERE id = $1"
)
DELIVERIES = (
    "SELECT r.id, r.tg_id, r.status, i.token, i.role, i.expires_at "
    "FROM access_requests r LEFT JOIN invites i ON i.id = r.invite_id "
    "WHERE r.status IN ('approved', 'rejected') AND NOT r.notified ORDER BY r.id LIMIT 20"
)
MARK_NOTIFIED = "UPDATE access_requests SET notified = TRUE WHERE id = $1"
LIST_USERS = (
    "SELECT u.id, u.username, u.role, u.tg_id, u.created_at, "
    "COALESCE((SELECT count FROM search_usage s WHERE s.user_id = u.id "
    f"AND s.day = {TODAY_SQL}), 0) AS today, "
    "COALESCE((SELECT sum(count) FROM search_usage s WHERE s.user_id = u.id), 0)::int AS total "
    "FROM users u ORDER BY u.id"
)
GET_USER = "SELECT id, role FROM users WHERE id = $1"
SET_ROLE = "UPDATE users SET role = $2 WHERE id = $1"
DELETE_USER = "DELETE FROM users WHERE id = $1"
COUNT_ADMINS = "SELECT count(*)::int FROM users WHERE role = 'admin'"


class AuthError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def b64(data):
    return base64.b64encode(data).decode()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${b64(salt)}${b64(digest)}"


def check_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


DUMMY_HASH = hash_password("dummy-password")


def new_token():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return "-".join(raw[i : i + 4] for i in range(0, 12, 4))


def normalize_token(value):
    raw = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def session_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def limit_for(role):
    return {"user": settings.quota_user, "vip": settings.quota_vip}.get(role)


def quota_info(role, used):
    limit = limit_for(role)
    return {
        "limit": limit,
        "used": used,
        "remaining": None if limit is None else max(0, limit - used),
    }


def rank_info(total):
    index = max(i for i, (start, _) in enumerate(RANKS) if start <= total)
    upcoming = RANKS[index + 1] if index + 1 < len(RANKS) else None
    return {
        "title": RANKS[index][1],
        "total": total,
        "next_at": upcoming[0] if upcoming else None,
        "next_title": upcoming[1] if upcoming else None,
    }


def public_user(row):
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def throttled(key):
    now = time.monotonic()
    if len(ATTEMPTS) > 10000:
        ATTEMPTS.clear()
    recent = [t for t in ATTEMPTS.get(key, []) if now - t < WINDOW]
    ATTEMPTS[key] = recent
    return len(recent) >= MAX_FAILS


def validate_credentials(username, password):
    if not USERNAME.match(username):
        raise AuthError("Логин: 3-32 символа, латиница, цифры, _ . -")
    if not 8 <= len(password) <= 128:
        raise AuthError("Пароль: от 8 до 128 символов")


async def create_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    await conn.execute(NEW_SESSION, session_hash(token), user_id, settings.session_days)
    return token


async def register(token, username, password):
    username = (username or "").strip()
    password = password or ""
    validate_credentials(username, password)
    pass_hash = await asyncio.to_thread(hash_password, password)
    try:
        async with database.get_pool().acquire() as conn:
            async with conn.transaction():
                invite = await conn.fetchrow(CLAIM_INVITE, normalize_token(token))
                if invite is None:
                    raise AuthError("Токен недействителен или истек")
                user = await conn.fetchrow(
                    CREATE_USER, username, pass_hash, invite["role"], invite["tg_id"]
                )
                await conn.execute(LINK_INVITE, invite["id"], user["id"])
                session = await create_session(conn, user["id"])
    except asyncpg.UniqueViolationError as e:
        if "tg" in (e.constraint_name or ""):
            raise AuthError("Этот Telegram уже привязан к другому аккаунту")
        raise AuthError("Логин уже занят")
    return public_user(user), session


async def login(username, password, ip):
    key = (ip, (username or "").strip().lower())
    if throttled(key):
        raise AuthError("Слишком много попыток, подождите несколько минут", 429)
    pool = database.get_pool()
    row = await pool.fetchrow(USER_BY_NAME, (username or "").strip())
    ok = await asyncio.to_thread(
        check_password, password or "", row["pass_hash"] if row else DUMMY_HASH
    )
    if not row or not ok:
        ATTEMPTS.setdefault(key, []).append(time.monotonic())
        raise AuthError("Неверный логин или пароль", 401)
    ATTEMPTS.pop(key, None)
    await pool.execute(DROP_EXPIRED)
    async with pool.acquire() as conn:
        session = await create_session(conn, row["id"])
    return public_user(row), session


async def logout(token):
    if token:
        await database.get_pool().execute(DROP_SESSION, session_hash(token))


async def user_by_session(token):
    if not token:
        return None
    row = await database.get_pool().fetchrow(USER_BY_SESSION, session_hash(token))
    return dict(row) if row else None


async def user_by_tg(tg_id):
    row = await database.get_pool().fetchrow(USER_BY_TG, tg_id)
    return dict(row) if row else None


async def consume(user):
    limit = limit_for(user["role"])
    used = await database.get_pool().fetchval(
        BUMP, user["id"], UNLIMITED if limit is None else limit
    )
    if used is None:
        raise AuthError(
            f"Лимит на сегодня исчерпан ({limit}). Сброс в 00:00 UTC.", 429
        )
    return quota_info(user["role"], used)


async def profile(user):
    pool = database.get_pool()
    used = await pool.fetchval(USED_TODAY, user["id"])
    total = await pool.fetchval(USED_TOTAL, user["id"])
    return {
        **public_user(user),
        "tg_linked": user["tg_id"] is not None,
        "quota": quota_info(user["role"], used),
        "rank": rank_info(total),
    }


async def bootstrap_admin():
    pool = database.get_pool()
    if await pool.fetchval(COUNT_ADMINS):
        return
    name = settings.admin_username.strip() or "admin"
    generated = not settings.admin_password
    password = settings.admin_password or secrets.token_urlsafe(9)
    pass_hash = await asyncio.to_thread(hash_password, password)
    row = await pool.fetchrow(UPSERT_ADMIN, name, pass_hash)
    if not row["created"]:
        print(f"ADMIN READY: existing user {name} is now admin", flush=True)
    elif generated:
        print(f"ADMIN READY: login={name} password={password}", flush=True)
    else:
        print(f"ADMIN READY: login={name} password from ADMIN_PASSWORD", flush=True)


async def create_invite(role, note, admin_id, tg_id=None, conn=None):
    if role not in ROLES:
        raise AuthError("Неизвестная роль")
    runner = conn or database.get_pool()
    row = await runner.fetchrow(
        NEW_INVITE,
        new_token(),
        role,
        tg_id,
        (note or "").strip()[:200] or None,
        admin_id,
        settings.invite_hours,
    )
    return dict(row)


async def list_invites():
    return [dict(r) for r in await database.get_pool().fetch(LIST_INVITES)]


async def delete_invite(invite_id):
    if await database.get_pool().fetchval(DELETE_INVITE, invite_id) is None:
        raise AuthError("Токен не найден или уже использован", 404)


async def create_request(tg_id, tg_username, message):
    if await user_by_tg(tg_id):
        return "account"
    created = await database.get_pool().fetchval(
        NEW_REQUEST, tg_id, tg_username, (message or "").strip()[:200] or None
    )
    return "created" if created else "pending"


async def request_status(tg_id):
    user = await user_by_tg(tg_id)
    if user:
        used = await database.get_pool().fetchval(USED_TODAY, user["id"])
        return {"state": "account", "user": user, "quota": quota_info(user["role"], used)}
    row = await database.get_pool().fetchrow(LAST_REQUEST, tg_id)
    if row is None:
        return {"state": "none"}
    return {"state": row["status"], "request": dict(row)}


async def list_requests():
    return [dict(r) for r in await database.get_pool().fetch(LIST_REQUESTS)]


async def approve_request(request_id, role, admin_id):
    if role not in REQUEST_ROLES:
        raise AuthError("По заявке можно выдать только роль user или vip")
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(GET_REQUEST, request_id)
            if row is None:
                raise AuthError("Заявка не найдена", 404)
            if row["status"] != "pending":
                raise AuthError("Заявка уже обработана", 409)
            who = f"@{row['tg_username']}" if row["tg_username"] else str(row["tg_id"])
            invite = await create_invite(
                role, f"заявка #{request_id} {who}", admin_id, row["tg_id"], conn
            )
            await conn.execute(DECIDE, request_id, "approved", invite["id"])
    return invite


async def reject_request(request_id):
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(GET_REQUEST, request_id)
            if row is None:
                raise AuthError("Заявка не найдена", 404)
            if row["status"] != "pending":
                raise AuthError("Заявка уже обработана", 409)
            await conn.execute(DECIDE, request_id, "rejected", None)


async def deliveries():
    return [dict(r) for r in await database.get_pool().fetch(DELIVERIES)]


async def mark_notified(request_id):
    await database.get_pool().execute(MARK_NOTIFIED, request_id)


async def list_users():
    return [dict(r) for r in await database.get_pool().fetch(LIST_USERS)]


async def guard_admin(conn, user_id, acting_id):
    target = await conn.fetchrow(GET_USER, user_id)
    if target is None:
        raise AuthError("Пользователь не найден", 404)
    if user_id == acting_id:
        raise AuthError("Нельзя менять или удалять самого себя")
    if target["role"] == "admin" and await conn.fetchval(COUNT_ADMINS) <= 1:
        raise AuthError("Нельзя убрать последнего админа")


async def set_role(user_id, role, acting_id):
    if role not in ROLES:
        raise AuthError("Неизвестная роль")
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            await guard_admin(conn, user_id, acting_id)
            await conn.execute(SET_ROLE, user_id, role)


async def delete_user(user_id, acting_id):
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            await guard_admin(conn, user_id, acting_id)
            await conn.execute(DELETE_USER, user_id)
