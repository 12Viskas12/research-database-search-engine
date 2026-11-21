import re

from app.db import database
from app.services import compression_service, normalize

WORD = compression_service.WORD
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
MAX_GROUP = 20
MAX_KEY_HITS = 20
MAX_TOKENS = 60
RELATED_LIMIT = 200

RELATED_SQL = (
    "SELECT r.id, r.file_id, r.data FROM records r "
    "WHERE NOT r.hidden AND r.tsv @@ to_tsquery('simple', $1) LIMIT $2"
)
FILE_NAMES = "SELECT id, name FROM files WHERE id = ANY($1::int[])"


def record_keys(data):
    keys = {}
    for value in data.values():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = str(value)
        for match in normalize.PHONE.finditer(text):
            key = normalize.phone_key(match.group(0))
            if key:
                digits = re.sub(r"\D", "", match.group(0))
                keys.setdefault("p:" + key, set()).update({key, digits})
        for match in EMAIL.finditer(text):
            email = match.group(0).lower()
            keys.setdefault("e:" + email, set()).add(email)
    return keys


def quote(token):
    return "'" + token.replace("'", "''") + "'"


def packed_sets(keys):
    sets = []
    for key, tokens in keys.items():
        if key.startswith("p:"):
            sets.append([frozenset(tokens)])
        else:
            parts = WORD.findall(key[2:])
            if parts:
                sets.append([frozenset({p}) for p in parts])
    return sets


async def fetch_related(conn, keys, known):
    tokens = sorted({t for toks in keys.values() for t in toks})[:MAX_TOKENS]
    found = []
    if tokens:
        query = " | ".join(quote(t) for t in tokens)
        rows = await conn.fetch(RELATED_SQL, query, RELATED_LIMIT)
        found += [dict(r) for r in rows]
    sets = packed_sets(keys)
    if sets:
        spec = {"mode": "anyall", "sets": sets, "filters": []}
        found += await compression_service.search_packed(conn, spec, None, RELATED_LIMIT)
    return [r for r in found if r["id"] not in known]


class Components:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def build_groups(items, related, names):
    nodes = list(items) + related
    node_keys = [record_keys(n["data"]) for n in nodes]
    index = {}
    for i, keys in enumerate(node_keys):
        for key in keys:
            index.setdefault(key, []).append(i)
    comp = Components(len(nodes))
    for members in index.values():
        if len(members) > MAX_KEY_HITS:
            continue
        for other in members[1:]:
            comp.join(members[0], other)
    groups = {}
    order = []
    for i in range(len(items)):
        root = comp.find(i)
        if root not in groups:
            groups[root] = {"own": [], "other": []}
            order.append(root)
        groups[root]["own"].append(i)
    for i in range(len(items), len(nodes)):
        root = comp.find(i)
        if root in groups:
            groups[root]["other"].append(i)
    result = []
    for root in order:
        own, other = groups[root]["own"], groups[root]["other"]
        records = [
            {
                "id": nodes[i]["id"],
                "file_id": nodes[i]["file_id"],
                "file": names.get(nodes[i]["file_id"], ""),
                "data": nodes[i]["data"],
                "own": i < len(items),
            }
            for i in (own + other)[:MAX_GROUP]
        ]
        first = nodes[own[0]]
        result.append(
            {
                "id": first["id"],
                "file_id": first["file_id"],
                "data": first["data"],
                "own_ids": [nodes[i]["id"] for i in own],
                "records": records,
            }
        )
    return result


async def link(items):
    if not items:
        return []
    keys = {}
    for item in items:
        for key, tokens in record_keys(item["data"]).items():
            keys.setdefault(key, set()).update(tokens)
    async with database.get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            known = {item["id"] for item in items}
            related = await fetch_related(conn, keys, known) if keys else []
            ids = {n["file_id"] for n in list(items) + related}
            rows = await conn.fetch(FILE_NAMES, sorted(ids))
    names = {r["id"]: r["name"] for r in rows}
    return build_groups(items, related, names)
