import csv
import itertools

from app.parsers.text import TextParser
from app.parsers.utils import KEY_VALUE, detect_delimiter

HEAD_LINES = 200


class TxtParser(TextParser):
    extensions = (".txt", ".text", ".log", ".md", ".dat")

    def rows(self):
        with self.open_text() as stream:
            buffered, head = [], []
            for line in stream:
                buffered.append(line)
                if line.strip():
                    head.append(line.rstrip("\r\n"))
                if len(head) >= HEAD_LINES:
                    break
            lines = itertools.chain(buffered, stream)
            delimiter = detect_delimiter(head)
            if delimiter:
                yield from csv.DictReader(lines, delimiter=delimiter)
            elif head and sum(1 for x in head if KEY_VALUE.match(x)) / len(head) >= 0.8:
                yield from self.blocks(lines)
            else:
                yield from self.plain(lines)

    @staticmethod
    def plain(lines):
        for line in lines:
            line = line.strip()
            if line:
                yield {"text": line}

    @staticmethod
    def blocks(lines):
        record, last = {}, None
        for line in lines:
            line = line.rstrip("\r\n")
            if not line.strip():
                if record:
                    yield record
                record, last = {}, None
                continue
            match = KEY_VALUE.match(line)
            if match:
                last = match.group(1)
                record[last] = match.group(2)
            elif last:
                record[last] = f"{record[last]} {line.strip()}"
            else:
                record["text"] = line.strip()
        if record:
            yield record
