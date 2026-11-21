from openpyxl import load_workbook
from app.parsers.base import BaseParser


class XlsxParser(BaseParser):
    def parse(self):
        wb = load_workbook(self.path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                continue
            for row in rows:
                yield dict(zip(header, row))
