import json

from app.parsers.text import CHUNK, TextParser
from app.parsers.utils import scalar

SPACE = " \t\r\n,"


def flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten(item, name))
        return out
    if isinstance(value, list):
        if all(not isinstance(x, (dict, list)) for x in value):
            joined = ", ".join(str(scalar(x)) for x in value if x is not None)
            return {prefix or "value": joined}
        return {prefix or "value": json.dumps(value, ensure_ascii=False)}
    return {prefix or "value": scalar(value)}


def records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for item in data.values():
            if isinstance(item, list) and item:
                return item
        return [data]
    return [data]


class JsonParser(TextParser):
    extensions = (".json", ".jsonl", ".ndjson")

    def rows(self):
        decoder = json.JSONDecoder()
        with self.open_text() as stream:
            first = stream.read(CHUNK)
            if first.lstrip().startswith("["):
                yield from self.array(decoder, first, stream)
            else:
                yield from self.documents(first, stream)

    def array(self, decoder, buffer, stream):
        buffer = buffer.lstrip()[1:]
        index, eof = 0, False
        while True:
            while True:
                while index < len(buffer) and buffer[index] in SPACE:
                    index += 1
                if index < len(buffer):
                    break
                more = stream.read(CHUNK)
                if not more:
                    return
                buffer, index = more, 0
            if buffer[index] == "]":
                return
            while True:
                try:
                    item, end = decoder.raw_decode(buffer, index)
                    if eof or (end < len(buffer) and buffer[end] in SPACE + "]"):
                        break
                except json.JSONDecodeError:
                    if eof:
                        raise
                more = stream.read(CHUNK)
                if more:
                    buffer = buffer[index:] + more
                    index = 0
                else:
                    eof = True
            yield flatten(item)
            index = end
            if index > CHUNK * 4:
                buffer, index = buffer[index:], 0

    def documents(self, first, stream):
        lines = self.lines_of(first, stream)
        head = next((x for x in lines if x.strip()), None)
        if head is None:
            return
        try:
            obj = json.loads(head)
        except json.JSONDecodeError:
            whole = head + "\n" + "\n".join(lines)
            for item in records(json.loads(whole)):
                yield flatten(item)
            return
        following = next((x for x in lines if x.strip()), None)
        if following is None:
            for item in records(obj):
                yield flatten(item)
            return
        yield flatten(obj)
        for line in self.chain(following, lines):
            line = line.strip()
            if not line:
                continue
            try:
                yield flatten(json.loads(line))
            except json.JSONDecodeError:
                continue

    @staticmethod
    def chain(first, rest):
        yield first
        yield from rest
