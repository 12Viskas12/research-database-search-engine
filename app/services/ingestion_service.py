import asyncio

import pandas as pd

from app.db import database
from app.services.cleaner import clean_dataframe

BATCH = 1000


def _build(file_id, rows):
    df = clean_dataframe(pd.DataFrame(list(rows)))
    records = []
    for row in df.to_dict("records"):
        data = {k: v for k, v in row.items() if isinstance(v, str)}
        if data:
            records.append((file_id, data, " ".join(data.values())))
    return records


async def ingest(file_id, rows):
    records = await asyncio.to_thread(_build, file_id, rows)
    total = len(records)
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM records WHERE file_id = $1", file_id)
            for i in range(0, total, BATCH):
                await conn.executemany(
                    "INSERT INTO records (file_id, data, search_text) "
                    "VALUES ($1, $2, $3)",
                    records[i : i + BATCH],
                )
                await database.set_file_progress(
                    file_id, min(99, (i + BATCH) * 100 // total)
                )
    return total
