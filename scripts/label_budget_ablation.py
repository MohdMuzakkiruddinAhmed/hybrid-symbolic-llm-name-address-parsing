"""Exploratory development-label curve evaluated on validation only.

Does not change the frozen primary CRF or evaluate extra models on final data.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".research-deps"))
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.baselines import CRFProposer, features
from adaptive_parser.contracts import InputRecord
from adaptive_parser.research import score, validate_response
from adaptive_parser.tokenization import tokenize


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main():
    import sklearn_crfsuite
    folder = ROOT / "results/label_budget_ablation"
    folder.mkdir(exist_ok=True)
    protocol = {"status": "exploratory validation-only supplement", "training_sizes": [30, 100, 300, 1000],
                "selection": "nested SHA256 ordering of mapped development IDs using label-budget-v1 prefix",
                "features": "same frozen CRF features", "c1": 0.1, "c2": 0.1, "max_iterations": 60,
                "confidence_threshold": 0, "evaluation_split": "validation", "final_evaluated": False,
                "changes_frozen_primary_baseline": False, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (folder / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    corpus = ROOT / "data/corpus-draft-v1"
    train = {r["record_id"]: InputRecord(**r) for r in load(corpus / "inputs/development.jsonl")}
    labels = sorted([g for g in load(corpus / "evaluator/development.labels.jsonl") if g["expected_status"] == "mapped"],
                    key=lambda g: hashlib.sha256(("label-budget-v1|" + g["record_id"]).encode()).digest())
    validation = [InputRecord(**r) for r in load(corpus / "inputs/validation.jsonl")]
    refs = load(corpus / "evaluator/validation.labels.jsonl")
    results = []
    for count in protocol["training_sizes"]:
        target = folder / f"n{count}.metrics.json"
        if target.exists():
            results.append(json.loads(target.read_text(encoding="utf-8")))
            continue
        subset = labels[:count]
        x = [features(train[g["record_id"]]) for g in subset]
        y = [[g["mapping"][str(i)] for i in range(len(tokenize(train[g["record_id"]].raw)))] for g in subset]
        model = sklearn_crfsuite.CRF(algorithm="lbfgs", c1=0.1, c2=0.1, max_iterations=60, all_possible_transitions=True)
        model.fit(x, y)
        provider = CRFProposer(model, threshold=0)
        predictions = [validate_response(record, provider.propose(record, tokenize(record.raw))) for record in validation]
        metrics = score(predictions, refs)
        metrics.update(training_records=count, split="validation", live_calls=0,
                       training_ids=[g["record_id"] for g in subset], exploratory=True, final_evaluated=False)
        target.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        results.append(metrics)
        print(json.dumps({key: metrics[key] for key in ("training_records", "records", "accepted", "exact_records", "accepted_errors")}), flush=True)
    (folder / "metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
