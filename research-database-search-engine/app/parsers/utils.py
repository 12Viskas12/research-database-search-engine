import codecs
import csv
import io
import re

DELIMITERS = ",;\t|"
KEY_VALUE = re.compile(r"^\s*([^:=\n]{1,40}?)\s*[:=]\s*(.+?)\s*$")


def detect_encoding(path):
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for enc in ("utf-8-sig", "cp1251"):
        try:
            with open(path, encoding=enc, newline="") as f:
                while f.read(1 << 20):
                    pass
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def read_text(path):
    with open(path, encoding=detect_encoding(path), newline="") as f:
        return f.read()


def detect_delimiter(lines):
    lines = [x for x in lines if x.strip()][:50]
    if len(lines) < 2:
        return None
    for delimiter in DELIMITERS:
        try:
            counts = {len(r) for r in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)}
        except csv.Error:
            continue
        if len(counts) == 1 and counts.pop() >= 2:
            return delimiter
    return None


def scalar(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return value
