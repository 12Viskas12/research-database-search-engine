import asyncio
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.deps import current_user
from app.services import auth_service, history_service, link_service, search_service

router = APIRouter(prefix="/api")

EXPORT_MAX = 5000
BULK_MAX = 100


class BulkBody(BaseModel):
    values: list[str]
    files: str | None = None


def parse_files(value):
    if not value:
        return []
    ids = {int(p) for p in value.split(",") if p.strip().isdigit()}
    return sorted(ids)[:50]


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=300),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000),
    files: str | None = None,
    search_id: int | None = None,
    hidden: bool = False,
    user=Depends(current_user),
):
    if hidden and user["role"] not in ("admin", "creator"):
        raise HTTPException(403, "Admin only")
    ids = parse_files(files)
    free = offset > 0 and await history_service.valid(search_id, user["id"], q, ids)
    quota = await (auth_service.quota_now(user) if free else auth_service.consume(user))
    result = await search_service.search(q, limit, offset, ids, hidden)
    raw = len(result["items"])
    if hidden:
        items = [
            {**i, "own_ids": [i["id"]], "records": [{**i, "file": "", "own": True}]}
            for i in result["items"]
        ]
    else:
        items = await link_service.link(result["items"])
    if not free:
        search_id = await history_service.add(user["id"], q, ids, "web", raw)
        if raw == 0 and not hidden:
            await history_service.missed(user["id"], q, ids, "web")
    return {**result, "items": items, "raw": raw, "quota": quota, "search_id": search_id}


@router.get("/export")
async def export(
    q: str = Query(..., min_length=1, max_length=300),
    files: str | None = None,
    search_id: int | None = None,
    user=Depends(current_user),
):
    ids = parse_files(files)
    if not await history_service.valid(search_id, user["id"], q, ids):
        await auth_service.consume(user)
    result = await search_service.search(q, EXPORT_MAX, 0, ids)
    columns = []
    for item in result["items"]:
        for key in item["data"]:
            if key not in columns:
                columns.append(key)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    for item in result["items"]:
        writer.writerow([item["data"].get(c, "") for c in columns])
    body = "\ufeff" + out.getvalue()
    return Response(
        body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="search.csv"'},
    )


@router.post("/search/bulk")
async def bulk(body: BulkBody, user=Depends(current_user)):
    values = []
    for value in body.values:
        value = value.strip()[:200]
        if value and value not in values:
            values.append(value)
    if not values:
        raise HTTPException(400, "The list is empty")
    if len(values) > BULK_MAX:
        raise HTTPException(400, f"At most {BULK_MAX} values at once")
    quota = await auth_service.consume(user)
    ids = parse_files(body.files)
    gate = asyncio.Semaphore(4)

    async def one(value):
        async with gate:
            result = await search_service.search(value, 1, 0, ids)
        item = result["items"][0] if result["items"] else None
        return {"value": value, "found": item is not None, "item": item}

    results = await asyncio.gather(*(one(v) for v in values))
    return {
        "results": results,
        "found": sum(1 for r in results if r["found"]),
        "quota": quota,
    }


@router.get("/sources")
async def sources(user=Depends(current_user)):
    return await search_service.sources()


@router.get("/history")
async def history(user=Depends(current_user)):
    return await history_service.items(user["id"])


@router.delete("/history")
async def clear_history(user=Depends(current_user)):
    await history_service.clear(user["id"])
    return {"ok": True}


@router.get("/lucky")
async def lucky(user=Depends(current_user)):
    quota = await auth_service.consume(user)
    item = await search_service.lucky()
    if item is None:
        raise HTTPException(404, "The database is empty")
    return {"item": item, "quota": quota}
