class BaseParser:
    def __init__(self, path: str):
        self.path = path

    def parse(self):
        """Медленный режим обратной совместимости (построчный yield dict)."""
        raise NotImplementedError

    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        """Быстрый режим заливки в БД. Переопределяется в DuckDB-парсерах."""
        # Fallback для Python-парсеров (PDF, DOCX, HTML): собираем чанками и льем через pyarrow -> DuckDB -> Postgres
        import pyarrow as pa

        batch = []
        batch_size = 50_000
        con = ingestor._connect()
        created = False

        try:
            for record in self.parse():
                batch.append(record)
                if len(batch) >= batch_size:
                    arrow_tbl = pa.Table.from_pylist(batch)
                    con.register("tmp_batch", arrow_tbl)
                    if not created:
                        con.execute(f'CREATE TABLE IF NOT EXISTS pg_db.{schema}."{table_name}" AS SELECT * FROM tmp_batch LIMIT 0;')
                        created = True
                    con.execute(f'INSERT INTO pg_db.{schema}."{table_name}" SELECT * FROM tmp_batch;')
                    con.unregister("tmp_batch")
                    batch.clear()

            if batch:
                arrow_tbl = pa.Table.from_pylist(batch)
                con.register("tmp_batch", arrow_tbl)
                if not created:
                    con.execute(f'CREATE TABLE IF NOT EXISTS pg_db.{schema}."{table_name}" AS SELECT * FROM tmp_batch LIMIT 0;')
                con.execute(f'INSERT INTO pg_db.{schema}."{table_name}" SELECT * FROM tmp_batch;')
                con.unregister("tmp_batch")
        finally:
            con.close()