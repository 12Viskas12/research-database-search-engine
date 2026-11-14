from fastapi import APIRouter, Query

from app.services import search_service

router = APIRouter(prefix="/api")


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items = await search_service.search(q, limit, offset)
    return {"items": items}
