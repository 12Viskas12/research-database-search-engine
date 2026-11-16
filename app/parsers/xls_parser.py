from app.parsers.base import BaseParser


class XlsParser(BaseParser):
    def parse(self):
        import xlrd

        wb = xlrd.open_workbook(self.path, on_demand=True)
        try:
            for sheet in wb.sheets():
                if sheet.nrows < 1:
                    continue
                header = [
                    str(h).strip() or f"col{i + 1}"
                    for i, h in enumerate(sheet.row_values(0))
                ]
                for r in range(1, sheet.nrows):
                    record = {}
                    for i, cell in enumerate(sheet.row(r)):
                        name = header[i] if i < len(header) else f"col{i + 1}"
                        record[name] = self._value(xlrd, wb, cell)
                    yield record
                wb.unload_sheet(sheet.name)
        finally:
            wb.release_resources()

    def _value(self, xlrd, wb, cell):
        if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
            return None
        if cell.ctype == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate_as_datetime(cell.value, wb.datemode).isoformat()
            except Exception:
                return str(cell.value)
        if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
            return int(cell.value)
        if cell.ctype == xlrd.XL_CELL_BOOLEAN:
            return "true" if cell.value else "false"
        return cell.value
