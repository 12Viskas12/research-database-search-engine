from app.db import database
from app.parsers.factory import get_parser
from app.services import compression_service
from app.services.ingestion_service import ingest


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


async def pack_file(ctx, file_id, method="bz2"):
    await compression_service.pack_file(file_id, method)


async def unpack_file(ctx, file_id):
    await compression_service.unpack_file(file_id)


async def merge_files(ctx, target_id, source_ids, method="bz2"):
    await compression_service.merge_files(target_id, source_ids, method)


async def reclaim_space(ctx):
    await compression_service.reclaim()
