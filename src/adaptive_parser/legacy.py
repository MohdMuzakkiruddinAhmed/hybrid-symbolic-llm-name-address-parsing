"""Legacy V1/V2 admission decisions, retained for research comparisons.

Return reason codes rather than the original notebook's prose. Approval decisions
are parity-checked against its 150 original diagnostic proposals per validator.
"""

from .contracts import TOKEN_FIELDS
from .tokenization import legacy_code
from .validation import CODE_FIELDS


def validate_v1(mapping, tokens, clue_codes=None):
    codes = clue_codes if clue_codes is not None else [legacy_code(t) for t in tokens]
    errors = []
    if set(mapping) != set(range(len(tokens))):
        errors.append("position_coverage")
    for position, label in mapping.items():
        if label not in TOKEN_FIELDS:
            errors.append(f"schema:{position}")
    for position, code in enumerate(codes):
        if position in mapping and mapping[position] in TOKEN_FIELDS and mapping[position] not in CODE_FIELDS[code]:
            errors.append(f"clue:{position}")
    return not errors, errors


def validate_v2(mapping, tokens, clue_codes=None):
    codes = clue_codes if clue_codes is not None else [legacy_code(t) for t in tokens]
    approved, errors = validate_v1(mapping, tokens, codes)
    if not approved:
        return approved, errors
    boundary = next((i for i, code in enumerate(codes) if code == "N"), None)
    if boundary is not None:
        core = [i for i in range(boundary) if codes[i] not in {"P", "J"}]
        expected = ("first_name", "last_name") if len(core) == 2 else (
            ("first_name", "middle_name", "last_name") if len(core) == 3 else ()
        )
        for position, field in zip(core, expected):
            if mapping.get(position) != field:
                errors.append(f"name_position:{position}")
    return not errors, errors
