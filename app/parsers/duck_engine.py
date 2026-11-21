import os
import duckdb


class DuckIngestor:
    def __init__(self, pg_dsn: str, memory_limit: str = "4GB", threads: int = 4):
        self.pg_dsn = pg_dsn
        self.memory_limit = memory_limit
        self.threads = threads

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(database=":memory:")
        con.execute(f"SET memory_limit = '{self.memory_limit}';")
        con.execute(f"SET threads = {self.threads};")
        # Подключаем расширение для прямой заливки в Postgres через COPY
        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute(f"ATTACH '{self.pg_dsn}' AS pg_db (TYPE postgres);")
        return con

    def ingest_sql_query(self, select_sql: str, target_table: str, schema: str = "public"):
        """Выполняет SELECT в DuckDB и льет результат напрямую в таблицу Postgres."""
        con = self._connect()
        try:
            # Создаем таблицу автоматически по типам, которые определил DuckDB, и заливаем данные
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS pg_db.{schema}."{target_table}" AS 
                SELECT * FROM ({select_sql}) LIMIT 0;
            """)
            con.execute(f"""
                INSERT INTO pg_db.{schema}."{target_table}"
                {select_sql};
            """)
        finally:
            con.close()

    def iter_batches(self, select_sql: str, batch_size: int = 10_000):
        """Fallback: если нужен старый интерфейс yield dict, читаем батчами без загрузки всего файла в RAM."""
        con = self._connect()
        try:
            cursor = con.execute(select_sql)
            cols = [desc[0] for desc in cursor.description]
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    yield dict(zip(cols, row))
        finally:
            con.close()