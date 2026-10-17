"""Analysis of matched Sonnet inputs, repeated discovery and small live runs."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.research import score
from adaptive_parser.legacy import validate_v1, validate_v2
from adaptive_parser.tokenization import tokenize
from adaptive_parser.validation import validate_mapping

VERSION = "mapping-json-v4-typed-streets"


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    output = ROOT / "results/analysis"
    output.mkdir(exist_ok=True)
    corpus = ROOT / "data/corpus-draft-v1"
    gold = {r["record_id"]: r for r in load(corpus / "evaluator/final.labels.jsonl")}
    inputs = {r["record_id"]: r for r in load(corpus / "inputs/final.jsonl")}
    frozen = json.loads((ROOT / "configs/experiment_protocol.json").read_text(encoding="utf-8"))
    selected = frozen["final_model_record_ids"]["sonnet"]
    matched, variability, live = [], [], []
    for model in ("nova", "haiku45", "sonnet"):
        bank_dir = ROOT / f"results/study_banks/{VERSION}/final/{model}"
        predictions = {r["record_id"]: r for r in load(bank_dir / "predictions.jsonl")}
        responses = {r["record_id"]: r for r in load(bank_dir / "responses.jsonl")}
        row = score([predictions[rid] for rid in selected], [gold[rid] for rid in selected])
        row.update(model=model, scope="Same 250 preselected final inputs; per-record structural gate, no memory",
                   estimated_response_cost_usd=sum(float(responses[rid].get("usage", {}).get("estimated_usd", 0)) for rid in selected),
                   unknown_response_costs=sum("estimated_usd" not in responses[rid].get("usage", {}) for rid in selected),
                   median_bank_request_seconds=statistics.median(responses[rid]["elapsed_seconds"] for rid in selected),
                   latency_scope="Different dispatch concurrency and service conditions; not a controlled latency ranking")
        matched.append(row)
        if model == "sonnet":
            continue
        repeated = load(ROOT / f"results/followups/variability/{model}/generations.jsonl")
        groups = defaultdict(list)
        for sample in repeated:
            groups[sample["record_id"]].append(sample["prediction"])
        if len(groups) != 50 or any(len(samples) != 2 for samples in groups.values()):
            raise ValueError("expected fifty inputs with two extra generations each")
        counts = Counter()
        for rid, samples in groups.items():
            counts["inputs"] += 1
            samples = [predictions[rid], *samples]
            outcomes = []
            for prediction in samples:
                correct = (prediction["status"] == "accepted" and prediction.get("mapping") == gold[rid]["mapping"]
                           and prediction.get("fields") == gold[rid]["fields"])
                counts["generations"] += 1
                counts["accepted"] += prediction["status"] == "accepted"
                counts["exact_records"] += correct
                counts["failed"] += prediction["status"] == "failed"
                outcomes.append(json.dumps({"status": prediction["status"], "mapping": prediction.get("mapping", {})}, sort_keys=True))
            counts["all_three_status_mapping_agree"] += len(set(outcomes)) == 1
            counts["all_three_match_construction_reference"] += all(p["status"] == "accepted" and p.get("mapping") == gold[rid]["mapping"] and p.get("fields") == gold[rid]["fields"] for p in samples)
        variability.append({"model": model, **dict(counts), "additional_provider_generations": len(repeated),
                            "scope": "50 preselected D1 family representatives, three generations per input including original bank; repeated same-input sampling is not distinct-input admission evidence"})
        for policy in ("per_record_context_gate", "proposed"):
            directory = ROOT / f"results/followups/live/{model}"
            metrics = json.loads((directory / f"{policy}.metrics.json").read_text(encoding="utf-8"))
            events = load(directory / f"{policy}.requests.jsonl")
            # Request events contain the provider's settled cost, once per call.
            cost_values = [e["charged_estimate_usd_with_factor"] for e in events if "charged_estimate_usd_with_factor" in e]
            metrics.update(observed_settled_response_cost_usd=sum(float(value) for value in cost_values),
                           cost_bearing_event_count=len(cost_values), request_event_count=len(events))
            live.append(metrics)
    reviews = load(ROOT / "annotation/model-assisted-v2/final_audit/consensus.jsonl")
    review_counts, divergences = defaultdict(Counter), []
    for review in reviews:
        rid, status = review["record_id"], review["review_status"]
        cohort = gold[rid]["cohort"]
        review_counts[cohort][status] += 1
        reference = gold[rid]
        agrees = ((status == "mapped" and reference["expected_status"] == "mapped" and review["mapping"] == reference["mapping"])
                  or (status == "ambiguous" and reference["expected_status"] == "ambiguous")
                  or (status in ("unsupported", "insufficient") and reference["expected_status"] in ("unsupported", "insufficient")))
        review_counts[cohort]["agrees_with_construction_status_and_mapping"] += agrees
        if not agrees:
            divergences.append({"record_id": rid, "raw": inputs[rid]["raw"], "construction_status": reference["expected_status"],
                                "construction_mapping": reference["mapping"], "review_status": status,
                                "review_mapping": review.get("mapping", {}), "basis": "Two reference systems differ; not adjudicated as either system being correct"})
    failures = []
    for model, policy, path in [
        *( (m, p, ROOT / f"results/replay/{VERSION}/final/{m}.{p}.predictions.jsonl")
           for m in ("nova", "haiku45") for p in ("proposed", "legacy_v1", "per_record_context_gate") ),
        ("local", "crf", ROOT / "results/local_baselines/final/crf.predictions.jsonl"),
    ]:
        for prediction in load(path):
            rid = prediction["record_id"]
            if prediction["status"] != "accepted":
                continue
            reference = gold[rid]
            if reference["expected_status"] == "mapped" and prediction.get("mapping") == reference["mapping"] and prediction.get("fields") == reference["fields"]:
                continue
            failures.append({"model": model, "policy": policy, "record_id": rid, "cohort": reference["cohort"],
                             "route": prediction.get("route"), "raw": inputs[rid]["raw"],
                             "construction_status": reference["expected_status"], "reference_mapping": reference["mapping"],
                             "prediction_mapping": prediction.get("mapping", {}),
                             "differing_fields": [k for k in sorted(set(reference.get("fields", {})) | set(prediction.get("fields", {})))
                                                  if reference.get("fields", {}).get(k) != prediction.get("fields", {}).get(k)]})
    write(output / "matched_sonnet_subset.json", matched)
    write(output / "discovery_variability.json", variability)
    write(output / "paired_live_streams.json", live)
    write(output / "model_review_reference_comparison.json", {"by_cohort": {k: dict(v) for k, v in review_counts.items()},
                                                       "divergent_rows": len(divergences), "human_annotations": 0})
    candidate_counts = defaultdict(Counter)
    candidate_rows = load(corpus / "evaluator/final.validator_candidates.jsonl")
    for candidate in candidate_rows:
        record = inputs[candidate["record_id"]]
        tokens = tokenize(record["raw"])
        mapping = {int(i): field for i, field in candidate["mapping"].items()}
        decisions = {
            "legacy_v1": validate_v1(mapping, [t.text for t in tokens])[0],
            "legacy_v2": validate_v2(mapping, [t.text for t in tokens])[0],
            "structural_v05": validate_mapping(mapping, tokens, record.get("name_order")).approved,
        }
        for method, admitted in decisions.items():
            counts = candidate_counts[(method, candidate["candidate_id"])]
            counts["decisions"] += 1
            counts["admitted"] += admitted
            counts["expected_admission"] += candidate["expected_admission"]
    write(output / "final_candidate_admission.json", {"rows": [{"method": method, "candidate_type": kind, **dict(counts)} for (method, kind), counts in candidate_counts.items()],
                                                       "base_inputs": len({r["record_id"] for r in candidate_rows}), "candidate_decisions": len(candidate_rows),
                                                       "scope": "Generator-authored, correlated candidate perturbations of final D3 mapped inputs; no LLM calls; not a universal semantic-safety guarantee"})
    (output / "model_review_reference_divergences.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in divergences), encoding="utf-8")
    (output / "accepted_error_catalog.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in failures), encoding="utf-8")
    write(output / "followup_analysis_manifest.json", {"analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                                        "main_protocol_sha256": hashlib.sha256((ROOT / "configs/experiment_protocol.json").read_bytes()).hexdigest(),
                                                        "human_annotations": 0, "error_catalog_rows": len(failures), "model_review_divergent_rows": len(divergences)})
    print(json.dumps({"matched_models": len(matched), "variability_models": len(variability), "live_policies": len(live), "error_catalog_rows": len(failures)}))


if __name__ == "__main__":
    main()
