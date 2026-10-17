"""Local engineering demo and deliberately bounded Bedrock smoke runs."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import uuid

from .budget import SpendingLedger
from .contracts import InputRecord
from .discovery import BedrockProposer
from .evaluation import evaluate
from .memory import RuleMemory
from .pipeline import Parser

ROOT = Path(__file__).resolve().parents[2]


class FixtureProposer:
    route = "fixture_replay"

    def __init__(self, fixtures):
        self.responses = {f["record_id"]: f["response_text"] for f in fixtures}
        self.calls = 0

    def propose(self, record, tokens):
        self.calls += 1
        return {"text": self.responses[record.record_id], "usage": {"live_requests": 0}}


def dump(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("demo", "smoke"))
    parser.add_argument("--fixtures", type=Path, default=ROOT / "data/development/engineering_fixtures.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/parser_runs")
    parser.add_argument("--runtime", type=Path, default=ROOT / "configs/bedrock_runtime.json")
    parser.add_argument("--model", default="nova")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = args.output / run_id
    output.mkdir(parents=True, exist_ok=False)
    ledger = None
    if args.mode == "demo":
        proposer = FixtureProposer(fixtures)
        selected = fixtures
    else:
        import boto3
        from botocore.config import Config
        if not 1 <= args.limit <= 10:
            parser.error("engineering smoke runs allow 1-10 records only")
        runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
        model = runtime["models"][args.model]
        plan = json.loads((ROOT / "configs/research_plan.json").read_text(encoding="utf-8"))
        client = boto3.client("bedrock-runtime", region_name=runtime["region"],
                              config=Config(connect_timeout=10, read_timeout=60,
                                            retries={"total_max_attempts": 1}))
        ledger = SpendingLedger(ROOT / "results/spending.sqlite3", 40,
                                {s["id"]: s["allocation_usd"] for s in plan["stages"]})
        proposer = BedrockProposer(client, ledger, model, "screening", output / "requests.jsonl")
        selected = [f for f in fixtures if f["expected_status"] == "accepted"][:args.limit]
    memory = RuleMemory(output / "memory.sqlite3", support=3)
    try:
        engine = Parser(memory, proposer)
        predictions = [engine.parse(InputRecord(f["record_id"], f["raw"])) for f in selected]
        with (output / "predictions.jsonl").open("w", encoding="utf-8") as stream:
            for prediction in predictions:
                stream.write(json.dumps(prediction.to_dict(), ensure_ascii=False) + "\n")
        metrics = evaluate(predictions, selected)
        metrics.update({"run_id": run_id, "mode": args.mode, "proposer_calls": proposer.calls,
                        "live_inference": args.mode == "smoke",
                        "proposal_normalization": "exact-json-fence-v1; raw format deviations are retained"})
        if ledger:
            metrics["project_spending_ledger"] = ledger.summary()
        dump(output / "metrics.json", metrics)
        sources = sorted((ROOT / "src/adaptive_parser").glob("*.py")) + [args.fixtures]
        manifest = {"run_id": run_id, "scope": "Engineering development only; not final research evaluation.",
                    "python": platform.python_version(), "platform": platform.platform(),
                    "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                    "mode": args.mode, "memory_support": 3, "records_in_order": [f["record_id"] for f in selected]}
        if ledger:
            manifest["runtime_model_settings"] = model
            manifest["sdk_versions"] = {p: importlib.metadata.version(p) for p in ("boto3", "botocore")}
        dump(output / "manifest.json", manifest)
        args.output.mkdir(parents=True, exist_ok=True)
        dump(args.output / "latest.json", {"run_id": run_id, "path": str(output), "mode": args.mode})
        print(json.dumps({"run_id": run_id, "mode": args.mode, "records": metrics["records"],
                          "accepted": metrics.get("accepted", 0), "status_matches": metrics["status_matches"],
                          "exact_mappings": metrics["exact_mappings"], "memory_hits": metrics.get("memory_hits", 0),
                          "proposer_calls": proposer.calls, "output": str(output)}, indent=2))
        if args.mode == "demo":
            return 0 if metrics["status_matches"] == len(selected) and metrics["exact_mappings"] == metrics["eligible_extraction_records"] else 1
        return 0 if metrics["exact_mappings"] == len(selected) else 1
    finally:
        memory.close()
        if ledger:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
