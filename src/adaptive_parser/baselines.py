"""Local comparators; all receive the same raw input and declared context."""

import json
import re

from .tokenization import PREFIXES, SUFFIXES, RUNTIME_DIRECTIONALS, RUNTIME_STREET_TYPES, US_STATES, clean, clues, tokenize


def name_prefix(record, tokens):
    if record.name_order != "given_middle_family":
        return None, None
    number = next((t.index for t in tokens if re.fullmatch(r"\d+[A-Za-z]?(?:[-/]\d+[A-Za-z]?)?", clean(t.text))), None)
    if number is None:
        return None, None
    indices = list(range(number))
    mapping = {}
    if indices and clean(tokens[indices[0]].text).lower() in PREFIXES:
        mapping[indices.pop(0)] = "prefix_title"
    if indices and clean(tokens[indices[-1]].text).lower() in SUFFIXES:
        mapping[indices.pop()] = "suffix"
    if len(indices) not in (2, 3):
        return None, None
    mapping[indices[0]], mapping[indices[-1]] = "first_name", "last_name"
    if len(indices) == 3:
        if not re.fullmatch(r"[^\W\d_]\.?", tokens[indices[1]].text, re.UNICODE):
            return None, None
        mapping[indices[1]] = "middle_name"
    return number, mapping


def response(mapping=None, reason="no_unique_supported_parse"):
    return {"text": json.dumps({"status": "mapped" if mapping is not None else "ambiguous",
                                "mapping": mapping or {}, "reason": "" if mapping is not None else reason})}


class GrammarProposer:
    route = "grammar"

    def propose(self, record, tokens):
        house, mapping = name_prefix(record, tokens)
        if house is None:
            return response()
        zip_index = next((t.index for t in reversed(tokens) if re.fullmatch(r"\d{5}(?:-\d{4})?", clean(t.text))), None)
        if zip_index is None or zip_index <= house + 3:
            return response()
        state = zip_index - 1
        if clean(tokens[state].text).upper() not in US_STATES:
            return response()
        mapping.update({house: "street_number", state: "state", zip_index: "postal_code"})
        mapping.update({i: "country" for i in range(zip_index + 1, len(tokens))})
        start = house + 1
        if clean(tokens[start].text).lower() in RUNTIME_DIRECTIONALS:
            mapping[start] = "pre_directional"
            start += 1
        # Deterministic conventional reading; ambiguity/false matches remain
        # measurable failures, not silently resolved using evaluator labels.
        kind = next((i for i in range(start + 1, state - 1) if clean(tokens[i].text).lower() in RUNTIME_STREET_TYPES), None)
        if kind is None:
            return response()
        mapping.update({i: "street_name" for i in range(start, kind)})
        mapping[kind] = "street_type"
        start = kind + 1
        if start < state and clean(tokens[start].text).lower() in RUNTIME_DIRECTIONALS:
            mapping[start] = "post_directional"
            start += 1
        if start < state and "S" in clues(tokens[start].text):
            if start + 2 >= state:
                return response()
            mapping[start], mapping[start + 1] = "unit_type", "unit_number"
            start += 2
        if start >= state:
            return response()
        mapping.update({i: "city" for i in range(start, state)})
        return response(mapping)


class USAddressProposer:
    """Native pretrained address tagger plus the shared explicit name convention."""
    route = "usaddress_composite"
    TAGS = {"AddressNumber": "street_number", "StreetNamePreDirectional": "pre_directional",
            "StreetName": "street_name", "StreetNamePostType": "street_type",
            "StreetNamePostDirectional": "post_directional", "OccupancyType": "unit_type",
            "OccupancyIdentifier": "unit_number", "PlaceName": "city", "StateName": "state", "ZipCode": "postal_code"}

    def propose(self, record, tokens):
        import usaddress
        house, mapping = name_prefix(record, tokens)
        if house is None:
            return response()
        end = next((t.index for t in reversed(tokens) if re.fullmatch(r"\d{5}(?:-\d{4})?", clean(t.text))), None)
        if end is None or end <= house:
            return response()
        parsed = usaddress.parse(record.raw[tokens[house].start:tokens[end].end])
        if len(parsed) != end - house + 1:
            return response(reason="native_token_alignment_unsupported")
        for index, (text, tag) in enumerate(parsed, house):
            if text != tokens[index].text or tag not in self.TAGS:
                return response(reason="native_token_or_label_not_representable")
            mapping[index] = self.TAGS[tag]
        mapping.update({i: "country" for i in range(end + 1, len(tokens))})
        return response(mapping)


def features(record):
    tokens = tokenize(record.raw)
    result = []
    for i, token in enumerate(tokens):
        word = token.text
        row = {"bias": 1.0, "word": word.casefold(), "clean": clean(word).casefold(),
               "upper": word.isupper(), "digit": word.isdigit(), "initial": bool(re.fullmatch(r"[A-Za-z]\.?", word)),
               "position": i, "relative_position": i / max(1, len(tokens) - 1),
               "remaining": len(tokens) - i, "locale": record.locale, "name_order": str(record.name_order)}
        row.update({"clue:" + c: True for c in clues(word)})
        for n in (1, 2, 3):
            row["suffix" + str(n)] = word[-n:].casefold()
        for offset in (-2, -1, 1, 2):
            j = i + offset
            if 0 <= j < len(tokens):
                row[f"neighbor{offset}"] = tokens[j].text.casefold()
                row[f"neighbor{offset}_clues"] = "".join(sorted(clues(tokens[j].text)))
        result.append(row)
    return result


class CRFProposer:
    route = "trained_crf"

    def __init__(self, model, threshold=0.0):
        self.model, self.threshold = model, threshold
        self.last_confidence = 0.0

    def propose(self, record, tokens):
        if record.name_order is None:
            return response(reason="name_order_not_declared")
        x = features(record)
        labels = self.model.predict_single(x)
        marginals = self.model.predict_marginals_single(x)
        self.last_confidence = min((p[label] for p, label in zip(marginals, labels)), default=0.0)
        if self.last_confidence < self.threshold:
            return response(reason="crf_confidence_below_validation_threshold")
        return response(dict(enumerate(labels)))
