from lxml import etree, html

from app.parsers.base import TableParser

BLOCKS = (
    "p", "div", "li", "br", "tr", "pre", "blockquote", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "header", "footer", "td", "th",
)


def cell_text(cell):
    return " ".join(cell.text_content().split())


class HtmlParser(TableParser):
    extensions = (".html", ".htm")

    def rows(self):
        tree = html.parse(self.path)
        etree.strip_elements(tree, "script", "style", "noscript", with_tail=False)
        root = tree.getroot()
        if root is None:
            return
        found = False
        for table in root.xpath("//table"):
            rows = [[cell_text(c) for c in tr.xpath("./th|./td")] for tr in table.xpath(".//tr")]
            rows = [r for r in rows if any(r)]
            if len(rows) < 2:
                continue
            found = True
            header = self.header_of(rows[0])
            for row in rows[1:]:
                yield self.record_of(header, row)
        if found:
            return
        for element in root.iter(*BLOCKS):
            element.text = "\n" + (element.text or "")
            element.tail = "\n" + (element.tail or "")
        for line in root.text_content().splitlines():
            line = " ".join(line.split())
            if line:
                yield {"text": line}
