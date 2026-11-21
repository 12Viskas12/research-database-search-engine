import re

PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}")
SEPARATORS = re.compile(r"[+\s().-]")


def phone_key(span):
    if DATE.match(span):
        return None
    digits = re.sub(r"\D", "", span)
    if not 9 <= len(digits) <= 15:
        return None
    local = len(digits) == 12 and digits.startswith("380")
    local = local or (len(digits) == 10 and digits.startswith("0"))
    if not (local or SEPARATORS.search(span)):
        return None
    return digits[-9:]


def query_text(text):
    def swap(match):
        return phone_key(match.group(0)) or match.group(0)

    return PHONE.sub(swap, text)


def index_extra(values):
    keys = []
    for value in values:
        for match in PHONE.finditer(value):
            key = phone_key(match.group(0))
            if key and key not in keys:
                keys.append(key)
    return " ".join(keys)
