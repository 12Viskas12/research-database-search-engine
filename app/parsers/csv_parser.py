import csv

from app.parsers.base import BaseParser

ENCODINGS = ("utf-8-sig", "cp1251")


class CsvParser(BaseParser):
    def _encoding(self):
        for enc in ENCODINGS:
            try:
                with open(self.path, encoding=enc, newline="") as f:
                    while f.read(1 << 20):
                        pass
                return enc
            except UnicodeDecodeError:
                continue
        return "latin-1"

    def parse(self):
        with open(self.path, encoding=self._encoding(), newline="") as f:
            sample = f.read(65536)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            for row in csv.DictReader(f, dialect=dialect):
                yield row
