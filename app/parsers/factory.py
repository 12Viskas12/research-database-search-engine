import os
from app.parsers.csv_parser import CsvParser
from app.parsers.xlsx_parser import XlsxParser
from app.parsers.xml_parser import XmlParser

PARSERS = {
    ".csv": CsvParser,
    ".xlsx": XlsxParser,
    ".xml": XmlParser,
}


def get_parser(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in PARSERS:
        raise ValueError(f"Unsupported file type: {ext}")
    return PARSERS[ext](path)
