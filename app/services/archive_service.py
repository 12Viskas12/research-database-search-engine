import bz2
import gzip
import hashlib
import lzma
import os
import shutil
import tarfile
import uuid
import zipfile
from contextlib import ExitStack

from app.parsers.factory import PARSERS

CHUNK = 1024 * 1024
MAX_NAME = 255
TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz", ".tar")
SINGLE = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}


class ArchiveError(Exception):
    pass


def kind_of(name):
    name = (name or "").lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".7z"):
        return "7z"
    if name.endswith(TAR_SUFFIXES):
        return "tar"
    if name.endswith(tuple(SINGLE)):
        return "single"
    return None


def sniff(path):
    if zipfile.is_zipfile(path):
        return "zip"
    try:
        import py7zr

        if py7zr.is_7zfile(path):
            return "7z"
    except ImportError:
        pass
    if tarfile.is_tarfile(path):
        return "tar"
    return None


def detect(path, name):
    kind = kind_of(name)
    if kind in ("zip", "7z", "tar") and sniff(path) is None:
        return None
    if kind or os.path.splitext(name or "")[1].lower() in PARSERS:
        return kind
    return sniff(path)


def safe_relpath(name):
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def zip_name(info):
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("cp866")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


class Entry:
    def __init__(self, name, opener, encrypted=False):
        self.name = name
        self.opener = opener
        self.encrypted = encrypted


class Reader:
    def __init__(self, path, name, stack):
        self.path = path
        self.name = name
        self.stack = stack

    def entries(self):
        raise NotImplementedError


class ZipReader(Reader):
    def entries(self):
        try:
            zf = self.stack.enter_context(zipfile.ZipFile(self.path))
        except zipfile.BadZipFile:
            raise ArchiveError("Corrupted ZIP archive")
        for info in zf.infolist():
            if not info.is_dir():
                yield Entry(zip_name(info), lambda i=info: zf.open(i), bool(info.flag_bits & 1))


class TarReader(Reader):
    def entries(self):
        try:
            tf = self.stack.enter_context(tarfile.open(self.path, "r:*"))
        except (tarfile.TarError, EOFError, OSError):
            raise ArchiveError("Corrupted TAR archive")
        for member in tf:
            if member.isfile():
                yield Entry(member.name, lambda m=member: tf.extractfile(m))


class SingleReader(Reader):
    def entries(self):
        opener = SINGLE[os.path.splitext(self.name.lower())[1]]
        name = os.path.splitext(os.path.basename(self.name))[0] or "data"
        yield Entry(name, lambda: opener(self.path, "rb"))


class SevenZipReader(Reader):
    def entries(self):
        import py7zr

        tmp = os.path.join(os.path.dirname(self.path), f"x{uuid.uuid4().hex}")
        os.makedirs(tmp)
        self.stack.callback(shutil.rmtree, tmp, True)
        try:
            with py7zr.SevenZipFile(self.path) as z:
                if z.needs_password():
                    raise ArchiveError("The archive is password protected")
                z.extractall(path=tmp)
        except ArchiveError:
            raise
        except Exception as e:
            raise ArchiveError(f"Cannot read 7z archive: {e}")
        for root, _, files in os.walk(tmp):
            for name in files:
                full = os.path.join(root, name)
                if not os.path.islink(full):
                    yield Entry(os.path.relpath(full, tmp), lambda p=full: open(p, "rb"))


READERS = {"zip": ZipReader, "tar": TarReader, "7z": SevenZipReader, "single": SingleReader}


def write_member(entry, dest_dir, ext):
    target = os.path.join(dest_dir, f"{uuid.uuid4().hex}{ext}")
    digest = hashlib.sha256()
    try:
        with entry.opener() as src, open(target, "wb") as out:
            while chunk := src.read(CHUNK):
                digest.update(chunk)
                out.write(chunk)
    except Exception as e:
        try:
            os.remove(target)
        except OSError:
            pass
        raise ArchiveError(f"Extraction failed: {e}")
    return target, digest.hexdigest()


def extract(path, name, dest_dir, kind=None):
    kind = kind or detect(path, name)
    if kind is None:
        raise ArchiveError("Not a supported archive")
    os.makedirs(dest_dir, exist_ok=True)
    members, skipped = [], []
    with ExitStack() as stack:
        try:
            for entry in READERS[kind](path, name, stack).entries():
                rel = safe_relpath(entry.name)[-MAX_NAME:]
                parts = rel.split("/")
                base = parts[-1] if rel else ""
                if not base or base.startswith(".") or "__MACOSX" in parts:
                    continue
                if entry.encrypted:
                    skipped.append({"name": rel, "reason": "Password protected"})
                    continue
                ext = os.path.splitext(base)[1].lower()
                if ext not in PARSERS and kind_of(base) is None:
                    skipped.append({"name": rel, "reason": "Unsupported file type"})
                    continue
                target, sha = write_member(entry, dest_dir, ext)
                members.append({"name": rel, "path": target, "sha256": sha})
        except Exception:
            for item in members:
                try:
                    os.remove(item["path"])
                except OSError:
                    pass
            raise
    return members, skipped
