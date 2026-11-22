import asyncio
import hashlib
import os
import re
import shutil
import uuid

from app.core.config import settings
from app.db import database
from app.parsers.factory import get_parser
from app.services import archive_service, audit_service

MAX_DEPTH = 8


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stored_path(name):
    ext = os.path.splitext(name)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", ext):
        ext = ""
    os.makedirs(settings.upload_dir, exist_ok=True)
    return os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{ext}")


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


async def add_plain(queue, path, name, sha=None):
    sha = sha or await asyncio.to_thread(file_hash, path)
    duplicate = await database.find_duplicate(sha)
    if duplicate:
        await asyncio.to_thread(remove, path)
        return None, f"Already uploaded as {duplicate['name']}"
    try:
        get_parser(path)
    except ValueError as e:
        await asyncio.to_thread(remove, path)
        return None, str(e)
    target = stored_path(name)
    if target != path:
        await asyncio.to_thread(shutil.move, path, target)
    file_id = await database.create_file(name, target, sha)
    await queue.enqueue_job("process_file", file_id)
    return file_id, None


async def add_any(queue, path, name, report, depth=0):
    kind = await asyncio.to_thread(archive_service.detect, path, name)
    if kind is None or depth >= MAX_DEPTH:
        file_id, reason = await add_plain(queue, path, name)
        if file_id is not None:
            report["added"].append(file_id)
        else:
            report["skipped"].append({"name": name, "reason": reason})
        return
    tmp = os.path.join(settings.upload_dir, f"x{uuid.uuid4().hex}")
    try:
        members, skipped = await asyncio.to_thread(
            archive_service.extract, path, name, tmp, kind
        )
    except archive_service.ArchiveError as e:
        report["skipped"].append({"name": name, "reason": str(e)})
        await asyncio.to_thread(shutil.rmtree, tmp, True)
        return
    report["skipped"].extend({"name": f"{name}/{s['name']}", "reason": s["reason"]} for s in skipped)
    try:
        for member in members:
            await add_any(queue, member["path"], member["name"], report, depth + 1)
    finally:
        await asyncio.to_thread(shutil.rmtree, tmp, True)
    await asyncio.to_thread(remove, path)


async def expand(queue, file_id):
    record = await database.get_file(file_id)
    if record is None:
        return
    report = {"added": [], "skipped": []}
    try:
        await add_any(queue, record["path"], record["name"], report)
    except Exception as e:
        await database.set_file_status(file_id, "failed", error=str(e))
        raise
    if report["added"]:
        await database.get_pool().execute("DELETE FROM files WHERE id = $1", file_id)
    else:
        reasons = "; ".join(f"{s['name']}: {s['reason']}" for s in report["skipped"][:5])
        await database.set_file_status(file_id, "failed", error=reasons or "Nothing to load")
    await audit_service.log(
        None, "archive_expanded", name="system", file=file_id,
        added=len(report["added"]), skipped=len(report["skipped"]),
    )
    return report


async def register_archive(queue, path, name, sha=None):
    target = stored_path(name)
    if target != path:
        await asyncio.to_thread(shutil.move, path, target)
    file_id = await database.create_file(name, target, sha)
    await database.set_file_status(file_id, "extracting")
    await queue.enqueue_job("expand_archive", file_id)
    return file_id
