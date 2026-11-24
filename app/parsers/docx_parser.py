import zipfile
import xml.etree.ElementTree as ET
from app.parsers.base import BaseParser

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def text_of(element):
    return "".join(t.text or "" for t in element.iter(f"{W}t")).strip()


class DocxParser(BaseParser):
    def parse(self):
        with zipfile.ZipFile(self.path) as z:
            with z.open("word/document.xml") as f:
                in_table = False
                for event, elem in ET.iterparse(f, events=("start", "end")):
                    if event == "start" and elem.tag == f"{W}tbl":
                        in_table = True
                    elif event == "end":
                        if elem.tag == f"{W}p" and not in_table:
                            text = text_of(elem)
                            if text:
                                yield {"text": text}
                            elem.clear()
                        elif elem.tag == f"{W}tbl":
                            in_table = False
                            yield from self._table(elem)
                            elem.clear()

    def _table(self, table):
        rows = [
            [text_of(c) for c in tr.findall(f"{W}tc")]
            for tr in table.findall(f"{W}tr")
        ]
        rows = [r for r in rows if any(r)]
        if len(rows) < 2:
            for row in rows:
                yield {"text": " ".join(row)}
            return
        header = [h or f"col{i + 1}" for i, h in enumerate(rows[0])]
        for row in rows[1:]:
            yield {
                (header[i] if i < len(header) else f"col{i + 1}"): v
                for i, v in enumerate(row)
            }