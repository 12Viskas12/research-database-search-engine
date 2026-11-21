import duckdb
from app.parsers.base import BaseParser
from app.parsers.utils import KEY_VALUE, detect_delimiter, detect_encoding


class TxtParser(BaseParser):
    def _inspect_mode(self):
        enc = detect_encoding(self.path)
        head = []
        with open(self.path, encoding=enc, errors="replace") as f:
            for _ in range(200):
                line = f.readline()
                if not line:
                    break
                if line.strip():
                    head.append(line)

        delimiter = detect_delimiter(head)
        if delimiter:
            return "csv", delimiter
        if head and sum(1 for x in head if KEY_VALUE.match(x)) / len(head) >= 0.8:
            return "kv", enc
        return "lines", enc

    def to_postgres(self, ingestor, table_name: str, schema: str = "public"):
        mode, param = self._inspect_mode()
        if mode == "csv":
            safe_path = self.path.replace("'", "''")
            sep = param.replace("'", "''")
            query = f"SELECT * FROM read_csv('{safe_path}', delim='{sep}', auto_detect=true, ignore_errors=true)"
            ingestor.ingest_sql_query(query, table_name, schema)
        else:
            # Для Key-Value и сплошного текста работает потоковый fallback из BaseParser
            super().to_postgres(ingestor, table_name, schema)

    def parse(self):
        mode, param = self._inspect_mode()
        if mode == "csv":
            safe_path = self.path.replace("'", "''")
            sep = param.replace("'", "''")
            con = duckdb.connect()
            cursor = con.execute(f"SELECT * FROM read_csv('{safe_path}', delim='{sep}', auto_detect=true, ignore_errors=true)")
            cols = [d[0] for d in cursor.description]
            while rows := cursor.fetchmany(10_000):
                for r in rows:
                    yield dict(zip(cols, r))
            con.close()
            return

        # Потоковое чтение без read_text() для гигантских логов и KV-файлов
        with open(self.path, encoding=param, errors="replace") as f:
            if mode == "kv":
                yield from self._blocks(f)
            else:
                for line in f:
                    line = line.strip()
                    if line:
                        yield {"text": line}

    def _blocks(self, file_obj):
        record = {}
        last = None
        for line in file_obj:
            if not line.strip():
                if record:
                    yield record
                record, last = {}, None
                continue
            m = KEY_VALUE.match(line)
            if m:
                last = m.group(1)
                record[last] = m.group(2)
            elif last:
                record[last] = f"{record[last]} {line.strip()}"
            else:
                record["text"] = line.strip()
        if record:
            yield record