import asyncio
import os
import shutil
from contextlib import asynccontextmanager

from app.db import database
from app.parsers.factory import get_parser
from app.services import (
    audit_service,
    archive_service,
    compression_service,
    download_service,
    inbox_service,
    intake_service,
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
    "WHERE status IN ('processing', 'packing', 'unpacking', 'deleting', 'downloading', 'extracting')"
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
        count = await ingest(file_id, get_parser(record["path"]))
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


@asynccontextmanager
async def held(file_id):
    async with database.get_pool().acquire() as conn:
        taken = await conn.fetchval(TRY_LOCK, INGEST_KEY, file_id)
        try:
            yield taken
        finally:
            if taken:
                await conn.fetchval(UNLOCK, INGEST_KEY, file_id)


async def expand_archive(ctx, file_id):
    async with held(file_id) as taken:
        if taken:
            await intake_service.expand(ctx["redis"], file_id)


async def download_file(ctx, file_id, url):
    async with held(file_id) as taken:
        if taken:
            await fetch_and_register(ctx["redis"], file_id, url)


async def fetch_and_register(queue, file_id, url):
    pool = database.get_pool()
    try:
        path, name = await download_service.run(file_id, url)
    except Exception as e:
        await database.set_file_status(file_id, "failed", error=str(e))
        return
    target = intake_service.stored_path(name)
    await asyncio.to_thread(shutil.move, path, target)
    path = target
    await pool.execute("UPDATE files SET name = $2, path = $3, progress = 0 WHERE id = $1", file_id, name, path)
    if await asyncio.to_thread(archive_service.detect, path, name):
        await database.set_file_status(file_id, "extracting")
        await intake_service.expand(queue, file_id)
        return
    sha = await asyncio.to_thread(intake_service.file_hash, path)
    duplicate = await database.find_duplicate(sha)
    error = None
    if duplicate:
        error = f"Already uploaded as {duplicate['name']}"
    else:
        try:
            get_parser(path)
        except ValueError as e:
            error = str(e)
    if error:
        await asyncio.to_thread(intake_service.remove, path)
        await pool.execute("UPDATE files SET path = '' WHERE id = $1", file_id)
        await database.set_file_status(file_id, "failed", error=error)
        return
    await pool.execute("UPDATE files SET sha256 = $2 WHERE id = $1", file_id, sha)
    await database.set_file_status(file_id, "pending")
    await queue.enqueue_job("process_file", file_id)


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
            key = INGEST_KEY if row["status"] in ("processing", "downloading", "extracting") else compression_service.LOCK_KEY
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
    elif status in ("downloading", "extracting"):
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
