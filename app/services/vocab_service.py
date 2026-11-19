import asyncio
from collections import Counter

from app.db import database
from app.services import compression_service

WORD = compression_service.WORD
MIN_LEN = 3
MAX_LEN = 40
BATCH = 5000

UPSERT = (
    "INSERT INTO vocab (word, freq) SELECT * FROM unnest($1::text[], $2::int[]) "
    "ON CONFLICT (word) DO UPDATE SET freq = vocab.freq + EXCLUDED.freq"
)
INSERT = "INSERT INTO vocab (word, freq) SELECT * FROM unnest($1::text[], $2::int[])"
CLEAR = "DELETE FROM vocab"
ALL_TEXT = "SELECT search_text FROM records"
ALL_BLOCKS = "SELECT codec, payload FROM blocks"
IS_EMPTY = "SELECT NOT EXISTS (SELECT 1 FROM vocab)"
HAS_DATA = "SELECT EXISTS (SELECT 1 FROM records) OR EXISTS (SELECT 1 FROM blocks)"


def vocab_words(text):
    return [
        w
        for w in WORD.findall(text.lower())
        if MIN_LEN <= len(w) <= MAX_LEN and w.isalpha()
    ]


def count_texts(texts):
    counter = Counter()
    for text in texts:
        counter.update(vocab_words(text))
    return counter


async def write(conn, counter, query):
    words = sorted(counter)
    for i in range(0, len(words), BATCH):
        chunk = words[i : i + BATCH]
        await conn.execute(query, chunk, [counter[w] for w in chunk])


async def add_texts(texts):
    counter = await asyncio.to_thread(count_texts, texts)
    if not counter:
        return
    async with database.get_pool().acquire() as conn:
        await write(conn, counter, UPSERT)


async def needs_rebuild():
    pool = database.get_pool()
    return bool(await pool.fetchval(IS_EMPTY)) and bool(await pool.fetchval(HAS_DATA))


def count_block(payload, codec):
    counter = Counter()
    for row in compression_service.decode_block(payload, codec):
        counter.update(vocab_words(compression_service.row_text(row)))
    return counter


async def rebuild():
    counter = Counter()
    async with database.get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            batch = []
            async for record in conn.cursor(ALL_TEXT, prefetch=5000):
                batch.append(record["search_text"])
                if len(batch) >= 5000:
                    counter += await asyncio.to_thread(count_texts, batch)
                    batch = []
            if batch:
                counter += await asyncio.to_thread(count_texts, batch)
            async for block in conn.cursor(ALL_BLOCKS, prefetch=4):
                counter += await asyncio.to_thread(
                    count_block, block["payload"], block["codec"]
                )
    async with database.get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(CLEAR)
            await write(conn, counter, INSERT)
    return len(counter)
