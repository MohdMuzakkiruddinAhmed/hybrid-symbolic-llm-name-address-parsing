"""Evaluate frozen response-bank policies; no provider calls or live timing claims."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.discovery import PROMPT_VERSION
from adaptive_parser.replay import run_policy
from adaptive_parser.research import score
from adaptive_parser.tokenization import signature, tokenize

POLICIES = ("per_record_structural", "per_record_context_gate", "legacy_v1", "legacy_v2", "context_support1", "context_support3", "proposed")
REGIMES = ("high_recurrence", "long_tail", "cohort_shift", "conflict_late")


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def stream_selection(inputs, gold, regime, seed):
    randomizer = random.Random(f"streams-v1|{regime}|{seed}")
    refs = {g["record_id"]: g for g in gold}
    grouped = defaultdict(list)
    for row in inputs:
        grouped[signature(tokenize(row["raw"]), row["locale"], row.get("name_order"))].append(row)
    if regime == "high_recurrence":
        selected = [row for key, values in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])) for row in values][:2000]
        randomizer.shuffle(selected)
    elif regime == "long_tail":
        keys = list(grouped)
        randomizer.shuffle(keys)
        selected = [values[0] for key in keys if (values := grouped[key])]
        selected_ids = {r["record_id"] for r in selected}
        tail = [r for r in inputs if r["record_id"] not in selected_ids]
        randomizer.shuffle(tail)
        selected = (selected + tail)[:2000]
    elif regime == "cohort_shift":
        selected = []
        for cohort in ("D4", "D1", "D2", "D3"):
            candidates = [r for r in inputs if refs[r["record_id"]]["cohort"] == cohort]
            randomizer.shuffle(candidates)
            selected.extend(candidates[:500])
    else:
        ordered = list(inputs)
        randomizer.shuffle(ordered)
        # Late address-transfer records stress conflicting signature semantics;
        # selecting cohorts uses no model outcomes or final correctness labels.
        early = [r for r in ordered if refs[r["record_id"]]["cohort"] in ("D1", "D4")][:1500]
        late = [r for r in ordered if refs[r["record_id"]]["cohort"] == "D2"][:500]
        selected = early + late
    if len(selected) != 2000 or len({r["record_id"] for r in selected}) != 2000:
        raise ValueError("stream selection must have 2000 distinct records")
    return selected


def run(split, streams):
    corpus = ROOT / "data/corpus-draft-v1"
    if split == "final":
        protocol = json.loads((ROOT / "configs/experiment_protocol.json").read_text(encoding="utf-8"))
        if not protocol.get("frozen"):
            raise ValueError("final policy evaluation requires a frozen protocol")
        for path, digest in protocol["predictive_source_sha256"].items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise ValueError("predictive code changed after protocol freeze")
    inputs = load(corpus / f"inputs/{split}.jsonl")
    gold = load(corpus / f"evaluator/{split}.labels.jsonl")
    collisions = [r["signature"] for r in load(ROOT / "results/development_collision_catalog.jsonl")]
    output = ROOT / f"results/replay/{PROMPT_VERSION}/{split}"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for model in ("nova", "haiku45"):
        folder = ROOT / f"results/study_banks/{PROMPT_VERSION}/{split}/{model}"
        metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
        if not metrics["complete"]:
            raise ValueError("response bank is incomplete")
        bank = {r["record_id"]: r for r in load(folder / "responses.jsonl")}
        selected = [r for r in inputs if r["record_id"] in bank]
        references = [g for g in gold if g["record_id"] in bank]
        order = sorted(selected, key=lambda r: hashlib.sha256(("main-order-v1|" + r["record_id"]).encode()).digest())
        for policy in POLICIES:
            predictions, routing = run_policy(order, bank, policy, collisions)
            result = {"model": model, "policy": policy, "split": split, "regime": "static_main", "seed": 0,
                      **score(predictions, references), **routing}
            results.append(result)
            (output / f"{model}.{policy}.predictions.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions), encoding="utf-8")
        if streams:
            if split != "final":
                raise ValueError("registered streams use the fixed final corpus")
            manifest_rows = []
            for regime in REGIMES:
                for seed in range(5):
                    records = stream_selection(selected, references, regime, seed)
                    ids = {r["record_id"] for r in records}
                    subset = [g for g in references if g["record_id"] in ids]
                    for position, record in enumerate(records):
                        manifest_rows.append({"regime": regime, "seed": seed, "position": position, "record_id": record["record_id"]})
                    for policy in POLICIES:
                        predictions, routing = run_policy(records, bank, policy, collisions)
                        results.append({"model": model, "policy": policy, "split": split, "regime": regime, "seed": seed,
                                        **score(predictions, subset), **routing})
            (output / f"{model}.stream_orders.jsonl").write_text("".join(json.dumps(r) + "\n" for r in manifest_rows), encoding="utf-8")
        print(json.dumps({"model": model, "split": split, "static_policies": 7, "streams": streams}), flush=True)
    (output / "metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    print(json.dumps({"policy_evaluations": len(results), "live_inference_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("validation", "final"), required=True)
    parser.add_argument("--streams", action="store_true")
    args = parser.parse_args()
    run(args.split, args.streams)
