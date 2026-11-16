import os

from app.parsers.csv_parser import CsvParser
from app.parsers.docx_parser import DocxParser
from app.parsers.html_parser import HtmlParser
from app.parsers.json_parser import JsonParser
from app.parsers.ods_parser import OdsParser
from app.parsers.pdf_parser import PdfParser
from app.parsers.sql_parser import SqlParser
from app.parsers.txt_parser import TxtParser
from app.parsers.xls_parser import XlsParser
from app.parsers.xlsx_parser import XlsxParser
from app.parsers.xml_parser import XmlParser

PARSERS = {
    ".csv": CsvParser,
    ".tsv": CsvParser,
    ".xlsx": XlsxParser,
    ".xlsm": XlsxParser,
    ".xls": XlsParser,
    ".ods": OdsParser,
    ".xml": XmlParser,
    ".json": JsonParser,
    ".jsonl": JsonParser,
    ".ndjson": JsonParser,
    ".sql": SqlParser,
    ".html": HtmlParser,
    ".htm": HtmlParser,
    ".docx": DocxParser,
    ".pdf": PdfParser,
    ".txt": TxtParser,
    ".text": TxtParser,
    ".log": TxtParser,
    ".md": TxtParser,
    ".dat": TxtParser,
}


def is_text(path):
    with open(path, "rb") as f:
        head = f.read(8192)
    return b"\x00" not in head or head.startswith((b"\xff\xfe", b"\xfe\xff"))


def get_parser(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in PARSERS:
        return PARSERS[ext](path)
    if is_text(path):
        return TxtParser(path)
    raise ValueError(f"Unsupported file type: {ext or 'unknown'}")
