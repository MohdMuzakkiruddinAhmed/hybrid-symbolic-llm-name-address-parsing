"""Resumable, guarded response banks on preselected research inputs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.budget import BudgetExceeded, SpendingLedger
from adaptive_parser.contracts import InputRecord
from adaptive_parser.discovery import BedrockProposer, PROMPT_VERSION
from adaptive_parser.research import score, validate_response
from adaptive_parser.tokenization import tokenize


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def selected(split, model):
    corpus = ROOT / "data/corpus-draft-v1"
    if split == "screening":
        inputs, gold = load(corpus / "screening/inputs.jsonl"), load(corpus / "screening/labels.jsonl")
        if model == "sonnet":
            ids = {g["record_id"] for cohort, quota in (("D1", 100), ("D2", 38), ("D3", 12))
                   for g in sorted([g for g in gold if g["cohort"] == cohort],
                                   key=lambda g: hashlib.sha256(("sonnet-screen-v1|" + g["record_id"]).encode()).digest())[:quota]}
            inputs, gold = [r for r in inputs if r["record_id"] in ids], [g for g in gold if g["record_id"] in ids]
        return inputs, gold, "screening"
    if split == "validation":
        quotas = {"D1": 500, "D2": 375, "D3": 125}
        gold = load(corpus / "evaluator/validation.labels.jsonl")
        ids = {g["record_id"] for cohort, quota in quotas.items() for g in sorted(
            [g for g in gold if g["cohort"] == cohort],
            key=lambda g: hashlib.sha256(("calibration-v1|" + g["record_id"]).encode()).digest())[:quota]}
        return [r for r in load(corpus / "inputs/validation.jsonl") if r["record_id"] in ids], [g for g in gold if g["record_id"] in ids], "calibration"
    protocol = json.loads((ROOT / "configs/experiment_protocol.json").read_text(encoding="utf-8"))
    if not protocol.get("frozen"):
        raise ValueError("final inference requires a frozen protocol")
    for path, digest in protocol["predictive_source_sha256"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("predictive code changed after protocol freeze: " + path)
    ids = protocol["final_model_record_ids"][model]
    inputs = [r for r in load(corpus / "inputs/final.jsonl") if r["record_id"] in set(ids)]
    gold = [g for g in load(corpus / "evaluator/final.labels.jsonl") if g["record_id"] in set(ids)]
    return inputs, gold, "sonnet_final_reference" if model == "sonnet" else "main_final_response_bank"


def run(args):
    import boto3
    from botocore.config import Config
    inputs, references, stage = selected(args.split, args.model)
    runtime = json.loads((ROOT / "configs/bedrock_runtime.json").read_text(encoding="utf-8"))
    model = runtime["models"][args.model]
    if not model.get("enabled") or not model.get("rates_verified"):
        raise ValueError("model unavailable or rates unverified; no paid dispatch")
    folder = ROOT / f"results/study_banks/{PROMPT_VERSION}/{args.split}/{args.model}"
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw"
    raw.mkdir(exist_ok=True)
    settings = {k: model.get(k) for k in ("model_id", "max_output_tokens", "additional_fields", "input_usd_per_million", "output_usd_per_million", "max_request_utf8_bytes", "reservation_input_tokens")}
    manifest = {"model": args.model, "settings": settings, "prompt_version": PROMPT_VERSION,
                "stage": stage, "record_ids": [r["record_id"] for r in inputs],
                "input_sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                "memory_enabled": False, "attempt_policy": "one generation per input; no SDK retries; failures retained",
                "sdk_versions": {p: importlib.metadata.version(p) for p in ("boto3", "botocore")}}
    manifest_path = folder / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("response-bank configuration changed; use a versioned bank")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with (folder / "executions.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"started_utc": datetime.now(timezone.utc).isoformat(),
                                 "workers": args.workers, "requests_per_second_limit": args.rps,
                                 "limit_new_records": args.limit}) + "\n")
    plan = json.loads((ROOT / "configs/research_plan.json").read_text(encoding="utf-8"))
    limits = {s["id"]: s["allocation_usd"] for s in plan["stages"]}
    client = boto3.client("bedrock-runtime", region_name=runtime["region"],
                          config=Config(connect_timeout=10, read_timeout=60, retries={"total_max_attempts": 1},
                                        max_pool_connections=args.workers))
    lock, next_slot = threading.Lock(), [0.0]
    stopped = threading.Event()

    def fetch(row):
        rid = row["record_id"]
        path = raw / f"{rid}.response.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if stopped.is_set():
            return None
        with lock:
            delay = max(0, next_slot[0] - time.monotonic())
            next_slot[0] = max(time.monotonic(), next_slot[0]) + 1 / args.rps
        if stopped.wait(delay):
            return None
        ledger = SpendingLedger(ROOT / "results/spending.sqlite3", 40, limits)
        try:
            provider = BedrockProposer(client, ledger, model, stage, raw / f"{rid}.events.jsonl")
            record = InputRecord(**row)
            start = time.monotonic()
            try:
                response = provider.propose(record, tokenize(record.raw))
            except BudgetExceeded:
                stopped.set()
                return None
            except Exception as exc:
                response = {"error": type(exc).__name__}
                if hasattr(exc, "response"):
                    response["error_code"] = exc.response.get("Error", {}).get("Code")
            response.update(record_id=rid, elapsed_seconds=time.monotonic() - start)
            path.write_text(json.dumps(response, ensure_ascii=False) + "\n", encoding="utf-8")
            return response
        finally:
            ledger.close()
    pending = [r for r in inputs if not (raw / f"{r['record_id']}.response.json").exists()]
    if args.limit is not None:
        pending = pending[:args.limit]
    completed, errors = 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch, row) for row in pending]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                completed += 1
                errors += bool(result.get("error"))
            if errors >= 5:
                stopped.set()
            if completed and completed % 25 == 0:
                print(json.dumps({"model": args.model, "split": args.split, "completed_new": completed,
                                  "new_errors": errors, "pending_at_start": len(pending)}), flush=True)
    bank = [json.loads((raw / f"{r['record_id']}.response.json").read_text(encoding="utf-8")) for r in inputs if (raw / f"{r['record_id']}.response.json").exists()]
    record_by_id = {r["record_id"]: r for r in inputs}
    predictions = [validate_response(InputRecord(**record_by_id[b["record_id"]]), b) for b in bank]
    ids = {r["record_id"] for r in bank}
    metrics = score(predictions, [g for g in references if g["record_id"] in ids])
    ledger = SpendingLedger(ROOT / "results/spending.sqlite3", 40, limits)
    metrics.update(model=args.model, split=args.split, target_records=len(inputs), complete=len(bank) == len(inputs),
                   stopped=stopped.is_set(), ledger=ledger.summary(), source_scope="fixed research subset with source/construction references")
    ledger.close()
    for filename, rows in (("responses.jsonl", bank), ("predictions.jsonl", predictions)):
        (folder / filename).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("model", "split", "records", "target_records", "complete", "accepted", "exact_records", "accepted_errors", "ledger")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("screening", "validation", "final"), required=True)
    parser.add_argument("--model", choices=("nova", "haiku", "haiku45", "sonnet"), required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--rps", type=float, default=3)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not 1 <= args.workers <= 32 or not 0 < args.rps <= 10:
        parser.error("workers must be 1..32 and request rate at most 10/s")
    run(args)
