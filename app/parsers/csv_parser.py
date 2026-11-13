import csv
from app.parsers.base import BaseParser


class CsvParser(BaseParser):
    def parse(self):
        with open(self.path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                yield row
