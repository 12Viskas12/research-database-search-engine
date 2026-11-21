import duckdb
from app.parsers.base import BaseParser


class XlsParser(BaseParser):
    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        con = ingestor._connect()
        safe_path = self.path.replace("'", "''")
        try:
            con.execute("INSTALL spatial; LOAD spatial;")
            q = f"SELECT * FROM st_read('{safe_path}')"
            con.execute(f'CREATE TABLE IF NOT EXISTS pg_db.{schema}."{table_name}" AS SELECT * FROM ({q}) LIMIT 0;')
            con.execute(f'INSERT INTO pg_db.{schema}."{table_name}" {q};')
        except Exception:
            super().to_postgres(ingestor, table_name, schema)
        finally:
            con.close()

    def parse(self):
        import xlrd

        wb = xlrd.open_workbook(self.path, on_demand=True)
        for sheet_idx in range(wb.nsheets):
            sheet = wb.sheet_by_index(sheet_idx)
            if sheet.nrows < 2:
                continue
            header = [
                str(sheet.cell_value(0, c)).strip() or f"col{c + 1}"
                for c in range(sheet.ncols)
            ]
            for r in range(1, sheet.nrows):
                row_vals = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
                if not any(v != "" for v in row_vals):
                    continue
                yield {
                    header[c]: ("" if row_vals[c] is None else str(row_vals[c]))
                    for c in range(sheet.ncols)
                }
            wb.unload_sheet(sheet_idx)