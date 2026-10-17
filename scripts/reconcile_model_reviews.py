"""Conservative agreement summaries; preserve model disagreements and original labels."""

from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def reconcile(cohort):
    folder = ROOT / f"annotation/model-assisted-v2/{cohort}"
    a, b = ({r["record_id"]: r for r in load(folder / p / "annotations.jsonl")} for p in ("a", "b"))
    if set(a) != set(b):
        raise ValueError("model-assisted review passes do not cover the same record IDs")
    counts, output = Counter(), []
    for rid in sorted(a):
        first, second = a[rid], b[rid]
        valid_pair = "review_failed" not in (first["status"], second["status"])
        status_equal = valid_pair and first["status"] == second["status"]
        mapping_equal = first["mapping"] == second["mapping"]
        counts["records"] += 1
        counts["valid_paired_reviews"] += valid_pair
        counts["incomplete_paired_reviews"] += not valid_pair
        counts["status_agreement"] += status_equal
        counts["mapped_agreement"] += status_equal and first["status"] == "mapped" and mapping_equal
        counts["either_pass_ambiguous"] += "ambiguous" in (first["status"], second["status"])
        consensus = (first["status"] if status_equal and (first["status"] != "mapped" or mapping_equal) else "disputed") if valid_pair else "review_incomplete"
        row = {"record_id": rid, "review_status": consensus,
               "mapping": first["mapping"] if consensus == "mapped" else {},
               "reviewer_a": first, "reviewer_b": second,
               "human_annotation": False, "label_basis": "model_assisted_two_pass_review",
               "independent_human_verified": False}
        output.append(row)
        counts["consensus_" + consensus] += 1
    (folder / "consensus.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in output), encoding="utf-8")
    report = {**dict(counts), "status_agreement_fraction": counts["status_agreement"] / counts["valid_paired_reviews"] if counts["valid_paired_reviews"] else None,
              "cohort": cohort, "human_annotations": 0, "review_engine": "Configured gpt-6.1-sol, two input-only passes",
              "independence_limit": "Fresh input-only sessions of the same model; correlated errors and prompt/order sensitivity remain",
              "original_construction_labels_overwritten": False,
              "disagreement_policy": "Retain both outputs; disputed/ambiguous rows have no invented unique consensus mapping"}
    (folder / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    reconcile(sys.argv[1] if len(sys.argv) > 1 else "pilot")
