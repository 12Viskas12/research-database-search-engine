import csv
import io

from app.parsers.base import BaseParser
from app.parsers.utils import KEY_VALUE, detect_delimiter, read_text


class TxtParser(BaseParser):
    def parse(self):
        text = read_text(self.path)
        lines = text.splitlines()
        head = [x for x in lines[:200] if x.strip()]

        delimiter = detect_delimiter(head)
        if delimiter:
            yield from csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
            return

        if head and sum(1 for x in head if KEY_VALUE.match(x)) / len(head) >= 0.8:
            yield from self._blocks(lines)
            return

        for line in lines:
            line = line.strip()
            if line:
                yield {"text": line}

    def _blocks(self, lines):
        record = {}
        last = None
        for line in lines:
            if not line.strip():
                if record:
                    yield record
                record, last = {}, None
                continue
            m = KEY_VALUE.match(line)
            if m:
                last = m.group(1)
                record[last] = m.group(2)
            elif last:
                record[last] = f"{record[last]} {line.strip()}"
            else:
                record["text"] = line.strip()
        if record:
            yield record
