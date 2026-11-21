import json

from app.parsers.base import BaseParser
from app.parsers.utils import detect_encoding, read_text, scalar


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


class JsonParser(BaseParser):
    def parse(self):
        try:
            data = json.loads(read_text(self.path))
        except json.JSONDecodeError:
            yield from self._lines()
            return
        for item in records(data):
            yield flatten(item)

    def _lines(self):
        with open(self.path, encoding=detect_encoding(self.path)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield flatten(json.loads(line))
                except json.JSONDecodeError:
                    continue
