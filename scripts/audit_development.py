"""Local validator diagnostics on development labels; never runs final inference."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.contracts import InputRecord
from adaptive_parser.tokenization import signature, tokenize
from adaptive_parser.validation import VALIDATOR_VERSION, input_reasons, validate_mapping


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def audit(output_name="development_gate_v01.json"):
    corpus = ROOT / "data/corpus-draft-v1"
    records = {row["record_id"]: InputRecord(**row) for row in load(corpus / "inputs/development.jsonl")}
    labels = load(corpus / "evaluator/development.labels.jsonl")
    counts, reasons, collisions = defaultdict(Counter), Counter(), defaultdict(set)
    for gold in labels:
        record = records[gold["record_id"]]
        tokens = tokenize(record.raw)
        if gold["expected_status"] == "mapped":
            mapping = {int(i): f for i, f in gold["mapping"].items()}
            decision = validate_mapping(mapping, tokens, record.name_order)
            counts[gold["cohort"]]["construction_labels_checked"] += 1
            counts[gold["cohort"]]["admitted_correct_construction_label"] += int(decision.approved)
            reasons.update(decision.reasons)
            key = signature(tokens, record.locale, record.name_order)
            collisions[key].add(json.dumps(mapping, sort_keys=True))
        else:
            counts[gold["cohort"]][f"draft_status_{gold['expected_status']}"] += 1
            counts[gold["cohort"]]["caught_by_input_gate"] += bool(input_reasons(record, tokens))
    candidate_counts = defaultdict(Counter)
    for candidate in load(corpus / "evaluator/development.validator_candidates.jsonl"):
        record = records[candidate["record_id"]]
        result = validate_mapping({int(i): f for i, f in candidate["mapping"].items()}, tokenize(record.raw), record.name_order)
        bucket = candidate_counts[candidate["candidate_id"]]
        bucket["decisions"] += 1
        bucket["admitted"] += int(result.approved)
    result = {"scope": "Local development diagnostics against draft source/construction labels; no model inference or independent human annotation",
              "validator_version": VALIDATOR_VERSION,
              "development_records": len(records), "per_cohort": {k: dict(v) for k, v in counts.items()},
              "rejection_reason_counts": dict(reasons),
              "D3_candidate_admission": {k: dict(v) for k, v in candidate_counts.items()},
              "distinct_signatures_with_mapped_labels": len(collisions),
              "signatures_with_multiple_construction_mappings": sum(len(v) > 1 for v in collisions.values()),
              "final_behavior_evaluated": False, "live_calls": 0,
              "source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in sorted((ROOT / "src/adaptive_parser").glob("*.py"))}}
    output = ROOT / "results" / output_name
    if output.exists():
        raise ValueError("use a new versioned diagnostic filename")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    audit(sys.argv[1] if len(sys.argv) > 1 else "development_gate_v01.json")
