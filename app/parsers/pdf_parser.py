from app.parsers.base import BaseParser


class PdfParser(BaseParser):
    def parse(self):
        from pypdf import PdfReader

        reader = PdfReader(self.path)
        if reader.is_encrypted:
            reader.decrypt("")
        for number, page in enumerate(reader.pages, 1):
            for line in (page.extract_text() or "").splitlines():
                line = " ".join(line.split())
                if line:
                    yield {"page": number, "text": line}