"""Verify released source/data hashes, reference provenance and numerical results."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-only", action="store_true")
    args = parser.parse_args()
    protocol = json.loads((ROOT / "configs/experiment_protocol.json").read_text(encoding="utf-8"))
    checks = 0
    for relative, expected in protocol["predictive_source_sha256"].items():
        assert digest(ROOT / relative) == expected, relative
        checks += 1
    manifest_path = ROOT / "data/corpus-draft-v1/manifest.json"
    assert digest(manifest_path) == protocol["data_manifest_sha256"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        assert digest(ROOT / entry["path"]) == entry["sha256"], entry["path"]
        checks += 1
    assert sum(manifest["counts"].values()) == 20000
    assert protocol["annotation"]["human_annotations"] == 0
    if not args.dataset_only:
        version = protocol["prompt_version"]
        for model, ids in protocol["final_model_record_ids"].items():
            folder = ROOT / f"results/study_banks/{version}/final/{model}"
            rows = load(folder / "responses.jsonl")
            assert len(rows) == len(ids) and {r["record_id"] for r in rows} == set(ids)
            checks += 1
        evaluations = load(ROOT / f"results/replay/{version}/final/metrics.jsonl")
        assert len(evaluations) == 294
        assert all(r["live_inference_calls"] == 0 for r in evaluations)
        expected = json.loads((ROOT / "results/expected_main_results.json").read_text(encoding="utf-8"))
        actual = json.loads((ROOT / "results/analysis/main_results.json").read_text(encoding="utf-8"))
        keys = ("records", "accepted", "exact_records", "accepted_errors", "logical_generations", "automatic_coverage", "accepted_error_rate")
        keyed = {(r["model"], r["policy"]): r for r in actual}
        for row in expected:
            comparison = keyed[row["model"], row["policy"]]
            assert all(comparison[key] == row[key] for key in keys), (row["model"], row["policy"])
            checks += 1
        reviews = load(ROOT / "annotation/model-assisted-v2/final_audit/consensus.jsonl")
        assert len(reviews) == 2000
        assert all(r["human_annotation"] is False and r["independent_human_verified"] is False for r in reviews)
        counts = {s: sum(r["review_status"] == s for r in reviews) for s in ("mapped", "ambiguous", "disputed", "unsupported", "insufficient")}
        assert counts == {"mapped": 1442, "ambiguous": 324, "disputed": 34, "unsupported": 100, "insufficient": 100}
        summary = json.loads((ROOT / "annotation/model-assisted-v2/final_audit/summary.json").read_text(encoding="utf-8"))
        assert "gpt-6.1-sol" in summary["review_engine"]
        costs = json.loads((ROOT / "results/analysis/costs.json").read_text(encoding="utf-8"))
        assert abs(costs["committed_estimate_usd"] - 30.521921) < 0.000001
        assert all(r["state"] != "reserved" for r in costs["stages"])
        assert sum(r["attempts"] for r in costs["stages"]) == 23358
        requests = load(ROOT / "results/accounting/request_estimates.jsonl")
        assert len(requests) == 23358
        assert sum(r["charged_microusd"] if r["charged_microusd"] is not None else r["reserved_microusd"] for r in requests) == 30521921
        runtime = json.loads((ROOT / "configs/bedrock_runtime.json").read_text(encoding="utf-8"))
        for model in runtime["models"].values():
            assert model["enabled"] is False
            for snapshot in model.get("price_snapshots", {}).values():
                assert digest(ROOT / snapshot["path"]) == snapshot["sha256"]
    print(json.dumps({"verified": True, "checks": checks, "corpus_inputs": 20000, "human_annotations": 0, "provider_calls": 0, "scope": "Dataset/source only" if args.dataset_only else "Released study and numerical results"}))


if __name__ == "__main__":
    main()
