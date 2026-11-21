import re
from app.parsers.base import BaseParser
from app.parsers.utils import detect_encoding

CREATE_RE = re.compile(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)\s*\(", re.I)
INSERT_RE = re.compile(r"INSERT\s+(?:IGNORE\s+)?INTO\s+([^\s(]+)\s*(\([^)]*\))?\s*(?:VALUES|VALUE)\s*", re.I)
COPY_RE = re.compile(r"COPY\s+([^\s(]+)\s*(\([^)]*\))?\s+FROM\s+stdin\s*;", re.I)
STRING_RE = re.compile(r"(?:[NnEeBbXx]|_[A-Za-z0-9]+)?'((?:[^'\\]|\\.|'')*)'", re.S)
ESCAPE_RE = re.compile(r"\\(.)|''", re.S)

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "Z": "\x1a"}
NOT_COLUMNS = {
    "PRIMARY", "KEY", "UNIQUE", "CONSTRAINT", "FOREIGN", "INDEX",
    "FULLTEXT", "SPATIAL", "CHECK", "EXCLUDE", "LIKE",
}
SPACE = " \t\r\n"


def unquote(value: str) -> str:
    return ESCAPE_RE.sub(lambda m: "'" if m.group(0) == "''" else ESCAPES.get(m.group(1), m.group(1)), value)


def clean_name(name: str) -> str:
    name = name.strip().rstrip(";")
    if "." in name and not name.startswith(("`", '"', "[")):
        name = name.rsplit(".", 1)[1]
    return name.strip('`"[]')


def copy_value(value: str):
    if value == "\\N":
        return None
    return re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), m.group(1)), value)


def split_top(body: str):
    parts, depth, start, i = [], 0, 0, 0
    while i < len(body):
        c = body[i]
        if c == "'":
            m = STRING_RE.match(body, i)
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


def parse_create_columns(stmt: str):
    m = CREATE_RE.search(stmt)
    if not m:
        return None, []
    depth, i = 1, m.end()
    while i < len(stmt) and depth:
        c = stmt[i]
        if c == "'":
            s = STRING_RE.match(stmt, i)
            i = s.end() if s else i + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    columns = []
    for part in split_top(stmt[m.end():i - 1]):
        part = part.strip()
        if not part:
            continue
        first = re.split(r"\s+", part, maxsplit=1)[0]
        if first.upper() in NOT_COLUMNS:
            continue
        columns.append(clean_name(first))
    return clean_name(m.group(1)), columns


def read_insert_rows(text: str, pos: int):
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
            m = STRING_RE.match(text, pos)
            if m:
                row.append(unquote(m.group(1)))
                pos = m.end()
            else:
                start, depth = pos, 0
                while pos < n:
                    c = text[pos]
                    if c == "'":
                        s = STRING_RE.match(text, pos)
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
    return rows


class SqlParser(BaseParser):
    def _iter_statements(self):
        """Потоково читает SQL-выражения до ';' вне строковых литералов и COPY-блоки."""
        enc = detect_encoding(self.path)
        with open(self.path, encoding=enc, errors="replace") as f:
            in_copy = False
            copy_meta = None
            buf = []
            in_string = False
            escape_next = False

            for line in f:
                if in_copy:
                    if line.rstrip("\r\n") == "\\.":
                        in_copy = False
                        copy_meta = None
                    else:
                        row = [copy_value(v) for v in line.rstrip("\r\n").split("\t")]
                        yield ("copy_row", copy_meta, row)
                    continue

                stripped = line.strip()
                if not buf and (not stripped or stripped.startswith("--")):
                    continue

                buf.append(line)
                # Проверяем окончание SQL-инструкции с учетом кавычек
                for ch in line:
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == "\\" and in_string:
                        escape_next = True
                        continue
                    if ch == "'":
                        in_string = not in_string
                    elif ch == ";" and not in_string:
                        stmt = "".join(buf).strip()
                        buf.clear()
                        m_copy = COPY_RE.match(stmt)
                        if m_copy:
                            in_copy = True
                            table = clean_name(m_copy.group(1))
                            cols_raw = m_copy.group(2)
                            cols = [clean_name(c) for c in cols_raw.strip("()").split(",")] if cols_raw else None
                            copy_meta = (table, cols)
                        else:
                            yield ("stmt", stmt, None)
                        break

            if buf:
                stmt = "".join(buf).strip()
                if stmt and not stmt.startswith("--"):
                    yield ("stmt", stmt, None)

    def parse(self):
        schemas = {}
        seen_tables = set()
        found_data = False

        for kind, payload, extra in self._iter_statements():
            if kind == "copy_row":
                found_data = True
                table, cols_override = payload
                seen_tables.add(table)
                columns = cols_override if cols_override is not None else schemas.get(table, [])
                record = {"_source_table": table}
                for i, val in enumerate(extra):
                    record[columns[i] if i < len(columns) else f"col{i + 1}"] = val
                yield record
                continue

            stmt = payload
            if CREATE_RE.match(stmt):
                tbl, cols = parse_create_columns(stmt)
                if tbl:
                    schemas[tbl] = cols
                continue

            m_ins = INSERT_RE.match(stmt)
            if m_ins:
                found_data = True
                table = clean_name(m_ins.group(1))
                seen_tables.add(table)
                cols_raw = m_ins.group(2)
                columns = [clean_name(c) for c in cols_raw.strip("()").split(",")] if cols_raw else schemas.get(table, [])
                rows = read_insert_rows(stmt, m_ins.end())
                for row in rows:
                    record = {"_source_table": table}
                    for i, val in enumerate(row):
                        record[columns[i] if i < len(columns) else f"col{i + 1}"] = val
                    yield record

        if not found_data:
            for kind, payload, _ in self._iter_statements():
                if kind == "stmt":
                    yield {"statement": payload}