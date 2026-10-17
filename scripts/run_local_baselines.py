"""Train on development, select CRF confidence on validation, then evaluate."""

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import pickle
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".research-deps"))
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.baselines import CRFProposer, GrammarProposer, USAddressProposer, features
from adaptive_parser.contracts import InputRecord
from adaptive_parser.research import score, validate_response
from adaptive_parser.tokenization import tokenize


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run(split):
    import sklearn_crfsuite
    if split == "final":
        protocol = json.loads((ROOT / "configs/experiment_protocol.json").read_text(encoding="utf-8"))
        if not protocol.get("frozen"):
            raise ValueError("final baseline evaluation requires protocol freeze")
        for path, digest in protocol["predictive_source_sha256"].items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise ValueError("predictive source changed after protocol freeze")
    folder = ROOT / "results/local_baselines"
    folder.mkdir(parents=True, exist_ok=True)
    corpus = ROOT / "data/corpus-draft-v1"
    model_path = folder / "crf.pkl"
    if not model_path.exists():
        training = {r["record_id"]: InputRecord(**r) for r in load(corpus / "inputs/development.jsonl")}
        gold = [g for g in load(corpus / "evaluator/development.labels.jsonl") if g["expected_status"] == "mapped"]
        x = [features(training[g["record_id"]]) for g in gold]
        y = [[g["mapping"][str(i)] for i in range(len(tokenize(training[g["record_id"]].raw)))] for g in gold]
        model = sklearn_crfsuite.CRF(algorithm="lbfgs", c1=0.1, c2=0.1, max_iterations=60, all_possible_transitions=True)
        start = time.monotonic()
        model.fit(x, y)
        model_path.write_bytes(pickle.dumps(model))
        manifest = {"training_split": "development", "mapped_training_records": len(gold),
                    "fit_seconds": time.monotonic() - start, "c1": 0.1, "c2": 0.1, "max_iterations": 60,
                    "training_input_sha256": hashlib.sha256((corpus / "inputs/development.jsonl").read_bytes()).hexdigest(),
                    "training_label_sha256": hashlib.sha256((corpus / "evaluator/development.labels.jsonl").read_bytes()).hexdigest(),
                    "features_source_sha256": hashlib.sha256((ROOT / "src/adaptive_parser/baselines.py").read_bytes()).hexdigest(),
                    "packages": {p: importlib.metadata.version(p) for p in ("usaddress", "sklearn-crfsuite", "python-crfsuite", "scikit-learn", "numpy")}}
        (folder / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"trained_crf_records": len(gold), "fit_seconds": round(manifest["fit_seconds"], 1)}), flush=True)
    model = pickle.loads(model_path.read_bytes())  # Local artifact generated above, never untrusted download.
    manifest = json.loads((folder / "training_manifest.json").read_text(encoding="utf-8"))
    if manifest["features_source_sha256"] != hashlib.sha256((ROOT / "src/adaptive_parser/baselines.py").read_bytes()).hexdigest():
        raise ValueError("baseline features changed; use a versioned training artifact")
    threshold_path = folder / "threshold.json"
    if split == "final" and not threshold_path.exists():
        raise ValueError("fit confidence threshold on validation before final evaluation")
    inputs = [InputRecord(**r) for r in load(corpus / f"inputs/{split}.jsonl")]
    gold = load(corpus / f"evaluator/{split}.labels.jsonl")
    methods = {"grammar": GrammarProposer(), "usaddress_composite": USAddressProposer(), "crf": CRFProposer(model)}
    crf_predictions = []
    if split == "validation":
        provider = methods["crf"]
        for record in inputs:
            prediction = validate_response(record, provider.propose(record, tokenize(record.raw)))
            prediction["confidence"] = provider.last_confidence
            crf_predictions.append(prediction)
        candidates = []
        for threshold in (0.0, 0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999):
            predictions = [dict(p, status="abstained", mapping={}) if p["status"] == "accepted" and p["confidence"] < threshold else p for p in crf_predictions]
            metrics = score(predictions, gold)
            candidates.append({"threshold": threshold, "coverage": metrics["automatic_coverage"],
                               "accepted": metrics["accepted"], "accepted_error_rate": metrics["accepted_error_rate"]})
        feasible = [c for c in candidates if c["accepted"] >= 50 and c["accepted_error_rate"] <= 0.01]
        chosen = max(feasible, key=lambda c: (c["coverage"], -c["threshold"])) if feasible else {"threshold": 1.0, "target_unattainable": True}
        threshold_path.write_text(json.dumps({"chosen": chosen, "candidates": candidates, "selection_split": "validation"}, indent=2) + "\n", encoding="utf-8")
    threshold = json.loads(threshold_path.read_text(encoding="utf-8"))["chosen"]["threshold"]
    methods["crf"].threshold = threshold
    for name, provider in methods.items():
        predictions = []
        for record in inputs:
            prediction = validate_response(record, provider.propose(record, tokenize(record.raw)))
            if name == "crf":
                prediction["confidence"] = provider.last_confidence
            predictions.append(prediction)
        metrics = score(predictions, gold)
        metrics.update(method=name, split=split, live_calls=0, crf_threshold=threshold if name == "crf" else None)
        path = folder / split
        path.mkdir(exist_ok=True)
        (path / f"{name}.predictions.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions), encoding="utf-8")
        (path / f"{name}.metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: metrics[k] for k in ("method", "split", "records", "accepted", "exact_records", "accepted_errors")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("validation", "final"), required=True)
    run(parser.parse_args().split)
