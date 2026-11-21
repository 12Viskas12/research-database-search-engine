import bz2
import gzip
import hashlib
import lzma
import os
import shutil
import tarfile
import tempfile
import uuid
import zipfile

from app.core.config import settings
from app.parsers.factory import PARSERS

CHUNK = 1024 * 1024
MAX_NAME = 255

TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz")
SINGLE_OPENERS = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}


class ArchiveError(Exception):
    pass


def archive_kind(filename):
    name = (filename or "").lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".7z"):
        return "7z"
    if name.endswith(TAR_SUFFIXES):
        return "tar"
    if name.endswith(tuple(SINGLE_OPENERS)):
        return "single"
    return None


def is_archive(path, kind):
    if kind == "zip":
        return zipfile.is_zipfile(path)
    if kind == "7z":
        import py7zr

        return py7zr.is_7zfile(path)
    if kind == "tar":
        return tarfile.is_tarfile(path)
    return True


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def decode_zip_name(info):
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("cp866")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def safe_relpath(name):
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def zip_entries(path, stack):
    try:
        zf = stack.enter_context(zipfile.ZipFile(path))
    except zipfile.BadZipFile:
        raise ArchiveError("Поврежденный ZIP-архив")
    return [
        (decode_zip_name(i), i.file_size, bool(i.flag_bits & 0x1), lambda i=i: zf.open(i))
        for i in zf.infolist()
        if not i.is_dir()
    ]


def tar_entries(path, stack):
    try:
        tf = stack.enter_context(tarfile.open(path, "r:*"))
    except (tarfile.TarError, EOFError, OSError):
        raise ArchiveError("Поврежденный TAR-архив")
    return [
        (m.name, m.size, False, lambda m=m: tf.extractfile(m))
        for m in tf.getmembers()
        if m.isfile()
    ]


def single_entries(path, stack, filename):
    opener = SINGLE_OPENERS[os.path.splitext(filename.lower())[1]]
    name = os.path.splitext(os.path.basename(filename))[0] or "data"
    return [(name, 0, False, lambda: opener(path, "rb"))]


def sevenzip_entries(path, stack):
    import py7zr

    tmp = tempfile.mkdtemp(dir=settings.upload_dir)
    stack.callback(shutil.rmtree, tmp, True)
    try:
        with py7zr.SevenZipFile(path) as z:
            if z.needs_password():
                raise ArchiveError("Архив защищен паролем")
            infos = [i for i in z.list() if not i.is_directory]
            if sum(i.uncompressed for i in infos) > settings.zip_max_bytes:
                raise ArchiveError("Архив слишком большой после распаковки")
            z.extractall(path=tmp)
    except ArchiveError:
        raise
    except Exception as e:
        raise ArchiveError(f"Ошибка чтения 7z-архива: {e}")
    entries = []
    for root, _, files in os.walk(tmp):
        for name in files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, tmp)
            entries.append((rel, os.path.getsize(full), False, lambda p=full: open(p, "rb")))
    return entries


def write_member(opener, dest_dir, ext, budget):
    target = os.path.join(dest_dir, f"{uuid.uuid4().hex}{ext}")
    digest = hashlib.sha256()
    written = 0
    try:
        with opener() as src, open(target, "wb") as out:
            while chunk := src.read(CHUNK):
                written += len(chunk)
                if written > budget:
                    raise ArchiveError("Архив слишком большой после распаковки")
                digest.update(chunk)
                out.write(chunk)
    except ArchiveError:
        _remove(target)
        raise
    except Exception as e:
        _remove(target)
        raise ArchiveError(f"Ошибка распаковки: {e}")
    return target, digest.hexdigest(), written


def extract(path, filename, dest_dir):
    kind = archive_kind(filename)
    if kind is None or not is_archive(path, kind):
        raise ArchiveError("Файл не является поддерживаемым архивом")
    os.makedirs(dest_dir, exist_ok=True)
    extracted = []
    skipped = []
    total = 0
    from contextlib import ExitStack

    with ExitStack() as stack:
        if kind == "zip":
            entries = zip_entries(path, stack)
        elif kind == "tar":
            entries = tar_entries(path, stack)
        elif kind == "7z":
            entries = sevenzip_entries(path, stack)
        else:
            entries = single_entries(path, stack, filename)
        if len(entries) > settings.zip_max_files:
            raise ArchiveError(f"В архиве больше {settings.zip_max_files} файлов")
        if sum(e[1] for e in entries) > settings.zip_max_bytes:
            raise ArchiveError("Архив слишком большой после распаковки")
        try:
            for name, _, encrypted, opener in entries:
                rel = safe_relpath(name)[-MAX_NAME:]
                parts = rel.split("/")
                base = parts[-1] if rel else ""
                if not base or base.startswith(".") or "__MACOSX" in parts:
                    continue
                if encrypted:
                    skipped.append({"name": rel, "reason": "Файл защищен паролем"})
                    continue
                ext = os.path.splitext(base)[1].lower()
                if ext not in PARSERS:
                    skipped.append({"name": rel, "reason": "Неподдерживаемый тип файла"})
                    continue
                target, sha, size = write_member(
                    opener, dest_dir, ext, settings.zip_max_bytes - total
                )
                total += size
                extracted.append({"name": rel, "path": target, "sha256": sha})
        except Exception:
            for item in extracted:
                _remove(item["path"])
            raise
    return extracted, skipped
