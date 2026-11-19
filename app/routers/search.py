from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import current_user
from app.services import auth_service, history_service, search_service

router = APIRouter(prefix="/api")


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
    user=Depends(current_user),
):
    ids = parse_files(files)
    free = offset > 0 and await history_service.valid(search_id, user["id"], q, ids)
    quota = await (auth_service.quota_now(user) if free else auth_service.consume(user))
    result = await search_service.search(q, limit, offset, ids)
    if not free:
        search_id = await history_service.add(
            user["id"], q, ids, "web", len(result["items"])
        )
    return {**result, "quota": quota, "search_id": search_id}


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
        raise HTTPException(404, "База пуста")
    return {"item": item, "quota": quota}
