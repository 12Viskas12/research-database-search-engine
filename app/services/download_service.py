import asyncio
import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.message import Message

from app.core.config import settings
from app.db import database

CHUNK = 1024 * 1024
MAX_REDIRECTS = 8
TIMEOUT = 30
AGENT = "Mozilla/5.0 (compatible; viskas-fetch)"


class DownloadError(Exception):
    pass


def check_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise DownloadError("Host not found")
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            raise DownloadError("This address is not allowed")
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise DownloadError("This address is not allowed")


def check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise DownloadError("Only http and https links are supported")
    check_host(parts.hostname)


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def filename_from(response, url):
    header = response.headers.get("Content-Disposition", "")
    if header:
        message = Message()
        message["content-disposition"] = header
        name = message.get_filename()
        if name:
            return os.path.basename(urllib.parse.unquote(name))
    path = urllib.parse.urlsplit(response.geturl() or url).path
    name = os.path.basename(urllib.parse.unquote(path))
    return name or "download"


def clean_name(name):
    name = re.sub(r"[\x00-\x1f\\/]", "_", name).strip(" .") or "download"
    return name[-200:]


def _drop(path):
    try:
        os.remove(path)
    except OSError:
        pass


def fetch(url, dest_dir, on_progress):
    check_url(url)
    opener = urllib.request.build_opener(Redirects)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(dest_dir, f"{uuid.uuid4().hex}.part")
    try:
        with opener.open(request, timeout=TIMEOUT) as response, open(tmp, "wb") as out:
            name = clean_name(filename_from(response, url))
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(CHUNK):
                out.write(chunk)
                done += len(chunk)
                on_progress(done, total)
    except DownloadError:
        _drop(tmp)
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        _drop(tmp)
        raise DownloadError(f"Download failed: {e}")
    except BaseException:
        _drop(tmp)
        raise
    return tmp, name


async def run(file_id, url):
    loop = asyncio.get_running_loop()
    state = {"last": -1}

    def on_progress(done, total):
        percent = min(99, done * 100 // total) if total else 0
        if percent != state["last"]:
            state["last"] = percent
            asyncio.run_coroutine_threadsafe(database.set_file_progress(file_id, percent), loop)

    return await asyncio.to_thread(fetch, url, settings.upload_dir, on_progress)
