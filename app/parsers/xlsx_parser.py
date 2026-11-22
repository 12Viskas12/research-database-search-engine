from openpyxl import load_workbook

from app.parsers.base import TableParser


class XlsxParser(TableParser):
    extensions = (".xlsx", ".xlsm")

    def rows(self):
        workbook = load_workbook(self.path, read_only=True, data_only=True)
        try:
            sheets = workbook.worksheets
            for number, sheet in enumerate(sheets):
                rows = sheet.iter_rows(values_only=True)
                header = next(rows, None)
                if not header:
                    continue
                keys = self.header_of(header)
                limit = sheet.max_row or 0
                for index, row in enumerate(rows, 1):
                    if limit and index % 2000 == 0:
                        self.fraction = (number + min(1.0, index / limit)) / len(sheets)
                    yield self.record_of(keys, row)
        finally:
            workbook.close()
