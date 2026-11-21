import json
import os
import re
import time

from app.core.config import settings
from app.services.auth_service import AuthError

NAME = re.compile(r"search-[\w.-]+\.sql\.gz")


def folder():
    return settings.backup_dir


def valid_name(name):
    if not NAME.fullmatch(name or "") or ".." in name:
        raise AuthError("Invalid backup name")
    path = os.path.join(folder(), name)
    if not os.path.isfile(path):
        raise AuthError("Backup not found", 404)
    return path


def listing():
    base = folder()
    if not os.path.isdir(base):
        return {"items": [], "status": None}
    items = []
    for entry in os.scandir(base):
        if entry.is_file() and NAME.fullmatch(entry.name):
            stat = entry.stat()
            items.append({"name": entry.name, "size": stat.st_size, "at": stat.st_mtime})
    items.sort(key=lambda i: i["at"], reverse=True)
    status = None
    try:
        with open(os.path.join(base, ".status"), encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        status = None
    return {"items": items, "status": status}


def request_backup():
    base = folder()
    if not os.path.isdir(base):
        raise AuthError("Backup service is not available", 503)
    with open(os.path.join(base, ".backup"), "w") as f:
        f.write(str(int(time.time())))


def request_restore(name):
    valid_name(name)
    with open(os.path.join(folder(), ".restore"), "w") as f:
        f.write(name)
