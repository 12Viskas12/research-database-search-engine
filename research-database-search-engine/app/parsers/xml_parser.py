import xml.etree.ElementTree as ET

from app.parsers.base import BaseParser


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
        sub = flatten(child, f"{name}.")
        for key, value in sub.items():
            out[key] = f"{out[key]}, {value}" if key in out and value else out.get(key, value)
    return out


class XmlParser(BaseParser):
    def parse(self):
        root = ET.parse(self.path).getroot()
        items = list(root)
        if not items:
            yield flatten(root)
            return
        if all(not list(item) and not item.attrib for item in items):
            yield flatten(root)
            return
        for item in items:
            yield flatten(item)
