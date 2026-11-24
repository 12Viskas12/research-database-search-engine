import codecs
import contextlib
import io

from app.parsers.base import BaseParser

SAMPLE = 4 * 1024 * 1024
CHUNK = 1024 * 1024


class CountingRaw(io.RawIOBase):
    def __init__(self, raw, owner):
        super().__init__()
        self.raw = raw
        self.owner = owner

    def readable(self):
        return True

    def readinto(self, buffer):
        count = self.raw.readinto(buffer)
        if count:
            self.owner.consumed += count
        return count

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


def detect_encoding(path):
    with open(path, "rb") as f:
        head = f.read(4)
        if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return "utf-16"
        f.seek(0)
        for encoding in ("utf-8-sig", "cp1251"):
            decoder = codecs.getincrementaldecoder(encoding)()
            f.seek(0)
            try:
                decoder.decode(f.read(SAMPLE), final=False)
                return encoding
            except UnicodeDecodeError:
                continue
    return "latin-1"


class TextParser(BaseParser):
    def __init__(self, path):
        super().__init__(path)
        self.encoding = detect_encoding(path)

    @contextlib.contextmanager
    def open_text(self):
        raw = open(self.path, "rb")
        stream = io.TextIOWrapper(
            io.BufferedReader(CountingRaw(raw, self), buffer_size=CHUNK),
            encoding=self.encoding,
            errors="replace",
            newline="",
        )
        try:
            yield stream
        finally:
            stream.close()

    def sample_text(self, size=65536):
        with open(self.path, encoding=self.encoding, errors="replace", newline="") as f:
            return f.read(size)

    @staticmethod
    def lines_of(first, stream):
        pending = first
        while True:
            parts = pending.split("\n")
            yield from parts[:-1]
            pending = parts[-1]
            more = stream.read(CHUNK)
            if not more:
                break
            pending += more
        if pending:
            yield pending
