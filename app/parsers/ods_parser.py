import xml.etree.ElementTree as ET
import zipfile

from app.parsers.base import TableParser

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
T = "{%s}" % NS["table"]
X = "{%s}" % NS["text"]
MAX_REPEAT = 256


def cell_value(cell):
    parts = ["".join(p.itertext()) for p in cell.findall(f"{X}p")]
    return "\n".join(parts).strip()


def row_values(row):
    values = []
    for cell in row:
        if cell.tag not in (f"{T}table-cell", f"{T}covered-table-cell"):
            continue
        repeat = int(cell.get(f"{T}number-columns-repeated", "1"))
        value = cell_value(cell)
        values.extend([value] * (repeat if value else min(repeat, 1)))
    while values and not values[-1]:
        values.pop()
    return values


class OdsParser(TableParser):
    extensions = (".ods",)

    def rows(self):
        with zipfile.ZipFile(self.path) as z:
            total = max(1, z.getinfo("content.xml").file_size)
            with z.open("content.xml") as stream:
                header, seen = None, 0
                for event, element in ET.iterparse(stream, events=("start", "end")):
                    if event == "start":
                        if element.tag == f"{T}table":
                            header = None
                        continue
                    if element.tag != f"{T}table-row":
                        continue
                    seen += 1
                    if seen % 500 == 0:
                        self.fraction = min(0.99, stream.tell() / total)
                    values = row_values(element)
                    if any(values):
                        if header is None:
                            header = self.header_of(values)
                        else:
                            repeat = min(int(element.get(f"{T}number-rows-repeated", "1")), MAX_REPEAT)
                            record = self.record_of(header, values)
                            for _ in range(repeat):
                                yield dict(record)
                    element.clear()
