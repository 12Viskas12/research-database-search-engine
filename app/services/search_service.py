import asyncio
import math
import random
import re
from dataclasses import dataclass, field

from app.db import database
from app.services import compression_service, normalize

WORD = compression_service.WORD
FIELD = re.compile(r'(?<!\S)([^\W\d_][\w.-]+):(?:"([^"]+)"|([^\s"]+))')
MAX_TERMS = 8
FUZZY_LIMIT = 6
PREFIX_LIMIT = 12
FUZZY_POOL = 40

SET_SIMILARITY = "SELECT set_config('pg_trgm.similarity_threshold', '0.2', true)"
FUZZY_SQL = (
    "SELECT word, freq FROM vocab WHERE word % $1 "
    "ORDER BY similarity(word, $1) DESC, freq DESC LIMIT $2"
)
PREFIX_SQL = "SELECT word FROM vocab WHERE word LIKE $1 ORDER BY freq DESC LIMIT $2"

SELECT = "SELECT r.id, r.file_id, r.data FROM records r"

LUCKY_COUNTS = """
SELECT
    COALESCE(sum(rows_count) FILTER (WHERE NOT packed AND status = 'done'), 0)::bigint AS live,
    COALESCE(sum(rows_count) FILTER (WHERE packed), 0)::bigint AS packed
FROM files
"""

LUCKY_LIVE = """
SELECT id, file_id, data FROM records
WHERE id >= (SELECT floor(random() * COALESCE(max(id), 0))::bigint + 1 FROM records)
AND NOT hidden
ORDER BY id LIMIT 1
"""

LUCKY_LIVE_FIRST = (
    "SELECT id, file_id, data FROM records WHERE NOT hidden ORDER BY id LIMIT 1"
)

LUCKY_BLOCK = """
SELECT file_id, block_no, codec, payload FROM blocks
ORDER BY random() LIMIT 1
"""

SOURCES_SQL = (
    "SELECT id, name, rows_count FROM files WHERE status = 'done' ORDER BY name, id"
)


@dataclass
class Query:
    text: str
    terms: list
    filters: list
    files: list
    groups: list = field(default_factory=list)
    hidden: bool = False


def like_pattern(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def parse(raw, files=None):
    filters = []

    def take(match):
        value = (match.group(2) or match.group(3) or "").strip()
        if not value or value.startswith("//"):
            return match.group(0)
        filters.append((match.group(1).lower(), value.lower()))
        return " "

    text = FIELD.sub(take, raw or "")
    text = normalize.query_text(" ".join(text.split()))
    terms = []
    for word in WORD.findall(text.lower()):
        if word not in terms:
            terms.append(word)
    return Query(text, terms[:MAX_TERMS], filters[:5], list(files or []))


def distance(a, b):
    prev2 = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


async def expand_term(conn, term):
    words = {term}
    if not term.isalpha():
        return sorted(words)
    if len(term) >= 4:
        limit = 1 if len(term) <= 5 else 2
        scored = []
        for row in await conn.fetch(FUZZY_SQL, term, FUZZY_POOL):
            d = distance(term, row["word"])
            if d <= limit:
                scored.append((d, -row["freq"], row["word"]))
        words.update(w for _, _, w in sorted(scored)[:FUZZY_LIMIT])
    if len(term) >= 3:
        rows = await conn.fetch(PREFIX_SQL, term + "%", PREFIX_LIMIT)
        words.update(r["word"] for r in rows)
    return sorted(words)


async def expand(conn, terms):
    await conn.execute(SET_SIMILARITY)
    return [await expand_term(conn, t) for t in terms]


def quote(word):
    return "'" + word.replace("'", "''") + "'"


def tsquery_all(groups):
    return " & ".join("(" + " | ".join(quote(w) for w in g) + ")" for g in groups)


def tsquery_any(groups):
    return " | ".join(quote(w) for g in groups for w in g)


def relaxed_min(count):
    return max(2, math.ceil(count / 2))


def build_stages(q):
    stages = []
    plain = [[t] for t in q.terms]
    if q.terms:
        stages.append({"kind": "strict", "groups": plain, "marks": list(q.terms)})
        if any(len(g) > 1 for g in q.groups):
            marks = sorted({w for g in q.groups for w in g})
            stages.append({"kind": "expanded", "groups": q.groups, "marks": marks})
    if q.text:
        stages.append({"kind": "like", "needle": q.text.lower(), "marks": [q.text]})
    if len(q.terms) >= 3:
        marks = sorted({w for g in q.groups for w in g})
        stages.append(
            {
                "kind": "relaxed",
                "groups": q.groups,
                "min": relaxed_min(len(q.terms)),
                "marks": marks,
            }
        )
    if not stages:
        stages.append({"kind": "filter", "marks": []})
    return stages


def live_filters(q, params):
    params.append(q.hidden)
    parts = [f"r.hidden = ${len(params)}"]
    if q.files:
        params.append(q.files)
        parts.append(f"r.file_id = ANY(${len(params)}::int[])")
    for key, value in q.filters:
        params.append(key)
        k = len(params)
        params.append(like_pattern(value))
        v = len(params)
        parts.append(f"r.search_text ILIKE ${v}")
        parts.append(
            "EXISTS (SELECT 1 FROM jsonb_each_text(r.data) e "
            f"WHERE lower(e.key) = ${k} AND e.value ILIKE ${v})"
        )
    return parts


def live_query(q, stage, need):
    params = []
    kind = stage["kind"]
    if kind == "strict":
        params.append(q.text)
        base = f"{SELECT}, websearch_to_tsquery('simple', $1) q"
        where = ["r.tsv @@ q"]
        order = "ts_rank(r.tsv, q) DESC, r.id"
    elif kind == "expanded":
        params.append(tsquery_all(stage["groups"]))
        base = f"{SELECT}, to_tsquery('simple', $1) q"
        where = ["r.tsv @@ q"]
        order = "ts_rank(r.tsv, q) DESC, r.id"
    elif kind == "like":
        params.append(like_pattern(stage["needle"]))
        base = SELECT
        where = ["r.search_text ILIKE $1"]
        order = "r.id"
    elif kind == "relaxed":
        params.append(tsquery_any(stage["groups"]))
        scores = []
        for group in stage["groups"]:
            params.append(tsquery_any([group]))
            scores.append(f"(r.tsv @@ to_tsquery('simple', ${len(params)}))::int")
        where = ["r.tsv @@ q"] + live_filters(q, params)
        params.append(stage["min"])
        params.append(need)
        sql = (
            "SELECT id, file_id, data FROM ("
            f"SELECT r.id, r.file_id, r.data, ({' + '.join(scores)}) AS score "
            "FROM records r, to_tsquery('simple', $1) q "
            f"WHERE {' AND '.join(where)}) s "
            f"WHERE score >= ${len(params) - 1} ORDER BY score DESC, id "
            f"LIMIT ${len(params)}"
        )
        return sql, params
    else:
        base = SELECT
        where = []
        order = "r.id"
    where += live_filters(q, params)
    params.append(need)
    sql = base
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order} LIMIT ${len(params)}"
    return sql, params


def packed_spec(q, stage):
    spec = {
        "mode": {"strict": "all", "expanded": "all", "relaxed": "min"}.get(
            stage["kind"], stage["kind"]
        ),
        "filters": q.filters,
    }
    if "groups" in stage:
        spec["groups"] = [frozenset(g) for g in stage["groups"]]
    if "min" in stage:
        spec["min"] = stage["min"]
    if "needle" in stage:
        spec["needle"] = stage["needle"]
    return spec


async def run_stage(conn, q, stage, need):
    sql, params = live_query(q, stage, need)
    items = [dict(r) for r in await conn.fetch(sql, *params)]
    if len(items) < need and not q.hidden:
        items += await compression_service.search_packed(
            conn, packed_spec(q, stage), q.files, need - len(items)
        )
    return items


async def search(raw, limit=20, offset=0, files=None, hidden=False):
    q = parse(raw, files)
    q.hidden = hidden
    if not q.text and not q.filters:
        return {"items": [], "more": False, "marks": []}
    need = offset + limit + 1
    async with database.get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            if q.terms:
                q.groups = await expand(conn, q.terms)
            items, marks = [], []
            for stage in build_stages(q):
                items = await run_stage(conn, q, stage, need)
                if items:
                    marks = stage["marks"]
                    break
    page = items[offset : offset + limit]
    return {"items": page, "more": len(items) > offset + limit, "marks": marks}


async def sources():
    return [dict(r) for r in await database.get_pool().fetch(SOURCES_SQL)]


async def lucky():
    pool = database.get_pool()
    counts = await pool.fetchrow(LUCKY_COUNTS)
    total = counts["live"] + counts["packed"]
    if total <= 0:
        return None
    if random.random() * total < counts["live"]:
        row = await pool.fetchrow(LUCKY_LIVE) or await pool.fetchrow(LUCKY_LIVE_FIRST)
        if row:
            return dict(row)
    block = await pool.fetchrow(LUCKY_BLOCK)
    if block is None:
        return None
    rows = await asyncio.to_thread(
        compression_service.decode_block, block["payload"], block["codec"]
    )
    if not rows:
        return None
    index = random.randrange(len(rows))
    return {
        "id": f"{block['file_id']}:{block['block_no']}:{index}",
        "file_id": block["file_id"],
        "data": rows[index],
    }
