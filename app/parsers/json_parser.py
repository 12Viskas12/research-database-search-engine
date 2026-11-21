import duckdb
from app.parsers.base import BaseParser


class JsonParser(BaseParser):
    def _query(self) -> str:
        safe_path = self.path.replace("'", "''")
        # format='auto' сам различает JSON-массив и построчный NDJSON/JSONL
        # maximum_object_size=104857600 (100 MB) защищает от падения на крупных вложенных объектах
        return (
            f"SELECT * FROM read_json_auto('{safe_path}', "
            f"format='auto', maximum_object_size=104857600, ignore_errors=true)"
        )

    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        ingestor.ingest_sql_query(self._query(), table_name, schema)

    def parse(self):
        con = duckdb.connect()
        try:
            cursor = con.execute(self._query())
            cols = [d[0] for d in cursor.description]
            while rows := cursor.fetchmany(10_000):
                for r in rows:
                    yield dict(zip(cols, r))
        finally:
            con.close()