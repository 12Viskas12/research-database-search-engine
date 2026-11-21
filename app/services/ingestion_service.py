import asyncio
import os
import time

import pandas as pd

from app.core.config import settings
from app.db import database
from app.services import normalize, vocab_service
from app.services.cleaner import clean_dataframe

BATCH = 5000
MIN_PER_WORKER = 25000
RECHECK = 2
INSERT = (
    "INSERT INTO records (file_id, data, search_text) "
    "SELECT $1::int, d::jsonb, s FROM unnest($2::text[], $3::text[]) AS t(d, s)"
)


def _build(file_id, rows):
    df = clean_dataframe(pd.DataFrame(list(rows)))
    records = []
    for row in df.to_dict("records"):
        data = {k: v for k, v in row.items() if isinstance(v, str)}
        if data:
            text = " ".join([*data.values(), normalize.index_extra(data.values())])
            records.append((file_id, data, text.strip()))
    return records


def _serialize(records):
    return [(database._dump(data), text) for _, data, text in records]


class Progress:
    def __init__(self, file_id, total):
        self.file_id = file_id
        self.total = max(1, total)
        self.done = 0
        self.last = -1

    async def add(self, count):
        self.done += count
        percent = min(99, self.done * 100 // self.total)
        if percent != self.last:
            self.last = percent
            await database.set_file_progress(self.file_id, percent)


def cpu_count():
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def pick_workers(total, cpu, active, free, cap):
    by_size = max(1, total // MIN_PER_WORKER)
    by_cpu = max(1, cpu // max(1, active))
    return max(1, min(by_size, by_cpu, max(1, free - 1), cap))


class Governor:
    def __init__(self, total, cap):
        self.total = total
        self.cap = cap
        self.value = 1
        self.stamp = None

    async def allowed(self):
        now = time.monotonic()
        if self.stamp is None or now - self.stamp >= RECHECK:
            self.stamp = now
            pool = database.get_pool()
            active = await pool.fetchval("SELECT count(*) FROM files WHERE status = 'processing'")
            try:
                free = pool.get_max_size() - (pool.get_size() - pool.get_idle_size())
            except AttributeError:
                free = self.cap + 1
            self.value = pick_workers(self.total, cpu_count(), active or 1, free, self.cap)
        return self.value


async def _insert_batch(file_id, part):
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL synchronous_commit = off")
            await conn.execute(INSERT, file_id, [r[0] for r in part], [r[1] for r in part])


async def _worker(index, file_id, batches, progress, governor):
    while batches:
        if index >= await governor.allowed():
            await asyncio.sleep(0.5)
            continue
        try:
            part = batches.pop()
        except IndexError:
            return
        await _insert_batch(file_id, part)
        await progress.add(len(part))


async def ingest(file_id, rows):
    records = await asyncio.to_thread(_build, file_id, rows)
    total = len(records)
    pool = database.get_pool()
    await pool.execute("DELETE FROM records WHERE file_id = $1", file_id)
    if total:
        payload = await asyncio.to_thread(_serialize, records)
        batches = [payload[i : i + BATCH] for i in range(0, total, BATCH)]
        batches.reverse()
        cap = max(1, getattr(settings, "ingest_workers_max", 8))
        governor = Governor(total, cap)
        progress = Progress(file_id, total)
        tasks = [
            asyncio.create_task(_worker(i, file_id, batches, progress, governor))
            for i in range(cap)
        ]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await pool.execute("DELETE FROM records WHERE file_id = $1", file_id)
            raise
    await vocab_service.add_texts([r[2] for r in records])
    return total
