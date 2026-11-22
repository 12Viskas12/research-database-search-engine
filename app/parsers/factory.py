import os

from app.parsers import base, text  # noqa: F401
from app.parsers.base import BaseParser
from app.parsers.csv_parser import CsvParser  # noqa: F401
from app.parsers.docx_parser import DocxParser  # noqa: F401
from app.parsers.html_parser import HtmlParser  # noqa: F401
from app.parsers.json_parser import JsonParser  # noqa: F401
from app.parsers.ods_parser import OdsParser  # noqa: F401
from app.parsers.pdf_parser import PdfParser  # noqa: F401
from app.parsers.sql_parser import SqlParser  # noqa: F401
from app.parsers.txt_parser import TxtParser
from app.parsers.xls_parser import XlsParser  # noqa: F401
from app.parsers.xlsx_parser import XlsxParser  # noqa: F401
from app.parsers.xml_parser import XmlParser  # noqa: F401

PARSERS = BaseParser.registry


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
