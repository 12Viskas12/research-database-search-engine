import os

from app.parsers.csv_parser import CsvParser
from app.parsers.docx_parser import DocxParser
from app.parsers.html_parser import HtmlParser
from app.parsers.json_parser import JsonParser
from app.parsers.ods_parser import OdsParser
from app.parsers.parquet_parser import ParquetParser
from app.parsers.pdf_parser import PdfParser
from app.parsers.sql_parser import SqlParser
from app.parsers.sqlite_parser import SqliteParser
from app.parsers.txt_parser import TxtParser
from app.parsers.xls_parser import XlsParser
from app.parsers.xlsx_parser import XlsxParser
from app.parsers.xml_parser import XmlParser

PARSERS = {
    ".csv": CsvParser,
    ".tsv": CsvParser,
    ".parquet": ParquetParser,
    ".db": SqliteParser,
    ".sqlite": SqliteParser,
    ".sqlite3": SqliteParser,
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