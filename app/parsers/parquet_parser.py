import duckdb
from app.parsers.base import BaseParser


class ParquetParser(BaseParser):
    def _query(self) -> str:
        safe_path = self.path.replace("'", "''")
        return f"SELECT * FROM read_parquet('{safe_path}')"

    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        ingestor.ingest_sql_query(self._query(), table_name, schema)

    def parse(self):
        con = duckdb.connect()
        cursor = con.execute(self._query())
        cols = [d[0] for d in cursor.description]
        while rows := cursor.fetchmany(10_000):
            for r in rows:
                yield dict(zip(cols, r))
        con.close()