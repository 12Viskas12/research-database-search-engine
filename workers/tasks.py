from app.db import database
from app.parsers.factory import get_parser
from app.services import audit_service, compression_service, settings_service, vocab_service
from app.services.ingestion_service import ingest

CANDIDATES = (
    "SELECT id FROM files WHERE status = 'done' AND NOT packed AND error IS NULL "
    "AND rows_count > 0 AND created_at < now() - make_interval(days => $1) "
    "ORDER BY id LIMIT 5"
)


async def autopack(file_id, method):
    await database.set_file_status(file_id, "packing")
    try:
        await compression_service.pack_file(file_id, method)
    except Exception:
        return
    await audit_service.log(None, "autopack", name="system", file=file_id, method=method)


async def process_file(ctx, file_id):
    record = await database.get_file(file_id)
    if record is None:
        return
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


async def pack_file(ctx, file_id, method="bz2"):
    await compression_service.pack_file(file_id, method)


async def unpack_file(ctx, file_id):
    await compression_service.unpack_file(file_id)


async def merge_files(ctx, target_id, source_ids, method="bz2"):
    await compression_service.merge_files(target_id, source_ids, method)


async def reclaim_space(ctx):
    await compression_service.reclaim()


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
