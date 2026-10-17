"""Reproduce the legacy pilot's offline data and validator diagnostics.

This transitional audit loads selected definitions from the unchanged source.
It does not execute the Colab setup, load credentials, or make model requests.
Its extra corruption cases are development diagnostics, not a new safety test.
Run with Python 3.12 or newer from any working directory.
"""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import hashlib
import json
import platform
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "legacy/pilot_reference.py"

FAMILY_SPECS = (
    ("A_standard", "A_standard", "A_fields"),
    ("B_directional", "B_directional", "B_fields"),
    ("C_apartment", "C_apartment", "C_fields"),
    ("D_title_middle", "D_title_middle", "D_fields"),
    ("E_suffix", "E_suffix", "E_fields"),
    ("F_two_word_city", "F_two_word_city", "F_fields"),
)

ASSIGNMENTS = {
    "schema_fields", "allowed_token_fields", "PREFIXES", "SUFFIXES",
    "DIRECTIONALS", "STREET_TYPES", "UNIT_TYPES", "US_STATES",
    "known_families", "heldout_families",
} | {name for _, rows, fields in FAMILY_SPECS for name in (rows, fields)}

FUNCTIONS = {
    "clean_token", "get_clue_code", "mapping_from_fields", "make_record",
    "validate_real_mapping", "validate_mapping_v2", "make_semantic_swap",
    "make_clue_violation", "make_missing_position", "make_invalid_schema",
}

VALIDATORS = {
    "V1": "validate_real_mapping",
    "V2": "validate_mapping_v2",
}


def load_selected_definitions() -> dict:
    """Load reviewed definitions; skip every original top-level experiment."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    selected = []
    loaded = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            selected.append(node)
            loaded.add(node.name)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names and names <= ASSIGNMENTS:
                selected.append(node)
                loaded.update(names)
    missing = (ASSIGNMENTS | FUNCTIONS) - loaded
    if missing:
        raise RuntimeError(f"Legacy definitions changed or are missing: {sorted(missing)}")
    namespace = {"copy": copy, "re": re}
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def swap_fields(mapping: dict, first: str, second: str) -> dict:
    proposal = copy.deepcopy(mapping)
    positions = [next(p for p, f in proposal.items() if f == name)
                 for name in (first, second)]
    a, b = positions
    proposal[a], proposal[b] = proposal[b], proposal[a]
    return proposal


def run_cases(namespace: dict, records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        gold = record["gold_mapping"]
        original = {
            "correct": copy.deepcopy(gold),
            "semantic_swap": namespace["make_semantic_swap"](gold),
            "clue_violation": namespace["make_clue_violation"](
                gold, record["clue_codes"]
            ),
            "missing_position": namespace["make_missing_position"](gold),
            "invalid_schema": namespace["make_invalid_schema"](gold),
        }
        extra = {
            "street_city_swap": swap_fields(gold, "street_name", "city"),
            "street_postal_number_swap": swap_fields(
                gold, "street_number", "postal_code"
            ),
        }
        for suite, cases in (("legacy", original), ("additional_development", extra)):
            for case_type, proposal in cases.items():
                for version, function_name in VALIDATORS.items():
                    approved, errors = namespace[function_name](
                        copy.deepcopy(proposal), record["tokens"], record["clue_codes"]
                    )
                    rows.append({
                        "record_id": record["record_id"],
                        "pattern_family": record["pattern_family"],
                        "mask": record["token_mask"],
                        "suite": suite,
                        "test_type": case_type,
                        "validator": version,
                        "actually_correct": proposal == gold,
                        "validator_approved": approved,
                        "errors": errors,
                        "proposed_mapping": proposal,
                    })
    return rows


def summarize(rows: list[dict], suite: str, version: str) -> dict:
    selected = [r for r in rows if r["suite"] == suite and r["validator"] == version]
    correct = [r for r in selected if r["actually_correct"]]
    incorrect = [r for r in selected if not r["actually_correct"]]
    correct_approved = sum(r["validator_approved"] for r in correct)
    unsafe = sum(r["validator_approved"] for r in incorrect)
    by_type = {}
    for case_type in sorted({r["test_type"] for r in selected}):
        cases = [r for r in selected if r["test_type"] == case_type]
        approved = sum(r["validator_approved"] for r in cases)
        by_type[case_type] = {
            "cases": len(cases), "approved": approved,
            "rejected": len(cases) - approved,
        }
    return {
        "cases": len(selected),
        "correct_cases": len(correct),
        "correct_approved": correct_approved,
        "correct_approval_rate": correct_approved / len(correct) if correct else None,
        "incorrect_cases": len(incorrect),
        "unsafe_approved": unsafe,
        "ukar": unsafe / len(incorrect) if incorrect else None,
        "by_test_type": by_type,
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12+ is required to parse the original script's f-strings.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "pilot_audit")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    namespace = load_selected_definitions()
    records = [
        namespace["make_record"](rid, family, raw, namespace[fields])
        for family, row_name, fields in FAMILY_SPECS
        for rid, raw in namespace[row_name]
    ]
    family_counts = Counter(r["pattern_family"] for r in records)
    family_masks = {
        family: sorted({r["token_mask"] for r in records if r["pattern_family"] == family})
        for family in family_counts
    }
    known = {r["token_mask"] for r in records
             if r["pattern_family"] in namespace["known_families"]}
    heldout = {r["token_mask"] for r in records
               if r["pattern_family"] in namespace["heldout_families"]}
    rows = run_cases(namespace, records)
    legacy = {v: summarize(rows, "legacy", v) for v in VALIDATORS}
    additional = {v: summarize(rows, "additional_development", v) for v in VALIDATORS}
    checks = {
        "30_records": len(records) == 30,
        "6_families_with_5_records_each": len(family_counts) == 6
        and set(family_counts.values()) == {5},
        "one_mask_per_family": all(len(masks) == 1 for masks in family_masks.values()),
        "same_mapping_within_each_family": all(
            len({tuple(r["gold_mapping"].items()) for r in records
                 if r["pattern_family"] == family}) == 1
            for family in family_counts
        ),
        "3_known_and_3_heldout_masks": len(known) == len(heldout) == 3,
        "no_mask_overlap": not known.intersection(heldout),
        "v1_matches_reported_counts": (
            legacy["V1"]["cases"], legacy["V1"]["correct_approved"],
            legacy["V1"]["incorrect_cases"], legacy["V1"]["unsafe_approved"]
        ) == (150, 30, 120, 30),
        "v2_matches_reported_counts": (
            legacy["V2"]["cases"], legacy["V2"]["correct_approved"],
            legacy["V2"]["incorrect_cases"], legacy["V2"]["unsafe_approved"]
        ) == (150, 30, 120, 0),
        "v2_extra_weaknesses_reproduced": additional["V2"]["unsafe_approved"] == 60,
    }
    summary = {
        "audit_version": "0.1.0",
        "scope": "Offline development audit; no live LLM outcomes reproduced.",
        "records": len(records),
        "families": dict(family_counts),
        "family_masks": family_masks,
        "known_masks": sorted(known),
        "heldout_masks": sorted(heldout),
        "legacy_validator_results": legacy,
        "additional_development_diagnostics": additional,
        "clue_ambiguity_examples": {
            token: namespace["get_clue_code"](token) for token in ("Dr", "dr", "MS", "Ms")
        },
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "live_model_requests": 0,
    }
    manifest = {
        "audit_version": "0.1.0",
        "source_files": [
            {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (SOURCE,) if path.exists()
        ],
        "runtime": {"python": sys.version, "platform": platform.platform()},
        "method": "AST selection of reviewed constants, benchmark literals, and functions; "
                  "original top-level experiments are not executed.",
        "limitations": [
            "All records and diagnostic cases are development material.",
            "No historical Gemini responses or request logs were supplied or reproduced.",
            "Extra cases share base records and are not independent safety evidence.",
            "This audit does not implement the proposed new system.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", summary)
    write_json(output / "manifest.json", manifest)
    (output / "benchmark.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    with (output / "validator_cases.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "errors": json.dumps(row["errors"]),
                             "proposed_mapping": json.dumps(row["proposed_mapping"])})
    print(f"Offline audit: {'PASS' if summary['all_checks_passed'] else 'FAIL'}")
    print(f"Records: {len(records)}; families: {len(family_counts)}; model requests: 0")
    for version, metrics in legacy.items():
        print(f"{version}: {metrics['correct_approved']}/{metrics['correct_cases']} correct approved; "
              f"{metrics['unsafe_approved']}/{metrics['incorrect_cases']} incorrect approved")
    print("V2 additional development swaps accepted: "
          f"{additional['V2']['unsafe_approved']}/{additional['V2']['incorrect_cases']}")
    print(f"Artifacts: {output}")
    return 0 if summary["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
