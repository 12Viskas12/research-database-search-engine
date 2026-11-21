import json

from app.db import database
from app.services import audit_service, normalize, vocab_service
from app.services.auth_service import AuthError

GET = "SELECT id, file_id, data FROM records WHERE id = $1"
UPDATE = "UPDATE records SET data = $2, search_text = $3 WHERE id = $1"
HIDE = "UPDATE records SET hidden = $2 WHERE id = $1"
DELETE = "DELETE FROM records WHERE id = $1 RETURNING file_id"
DECREMENT = "UPDATE files SET rows_count = GREATEST(rows_count - 1, 0) WHERE id = $1"
MAX_KEYS = 100
MAX_VALUE = 10000
MAX_BYTES = 100000


def live_id(record_id):
    try:
        return int(record_id)
    except (TypeError, ValueError):
        raise AuthError("Record is in a compressed file, unpack the file first", 409)


def clean_data(data):
    if not isinstance(data, dict) or not data or len(data) > MAX_KEYS:
        raise AuthError("Record must be an object with 1 to 100 fields")
    out = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 100:
            raise AuthError("Invalid field name")
        if isinstance(value, (dict, list)):
            raise AuthError("Field values must be text, numbers or empty")
        if isinstance(value, str) and len(value) > MAX_VALUE:
            raise AuthError("Field value is too long")
        out[key.strip()] = value
    if len(json.dumps(out, ensure_ascii=False)) > MAX_BYTES:
        raise AuthError("Record is too large")
    return out


def search_text(data):
    values = [str(v) for v in data.values() if v not in (None, "")]
    return " ".join([*values, normalize.index_extra(values)]).strip()


def snapshot(data):
    return json.dumps(data, ensure_ascii=False)[:2000]


async def load(conn, record_id):
    row = await conn.fetchrow(GET, record_id)
    if row is None:
        raise AuthError("Record not found", 404)
    return row


async def edit(admin, record_id, data):
    record_id = live_id(record_id)
    data = clean_data(data)
    text = search_text(data)
    async with database.get_pool().acquire() as conn:
        row = await load(conn, record_id)
        await conn.execute(UPDATE, record_id, data, text)
    await vocab_service.add_texts([text])
    await audit_service.log(
        admin,
        "record_edited",
        record=record_id,
        file=row["file_id"],
        before=snapshot(row["data"]),
    )


async def hide(admin, record_id, hidden):
    record_id = live_id(record_id)
    async with database.get_pool().acquire() as conn:
        row = await load(conn, record_id)
        await conn.execute(HIDE, record_id, hidden)
    await audit_service.log(
        admin,
        "record_hidden" if hidden else "record_unhidden",
        record=record_id,
        file=row["file_id"],
    )


async def delete(admin, record_id):
    record_id = live_id(record_id)
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            row = await load(conn, record_id)
            await conn.fetchval(DELETE, record_id)
            await conn.execute(DECREMENT, row["file_id"])
    await audit_service.log(
        admin,
        "record_deleted",
        record=record_id,
        file=row["file_id"],
        before=snapshot(row["data"]),
    )
