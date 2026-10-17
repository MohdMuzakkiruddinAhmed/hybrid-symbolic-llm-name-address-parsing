"""Preselected repeated discovery and paired live streams under existing stage caps."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.budget import SpendingLedger
from adaptive_parser.contracts import InputRecord
from adaptive_parser.discovery import BedrockProposer
from adaptive_parser.memory import RuleMemory
from adaptive_parser.pipeline import Parser
from adaptive_parser.research import score, validate_response
from adaptive_parser.tokenization import signature, tokenize


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def prepare():
    path = ROOT / "results/followup_protocol.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    corpus = ROOT / "data/corpus-draft-v1"
    metadata = load(corpus / "evaluator/final.labels.jsonl")
    inputs = {r["record_id"]: r for r in load(corpus / "inputs/final.jsonl")}
    grouped = {}
    for row in metadata:
        if row["cohort"] == "D1":
            grouped.setdefault(row["family_id"], []).append(row["record_id"])
    families = sorted(grouped, key=lambda value: hashlib.sha256(("variability-v1|" + value).encode()).digest())[:50]
    representatives = [min(grouped[family], key=lambda rid: hashlib.sha256(rid.encode()).digest()) for family in families]
    recurring = {}
    for row in metadata:
        if row["cohort"] == "D4":
            record = inputs[row["record_id"]]
            key = signature(tokenize(record["raw"]), record["locale"], record.get("name_order"))
            recurring.setdefault(key, []).append(record["record_id"])
    candidates = sorted([(key, ids) for key, ids in recurring.items() if len(ids) >= 10],
                        key=lambda item: hashlib.sha256(("live-stream-v1|" + item[0]).encode()).digest())[:5]
    live_ids = [rid for _, ids in candidates for rid in sorted(ids)[:10]]
    if len(live_ids) != 50:
        raise ValueError("cannot form five observable recurrence groups of ten fresh inputs")
    random.Random(20261016).shuffle(live_ids)
    protocol = {"created_utc": datetime.now(timezone.utc).isoformat(), "frozen_before_followup_calls": True,
                "selection_uses": "cohort/family metadata and observable signatures; no predictions or correctness outcomes",
                "variability_record_ids": representatives, "additional_generations_per_record": 2,
                "live_record_ids": live_ids, "live_scope": "Engineered high recurrence in D4; not an observed production workload",
                "models": ["nova", "haiku45"], "policy_order": {"nova": ["per_record_context_gate", "proposed"],
                                                                               "haiku45": ["proposed", "per_record_context_gate"]},
                "main_protocol_sha256": hashlib.sha256((ROOT / "configs/experiment_protocol.json").read_bytes()).hexdigest(),
                "followup_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "latency_condition": "Run paired live streams after bulk banks; record actual request and parse times; no replay timing claims"}
    path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    return protocol


def run(mode, model_key):
    import boto3
    from botocore.config import Config
    protocol = prepare()
    frozen = json.loads((ROOT / "configs/experiment_protocol.json").read_text(encoding="utf-8"))
    if not frozen["frozen"]:
        raise ValueError("freeze main protocol first")
    for path, digest in frozen["predictive_source_sha256"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("predictive source changed after freeze")
    if protocol["followup_source_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("follow-up method changed after selection freeze")
    runtime = json.loads((ROOT / "configs/bedrock_runtime.json").read_text(encoding="utf-8"))
    plan = json.loads((ROOT / "configs/research_plan.json").read_text(encoding="utf-8"))
    limits = {s["id"]: s["allocation_usd"] for s in plan["stages"]}
    client = boto3.client("bedrock-runtime", region_name=runtime["region"],
                          config=Config(retries={"total_max_attempts": 1}, connect_timeout=10, read_timeout=60))
    corpus = ROOT / "data/corpus-draft-v1"
    records = {r["record_id"]: r for r in load(corpus / "inputs/final.jsonl")}
    references = {g["record_id"]: g for g in load(corpus / "evaluator/final.labels.jsonl")}
    folder = ROOT / f"results/followups/{mode}/{model_key}"
    folder.mkdir(parents=True, exist_ok=True)
    ledger = SpendingLedger(ROOT / "results/spending.sqlite3", 40, limits)
    stage = "discovery_variability" if mode == "variability" else "paired_live_streams"
    try:
        if mode == "variability":
            output = []
            for rid in protocol["variability_record_ids"]:
                for generation in (1, 2):
                    path = folder / f"{rid}.{generation}.json"
                    if path.exists():
                        output.append(json.loads(path.read_text(encoding="utf-8")))
                        continue
                    provider = BedrockProposer(client, ledger, runtime["models"][model_key], stage,
                                               folder / f"{rid}.{generation}.events.jsonl")
                    record = InputRecord(**records[rid])
                    try:
                        response = provider.propose(record, tokenize(record.raw))
                    except Exception as exc:
                        response = {"error": type(exc).__name__}
                    result = {"record_id": rid, "additional_generation": generation, "response": response,
                              "prediction": validate_response(record, response)}
                    path.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
                    output.append(result)
                if len(output) % 20 == 0:
                    print(json.dumps({"mode": mode, "model": model_key, "new_generation_records": len(output)}), flush=True)
            (folder / "generations.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in output), encoding="utf-8")
            print(json.dumps({"mode": mode, "model": model_key, "additional_generations": len(output), "ledger": ledger.summary()}))
        else:
            for policy in protocol["policy_order"][model_key]:
                target = folder / f"{policy}.predictions.jsonl"
                if target.exists():
                    if len(load(target)) != 50:
                        raise ValueError("partial paired live stream retained; do not silently start another run")
                    continue
                provider = BedrockProposer(client, ledger, runtime["models"][model_key], stage, folder / f"{policy}.requests.jsonl")
                memory = RuleMemory(folder / f"{policy}.memory.sqlite3", support=3)
                parser = Parser(memory, provider, unsafe_signatures=frozen["known_collision_signatures"], require_name_convention=True)
                predictions = []
                try:
                    for rid in protocol["live_record_ids"]:
                        record = InputRecord(**records[rid])
                        start = time.monotonic()
                        if policy == "proposed":
                            prediction = parser.parse(record).to_dict()
                            prediction["mapping"] = {str(i): field for i, field in prediction["mapping"].items()}
                        else:
                            try:
                                response = provider.propose(record, tokenize(record.raw))
                            except Exception as exc:
                                response = {"error": type(exc).__name__}
                            prediction = validate_response(record, response)
                            prediction["route"] = "bedrock"
                        prediction["parse_elapsed_seconds"] = time.monotonic() - start
                        predictions.append(prediction)
                    target.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions), encoding="utf-8")
                    metrics = score(predictions, [references[rid] for rid in protocol["live_record_ids"]])
                    elapsed = sorted(p["parse_elapsed_seconds"] for p in predictions)
                    metrics.update(model=model_key, policy=policy, live_inference_calls=provider.calls,
                                   parse_p50_seconds=elapsed[24], parse_p95_seconds=elapsed[47],
                                   scope=protocol["live_scope"], policy_order=protocol["policy_order"][model_key])
                    (folder / f"{policy}.metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
                    print(json.dumps({k: metrics[k] for k in ("model", "policy", "records", "exact_records", "live_inference_calls")}), flush=True)
                finally:
                    memory.close()
    finally:
        ledger.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "variability", "live"), required=True)
    parser.add_argument("--model", choices=("nova", "haiku45"))
    args = parser.parse_args()
    if args.mode == "prepare":
        protocol = prepare()
        print(json.dumps({"variability_representatives": len(protocol["variability_record_ids"]), "live_records": len(protocol["live_record_ids"])}))
    else:
        if not args.model:
            parser.error("--model is required")
        run(args.mode, args.model)
