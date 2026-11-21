import asyncio
import bz2
import functools
import hashlib
import json
import lzma
import re
import zlib

from app.db import database

CODECS = {
    "zlib": (lambda b: zlib.compress(b, 9), zlib.decompress),
    "lzma": (lambda b: lzma.compress(b, preset=6), lzma.decompress),
    "bz2": (lambda b: bz2.compress(b, 9), bz2.decompress),
}
BLOCK_ROWS = 2000
BLOCK_BYTES = 1 << 20
BLOOM_BITS = 8
BLOOM_HASHES = 5
LOCK_KEY = 7352
WORD = re.compile(r"\w+")

INSERT_BLOCK = (
    "INSERT INTO blocks (file_id, block_no, rows_count, raw_size, codec, bloom, payload) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7)"
)
LIVE_ROWS = "SELECT data FROM records WHERE file_id = $1 ORDER BY id"
PACKED_ROWS = "SELECT codec, payload FROM blocks WHERE file_id = $1 ORDER BY block_no"
SEARCH_BLOCKS = (
    "SELECT file_id, block_no, codec, bloom, payload FROM blocks "
    "WHERE ($1::int[] IS NULL OR file_id = ANY($1)) ORDER BY file_id, block_no"
)
SOURCES = (
    "SELECT id, name, packed, status, rows_count FROM files "
    "WHERE id = ANY($1::int[]) ORDER BY id"
)
READY = (
    "SELECT id, name, packed, status, rows_count FROM files "
    "WHERE status = 'done' ORDER BY id"
)
FILE_STATE = "SELECT packed, rows_count FROM files WHERE id = $1"
TRY_LOCK = "SELECT pg_try_advisory_xact_lock($1, $2)"
DELETE_RECORDS = "DELETE FROM records WHERE file_id = $1"
DELETE_BLOCKS = "DELETE FROM blocks WHERE file_id = $1"
DELETE_FILES = "DELETE FROM files WHERE id = ANY($1::int[])"
INSERT_RECORD = "INSERT INTO records (file_id, data, search_text) VALUES ($1, $2, $3)"
MARK_PACKED = (
    "UPDATE files SET packed = TRUE, codec = $2, rows_count = $3, raw_bytes = $4, "
    "packed_bytes = $5, status = 'done', progress = 100, error = NULL WHERE id = $1"
)
MARK_UNPACKED = (
    "UPDATE files SET packed = FALSE, codec = NULL, raw_bytes = 0, packed_bytes = 0, "
    "status = 'done', progress = 100, error = NULL WHERE id = $1"
)
STATS = (
    "SELECT count(*)::int AS files, "
    "(count(*) FILTER (WHERE packed))::int AS packed_files, "
    "COALESCE(sum(raw_bytes) FILTER (WHERE packed), 0)::bigint AS raw_bytes, "
    "COALESCE(sum(packed_bytes) FILTER (WHERE packed), 0)::bigint AS packed_bytes, "
    "pg_total_relation_size('records')::bigint AS records_size, "
    "pg_total_relation_size('blocks')::bigint AS blocks_size FROM files"
)


class CompressionError(Exception):
    pass


def check_method(method):
    if method not in CODECS:
        raise CompressionError(f"Unknown method: {method}")


def row_text(row):
    return " ".join(str(v) for v in row.values() if v is not None)


def words(text):
    return set(WORD.findall(text.lower()))


def approx_size(row):
    return sum(len(v) for v in row.values() if isinstance(v, str)) + 16 * len(row)


@functools.lru_cache(maxsize=65536)
def token_hashes(token):
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
    return int.from_bytes(digest[:8], "big"), int.from_bytes(digest[8:], "big") | 1


def bloom_positions(token, bits):
    h1, h2 = token_hashes(token)
    return [(h1 + i * h2) % bits for i in range(BLOOM_HASHES)]


def bloom_build(tokens):
    size = max(8, (len(tokens) * BLOOM_BITS + 7) // 8)
    data = bytearray(size)
    for token in tokens:
        for pos in bloom_positions(token, size * 8):
            data[pos >> 3] |= 1 << (pos & 7)
    return bytes(data)


def bloom_has(bloom, token):
    bits = len(bloom) * 8
    return all(bloom[pos >> 3] >> (pos & 7) & 1 for pos in bloom_positions(token, bits))


def bloom_all(bloom, terms):
    return all(bloom_has(bloom, term) for term in terms)


def bloom_accepts(bloom, spec):
    groups = spec.get("groups")
    if spec["mode"] not in ("all", "min") or not groups:
        return True
    hit = sum(1 for group in groups if any(bloom_has(bloom, w) for w in group))
    if spec["mode"] == "all":
        return hit == len(groups)
    return hit >= spec["min"]


def encode_block(rows, codec):
    lines, tokens = [], set()
    for row in rows:
        lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        tokens |= words(row_text(row))
    raw = "\n".join(lines).encode("utf-8", "replace")
    return {
        "rows": len(rows),
        "raw": len(raw),
        "bloom": bloom_build(tokens),
        "payload": CODECS[codec][0](raw),
    }


def decode_block(payload, codec):
    raw = CODECS[codec][1](payload).decode("utf-8")
    return [json.loads(line) for line in raw.split("\n")] if raw else []


def row_matches_filters(row, filters):
    for key, value in filters:
        if not any(
            k.lower() == key and isinstance(v, str) and value in v.lower()
            for k, v in row.items()
        ):
            return False
    return True


def scan_block(payload, codec, spec):
    mode = spec["mode"]
    groups = spec.get("groups") or []
    needle = spec.get("needle")
    filters = spec.get("filters") or []
    found = []
    for i, row in enumerate(decode_block(payload, codec)):
        if filters and not row_matches_filters(row, filters):
            continue
        if mode == "filter":
            found.append((i, row))
            continue
        text = row_text(row)
        if mode == "like":
            if needle in text.lower():
                found.append((i, row))
            continue
        present = words(text)
        hit = sum(1 for group in groups if not present.isdisjoint(group))
        enough = hit == len(groups) if mode == "all" else hit >= spec["min"]
        if enough:
            found.append((i, row))
    return found


async def live_rows(conn, file_id):
    async for record in conn.cursor(LIVE_ROWS, file_id, prefetch=1000):
        yield record["data"]


async def packed_rows(conn, file_id):
    async for record in conn.cursor(PACKED_ROWS, file_id, prefetch=4):
        rows = await asyncio.to_thread(decode_block, record["payload"], record["codec"])
        for row in rows:
            yield row


async def merged_rows(conn, sources):
    for source in sources:
        rows = packed_rows if source["packed"] else live_rows
        async for data in rows(conn, source["id"]):
            if "source_file" not in data:
                data = {**data, "source_file": source["name"]}
            yield data


async def write_blocks(conn, file_id, rows, codec, total, progress):
    stats = {"rows": 0, "raw": 0, "packed": 0}
    buf, size, number = [], 0, 0

    async def flush():
        nonlocal buf, size, number
        if not buf:
            return
        block = await asyncio.to_thread(encode_block, buf, codec)
        await conn.execute(
            INSERT_BLOCK,
            file_id,
            number,
            block["rows"],
            block["raw"],
            codec,
            block["bloom"],
            block["payload"],
        )
        number += 1
        stats["rows"] += block["rows"]
        stats["raw"] += block["raw"]
        stats["packed"] += len(block["payload"]) + len(block["bloom"])
        buf, size = [], 0
        if total:
            await progress(file_id, min(99, stats["rows"] * 100 // total))

    async for row in rows:
        buf.append(row)
        size += approx_size(row)
        if len(buf) >= BLOCK_ROWS or size >= BLOCK_BYTES:
            await flush()
    await flush()
    return stats


async def lock(conn, ids):
    for file_id in sorted(set(ids)):
        if not await conn.fetchval(TRY_LOCK, LOCK_KEY, file_id):
            raise CompressionError("File is busy")


async def pick_sources(file_ids):
    pool = database.get_pool()
    if file_ids:
        rows = await pool.fetch(SOURCES, list(set(file_ids)))
        if len(rows) != len(set(file_ids)):
            raise CompressionError("File not found")
        if any(r["status"] != "done" for r in rows):
            raise CompressionError("Some files are not ready")
    else:
        rows = await pool.fetch(READY)
    if len(rows) < 2:
        raise CompressionError("Need at least two files")
    return [dict(r) for r in rows]


async def pack_file(file_id, method="bz2"):
    check_method(method)
    try:
        async with database.get_pool().acquire() as conn:
            async with conn.transaction():
                await lock(conn, [file_id])
                state = await conn.fetchrow(FILE_STATE, file_id)
                if state is None:
                    raise CompressionError("File not found")
                if state["packed"]:
                    raise CompressionError("Already packed")
                await database.set_file_progress(file_id, 0)
                stats = await write_blocks(
                    conn,
                    file_id,
                    live_rows(conn, file_id),
                    method,
                    state["rows_count"],
                    database.set_file_progress,
                )
                await conn.execute(DELETE_RECORDS, file_id)
                await conn.execute(
                    MARK_PACKED, file_id, method, stats["rows"], stats["raw"], stats["packed"]
                )
    except Exception as e:
        await database.set_file_status(file_id, "done", error=str(e))
        raise


async def unpack_file(file_id):
    try:
        async with database.get_pool().acquire() as conn:
            async with conn.transaction():
                await lock(conn, [file_id])
                state = await conn.fetchrow(FILE_STATE, file_id)
                if state is None:
                    raise CompressionError("File not found")
                if not state["packed"]:
                    raise CompressionError("File is not packed")
                await database.set_file_progress(file_id, 0)
                batch, done, total = [], 0, state["rows_count"]
                async for data in packed_rows(conn, file_id):
                    batch.append((file_id, data, row_text(data)))
                    if len(batch) >= 1000:
                        await conn.executemany(INSERT_RECORD, batch)
                        done += len(batch)
                        batch = []
                        if total:
                            await database.set_file_progress(file_id, min(99, done * 100 // total))
                if batch:
                    await conn.executemany(INSERT_RECORD, batch)
                await conn.execute(DELETE_BLOCKS, file_id)
                await conn.execute(MARK_UNPACKED, file_id)
    except Exception as e:
        await database.set_file_status(file_id, "done", error=str(e))
        raise


async def merge_files(target_id, source_ids, method="bz2"):
    check_method(method)
    try:
        async with database.get_pool().acquire() as conn:
            async with conn.transaction():
                await lock(conn, [*source_ids, target_id])
                sources = [dict(r) for r in await conn.fetch(SOURCES, list(set(source_ids)))]
                if len(sources) != len(set(source_ids)) or len(sources) < 2:
                    raise CompressionError("Files changed, try again")
                if any(s["status"] != "done" for s in sources):
                    raise CompressionError("Some files are not ready")
                await database.set_file_progress(target_id, 0)
                stats = await write_blocks(
                    conn,
                    target_id,
                    merged_rows(conn, sources),
                    method,
                    sum(s["rows_count"] for s in sources),
                    database.set_file_progress,
                )
                await conn.execute(DELETE_FILES, [s["id"] for s in sources])
                await conn.execute(
                    MARK_PACKED, target_id, method, stats["rows"], stats["raw"], stats["packed"]
                )
    except Exception as e:
        await database.set_file_status(target_id, "failed", error=str(e))
        raise


async def search_packed(conn, spec, files, limit):
    hits = []
    async for block in conn.cursor(SEARCH_BLOCKS, files or None, prefetch=4):
        if not bloom_accepts(block["bloom"], spec):
            continue
        found = await asyncio.to_thread(
            scan_block, block["payload"], block["codec"], spec
        )
        for i, row in found:
            hits.append(
                {
                    "id": f"{block['file_id']}:{block['block_no']}:{i}",
                    "file_id": block["file_id"],
                    "data": row,
                }
            )
        if len(hits) >= limit:
            break
    return hits[:limit]


async def stats():
    return dict(await database.get_pool().fetchrow(STATS))


async def reclaim():
    pool = database.get_pool()
    for table in ("records", "blocks"):
        await pool.execute(f"VACUUM FULL {table}")
