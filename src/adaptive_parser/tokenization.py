"""Lossless whitespace tokenization; normalized features never replace raw text."""

import hashlib
import json
import re
import unicodedata

from .contracts import SCHEMA_VERSION, Token

TOKENIZER_VERSION = "unicode-whitespace-spans-v1"
ENCODER_VERSION = "overlapping-clues-v2-postal-aliases"
PREFIXES = {"mr", "mrs", "ms", "miss", "dr", "prof"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
DIRECTIONALS = {"n", "s", "e", "w", "ne", "nw", "se", "sw"}
STREET_TYPES = {"street", "st", "avenue", "ave", "road", "rd", "drive", "dr",
                "boulevard", "blvd", "lane", "ln", "highway", "hwy", "court", "ct"}
# Keep the legacy lexicons above unchanged for the historical baseline. Runtime
# additions follow USPS Publication 28, C1 and I4; see docs/dataset_coverage.md.
RUNTIME_DIRECTIONALS = DIRECTIONALS | {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"}
RUNTIME_STREET_TYPES = STREET_TYPES | set(
    "circle cir place pl trail trl terrace ter parkway pkwy way square sq loop cove cv "
    "crossing xing point pt heights hts park pike run walk row path pass".split())
UNIT_TYPES = {"apt", "apartment", "unit", "suite", "ste"}
US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR".split())


def tokenize(raw: str) -> list[Token]:
    return [Token(i, m.group(), m.start(), m.end()) for i, m in enumerate(re.finditer(r"\S+", raw))]


def clean(text: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", unicodedata.normalize("NFKC", text)).strip()


def legacy_code(text: str) -> str:
    # Match the legacy precedence, including its ambiguous Dr/MS behavior.
    token = re.sub(r"^[^\w]+|[^\w]+$", "", text).strip()
    for code, lexicon in (("P", PREFIXES), ("J", SUFFIXES), ("D", DIRECTIONALS),
                          ("F", STREET_TYPES), ("S", UNIT_TYPES)):
        if token.lower() in lexicon:
            return code
    if token.upper() in US_STATES:
        return "T"
    return "N" if token and token[0].isdigit() else "W"


def clues(text: str) -> frozenset[str]:
    token = clean(text)
    result = set()
    for code, lexicon in (("P", PREFIXES), ("J", SUFFIXES), ("D", RUNTIME_DIRECTIONALS),
                          ("F", RUNTIME_STREET_TYPES), ("S", UNIT_TYPES)):
        if token.lower() in lexicon:
            result.add(code)
    if token.upper() in US_STATES:
        result.add("T")
    if token and token[0].isdigit():
        result.add("N")
    return frozenset(result or {"W"})


def signature(tokens: list[Token], locale: str, name_order: str | None = None) -> str:
    features = []
    for token in tokens:
        word = clean(token.text)
        shape = "zip" if re.fullmatch(r"\d{5}(?:-\d{4})?", word) else (
            "number" if word.isdigit() else "alphanumeric" if any(c.isdigit() for c in word) else "word"
        )
        punctuation = "".join(c for c in token.text if not c.isalnum())
        features.append([sorted(clues(token.text)), shape, punctuation])
    payload = [SCHEMA_VERSION, TOKENIZER_VERSION, ENCODER_VERSION, locale, name_order, features]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def input_fingerprint(raw: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", raw).casefold().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
