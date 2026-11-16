import re

from app.parsers.base import BaseParser
from app.parsers.utils import read_text

CREATE = re.compile(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)\s*\(", re.I)
INSERT = re.compile(
    r"INSERT\s+(?:IGNORE\s+)?INTO\s+([^\s(]+)\s*(\([^)]*\))?\s*(?:VALUES|VALUE)\s*", re.I
)
COPY = re.compile(r"COPY\s+([^\s(]+)\s*(\([^)]*\))?\s+FROM\s+stdin\s*;[ \t]*\r?\n", re.I)
STATEMENT = re.compile(INSERT.pattern + "|" + COPY.pattern, re.I)
COPY_END = re.compile(r"^\\\.[ \t]*\r?$", re.M)
STRING = re.compile(r"(?:[NnEeBbXx]|_[A-Za-z0-9]+)?'((?:[^'\\]|\\.|'')*)'", re.S)
ESCAPE = re.compile(r"\\(.)|''", re.S)
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "Z": "\x1a"}
NOT_COLUMNS = {
    "PRIMARY", "KEY", "UNIQUE", "CONSTRAINT", "FOREIGN", "INDEX",
    "FULLTEXT", "SPATIAL", "CHECK", "EXCLUDE", "LIKE",
}
SPACE = " \t\r\n"


def unquote(value):
    return ESCAPE.sub(lambda m: "'" if m.group(0) == "''" else ESCAPES.get(m.group(1), m.group(1)), value)


def clean_name(name):
    name = name.strip().rstrip(";")
    if "." in name and not name.startswith(("`", '"', "[")):
        name = name.rsplit(".", 1)[1]
    return name.strip('`"[]')


def split_top(body):
    parts, depth, start, i = [], 0, 0, 0
    while i < len(body):
        c = body[i]
        if c == "'":
            m = STRING.match(body, i)
            i = m.end() if m else i + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(body[start:i])
            start = i + 1
        i += 1
    parts.append(body[start:])
    return parts


def table_columns(text):
    schemas = {}
    for m in CREATE.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            c = text[i]
            if c == "'":
                s = STRING.match(text, i)
                i = s.end() if s else i + 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        columns = []
        for part in split_top(text[m.end() : i - 1]):
            part = part.strip()
            if not part:
                continue
            first = re.split(r"\s+", part, maxsplit=1)[0]
            if first.upper() in NOT_COLUMNS:
                continue
            columns.append(clean_name(first))
        schemas[clean_name(m.group(1))] = columns
    return schemas


def read_rows(text, pos):
    rows = []
    n = len(text)
    while True:
        while pos < n and text[pos] in SPACE:
            pos += 1
        if pos >= n or text[pos] != "(":
            break
        pos += 1
        row = []
        while True:
            while pos < n and text[pos] in SPACE:
                pos += 1
            m = STRING.match(text, pos)
            if m:
                row.append(unquote(m.group(1)))
                pos = m.end()
            else:
                start, depth = pos, 0
                while pos < n:
                    c = text[pos]
                    if c == "'":
                        s = STRING.match(text, pos)
                        pos = s.end() if s else pos + 1
                        continue
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        if depth == 0:
                            break
                        depth -= 1
                    elif c == "," and depth == 0:
                        break
                    pos += 1
                token = text[start:pos].strip()
                row.append(None if token.upper() == "NULL" else token)
            while pos < n and text[pos] in SPACE:
                pos += 1
            if pos < n and text[pos] == ",":
                pos += 1
                continue
            if pos < n and text[pos] == ")":
                pos += 1
            break
        rows.append(row)
        while pos < n and text[pos] in SPACE:
            pos += 1
        if pos < n and text[pos] == ",":
            pos += 1
            continue
        break
    return rows, pos


def copy_value(value):
    if value == "\\N":
        return None
    return re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), m.group(1)), value)


def make_record(columns, row, table, multi):
    record = {}
    if multi:
        record["table"] = table
    for i, value in enumerate(row):
        record[columns[i] if i < len(columns) else f"col{i + 1}"] = value
    return record


class SqlParser(BaseParser):
    def parse(self):
        text = read_text(self.path)
        schemas = table_columns(text)
        tables = {clean_name(m.group(1)) for m in INSERT.finditer(text)}
        tables |= {clean_name(m.group(1)) for m in COPY.finditer(text)}
        multi = len(tables) > 1
        found = False
        pos = 0

        while True:
            m = STATEMENT.search(text, pos)
            if not m:
                break
            found = True
            table = clean_name(m.group(1) or m.group(3))
            cols_raw = m.group(2) if m.group(1) else m.group(4)
            if cols_raw:
                columns = [clean_name(c) for c in cols_raw.strip("()").split(",")]
            else:
                columns = schemas.get(table, [])

            if m.group(1):
                rows, pos = read_rows(text, m.end())
                for row in rows:
                    yield make_record(columns, row, table, multi)
            else:
                end = COPY_END.search(text, m.end())
                stop = end.start() if end else len(text)
                for line in text[m.end() : stop].splitlines():
                    if line:
                        row = [copy_value(v) for v in line.split("\t")]
                        yield make_record(columns, row, table, multi)
                pos = end.end() if end else len(text)

        if not found:
            for statement in re.split(r";[ \t]*\r?\n", text):
                statement = statement.strip()
                if statement and not statement.startswith("--"):
                    yield {"statement": statement}
