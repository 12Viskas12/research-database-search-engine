import duckdb
from app.parsers.base import BaseParser


class XlsxParser(BaseParser):
    def _duck_query(self) -> str:
        safe_path = self.path.replace("'", "''")
        return f"SELECT * FROM read_xlsx('{safe_path}', all_varchar=true)"

    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        con = ingestor._connect()
        try:
            con.execute("INSTALL excel; LOAD excel;")
            q = self._duck_query()
            con.execute(f'CREATE TABLE IF NOT EXISTS pg_db.{schema}."{table_name}" AS SELECT * FROM ({q}) LIMIT 0;')
            con.execute(f'INSERT INTO pg_db.{schema}."{table_name}" {q};')
        except Exception:
            # Fallback на потоковый openpyxl через BaseParser.to_postgres
            super().to_postgres(ingestor, table_name, schema)
        finally:
            con.close()

    def parse(self):
        try:
            con = duckdb.connect()
            con.execute("INSTALL excel; LOAD excel;")
            cursor = con.execute(self._duck_query())
            cols = [d[0] for d in cursor.description]
            while rows := cursor.fetchmany(10_000):
                for r in rows:
                    yield dict(zip(cols, r))
            con.close()
        except Exception:
            yield from self._fallback_openpyxl()

    def _fallback_openpyxl(self):
        import openpyxl

        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        try:
            for sheet in wb.worksheets:
                rows_iter = sheet.iter_rows(values_only=True)
                header = None
                for row in rows_iter:
                    if not any(v is not None and str(v).strip() != "" for v in row):
                        continue
                    if header is None:
                        header = [str(h).strip() if h is not None and str(h).strip() else f"col{i + 1}" for i, h in enumerate(row)]
                        continue
                    yield {
                        (header[i] if i < len(header) else f"col{i + 1}"): ("" if v is None else str(v))
                        for i, v in enumerate(row)
                    }
        finally:
            wb.close()