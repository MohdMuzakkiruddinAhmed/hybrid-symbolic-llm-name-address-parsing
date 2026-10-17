"""Read-only AWS access checks and AWS public price verification.

No Invoke/Converse call, subscription, agreement creation, or AWS resource
creation occurs here. Only Nova's published regional rate is enabled initially.
"""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import urllib.request

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = {"haiku": "anthropic.claude-haiku-5-5", "nova": "amazon.nova-2-lite-v1:0",
             "sonnet": "anthropic.claude-sonnet-5-5"}


def main():
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or boto3.Session().region_name
    if not region:
        raise SystemExit("Select an AWS Region in the standard AWS environment/configuration first.")
    disabled = {"region": region, "purpose": "Preflight pending or failed; inference disabled.",
                "models": {key: {"model_id": "us." + value, "region": region, "enabled": False,
                                  "rates_verified": False} for key, value in MODEL_IDS.items()}}
    (ROOT / "configs/bedrock_runtime.json").write_text(json.dumps(disabled, indent=2) + "\n", encoding="utf-8")
    client = boto3.client("bedrock", region_name=region,
                          config=Config(connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 1}))
    results = {}
    for key, model_id in MODEL_IDS.items():
        try:
            response = client.get_foundation_model_availability(modelId=model_id)
            results[key] = {k: response.get(k) for k in ("authorizationStatus", "agreementAvailability",
                                                        "entitlementAvailability", "regionAvailability")}
        except Exception as exc:
            results[key] = {"error_code": getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)}
    directory = ROOT / "results/preflight"
    directory.mkdir(parents=True, exist_ok=True)
    source = f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/{region}/index.json"
    with urllib.request.urlopen(source, timeout=30) as response:
        body = response.read()
    digest = hashlib.sha256(body).hexdigest()
    snapshot = directory / f"amazon-bedrock-{region}-{digest[:12]}.json"
    if not snapshot.exists():
        snapshot.write_bytes(body)
    offer = json.loads(body)
    selected = {}
    for sku, product in offer.get("products", {}).items():
        attributes = product.get("attributes", {})
        if attributes.get("model") != "Nova 2.0 Lite" or attributes.get("regionCode") != region:
            continue
        # The unqualified standard input/output usage types are the regional /
        # geo rates. Exclude discounted global, batch, flex, and custom rates.
        usage = attributes.get("usagetype", "")
        kind = "input" if usage.endswith("-Nova2.0Lite-input-tokens") else "output" if usage.endswith("-Nova2.0Lite-output-tokens") else None
        if kind is None:
            continue
        rates = [rate for term in offer.get("terms", {}).get("OnDemand", {}).get(sku, {}).values()
                 for rate in term.get("priceDimensions", {}).values()]
        if len(rates) != 1 or rates[0].get("unit", "").lower() != "1k tokens":
            raise ValueError("Ambiguous or unexpected AWS pricing units; model remains disabled")
        if kind in selected:
            raise ValueError("Duplicate standard AWS rate; model remains disabled")
        selected[kind] = {"sku": sku, "usage_type": usage,
                          "usd_per_million": str(Decimal(rates[0]["pricePerUnit"]["USD"]) * 1000)}
    if set(selected) != {"input", "output"}:
        raise ValueError("Could not verify both standard Nova rates")
    availability = results["nova"]
    available = (availability.get("authorizationStatus") == "AUTHORIZED"
                 and availability.get("agreementAvailability", {}).get("status") == "AVAILABLE"
                 and availability.get("entitlementAvailability") == "AVAILABLE"
                 and availability.get("regionAvailability") == "AVAILABLE")
    # Do not enable an invocation route in another geography automatically.
    enabled = available and region.startswith("us-")
    runtime = {"region": region, "purpose": "Bounded engineering smoke only; not the full research screen.",
               "models": {key: {"model_id": "us." + value, "region": region, "enabled": False,
                                 "rates_verified": False} for key, value in MODEL_IDS.items()}}
    runtime["models"]["nova"].update({
        "enabled": enabled, "rates_verified": True,
        "input_usd_per_million": selected["input"]["usd_per_million"],
        "output_usd_per_million": selected["output"]["usd_per_million"],
        "reservation_input_usd_per_million": selected["input"]["usd_per_million"],
        "reservation_output_usd_per_million": selected["output"]["usd_per_million"],
        "reservation_input_tokens": 2097152, "max_output_tokens": 512, "cost_factor": "1.2",
        "additional_fields": {"reasoningConfig": {"type": "disabled"}},
        "price_source": source, "price_snapshot_sha256": digest,
        "price_verified_utc": datetime.now(timezone.utc).isoformat(),
        "price_publication_date": offer.get("publicationDate"), "price_skus": selected,
        "reservation_note": "Reserve 2 Mi tokens (above the published 1M context window), output cap, and 20% contingency.",
    })
    report = {"checked_utc": datetime.now(timezone.utc).isoformat(), "region": region,
              "credential_provider": boto3.Session().get_credentials().method,
              "python": sys.version.split()[0],
              "packages": {p: importlib.metadata.version(p) for p in ("boto3", "botocore")},
              "availability": results, "nova_standard_rates": selected,
              "price_source": source, "snapshot": str(snapshot.relative_to(ROOT)),
              "snapshot_sha256": digest, "nova_engineering_smoke_enabled": enabled,
              "paid_inference_calls_in_preflight": 0,
              "limits": ["Authorization/catalog checks do not substitute for a successful invocation.",
                         "Anthropic AWS rates are not verified by this source; those models stay disabled."]}
    (ROOT / "configs/bedrock_runtime.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    (directory / "access_and_pricing.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"region": region, "availability": results, "nova_rates": selected,
                      "nova_smoke_enabled": enabled, "paid_inference_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
