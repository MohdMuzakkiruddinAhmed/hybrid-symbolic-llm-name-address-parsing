"""Generate reference-agreement tables, paired intervals and scientific figures.

Analysis only: never modifies predictive code, labels, response banks or memory.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.contracts import InputRecord
from adaptive_parser.materialize import materialize
from adaptive_parser.research import score
from adaptive_parser.tokenization import legacy_code, signature, tokenize

VERSION = "mapping-json-v4-typed-streets"
POLICIES = ("per_record_structural", "per_record_context_gate", "legacy_v1", "legacy_v2", "context_support1", "context_support3", "proposed")


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def exact(prediction, gold):
    return prediction["status"] == "accepted" and gold["expected_status"] == "mapped" and prediction.get("fields") == gold["fields"] and prediction.get("mapping") == gold["mapping"]


def cluster(gold):
    cohort = gold["cohort"]
    return (gold["address_group"] if cohort in ("D1", "D4") else
            gold["source_group"] if cohort == "D2" else gold["record_id"])


def paired_bootstrap(first, second, gold, repetitions=2000):
    import numpy as np
    rng = np.random.default_rng(20261016)
    sums = np.zeros((repetitions, 10), dtype=float)
    cohorts = sorted({g["cohort"] for g in gold})
    units = {}
    for cohort in cohorts:
        grouped = defaultdict(lambda: np.zeros(10))
        total = 0
        for reference in gold:
            if reference["cohort"] != cohort:
                continue
            total += 1
            rid = reference["record_id"]
            eligible = reference["expected_status"] == "mapped"
            for offset, prediction in ((0, first[rid]), (5, second[rid])):
                accepted, correct = prediction["status"] == "accepted", exact(prediction, reference)
                grouped[cluster(reference)][offset:offset + 5] += [1, accepted, accepted and not correct, correct, eligible]
        matrix = np.array(list(grouped.values()))
        units[cohort] = len(matrix)
        weights = rng.multinomial(len(matrix), np.full(len(matrix), 1 / len(matrix)), size=repetitions)
        sample = weights @ matrix
        # Keep original cohort mixture weights despite unequal cluster sizes.
        sample *= (total / sample[:, 0])[:, None]
        sums += sample
    def ratio(num, den):
        return np.divide(num, den, out=np.full_like(num, np.nan), where=den != 0)
    differences = {
        "automatic_coverage_difference": ratio(sums[:, 1], sums[:, 0]) - ratio(sums[:, 6], sums[:, 5]),
        "accepted_error_rate_difference": ratio(sums[:, 2], sums[:, 1]) - ratio(sums[:, 7], sums[:, 6]),
        "exact_mapped_reference_accuracy_difference": ratio(sums[:, 3], sums[:, 4]) - ratio(sums[:, 8], sums[:, 9]),
    }
    intervals = {}
    for name, values in differences.items():
        values = values[np.isfinite(values)]
        intervals[name] = {"lower_95": float(np.quantile(values, 0.025)) if len(values) else None,
                           "upper_95": float(np.quantile(values, 0.975)) if len(values) else None}
    return {"replicates": repetitions, "seed": 20261016, "cluster_counts": units,
            "scope": "Descriptive paired intervals conditional on fixed routing and reference labels; do not establish human-verified accuracy or independent order effects",
            "intervals": intervals}


def field_metrics(predictions, references):
    ref = {g["record_id"]: g for g in references}
    fields = defaultdict(Counter)
    for p in predictions:
        gold = ref[p["record_id"]]
        if gold["expected_status"] != "mapped":
            continue
        for field, expected in gold["fields"].items():
            if field == "record_id":
                continue
            observed = p.get("fields", {}).get(field) if p["status"] == "accepted" else None
            equal = expected is not None and observed == expected
            fields[field]["true_positive_exact_value"] += equal
            fields[field]["false_positive_value"] += observed is not None and not equal
            fields[field]["false_negative_value"] += expected is not None and not equal
    result = {}
    for field, counts in fields.items():
        tp, fp, fn = counts["true_positive_exact_value"], counts["false_positive_value"], counts["false_negative_value"]
        result[field] = {**dict(counts), "precision": tp / (tp + fp) if tp + fp else None,
                         "recall": tp / (tp + fn) if tp + fn else None,
                         "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}
    return result


def review_sensitivity(predictions, reviews, inputs):
    references, selected, counters = [], [], Counter()
    by_id = {p["record_id"]: p for p in predictions}
    for review in reviews:
        rid, status = review["record_id"], review["review_status"]
        counters[status] += 1
        if status == "review_incomplete":
            continue
        reference = {"record_id": rid, "cohort": rid.split("-")[0], "expected_status": "ambiguous", "mapping": {}, "fields": {}}
        if status == "mapped":
            record = InputRecord(**inputs[rid])
            mapping = {int(i): field for i, field in review["mapping"].items()}
            tokens = tokenize(record.raw)
            # Reference integrity only: never apply the evaluated parser's
            # structural/clue acceptance rules to adjudicate its reference.
            if set(mapping) != set(range(len(tokens))):
                raise ValueError("model-assisted reference lacks complete token coverage")
            for field in set(mapping.values()):
                positions = sorted(i for i, value in mapping.items() if value == field)
                if positions != list(range(positions[0], positions[-1] + 1)):
                    raise ValueError("model-assisted reference has a noncontiguous field")
            fields, _ = materialize(record, tokens, mapping)
            reference.update(expected_status="mapped", mapping=review["mapping"], fields=fields)
        elif status in ("insufficient", "unsupported"):
            reference["expected_status"] = "unsupported"
        references.append(reference)
        selected.append(by_id[rid])
    return {"conservative_review_sensitivity": score(selected, references, label_basis="model-assisted consensus; disputed/ambiguous cases conservatively demand abstention"),
            "review_counts": dict(counters), "human_annotations": 0,
            "interpretation": "Sensitivity to a correlated model-assisted reference, not a replacement human gold standard"}


def collision_analysis(inputs, gold):
    refs = {g["record_id"]: g for g in gold}
    representations = {"legacy_mask": defaultdict(Counter), "enriched_signature": defaultdict(Counter)}
    for record in inputs:
        reference = refs[record["record_id"]]
        if reference["expected_status"] != "mapped":
            continue
        tokens = tokenize(record["raw"])
        sequence = tuple(reference["mapping"][str(i)] for i in range(len(tokens)))
        keys = {"legacy_mask": "".join(legacy_code(t.text) for t in tokens),
                "enriched_signature": signature(tokens, record["locale"], record.get("name_order"))}
        for name, key in keys.items():
            representations[name][key][sequence] += 1
    return {name: {"distinct_keys": len(groups), "conflicting_reference_keys": sum(len(counts) > 1 for counts in groups.values()),
                    "mapped_records_in_conflicting_keys": sum(sum(counts.values()) for counts in groups.values() if len(counts) > 1),
                    "interpretation": "Representation collision against construction mappings; not proof of raw-text semantic uniqueness"}
            for name, groups in representations.items()}


def main():
    output = ROOT / "results/analysis"
    output.mkdir(exist_ok=True)
    corpus = ROOT / "data/corpus-draft-v1"
    inputs = load(corpus / "inputs/final.jsonl")
    input_by_id = {r["record_id"]: r for r in inputs}
    gold = load(corpus / "evaluator/final.labels.jsonl")
    replay_folder = ROOT / f"results/replay/{VERSION}/final"
    replay = load(replay_folder / "metrics.jsonl")
    if len(replay) != 294:
        raise ValueError("expected 14 static and 280 stream policy evaluations")
    reviews = load(ROOT / "annotation/model-assisted-v2/final_audit/consensus.jsonl")
    if len(reviews) != 2000:
        raise ValueError("model-assisted final audit must cover 2000 attempted paired inputs")
    rows, sensitivities, field_results, intervals, reuse = [], [], {}, [], []
    source_files = []
    crf_path = ROOT / "results/local_baselines/final/crf.predictions.jsonl"
    crf = {p["record_id"]: p for p in load(crf_path)}
    source_files.append(crf_path)
    for model in ("nova", "haiku45"):
        maps = {}
        for policy in POLICIES:
            metric = next(r for r in replay if r["model"] == model and r["policy"] == policy and r["regime"] == "static_main")
            rows.append(metric)
            path = replay_folder / f"{model}.{policy}.predictions.jsonl"
            predictions = load(path)
            source_files.append(path)
            maps[policy] = {p["record_id"]: p for p in predictions}
            field_results[f"{model}/{policy}"] = field_metrics(predictions, gold)
            sensitivities.append({"model": model, "policy": policy, **review_sensitivity(predictions, reviews, input_by_id)})
            hits = [p for p in predictions if p.get("route") == "memory"]
            refs = {g["record_id"]: g for g in gold}
            incorrect = sum(not exact(p, refs[p["record_id"]]) for p in hits)
            reuse.append({"model": model, "policy": policy, "memory_reuse_events": len(hits),
                          "incorrect_reuse_events": incorrect, "harmful_reuse_rate": incorrect / len(hits) if hits else None})
        for comparator in ("per_record_context_gate", "legacy_v1", "legacy_v2", "crf"):
            second = crf if comparator == "crf" else maps[comparator]
            intervals.append({"model": model, "first": "proposed", "second": comparator,
                              **paired_bootstrap(maps["proposed"], second, gold)})
    for method in ("grammar", "usaddress_composite", "crf"):
        path = ROOT / f"results/local_baselines/final/{method}.predictions.jsonl"
        predictions = load(path)
        row = score(predictions, gold)
        row.update(model="local", policy=method, regime="static_main", logical_generations=0, memory_hits=0, live_inference_calls=0)
        rows.append(row)
        source_files.append(path)
        field_results[f"local/{method}"] = field_metrics(predictions, gold)
        sensitivities.append({"model": "local", "policy": method, **review_sensitivity(predictions, reviews, input_by_id)})
    streams = [r for r in replay if r["regime"] != "static_main"]
    stream_summary = []
    for model in ("nova", "haiku45"):
        for regime in ("high_recurrence", "long_tail", "cohort_shift", "conflict_late"):
            for policy in POLICIES:
                group = [r for r in streams if r["model"] == model and r["regime"] == regime and r["policy"] == policy]
                baselines = {r["seed"]: r for r in streams if r["model"] == model and r["regime"] == regime and r["policy"] == "per_record_context_gate"}
                savings = [1 - r["logical_generations"] / baselines[r["seed"]]["logical_generations"] for r in group]
                stream_summary.append({"model": model, "regime": regime, "policy": policy, "orders": len(group),
                                       "mean_generation_reduction": sum(savings) / len(savings), "minimum_generation_reduction": min(savings),
                                       "maximum_generation_reduction": max(savings),
                                       "mean_accepted_error_rate": sum(r["accepted_error_rate"] or 0 for r in group) / len(group),
                                       "scope": "Five orders of one response bank; not independent model samples or observed production savings"})
    # Publication analysis uses the released, settled accounting snapshot.
    cost_snapshot = json.loads((output / "costs.json").read_text(encoding="utf-8"))
    costs = cost_snapshot["stages"]
    write(output / "main_results.json", rows)
    write(output / "paired_cluster_intervals.json", intervals)
    write(output / "field_value_metrics.json", field_results)
    write(output / "model_assisted_sensitivity.json", sensitivities)
    write(output / "memory_reuse.json", reuse)
    write(output / "stream_summary.json", stream_summary)
    write(output / "representation_collisions.json", collision_analysis(inputs, gold))
    write(output / "costs.json", {"stages": costs, "committed_estimate_usd": sum(r["committed_estimate_usd"] for r in costs),
                                   "operational_cap_usd": 40, "project_maximum_usd": 50, "human_annotations": 0,
                                   "note": "Conservative token/rate estimates and retained unknown reservations; not AWS invoice. Annotation-engine usage is separate."})
    table = ["# Final construction-reference results", "", "All rows use the same 10,000 final inputs. These are source/construction-reference agreements; human annotations: zero.", "",
             "| Model | Method | Accepted | Exact records | Accepted error | Logical generations |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        risk = "undefined" if row["accepted_error_rate"] is None else f"{100 * row['accepted_error_rate']:.2f}%"
        table.append(f"| {row['model']} | {row['policy']} | {row['accepted']} | {row['exact_records']} | {risk} | {row['logical_generations']} |")
    table.extend(["", "Logical generations are policy requests in replay, not additional provider calls. The stored response banks incurred their separately reported actual generation costs. Local CRF uses 5,800 construction-labeled development records; its supervision differs from LLM-only discovery.", ""])
    (output / "tables.md").write_text("\n".join(table), encoding="utf-8")
    make_figures(output, rows, stream_summary)
    write(output / "analysis_manifest.json", {"generated_utc": datetime.now(timezone.utc).isoformat(), "analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                              "predictive_protocol_sha256": hashlib.sha256((ROOT / "configs/experiment_protocol.json").read_bytes()).hexdigest(),
                                              "inputs": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
                                              "human_annotations": 0, "static_comparators": len(rows), "policy_evaluations_with_streams": len(replay)})
    print(json.dumps({"analysis_rows": len(rows), "paired_cluster_comparisons": len(intervals), "model_assisted_audit_inputs": len(reviews), "output": str(output)}))


def make_figures(output, rows, streams):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42, "svg.fonttype": "none"})
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    colors = {"nova": "#245b91", "haiku45": "#c0652b"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3), layout="constrained")
    for model in colors:
        selected = [r for r in rows if r["model"] == model]
        x = np.arange(len(selected)) + (-0.18 if model == "nova" else 0.18)
        axes[0].bar(x, [100 * r["automatic_coverage"] for r in selected], width=0.34, color=colors[model], label=model)
        axes[1].bar(x, [100 * (r["accepted_error_rate"] or 0) for r in selected], width=0.34, color=colors[model])
    local = [r for r in rows if r["model"] == "local"]
    axes[0].bar(np.arange(7, 10), [100 * r["automatic_coverage"] for r in local], width=0.55, color="#65756a", label="Local baselines")
    axes[1].bar(np.arange(7, 10), [100 * (r["accepted_error_rate"] or 0) for r in local], width=0.55, color="#65756a")
    labels = ["Per record", "Context gate", "Legacy V1", "Legacy V2", "Support 1", "Support 3", "Proposed", "Grammar", "usaddress", "CRF"]
    for axis in axes:
        axis.set_xticks(range(10), labels, rotation=40, ha="right")
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    axes[0].set_ylabel("Automatic coverage (%)")
    axes[0].legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.01), ncol=3, fontsize=8, borderaxespad=0)
    axes[1].set_ylabel("Accepted construction-reference error (%)")
    axes[1].axhline(1, color="#555555", linewidth=1, linestyle="--", label="Validation target")
    axes[1].legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.01), fontsize=8, borderaxespad=0)
    for extension in ("png", "pdf", "svg"):
        fig.savefig(figures / f"coverage_and_reference_error.{extension}", dpi=220)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(8, 4), layout="constrained")
    regimes = ("high_recurrence", "long_tail", "cohort_shift", "conflict_late")
    for model in colors:
        selected = [next(r for r in streams if r["model"] == model and r["regime"] == regime and r["policy"] == "proposed") for regime in regimes]
        mean = np.array([100 * r["mean_generation_reduction"] for r in selected])
        low = np.maximum(0, mean - np.array([100 * r["minimum_generation_reduction"] for r in selected]))
        high = np.maximum(0, np.array([100 * r["maximum_generation_reduction"] for r in selected]) - mean)
        x = np.arange(4) + (-0.16 if model == "nova" else 0.16)
        axis.bar(x, mean, width=0.3, color=colors[model], label=model, yerr=np.array([low, high]), capsize=3)
    axis.set_xticks(range(4), ["High recurrence", "Long tail", "Cohort shift", "Late transfer"])
    axis.set_ylabel("Replay generation reduction (%)")
    axis.legend(frameon=False)
    axis.grid(axis="y", alpha=0.2)
    axis.set_axisbelow(True)
    for extension in ("png", "pdf", "svg"):
        fig.savefig(figures / f"replay_reduction_by_regime.{extension}", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    main()
