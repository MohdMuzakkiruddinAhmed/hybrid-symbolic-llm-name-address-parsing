"""Verify AWS website Geo pricing tokens against its public USD meter map.

Does not subscribe, accept agreements, or invoke a foundation model.
"""
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
PAGE = "https://aws.amazon.com/bedrock/pricing/"
MAP = "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrockfoundationmodels/USD/current/bedrockfoundationmodels.json"


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.global_tables = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs).get("data-pricing-markup", "")
        if "Geo and In-region Cross-region Inference" in data and "Claude Haiku 5.5" in data:
            self.tables.append(data)
        if "Global Cross-region Inference" in data and "Claude Haiku 4.5" in data:
            self.global_tables.append(data)


def download(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def main():
    runtime_path = ROOT / "configs/bedrock_runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    if runtime["region"] != "us-east-1":
        raise ValueError("this verifier requires explicit update for another Region")
    page, body = download(PAGE), download(MAP)
    parser = Markup()
    parser.feed(page.decode())
    if len(parser.tables) != 1 or "Price per 1M input tokens" not in parser.tables[0]:
        raise ValueError("ambiguous AWS pricing table or changed units")
    rates = json.loads(body)
    region = rates["regions"]["US East (N. Virginia)"]
    directory = ROOT / "results/preflight"
    snapshots = {}
    for label, data in (("aws-bedrock-pricing-page", page), ("aws-foundation-meter-map", body)):
        digest = hashlib.sha256(data).hexdigest()
        path = directory / f"{label}-{digest[:16]}.{'html' if label.endswith('page') else 'json'}"
        if not path.exists():
            path.write_bytes(data)
        snapshots[label] = {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}
    client = boto3.client("bedrock", region_name=runtime["region"],
                          config=Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=15))
    report = {}
    models = {"haiku": ("Claude Haiku 5.5", "anthropic.claude-haiku-5-5"),
              "haiku45": ("Claude Haiku 4.5", "anthropic.claude-haiku-4-5-20251001-v1:0"),
              "sonnet": ("Claude Sonnet 5.5", "anthropic.claude-sonnet-5-5")}
    for key, (name, model_id) in models.items():
        table = parser.global_tables[0] if key == "haiku45" and len(parser.global_tables) == 1 else parser.tables[0]
        route = "global." if key == "haiku45" else "us."
        rows = re.findall(r"<tr>\s*<td>" + re.escape(name) + r"</td>(.*?)</tr>", table, re.S)
        if len(rows) != 1:
            raise ValueError(f"cannot uniquely identify {name}")
        tokens = re.findall(r"priceOf![^!}]+!([^!}]+)", rows[0])
        if len(tokens) < 2:
            raise ValueError("missing input/output meter keys")
        selected = {kind: {**region[token], "meter_key": token}
                    for kind, token in zip(("input", "output"), tokens[:2])}
        available = client.get_foundation_model_availability(modelId=model_id)
        enabled = (available.get("authorizationStatus") == "AUTHORIZED"
                   and available.get("agreementAvailability", {}).get("status") == "AVAILABLE"
                   and available.get("entitlementAvailability") == "AVAILABLE"
                   and available.get("regionAvailability") == "AVAILABLE")
        runtime["models"][key] = {"model_id": route + model_id, "region": runtime["region"],
                                  "enabled": enabled, "rates_verified": True,
                                  "input_usd_per_million": selected["input"]["price"],
                                  "output_usd_per_million": selected["output"]["price"],
                                  "reservation_input_usd_per_million": selected["input"]["price"],
                                  "reservation_output_usd_per_million": selected["output"]["price"],
                                  "reservation_input_tokens": 65536, "max_request_utf8_bytes": 16384,
                                  "max_output_tokens": 512 if key != "sonnet" else 1024,
                                  "cost_factor": "1.2", "additional_fields": {"thinking": {"type": "between_tools" if key == "sonnet" else "disabled"}},
                                  "price_source": PAGE, "price_meter_map": MAP,
                                  "price_verified_utc": datetime.now(timezone.utc).isoformat(),
                                  "price_snapshots": snapshots, "price_meters": selected,
                                  "route": "Global" if key == "haiku45" else "US Geo",
                                  "reservation_note": "At most 16KiB serialized system/messages; reserve 64K input tokens and full output cap with 20% contingency. Unknown costs retained; overruns halt ledger."}
        report[key] = {"name": name, "input_usd_per_million": selected["input"]["price"],
                       "output_usd_per_million": selected["output"]["price"],
                       "agreement_status": available.get("agreementAvailability", {}).get("status"),
                       "enabled": enabled}
    runtime["purpose"] = "Verified, guarded development screening and later explicitly frozen study stages."
    # Use the same conservative bounded-input guard for Nova. No tools, retrieval,
    # history, or images are included in these fixed single-turn requests.
    runtime["models"]["nova"].update(reservation_input_tokens=65536, max_request_utf8_bytes=16384)
    runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    result = {"verified_utc": datetime.now(timezone.utc).isoformat(), "region": runtime["region"],
              "page": PAGE, "meter_map": MAP, "snapshots": snapshots, "models": report,
              "inference_calls": 0, "agreements_created": 0,
              "count_tokens_runtime_endpoint": "Tested unsupported for Nova 2 Lite and Sonnet 5.5; do not call as a dispatch prerequisite"}
    (directory / "claude_rates.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
