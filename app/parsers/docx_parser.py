import xml.etree.ElementTree as ET
import zipfile

from app.parsers.base import TableParser

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def text_of(element):
    return "".join(t.text or "" for t in element.iter(f"{W}t")).strip()


class DocxParser(TableParser):
    extensions = (".docx",)

    def rows(self):
        with zipfile.ZipFile(self.path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        body = root.find(f"{W}body")
        if body is None:
            return
        for node in body:
            if node.tag == f"{W}p":
                text = text_of(node)
                if text:
                    yield {"text": text}
            elif node.tag == f"{W}tbl":
                yield from self.table(node)

    def table(self, table):
        rows = [[text_of(c) for c in tr.findall(f"{W}tc")] for tr in table.findall(f"{W}tr")]
        rows = [r for r in rows if any(r)]
        if len(rows) < 2:
            for row in rows:
                yield {"text": " ".join(row)}
            return
        header = self.header_of(rows[0])
        for row in rows[1:]:
            yield self.record_of(header, row)
