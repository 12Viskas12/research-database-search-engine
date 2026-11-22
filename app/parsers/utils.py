import csv
import io
import re

DELIMITERS = ",;\t|"
KEY_VALUE = re.compile(r"^\s*([^:=\n]{1,40}?)\s*[:=]\s*(.+?)\s*$")


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
