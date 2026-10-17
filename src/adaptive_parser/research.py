"""Research scoring against explicitly named reference-label sources."""

from collections import Counter, defaultdict
from .contracts import InputRecord, empty_fields
from .materialize import materialize
from .tokenization import tokenize
from .validation import input_reasons, parse_proposal, validate_mapping


def validate_response(record, response):
    tokens = tokenize(record.raw)
    result = {"record_id": record.record_id, "status": "failed", "mapping": {},
              "fields": empty_fields(record.record_id), "reasons": [], "format_deviations": []}
    if response.get("error"):
        result["reasons"] = [response["error"]]
        return result
    try:
        proposal = parse_proposal(response["text"])
    except (ValueError, TypeError, KeyError):
        result["reasons"] = ["invalid_proposal"]
        return result
    result["proposal_status"] = proposal.status
    result["proposed_mapping"] = {str(i): f for i, f in proposal.mapping.items()}
    result["format_deviations"] = list(proposal.format_deviations)
    result["status"] = "abstained"
    if proposal.status != "mapped":
        result["reasons"] = ["model_" + proposal.status, proposal.reason]
        return result
    reasons = input_reasons(record, tokens) + list(validate_mapping(proposal.mapping, tokens, record.name_order).reasons)
    result["reasons"] = reasons
    if not reasons:
        result["status"] = "accepted"
        result["mapping"] = {str(i): f for i, f in proposal.mapping.items()}
        result["fields"], result["spans"] = materialize(record, tokens, proposal.mapping)
    return result


def score(predictions, references, *, label_basis="source/construction-derived"):
    refs = {g["record_id"]: g for g in references}
    if len(refs) != len(references):
        raise ValueError("duplicate research references")
    counts, groups, seen = Counter(), defaultdict(Counter), set()
    for pred in predictions:
        rid = pred["record_id"]
        if rid not in refs or rid in seen:
            raise ValueError("unknown/duplicate research prediction")
        seen.add(rid)
        gold = refs[rid]
        eligible = gold["expected_status"] == "mapped"
        accepted = pred["status"] == "accepted"
        exact = accepted and eligible and pred.get("mapping") == gold["mapping"]
        values = exact and pred.get("fields") == gold["fields"]
        for bucket in (counts, groups[gold["cohort"]]):
            bucket["records"] += 1
            bucket["mapped_reference_records"] += eligible
            bucket["accepted"] += accepted
            bucket["failed"] += pred["status"] == "failed"
            bucket["abstained"] += pred["status"] == "abstained"
            bucket["exact_mappings"] += exact
            bucket["exact_records"] += values
            bucket["accepted_errors"] += accepted and not values
            bucket["safe_abstentions_on_nonmapped_reference"] += not eligible and pred["status"] == "abstained"
            bucket["incorrect_acceptances_on_nonmapped_reference"] += accepted and not eligible
    if seen != set(refs):
        raise ValueError("missing research predictions")
    def metrics(bucket):
        result = dict(bucket)
        result["automatic_coverage"] = bucket["accepted"] / bucket["records"] if bucket["records"] else None
        result["exact_record_accuracy_on_mapped_reference"] = bucket["exact_records"] / bucket["mapped_reference_records"] if bucket["mapped_reference_records"] else None
        result["accepted_error_rate"] = bucket["accepted_errors"] / bucket["accepted"] if bucket["accepted"] else None
        return result
    return {**metrics(counts), "per_cohort": {k: metrics(v) for k, v in groups.items()},
            "label_basis": label_basis, "human_verified": False,
            "interpretation": "Reference agreement, not independently human-verified real-world accuracy"}
