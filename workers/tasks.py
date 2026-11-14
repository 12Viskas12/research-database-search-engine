from app.db import database
from app.parsers.factory import get_parser
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
