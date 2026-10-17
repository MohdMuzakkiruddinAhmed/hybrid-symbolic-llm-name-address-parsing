"""Offline scoring. This module alone consumes expected outputs."""

from collections import Counter

from .contracts import empty_fields


def evaluate(predictions, fixtures):
    references = {f["record_id"]: f for f in fixtures}
    if len(references) != len(fixtures):
        raise ValueError("duplicate fixture IDs")
    counts = Counter()
    details = []
    seen = set()
    for prediction in predictions:
        if prediction.record_id in seen or prediction.record_id not in references:
            raise ValueError("duplicate or unknown prediction")
        seen.add(prediction.record_id)
        gold = references[prediction.record_id]
        counts["records"] += 1
        counts[prediction.status] += 1
        mapping = {int(k): v for k, v in gold.get("expected_mapping", {}).items()}
        eligible = gold["expected_status"] == "accepted"
        exact = eligible and prediction.status == "accepted" and prediction.mapping == mapping
        expected_fields = empty_fields(prediction.record_id)
        expected_fields.update(gold.get("expected_fields", {}))
        value_exact = exact and prediction.fields == expected_fields
        counts["eligible_extraction_records"] += int(eligible)
        counts["exact_mappings"] += int(exact)
        counts["checked_field_values_exact"] += int(value_exact)
        counts["status_matches"] += int(prediction.status == gold["expected_status"])
        counts["memory_hits"] += int(prediction.route == "memory")
        counts["normalized_format_records"] += int(bool(prediction.format_deviations))
        details.append({"record_id": prediction.record_id, "status_matches": prediction.status == gold["expected_status"],
                        "exact_mapping": bool(exact), "checked_field_values_exact": bool(value_exact)})
    if seen != references.keys():
        raise ValueError("missing predictions")
    result = dict(counts)
    eligible = counts["eligible_extraction_records"]
    result["exact_mapping_accuracy"] = counts["exact_mappings"] / eligible if eligible else None
    result["exact_record_accuracy"] = counts["checked_field_values_exact"] / eligible if eligible else None
    result["automatic_coverage"] = counts["accepted"] / counts["records"] if counts["records"] else None
    result["scope"] = "Engineering fixtures only; not independent research accuracy evidence."
    result["records_detail"] = details
    return result
