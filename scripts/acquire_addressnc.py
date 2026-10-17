"""Acquire a bounded, reproducible public-address sample; no AWS calls.

Only address components and public source identifiers are requested. Sampling
uses a seeded SHA-256 ordering of county object IDs, independently of parsers.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.datasets import addressnc_components

SERVICE = "https://services.nconemap.gov/secure/rest/services/AddressNC/NC1Map_Addresses/MapServer/0"
ITEM = "https://www.arcgis.com/sharing/rest/content/items/a6ec71ff93d3429085765821bf5b5aa3?f=json"
TERMS = "https://www.arcgis.com/sharing/rest/content/items/e60514c3b78542ef9902e3d7f7a671c1/data?f=json"
COUNTIES = {
    "development": ["JACKSON", "WAKE", "GUILFORD"],
    "validation": ["BUNCOMBE", "DURHAM", "CUMBERLAND"],
    "final": ["MECKLENBURG", "FORSYTH", "NEW HANOVER", "UNION", "ORANGE", "ALAMANCE"],
}
FIELDS = ("objectid", "uniqueid", "county", "state", "add_number", "addnum_suf",
          "st_predir", "st_premod", "st_presep", "st_pretyp", "st_name",
          "st_postyp", "st_posmod", "st_posdir", "post_code", "post_comm",
          "unit", "unit_type", "building", "floor", "lot")
SEED = "addressnc-county-sample-v1-20261016"


def fetch(url):
    # IIS rejects long query URLs with 404. ArcGIS query also supports a read-only
    # form POST; the request still only retrieves public feature attributes.
    parts = urllib.parse.urlsplit(url)
    use_post = len(url) > 1800
    request = urllib.request.Request(
        urllib.parse.urlunsplit(parts._replace(query="")) if use_post else url,
        data=parts.query.encode() if use_post else None,
        headers={"User-Agent": "address-parsing-research/0.1",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read(25_000_001)
    if len(body) > 25_000_000:
        raise ValueError("public response exceeded bounded download size")
    obj = json.loads(body)
    if "error" in obj:
        raise ValueError(f"public API error: {obj['error'].get('code')}")
    return body, obj


def write_snapshot(folder, label, body):
    digest = hashlib.sha256(body).hexdigest()
    path = folder / f"{label}-{digest[:16]}.json"
    if path.exists() and path.read_bytes() != body:
        raise ValueError("snapshot collision")
    path.write_bytes(body)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": len(body)}


def texts(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("text", "html", "markdown") and isinstance(value, str):
                yield html.unescape(re.sub("<[^>]+>", " ", value))
            else:
                yield from texts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from texts(value)


def acquire(folder):
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in old["snapshots"] + [old["selected_addresses"]]:
            if hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("existing source checksum failed; refusing overwrite")
        print(json.dumps({"status": "reused_verified_snapshot", "addresses": old["selected_count"]}))
        return
    snapshots = []
    for label, url in (("terms", TERMS), ("item", ITEM), ("layer", SERVICE + "?f=json")):
        body, obj = fetch(url)
        snapshots.append({**write_snapshot(folder, label, body), "url": url})
        if label == "terms":
            policy = " ".join(texts(obj))
            if "free and unrestricted use policy" not in policy or "are not required" not in policy:
                raise ValueError("source use policy changed; inspect before acquisition")
            (folder / "terms-readable.txt").write_text(policy, encoding="utf-8")
    jobs = [(split, county) for split, counties in COUNTIES.items() for county in counties]

    def county_sample(job):
        split, county = job
        stem = county.lower().replace(" ", "-")
        query = {"where": f"county='{county}'", "returnIdsOnly": "true", "f": "json"}
        url = SERVICE + "/query?" + urllib.parse.urlencode(query)
        body, obj = fetch(url)
        entries = [{**write_snapshot(folder, stem + "-ids", body), "url": url}]
        ids = obj.get("objectIds") or []
        ids.sort(key=lambda i: hashlib.sha256(f"{SEED}|{county}|{i}".encode()).digest())
        chosen, rejected, seen = [], Counter(), set()
        examined = 0
        for offset in range(0, min(len(ids), 6000), 200):
            query = {"objectIds": ",".join(map(str, ids[offset:offset + 200])),
                     "outFields": ",".join(FIELDS), "returnGeometry": "false", "f": "json"}
            url = SERVICE + "/query?" + urllib.parse.urlencode(query)
            body, obj = fetch(url)
            entries.append({**write_snapshot(folder, f"{stem}-page-{offset // 200:02}", body), "url": url})
            if obj.get("exceededTransferLimit"):
                raise ValueError("truncated source page")
            by_id = {x["attributes"]["objectid"]: x["attributes"] for x in obj.get("features", [])}
            for oid in ids[offset:offset + 200]:
                examined += 1
                if oid not in by_id:
                    rejected["missing_id_at_query_time"] += 1
                    continue
                source = by_id[oid]
                components, reason = addressnc_components(source)
                if reason:
                    rejected[reason] += 1
                    continue
                identity = tuple((k, " ".join(v.casefold().split())) for k, v in components)
                if identity in seen:
                    rejected["duplicate_component_address"] += 1
                    continue
                seen.add(identity)
                chosen.append({"split": split, "source_group": f"addressnc:{county}",
                               "source_id": f"addressnc:{oid}", "attributes": source})
                if len(chosen) == 500:
                    break
            if len(chosen) == 500:
                break
        if len(chosen) != 500:
            raise ValueError(f"insufficient in-scope unique addresses for {county}: {len(chosen)}")
        return chosen, entries, {"county": county, "split": split, "available_ids": len(ids),
                                 "examined": examined, "selected": len(chosen), "exclusions": dict(rejected)}

    selected, sampling = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for rows, entries, report in pool.map(county_sample, jobs):
            selected.extend(rows)
            snapshots.extend(entries)
            sampling.append(report)
            print(json.dumps({"county": report["county"], "selected": len(rows)}), flush=True)
    data = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in selected).encode()
    entry = write_snapshot(folder, "selected-addresses", data)
    # JSONL has a .jsonl extension, unlike API snapshot JSON files.
    path = ROOT / entry["path"]
    target = path.with_suffix(".jsonl")
    path.replace(target)
    entry["path"] = target.relative_to(ROOT).as_posix()
    manifest = {"version": "addressnc-sample-v1", "acquired_utc": datetime.now(timezone.utc).isoformat(),
                "provider": "NC OneMap / NCCGIA and local authoritative providers",
                "source_page": "https://www.nconemap.gov/datasets/nconemap::addressnc-points-addressnc/about",
                "service": SERVICE, "terms_page": "https://www.nconemap.gov/pages/terms",
                "use_policy": "NC OneMap free and unrestricted use policy; custom public-use terms, not relabeled CC0",
                "citation": "NC OneMap (2019). North Carolina Department of Information Technology, Government Data Analytics Center, Center for Geographic Information and Analysis. Available at www.nconemap.gov.",
                "sampling_seed": SEED, "sampling": sampling, "selected_count": len(selected),
                "selected_addresses": entry, "snapshots": snapshots,
                "scope_limitations": ["One state and one aggregation service; county transfer, not independent provider transfer",
                                      "Equal county quotas; not population-representative statewide sampling",
                                      "Simple component ontology; exclusions are recorded before any model runs",
                                      "Public structured addresses will be rendered with explicitly fictional people"]}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "acquired", "addresses": len(selected), "manifest": str(manifest_path)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/sources/addressnc-v1")
    acquire(parser.parse_args().output.resolve())
