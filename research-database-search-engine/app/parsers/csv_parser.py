import csv

from app.parsers.base import BaseParser
from app.parsers.utils import detect_encoding


class CsvParser(BaseParser):
    def parse(self):
        with open(self.path, encoding=detect_encoding(self.path), newline="") as f:
            sample = f.read(65536)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            for row in csv.DictReader(f, dialect=dialect):
                yield row
