import csv
import sys

from app.parsers.text import TextParser

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


class CsvParser(TextParser):
    extensions = (".csv", ".tsv")

    def dialect(self):
        try:
            return csv.Sniffer().sniff(self.sample_text(), delimiters=",;\t|")
        except csv.Error:
            return csv.excel

    def rows(self):
        dialect = self.dialect()
        with self.open_text() as stream:
            for row in csv.DictReader(stream, dialect=dialect):
                yield row
