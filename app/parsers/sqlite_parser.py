import duckdb
from app.parsers.base import BaseParser


class SqliteParser(BaseParser):
    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        con = ingestor._connect()
        safe_path = self.path.replace("'", "''")
        try:
            con.execute("INSTALL sqlite; LOAD sqlite;")
            con.execute(f"ATTACH '{safe_path}' AS src_sqlite (TYPE sqlite, READ_ONLY);")
            tables = [r[0] for r in con.execute("SHOW TABLES FROM src_sqlite;").fetchall()]
            for tbl in tables:
                # Если в SQLite одна таблица — пишем в table_name, если несколько — добавляем суффикс
                dest = table_name if len(tables) == 1 else f"{table_name}_{tbl}"
                con.execute(f'CREATE TABLE IF NOT EXISTS pg_db.{schema}."{dest}" AS SELECT * FROM src_sqlite."{tbl}" LIMIT 0;')
                con.execute(f'INSERT INTO pg_db.{schema}."{dest}" SELECT * FROM src_sqlite."{tbl}";')
        finally:
            con.close()