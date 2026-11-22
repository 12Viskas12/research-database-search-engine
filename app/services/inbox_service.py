import asyncio
import hashlib
import os
import re
import shutil
import time
import uuid

from app.core.config import settings
from app.db import database
from app.parsers.factory import get_parser
from app.services import archive_service, audit_service, intake_service

STABLE_SECONDS = 15
SKIP_SUFFIX = (".part", ".tmp", ".crdownload", ".swp")
DUPLICATES = "_duplicates"
REJECTED = "_rejected"


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def park(path, folder):
    target_dir = os.path.join(os.path.dirname(path), folder)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, f"{int(time.time())}_{os.path.basename(path)}")
    shutil.move(path, target)


def candidates(base):
    now = time.time()
    for entry in sorted(os.scandir(base), key=lambda e: e.name):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if entry.name.lower().endswith(SKIP_SUFFIX):
            continue
        if now - entry.stat().st_mtime < STABLE_SECONDS:
            continue
        yield entry.path, entry.name


async def take(queue, path, name):
    sha = await asyncio.to_thread(file_hash, path)
    duplicate = await database.find_duplicate(sha)
    if duplicate:
        await asyncio.to_thread(park, path, DUPLICATES)
        await audit_service.log(
            None, "inbox_duplicate", name="inbox", file=name, same_as=duplicate["id"]
        )
        return None
    if await asyncio.to_thread(archive_service.detect, path, name):
        return await intake_service.register_archive(queue, path, name, sha)
    try:
        get_parser(path)
    except ValueError as e:
        await asyncio.to_thread(park, path, REJECTED)
        await audit_service.log(None, "inbox_rejected", name="inbox", file=name, error=str(e))
        return None
    ext = os.path.splitext(name)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", ext):
        ext = ""
    os.makedirs(settings.upload_dir, exist_ok=True)
    target = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{ext}")
    await asyncio.to_thread(shutil.move, path, target)
    file_id = await database.create_file(name, target, sha)
    await queue.enqueue_job("process_file", file_id)
    await audit_service.log(None, "inbox_file", name="inbox", file=file_id, source=name)
    return file_id


async def scan(queue):
    base = settings.inbox_dir
    if not os.path.isdir(base):
        return []
    taken = []
    for path, name in await asyncio.to_thread(lambda: list(candidates(base))):
        try:
            file_id = await take(queue, path, name)
        except OSError:
            continue
        if file_id is not None:
            taken.append(file_id)
    return taken
