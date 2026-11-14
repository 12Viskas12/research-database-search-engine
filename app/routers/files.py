import os
import uuid

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.core.redis_client import get_redis
from app.db import database
from app.parsers.factory import PARSERS

router = APIRouter(prefix="/api/files")


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in PARSERS:
        raise HTTPException(400, f"Unsupported file type: {ext}")
    os.makedirs(settings.upload_dir, exist_ok=True)
    path = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{ext}")
    async with aiofiles.open(path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            await out.write(chunk)
    file_id = await database.create_file(file.filename, path)
    redis = await get_redis()
    await redis.enqueue_job("process_file", file_id)
    return {"id": file_id, "status": "pending"}


@router.get("")
async def list_files():
    return await database.list_files()


@router.get("/{file_id}")
async def get_file(file_id: int):
    record = await database.get_file(file_id)
    if record is None:
        raise HTTPException(404, "File not found")
    record.pop("path", None)
    return record
