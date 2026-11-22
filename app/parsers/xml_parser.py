import xml.etree.ElementTree as ET

from app.parsers.base import BaseParser
from app.parsers.text import CountingRaw


def tag_name(tag):
    return tag.rsplit("}", 1)[-1]


def flatten(element, prefix=""):
    out = {}
    for key, value in element.attrib.items():
        out[f"{prefix}{tag_name(key)}"] = value.strip()
    children = list(element)
    text = (element.text or "").strip()
    if not children:
        if text or not out:
            out[prefix.rstrip(".") or tag_name(element.tag)] = text
        return out
    if text:
        out[f"{prefix}text"] = text
    for child in children:
        name = f"{prefix}{tag_name(child.tag)}"
        for key, value in flatten(child, f"{name}.").items():
            out[key] = f"{out[key]}, {value}" if key in out and value else out.get(key, value)
    return out


class XmlParser(BaseParser):
    extensions = (".xml",)

    def rows(self):
        with open(self.path, "rb") as raw:
            stream = CountingRaw(raw, self)
            depth, root, leaves, simple = 0, None, [], True
            for event, element in ET.iterparse(stream, events=("start", "end")):
                if event == "start":
                    depth += 1
                    if root is None:
                        root = element
                    continue
                depth -= 1
                if depth != 1:
                    continue
                is_leaf = not len(element) and not element.attrib
                if simple and is_leaf:
                    leaves.append(element)
                    continue
                if simple:
                    simple = False
                    for leaf in leaves:
                        yield flatten(leaf)
                    leaves = []
                yield flatten(element)
                element.clear()
                root.remove(element)
            if root is not None and simple:
                yield flatten(root)
