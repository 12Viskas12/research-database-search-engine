from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import current_user
from app.services import auth_service, search_service

router = APIRouter(prefix="/api")


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
):
    quota = await auth_service.consume(user)
    items = await search_service.search(q, limit, offset)
    return {"items": items, "quota": quota}


@router.get("/lucky")
async def lucky(user=Depends(current_user)):
    quota = await auth_service.consume(user)
    item = await search_service.lucky()
    if item is None:
        raise HTTPException(404, "База пуста")
    return {"item": item, "quota": quota}
