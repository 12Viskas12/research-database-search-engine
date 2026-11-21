import os

from app.db import database
from app.parsers.factory import get_parser
from app.services import (
    audit_service,
    compression_service,
    inbox_service,
    settings_service,
    vocab_service,
)
from app.services.ingestion_service import ingest

INGEST_KEY = 7353
TRY_LOCK = "SELECT pg_try_advisory_lock($1, $2)"
UNLOCK = "SELECT pg_advisory_unlock($1, $2)"
CANDIDATES = (
    "SELECT id FROM files WHERE status = 'done' AND NOT packed AND error IS NULL "
    "AND rows_count > 0 AND created_at < now() - make_interval(days => $1) "
    "ORDER BY id LIMIT 5"
)
ORPHANS = (
    "SELECT id, status, packed, path FROM files "
    "WHERE status IN ('processing', 'packing', 'unpacking', 'deleting')"
)
INTERRUPTED = "Operation interrupted by a restart, run it again"


async def autopack(file_id, method):
    await database.set_file_status(file_id, "packing")
    try:
        await compression_service.pack_file(file_id, method)
    except Exception:
        return
    await audit_service.log(None, "autopack", name="system", file=file_id, method=method)


async def run_ingest(record):
    file_id = record["id"]
    await database.set_file_status(file_id, "processing")
    try:
        count = await ingest(file_id, get_parser(record["path"]).parse())
    except Exception as e:
        await database.set_file_status(file_id, "failed", error=str(e))
        raise
    await database.set_file_status(file_id, "done", rows_count=count)
    config = await settings_service.autopack()
    if config["enabled"] and config["days"] == 0 and count > 0:
        await autopack(file_id, config["method"])


async def process_file(ctx, file_id):
    record = await database.get_file(file_id)
    if record is None:
        return
    async with database.get_pool().acquire() as conn:
        if not await conn.fetchval(TRY_LOCK, INGEST_KEY, file_id):
            return
        try:
            await run_ingest(record)
        finally:
            await conn.fetchval(UNLOCK, INGEST_KEY, file_id)


async def pack_file(ctx, file_id, method="bz2"):
    await compression_service.pack_file(file_id, method)


async def unpack_file(ctx, file_id):
    await compression_service.unpack_file(file_id)


async def merge_files(ctx, target_id, source_ids, method="bz2"):
    await compression_service.merge_files(target_id, source_ids, method)


async def reclaim_space(ctx):
    await compression_service.reclaim()


async def delete_file(ctx, file_id):
    record = await database.get_file(file_id)
    if record is None:
        return
    try:
        async with database.get_pool().acquire() as conn:
            async with conn.transaction():
                await compression_service.lock(conn, [file_id])
                await conn.execute("DELETE FROM files WHERE id = $1", file_id)
    except Exception as e:
        await database.set_file_status(file_id, "failed", error=str(e))
        raise
    if record["path"]:
        try:
            os.remove(record["path"])
        except OSError:
            pass


async def rebuild_vocab(ctx):
    words = await vocab_service.rebuild()
    await audit_service.log(None, "vocab_rebuilt", name="system", words=words)


async def autopack_files(ctx):
    config = await settings_service.autopack()
    if not config["enabled"]:
        return
    rows = await database.get_pool().fetch(CANDIDATES, config["days"])
    for row in rows:
        await autopack(row["id"], config["method"])


async def recover(ctx):
    queue = ctx.get("redis")
    async with database.get_pool().acquire() as conn:
        for row in await conn.fetch(ORPHANS):
            key = INGEST_KEY if row["status"] == "processing" else compression_service.LOCK_KEY
            if not await conn.fetchval(TRY_LOCK, key, row["id"]):
                continue
            try:
                await recover_one(queue, row)
            finally:
                await conn.fetchval(UNLOCK, key, row["id"])


async def recover_one(queue, row):
    file_id, status = row["id"], row["status"]
    if status == "processing":
        if row["path"] and os.path.exists(row["path"]) and queue is not None:
            await database.set_file_status(file_id, "pending")
            await queue.enqueue_job("process_file", file_id)
        else:
            await database.set_file_status(file_id, "failed", error=INTERRUPTED)
    elif status == "deleting":
        if queue is not None:
            await queue.enqueue_job("delete_file", file_id)
    elif status == "packing" and not row["packed"] and not row["path"]:
        await database.set_file_status(file_id, "failed", error=INTERRUPTED)
    else:
        await database.set_file_status(file_id, "done", error=INTERRUPTED)
    await audit_service.log(None, "file_recovered", name="system", file=file_id, was=status)


async def scan_inbox(ctx):
    queue = ctx.get("redis")
    if queue is not None:
        await inbox_service.scan(queue)
