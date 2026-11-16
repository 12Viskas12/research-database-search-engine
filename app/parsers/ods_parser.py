import zipfile
import xml.etree.ElementTree as ET

from app.parsers.base import BaseParser

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
T = "{%s}" % NS["table"]
X = "{%s}" % NS["text"]
MAX_REPEAT = 256


def cell_value(cell):
    parts = ["".join(p.itertext()) for p in cell.findall(f"{X}p")]
    text = "\n".join(parts).strip()
    return text


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


class OdsParser(BaseParser):
    def parse(self):
        with zipfile.ZipFile(self.path) as z:
            root = ET.fromstring(z.read("content.xml"))
        for sheet in root.iter(f"{T}table"):
            header = None
            for row in sheet.iter(f"{T}table-row"):
                values = row_values(row)
                if not any(values):
                    continue
                if header is None:
                    header = [h or f"col{i + 1}" for i, h in enumerate(values)]
                    continue
                repeat = min(int(row.get(f"{T}number-rows-repeated", "1")), MAX_REPEAT)
                record = {
                    (header[i] if i < len(header) else f"col{i + 1}"): v
                    for i, v in enumerate(values)
                }
                for _ in range(repeat):
                    yield dict(record)
