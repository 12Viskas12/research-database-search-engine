import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import admin_user
from app.core.redis_client import get_redis
from app.db import database
from app.services import audit_service
from app.services import compression_service as cs

router = APIRouter(prefix="/api/compress", dependencies=[Depends(admin_user)])


class MergeBody(BaseModel):
    file_ids: list[int] | None = None
    name: str | None = None
    method: str = "bz2"


async def get_ready(file_id):
    record = await database.get_file(file_id)
    if record is None:
        raise HTTPException(404, "File not found")
    if record["status"] != "done":
        raise HTTPException(409, "File is not ready")
    return record


@router.post("/files/{file_id}/pack", status_code=202)
async def pack(file_id: int, method: str = "bz2", admin=Depends(admin_user)):
    try:
        cs.check_method(method)
    except cs.CompressionError as e:
        raise HTTPException(400, str(e))
    record = await get_ready(file_id)
    if record["packed"]:
        raise HTTPException(409, "Already packed")
    await database.set_file_status(file_id, "packing")
    redis = await get_redis()
    await redis.enqueue_job("pack_file", file_id, method)
    await audit_service.log(admin, "file_pack", file=file_id, method=method)
    return {"id": file_id, "status": "packing"}


@router.post("/files/{file_id}/unpack", status_code=202)
async def unpack(file_id: int, admin=Depends(admin_user)):
    record = await get_ready(file_id)
    if not record["packed"]:
        raise HTTPException(409, "File is not packed")
    await database.set_file_status(file_id, "unpacking")
    redis = await get_redis()
    await redis.enqueue_job("unpack_file", file_id)
    await audit_service.log(admin, "file_unpack", file=file_id)
    return {"id": file_id, "status": "unpacking"}


@router.post("/merge", status_code=202)
async def merge(body: MergeBody, admin=Depends(admin_user)):
    try:
        cs.check_method(body.method)
        sources = await cs.pick_sources(body.file_ids)
    except cs.CompressionError as e:
        raise HTTPException(400, str(e))
    name = (body.name or "").strip() or time.strftime("merged-%Y%m%d-%H%M")
    target_id = await database.create_file(name, "")
    await database.set_file_status(target_id, "packing")
    redis = await get_redis()
    await redis.enqueue_job(
        "merge_files", target_id, [s["id"] for s in sources], body.method
    )
    await audit_service.log(
        admin, "files_merged", target=target_id, sources=[s["id"] for s in sources]
    )
    return {"id": target_id, "sources": len(sources)}


@router.post("/reclaim", status_code=202)
async def reclaim(admin=Depends(admin_user)):
    redis = await get_redis()
    await redis.enqueue_job("reclaim_space")
    await audit_service.log(admin, "reclaim")
    return {"status": "queued"}


@router.get("/stats")
async def stats():
    return await cs.stats()
