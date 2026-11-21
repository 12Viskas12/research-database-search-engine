from lxml import etree, html
from app.parsers.base import BaseParser

BLOCKS = (
    "p", "div", "li", "br", "tr", "pre", "blockquote", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "header", "footer", "td", "th",
)


def cell_text(cell) -> str:
    return " ".join(cell.text_content().split())


class HtmlParser(BaseParser):
    def parse(self):
        tree = html.parse(self.path)
        etree.strip_elements(tree, "script", "style", "noscript", with_tail=False)
        root = tree.getroot()
        if root is None:
            return

        tables = root.xpath("//table")
        found = False
        for table in tables:
            rows = [
                [cell_text(c) for c in tr.xpath("./th|./td")]
                for tr in table.xpath(".//tr")
            ]
            rows = [r for r in rows if any(r)]
            if len(rows) < 2:
                continue
            found = True
            header = [h or f"col{i + 1}" for i, h in enumerate(rows[0])]
            for row in rows[1:]:
                yield {
                    (header[i] if i < len(header) else f"col{i + 1}"): v
                    for i, v in enumerate(row)
                }

        if found:
            return

        for el in root.iter(*BLOCKS):
            el.text = "\n" + (el.text or "")
            el.tail = "\n" + (el.tail or "")

        for line in root.text_content().splitlines():
            line = " ".join(line.split())
            if line:
                yield {"text": line}