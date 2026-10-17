"""Dataset construction helpers, never imported by the runtime parser.

Labels here are source/construction-derived, not human-certified evaluation gold.
"""

import hashlib
import itertools
import json
import re

from .contracts import InputRecord, TOKEN_FIELDS, empty_fields
from .tokenization import input_fingerprint, tokenize

DATASET_VERSION = "corpus-draft-v1"
NAME_CONVENTION = "given_middle_family"


def addressnc_components(source):
    """Map separate authoritative components; never infer boundaries using our parser."""
    def value(key):
        raw = source.get(key)
        return " ".join(str(raw).split()) if raw is not None else ""
    for key in ("addnum_suf", "st_premod", "st_presep", "st_pretyp", "st_posmod", "building", "floor", "lot"):
        if value(key):
            return [], f"unmodeled_source_component:{key}"
    for key in ("add_number", "st_name", "st_postyp", "post_comm", "state", "post_code"):
        if not value(key):
            return [], f"missing_required_source_component:{key}"
    if not re.fullmatch(r"\d+[A-Za-z]?", value("add_number")):
        return [], "out_of_scope_number_shape"
    if not re.fullmatch(r"\d{5}(?:-\d{4})?", value("post_code")) or value("state") != "NC":
        return [], "out_of_scope_postal_or_state"
    if bool(value("unit")) != bool(value("unit_type")):
        return [], "unit_boundary_not_declared"
    fields = [("street_number", "add_number"), ("pre_directional", "st_predir"),
              ("street_name", "st_name"), ("street_type", "st_postyp"),
              ("post_directional", "st_posdir"), ("unit_type", "unit_type"),
              ("unit_number", "unit"), ("city", "post_comm"), ("state", "state"),
              ("postal_code", "post_code")]
    return [(field, value(key)) for field, key in fields if value(key)] + [("country", "USA")], None


def compose(record_id, components, *, name_order=NAME_CONVENTION, separator=" ", locale="en-US"):
    """Construct raw input and labels together using offsets, without re-parsing raw text."""
    spans, cursor, parts = [], 0, []
    for field, value in components:
        if field not in TOKEN_FIELDS or not value or not value.strip():
            raise ValueError("invalid declared component")
        if parts:
            cursor += len(separator)
        start = cursor
        parts.append(value)
        cursor += len(value)
        spans.append({"field": field, "start": start, "end": cursor})
    raw = separator.join(parts)
    record = InputRecord(record_id, raw, locale, name_order)
    mapping = {}
    for token in tokenize(raw):
        matches = [s["field"] for s in spans if s["start"] <= token.start and token.end <= s["end"]]
        if len(matches) != 1:
            raise ValueError("declared spans do not uniquely cover token")
        mapping[str(token.index)] = matches[0]
    expected = empty_fields(record_id)
    for span in spans:
        if expected[span["field"]] is not None:
            raise ValueError("a field must be one contiguous component")
        expected[span["field"]] = raw[span["start"]:span["end"]]
    return {"record_id": record.record_id, "raw": raw, "locale": locale, "name_order": name_order}, {
        "record_id": record_id, "expected_status": "mapped", "mapping": mapping,
        "fields": expected, "spans": spans, "fingerprint": input_fingerprint(raw),
        "label_basis": "construction_derived", "human_review_status": "pending"}


def registry():
    """8 name layouts x 50 actual token-field address sequences, with grouped splits."""
    addresses = [dict(street_words=s, city_words=c, pre_directional=p,
                      post_directional=q, unit=u)
                 for s, c, p, q, u in itertools.product((1, 2, 3), (1, 2), (False, True), (False, True), (False, True))]
    addresses += [dict(street_words=1, city_words=3, pre_directional=False,
                       post_directional=False, unit=u) for u in (False, True)]
    def key(a):
        return tuple(a[k] for k in ("street_words", "city_words", "pre_directional", "post_directional", "unit"))
    # The six inspected legacy structures use these address layouts. Keep them in development.
    legacy = {(1, 1, False, False, False), (1, 1, True, False, False),
              (1, 1, False, False, True), (1, 2, False, False, False)}
    required = [a for a in addresses if key(a) in legacy]
    other = sorted([a for a in addresses if key(a) not in legacy],
                   key=lambda a: hashlib.sha256(json.dumps(a, sort_keys=True).encode()).digest())
    ordered = required + other
    records = []
    for index, address in enumerate(ordered):
        split = "development" if index < 20 else "validation" if index < 30 else "final"
        address_id = "A-" + hashlib.sha256(json.dumps(address, sort_keys=True).encode()).hexdigest()[:12]
        for title, middle, suffix in itertools.product((False, True), repeat=3):
            names = {"title": title, "middle_initial": middle, "suffix": suffix}
            sequence = (["prefix_title"] if title else []) + ["first_name"]
            sequence += (["middle_name"] if middle else []) + ["last_name"] + (["suffix"] if suffix else [])
            sequence += ["street_number"] + (["pre_directional"] if address["pre_directional"] else [])
            sequence += ["street_name"] * address["street_words"] + ["street_type"]
            sequence += (["post_directional"] if address["post_directional"] else [])
            sequence += (["unit_type", "unit_number"] if address["unit"] else [])
            sequence += ["city"] * address["city_words"] + ["state", "postal_code", "country"]
            digest = hashlib.sha256(json.dumps(sequence).encode()).hexdigest()[:16]
            records.append({"family_id": "F-" + digest, "address_group": address_id, "split": split,
                            "name_layout": names, "address_layout": address, "field_sequence": sequence,
                            "name_order": NAME_CONVENTION,
                            "observability": "Source-declared given/middle-initial/family convention; street type, unit marker, state and ZIP delimit address components",
                            "rationale": "Distinct token-field sequence; lexical substitutions, whitespace and punctuation aliases stay in this family"})
    if len({tuple(r["field_sequence"]) for r in records}) != 400:
        raise ValueError("registry contains aliased semantic sequences")
    return records


def audit_rows(inputs, labels):
    """Check data integrity independently of parser admission or model predictions."""
    if len(inputs) != len(labels):
        raise ValueError("input/label length mismatch")
    ids, fingerprints, address_splits, family_splits, identities = set(), set(), {}, {}, {}
    grammar_splits, physical_splits = {}, {}
    counts = {}
    for record, gold in zip(inputs, labels):
        if set(record) != {"record_id", "raw", "locale", "name_order"}:
            raise ValueError("evaluator metadata leaked into runtime input")
        InputRecord(**record)
        rid = record["record_id"]
        fingerprint = input_fingerprint(record["raw"])
        if rid != gold["record_id"] or rid in ids or fingerprint in fingerprints:
            raise ValueError("duplicate or mismatched input")
        if fingerprint != gold["fingerprint"]:
            raise ValueError("fingerprint mismatch")
        ids.add(rid)
        fingerprints.add(fingerprint)
        split, cohort = gold["split"], gold["cohort"]
        counts[f"{cohort}/{split}"] = counts.get(f"{cohort}/{split}", 0) + 1
        if gold.get("source_group"):
            previous = address_splits.setdefault(gold["source_group"], split)
            if previous != split:
                raise ValueError("source jurisdiction leaks between splits")
        if gold.get("family_id") and cohort == "D1":
            previous = family_splits.setdefault(gold["family_id"], split)
            if previous != split:
                raise ValueError("D1 family leaks between splits")
            previous = grammar_splits.setdefault(gold["address_group"], split)
            if previous != split:
                raise ValueError("related D1 address layouts leak between splits")
        identity = gold.get("identity_id")
        if identity:
            previous = identities.setdefault(identity, split)
            if previous != split:
                raise ValueError("fictional identity leaks between splits")
        tokens = tokenize(record["raw"])
        if gold["expected_status"] == "mapped":
            mapping = gold["mapping"]
            if set(mapping) != {str(t.index) for t in tokens} or set(mapping.values()) - TOKEN_FIELDS:
                raise ValueError("incomplete or invalid gold mapping")
            fields = empty_fields(rid)
            covered = {}
            for span in gold["spans"]:
                start, end, field = span["start"], span["end"], span["field"]
                if not 0 <= start < end <= len(record["raw"]) or field not in TOKEN_FIELDS or fields[field] is not None:
                    raise ValueError("invalid gold span")
                fields[field] = record["raw"][start:end]
                for token in tokens:
                    if start <= token.start and token.end <= end:
                        if token.index in covered:
                            raise ValueError("overlapping gold spans")
                        covered[token.index] = field
                        if mapping[str(token.index)] != field:
                            raise ValueError("span/mapping disagreement")
            if fields != gold["fields"] or set(covered) != set(range(len(tokens))):
                raise ValueError("span/field or token coverage mismatch")
            # Group units at a shared base address; names and countries cannot
            # disguise repeated locations. This is component normalization,
            # not geocoding or a claim of complete fuzzy duplicate detection.
            address_key = tuple(input_fingerprint(str(fields.get(field) or "")) for field in (
                "street_number", "pre_directional", "street_name", "street_type",
                "post_directional", "city", "state", "postal_code"))
            previous = physical_splits.setdefault(address_key, split)
            if previous != split:
                raise ValueError("base address leaks between splits")
        elif gold["expected_status"] == "ambiguous":
            alternatives = gold.get("admissible_mappings", [])
            if len(alternatives) < 2 or len({json.dumps(a, sort_keys=True) for a in alternatives}) != len(alternatives):
                raise ValueError("ambiguous example needs distinct interpretations")
            if any(set(a) != {str(t.index) for t in tokens} or set(a.values()) - TOKEN_FIELDS for a in alternatives):
                raise ValueError("invalid alternative interpretation")
            if gold.get("mapping") or gold.get("fields") or gold.get("spans"):
                raise ValueError("ambiguous record must not expose arbitrary unique gold")
        elif gold["expected_status"] == "unsupported":
            if gold.get("mapping") or gold.get("fields") or gold.get("spans"):
                raise ValueError("unsupported input must not expose arbitrary extraction gold")
        else:
            raise ValueError("unknown gold status")
    return {"records": len(ids), "unique_fingerprints": len(fingerprints), "counts": counts,
            "D1_families": len(family_splits), "source_jurisdictions": len(address_splits),
            "D1_address_groups": len(grammar_splits), "base_address_split_overlaps": 0,
            "identity_split_overlaps": 0, "integrity_status": "passed",
            "independent_annotation_status": "pending", "protocol_frozen": False}
