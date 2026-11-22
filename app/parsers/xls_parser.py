from app.parsers.base import TableParser


class XlsParser(TableParser):
    extensions = (".xls",)

    def rows(self):
        import xlrd

        workbook = xlrd.open_workbook(self.path, on_demand=True)
        try:
            sheets = [s for s in workbook.sheets() if s.nrows >= 1]
            for number, sheet in enumerate(sheets):
                header = self.header_of(sheet.row_values(0))
                for index in range(1, sheet.nrows):
                    if index % 2000 == 0:
                        self.fraction = (number + index / sheet.nrows) / len(sheets)
                    values = [self.value(xlrd, workbook, c) for c in sheet.row(index)]
                    yield self.record_of(header, values)
                workbook.unload_sheet(sheet.name)
        finally:
            workbook.release_resources()

    @staticmethod
    def value(xlrd, workbook, cell):
        if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
            return None
        if cell.ctype == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate_as_datetime(cell.value, workbook.datemode).isoformat()
            except Exception:
                return str(cell.value)
        if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
            return int(cell.value)
        if cell.ctype == xlrd.XL_CELL_BOOLEAN:
            return "true" if cell.value else "false"
        return cell.value
