from collections import Counter
from lxml import etree
from app.parsers.base import BaseParser


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def flatten_xml(elem, prefix: str = "") -> dict:
    out = {}
    for k, v in elem.attrib.items():
        attr_name = f"{prefix}.@{strip_ns(k)}" if prefix else f"@{strip_ns(k)}"
        out[attr_name] = v

    children = [c for c in elem if isinstance(c.tag, str)]
    if not children:
        text = (elem.text or "").strip()
        if text or not out:
            out[prefix or strip_ns(elem.tag)] = text
        return out

    for child in children:
        tag = strip_ns(child.tag)
        next_prefix = f"{prefix}.{tag}" if prefix else tag
        out.update(flatten_xml(child, next_prefix))
    return out


class XmlParser(BaseParser):
    def _detect_record_tag(self) -> str | None:
        """Сканирует начало XML и находит повторяющийся тег строки/записи."""
        counts = Counter()
        depth_map = {}
        context = etree.iterparse(self.path, events=("start", "end"), recover=True)
        scanned = 0
        depth = 0
        for event, elem in context:
            if not isinstance(elem.tag, str):
                continue
            if event == "start":
                depth += 1
                if depth >= 2:
                    counts[elem.tag] += 1
                    depth_map[elem.tag] = depth
            else:
                depth -= 1
                elem.clear()
                scanned += 1
                if scanned >= 2000:
                    break
        del context

        # Берем самый частый тег на глубине >= 2
        candidates = [(tag, cnt) for tag, cnt in counts.items() if cnt >= 2]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (-x[1], depth_map.get(x[0], 99)))
        return candidates[0][0]

    def parse(self):
        record_tag = self._detect_record_tag()
        if record_tag:
            context = etree.iterparse(self.path, events=("end",), tag=record_tag, recover=True)
            for _, elem in context:
                row = flatten_xml(elem)
                if any(v for v in row.values()):
                    yield row
                # Очищаем обработанный узел и ссылки на предыдущих соседей, чтобы RAM не росла
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
            del context
        else:
            # Если файл не содержит повторяющихся записей (плоский документ)
            tree = etree.parse(self.path, parser=etree.XMLParser(recover=True))
            root = tree.getroot()
            if root is not None:
                yield flatten_xml(root)