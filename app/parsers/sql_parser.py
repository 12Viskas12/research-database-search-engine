import re

from app.parsers.text import CHUNK, TextParser

CREATE = re.compile(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)\s*\(", re.I)
INSERT = re.compile(
    r"INSERT\s+(?:IGNORE\s+)?INTO\s+([^\s(]+)\s*(\([^)]*\))?\s*(?:VALUES|VALUE)(?=[\s(])\s*", re.I
)
COPY = re.compile(r"COPY\s+([^\s(]+)\s*(\([^)]*\))?\s+FROM\s+stdin\s*;[ \t]*\r?\n", re.I)
HEAD = re.compile("(?P<create>" + CREATE.pattern + ")|(?P<insert>" + INSERT.pattern + ")|(?P<copy>" + COPY.pattern + ")", re.I)
STRING = re.compile(r"(?:[NnEeBbXx]|_[A-Za-z0-9]+)?'((?:[^'\\]|\\.|'')*)'", re.S)
ESCAPE = re.compile(r"\\(.)|''", re.S)
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "Z": "\x1a"}
NOT_COLUMNS = {
    "PRIMARY", "KEY", "UNIQUE", "CONSTRAINT", "FOREIGN", "INDEX",
    "FULLTEXT", "SPATIAL", "CHECK", "EXCLUDE", "LIKE",
}
SPACE = " \t\r\n"
KEEP = 8192
TRIM = 4 * 1024 * 1024
SPLIT = re.compile(r";[ \t]*\r?\n")
COPY_END = re.compile(r"^\\\.[ \t]*\r?$")


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


def create_end(text, pos):
    depth, i = 1, pos
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
    return i if depth == 0 else None


def column_names(body):
    columns = []
    for part in split_top(body):
        part = part.strip()
        if not part:
            continue
        first = re.split(r"\s+", part, maxsplit=1)[0]
        if first.upper() in NOT_COLUMNS:
            continue
        columns.append(clean_name(first))
    return columns


def read_rows(text, pos, final):
    rows = []
    n = len(text)
    while True:
        start = pos
        while pos < n and text[pos] in SPACE:
            pos += 1
        if pos < n and text[pos] == ",":
            pos += 1
            continue
        if pos >= n:
            return rows, start, final
        if text[pos] != "(":
            return rows, pos, True
        row_start = pos
        pos += 1
        row = []
        complete = True
        while True:
            while pos < n and text[pos] in SPACE:
                pos += 1
            m = STRING.match(text, pos)
            if m and not final and (m.end() >= n or text[m.end()] == "'"):
                complete = False
                break
            if m:
                row.append(unquote(m.group(1)))
                pos = m.end()
            elif pos < n and text[pos] == "'" and not final:
                complete = False
                break
            else:
                token_start, depth = pos, 0
                while pos < n:
                    c = text[pos]
                    if c == "'":
                        s = STRING.match(text, pos)
                        if not final and (s is None or s.end() >= n or text[s.end()] == "'"):
                            complete = False
                            break
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
                if not complete or (pos >= n and not final):
                    complete = False
                    break
                token = text[token_start:pos].strip()
                row.append(None if token.upper() == "NULL" else token)
            while pos < n and text[pos] in SPACE:
                pos += 1
            if pos >= n and not final:
                complete = False
                break
            if pos < n and text[pos] == ",":
                pos += 1
                continue
            if pos < n and text[pos] == ")":
                pos += 1
            break
        if not complete:
            return rows, row_start, False
        rows.append(row)
        after = pos
        while after < n and text[after] in SPACE:
            after += 1
        if after >= n and not final:
            return rows, pos, False
        if after < n and text[after] == ",":
            pos = after + 1
            continue
        return rows, pos, True


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


class Window:
    def __init__(self, stream):
        self.stream = stream
        self.text = ""
        self.pos = 0
        self.eof = False

    def more(self):
        chunk = self.stream.read(CHUNK)
        if not chunk:
            self.eof = True
            return False
        if self.pos > TRIM:
            self.text = self.text[self.pos :]
            self.pos = 0
        self.text += chunk
        return True


class SqlParser(TextParser):
    extensions = (".sql",)

    def tables(self):
        found, carry = set(), ""
        with open(self.path, encoding=self.encoding, errors="replace", newline="") as f:
            while len(found) < 2:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                text = carry + chunk
                for m in INSERT.finditer(text):
                    found.add(clean_name(m.group(1)))
                for m in COPY.finditer(text):
                    found.add(clean_name(m.group(1)))
                carry = text[-KEEP:]
        return found

    def rows(self):
        tables = self.tables()
        if not tables:
            yield from self.statements()
            return
        multi = len(tables) > 1
        schemas = {}
        with self.open_text() as stream:
            window = Window(stream)
            window.more()
            while True:
                m = HEAD.search(window.text, window.pos)
                if m is None:
                    if window.eof:
                        return
                    window.pos = max(window.pos, len(window.text) - KEEP)
                    window.more()
                    continue
                if m.group("create"):
                    end = create_end(window.text, m.end())
                    while end is None and window.more():
                        end = create_end(window.text, m.end())
                    if end is None:
                        end = len(window.text)
                    schemas[clean_name(m.group(2))] = column_names(window.text[m.end() : end - 1])
                    window.pos = end
                elif m.group("insert"):
                    table = clean_name(m.group(4))
                    columns = self.columns(m.group(5), schemas.get(table, []))
                    window.pos = m.end()
                    for row in self.insert_rows(window):
                        yield make_record(columns, row, table, multi)
                else:
                    table = clean_name(m.group(7))
                    columns = self.columns(m.group(8), schemas.get(table, []))
                    window.pos = m.end()
                    for row in self.copy_rows(window):
                        yield make_record(columns, row, table, multi)

    @staticmethod
    def columns(raw, fallback):
        if raw:
            return [clean_name(c) for c in raw.strip("()").split(",")]
        return fallback

    @staticmethod
    def insert_rows(window):
        while True:
            rows, pos, done = read_rows(window.text, window.pos, window.eof)
            window.pos = pos
            yield from rows
            if done:
                return
            if not window.more():
                rows, pos, _ = read_rows(window.text, window.pos, True)
                window.pos = pos
                yield from rows
                return

    @staticmethod
    def copy_rows(window):
        while True:
            newline = window.text.find("\n", window.pos)
            if newline == -1:
                if window.more():
                    continue
                line, window.pos = window.text[window.pos :], len(window.text)
                if line and not COPY_END.match(line):
                    yield [copy_value(v) for v in line.split("\t")]
                return
            line = window.text[window.pos : newline]
            window.pos = newline + 1
            if COPY_END.match(line):
                return
            line = line.rstrip("\r")
            if line:
                yield [copy_value(v) for v in line.split("\t")]

    def statements(self):
        self.consumed = 0
        with self.open_text() as stream:
            pending = ""
            while True:
                chunk = stream.read(CHUNK)
                pending += chunk
                parts = SPLIT.split(pending)
                pending = parts.pop() if chunk else ""
                for statement in parts:
                    statement = statement.strip()
                    if statement and not statement.startswith("--"):
                        yield {"statement": statement}
                if not chunk:
                    return
