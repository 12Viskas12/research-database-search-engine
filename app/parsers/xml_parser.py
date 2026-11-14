import xml.etree.ElementTree as ET
from app.parsers.base import BaseParser


class XmlParser(BaseParser):
    def parse(self):
        root = ET.parse(self.path).getroot()
        for item in root:
            yield {child.tag: (child.text or "").strip() for child in item}
