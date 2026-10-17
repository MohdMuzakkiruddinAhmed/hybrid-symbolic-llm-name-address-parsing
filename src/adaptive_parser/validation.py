"""Explicit proposal parsing and a limited, U.S. street-address structural gate.

This gate cannot prove semantic name roles or universal safe reuse. It is a
development implementation whose false acceptance needs independent evaluation.
"""

import json
import re

from .contracts import InputRecord, NAME_FIELDS, Proposal, TOKEN_FIELDS, Token, Validation
from .tokenization import US_STATES, clean, clues

CODE_FIELDS = {
    "P": {"prefix_title"}, "J": {"suffix"},
    "D": {"pre_directional", "post_directional"}, "F": {"street_type"},
    "S": {"unit_type"}, "T": {"state"},
    "N": {"street_number", "unit_number", "postal_code"}, "W": TOKEN_FIELDS,
}
VALIDATOR_VERSION = "structural-v0.5-typed-streets"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def parse_proposal(text: str, normalize_fence: bool = True) -> Proposal:
    text = text.strip()
    deviations = ()
    if normalize_fence:
        fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.S | re.I)
        if fence:
            text = fence.group(1).strip()
            deviations = ("markdown_fence_removed",)
    raw = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(raw, dict) or not {"status", "mapping"} <= raw.keys():
        raise ValueError("proposal_requires_status_and_mapping")
    if raw.keys() - {"status", "mapping", "reason"}:
        raise ValueError("unexpected_proposal_fields")
    if raw["status"] not in ("mapped", "ambiguous", "unsupported"):
        raise ValueError("invalid_proposal_status")
    if not isinstance(raw["mapping"], dict) or not isinstance(raw.get("reason", ""), str):
        raise ValueError("invalid_proposal_types")
    mapping = {}
    for position, label in raw["mapping"].items():
        if not isinstance(position, str) or not re.fullmatch(r"0|[1-9]\d*", position):
            raise ValueError("invalid_token_position")
        if not isinstance(label, str) or label not in TOKEN_FIELDS:
            raise ValueError("invalid_schema_label")
        mapping[int(position)] = label
    if raw["status"] != "mapped" and mapping:
        raise ValueError("abstention_requires_empty_mapping")
    return Proposal(raw["status"], mapping, raw.get("reason", "")[:1000], deviations)


def input_reasons(record: InputRecord, tokens: list[Token]) -> list[str]:
    if not tokens:
        return ["empty_input"]
    if record.locale != "en-US":
        return ["unsupported_locale"]
    if len(record.raw) > 4000 or len(tokens) > 100:
        return ["input_limit_exceeded"]
    if re.search(r"\bP\.?\s*O\.?\s+Box\b", record.raw, re.I):
        return ["unsupported_po_box"]
    return []


def validate_mapping(mapping: dict[int, str], tokens: list[Token], name_order: str | None = None) -> Validation:
    errors = []
    if set(mapping) != set(range(len(tokens))):
        errors.append("position_coverage")
    for position, label in mapping.items():
        if type(position) is not int or not isinstance(label, str) or label not in TOKEN_FIELDS:
            errors.append("schema_or_position_type")
    if errors:
        return Validation(False, tuple(errors))
    for token in tokens:
        compatible = set().union(*(CODE_FIELDS[c] for c in clues(token.text)))
        # Clue words can also be lexical values: NC 42 is a road name, Al can
        # be a given name, and N. can be a declared middle initial. Address
        # order and the explicit source convention still constrain the spans.
        compatible |= {"street_name", "city", "unit_number"}
        if name_order == "given_middle_family":
            compatible |= {"first_name", "middle_name", "last_name"}
        if mapping[token.index] not in compatible:
            errors.append(f"clue_conflict:{token.index}")
    positions = {label: sorted(i for i in mapping if mapping[i] == label) for label in TOKEN_FIELDS}
    for label, indices in positions.items():
        if indices and indices != list(range(min(indices), max(indices) + 1)):
            errors.append(f"noncontiguous_field:{label}")
    if name_order == "given_middle_family":
        for label in ("first_name", "last_name"):
            if len(positions[label]) != 1:
                errors.append(f"declared_name_single_token:{label}")
        if len(positions["middle_name"]) > 1 or any(
            not re.fullmatch(r"[^\W\d_]\.?", tokens[i].text, re.UNICODE)
            for i in positions["middle_name"]
        ):
            errors.append("declared_middle_initial")
        preceding_end = -1
        for label in ("prefix_title", "first_name", "middle_name", "last_name", "suffix"):
            indices = positions[label]
            if indices:
                if min(indices) <= preceding_end:
                    errors.append(f"declared_name_order:{label}")
                preceding_end = max(indices)
    for label in ("street_number", "state", "postal_code"):
        if len(positions[label]) != 1:
            errors.append(f"required_single_field:{label}")
    if not positions["street_name"] or not positions["city"]:
        errors.append("missing_street_or_city")
    if not positions["street_type"]:
        errors.append("required_street_type")
    street = positions["street_number"]
    if street:
        boundary = street[0]
        if not any(positions[label] for label in NAME_FIELDS):
            errors.append("missing_person_name")
        if any(i >= boundary for label in NAME_FIELDS for i in positions[label]):
            errors.append("name_after_address_boundary")
        if any(i < boundary for label in TOKEN_FIELDS - NAME_FIELDS for i in positions[label]):
            errors.append("address_before_street_number")
        if not re.fullmatch(r"\d+[A-Za-z]?(?:[-/]\d+[A-Za-z]?)?", clean(tokens[boundary].text)):
            errors.append("invalid_street_number")
    order = ("street_number", "pre_directional", "street_name", "street_type",
             "post_directional", "unit_type", "unit_number", "city", "state", "postal_code", "country")
    preceding_end = -1
    for label in order:
        indices = positions[label]
        if indices:
            if min(indices) <= preceding_end:
                errors.append(f"address_order:{label}")
            preceding_end = max(indices)
    for i in positions["state"]:
        if clean(tokens[i].text).upper() not in US_STATES:
            errors.append("invalid_us_state")
    for i in positions["postal_code"]:
        if not re.fullmatch(r"\d{5}(?:-\d{4})?", clean(tokens[i].text)):
            errors.append("invalid_postal_shape")
    if bool(positions["unit_type"]) != bool(positions["unit_number"]):
        errors.append("incomplete_unit")
    return Validation(not errors, tuple(errors))
