from app.parsers.base import BaseParser


class PdfParser(BaseParser):
    extensions = (".pdf",)

    def rows(self):
        from pypdf import PdfReader

        reader = PdfReader(self.path)
        if reader.is_encrypted:
            reader.decrypt("")
        total = max(1, len(reader.pages))
        for number, page in enumerate(reader.pages, 1):
            self.fraction = number / total
            for line in (page.extract_text() or "").splitlines():
                line = " ".join(line.split())
                if line:
                    yield {"page": number, "text": line}
