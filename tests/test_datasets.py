"""Research integrity checks: observable context, provenance and split separation."""

from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.contracts import InputRecord
from adaptive_parser.datasets import addressnc_components, audit_rows, compose, registry
from adaptive_parser.discovery import build_prompt
from adaptive_parser.tokenization import signature, tokenize
from adaptive_parser.validation import validate_mapping
from adaptive_parser.memory import RuleMemory
from adaptive_parser.pipeline import Parser
from adaptive_parser.cli import FixtureProposer


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class DatasetTests(unittest.TestCase):
    def test_known_collision_bypasses_existing_rule_and_is_never_promoted(self):
        fixtures = json.loads((ROOT / "data/development/engineering_fixtures.json").read_text(encoding="utf-8"))
        selected = fixtures[:2]
        provider = FixtureProposer(selected)
        memory = RuleMemory(":memory:", support=1)
        try:
            key = signature(tokenize(selected[0]["raw"]), "en-US")
            engine = Parser(memory, provider, unsafe_signatures={key})
            for item in selected:
                prediction = engine.parse(InputRecord(item["record_id"], item["raw"]))
                self.assertEqual(prediction.status, "accepted")
                self.assertIn("memory_disabled", prediction.route)
            self.assertEqual(provider.calls, 2)
            self.assertEqual(memory.db.execute("SELECT COUNT(*) FROM rules").fetchone()[0], 0)
        finally:
            memory.close()
    def test_related_address_layouts_stay_together(self):
        families = registry()
        self.assertEqual(len(families), 400)
        self.assertEqual(len({tuple(f["field_sequence"]) for f in families}), 400)
        self.assertEqual(Counter(f["split"] for f in families), {"development": 160, "validation": 80, "final": 160})
        grouped = defaultdict(set)
        for family in families:
            grouped[family["address_group"]].add(family["split"])
        self.assertEqual(len(grouped), 50)
        self.assertTrue(all(len(splits) == 1 for splits in grouped.values()))

    def test_context_is_supplied_to_model_and_isolates_memory(self):
        raw = "Ari Bela 42 Cedar Street Grove AR 72032 USA"
        tokens = tokenize(raw)
        known, unknown = InputRecord("known", raw, name_order="given_middle_family"), InputRecord("unknown", raw)
        self.assertIn("single-token given", build_prompt(known, tokens))
        self.assertIn("no name-order convention", build_prompt(unknown, tokens))
        self.assertNotEqual(signature(tokens, known.locale, known.name_order), signature(tokens, unknown.locale, unknown.name_order))
        with self.assertRaises(ValueError):
            InputRecord("x", raw, name_order="hidden_evaluation_family")

    def test_declared_name_contract_rejects_swapped_roles(self):
        record, gold = compose("x", [("first_name", "Ari"), ("middle_name", "R."), ("last_name", "Bela"),
                                     ("street_number", "42"), ("street_name", "Cedar"), ("street_type", "Street"),
                                     ("city", "Grove"), ("state", "AR"), ("postal_code", "72032")])
        good = {int(i): f for i, f in gold["mapping"].items()}
        bad = {i: "last_name" if f == "first_name" else "first_name" if f == "last_name" else f for i, f in good.items()}
        self.assertTrue(validate_mapping(good, tokenize(record["raw"]), record["name_order"]).approved)
        self.assertFalse(validate_mapping(bad, tokenize(record["raw"]), record["name_order"]).approved)
        # Explicitly retain the unknown-context limitation; don't infer a convention.
        self.assertTrue(validate_mapping(bad, tokenize(record["raw"])).approved)

    def test_external_labels_come_from_components_without_clue_inference(self):
        source = {"add_number": "0042", "st_name": "NC 42", "st_postyp": "HIGHWAY",
                  "post_comm": "TWO  WORD CITY", "state": "NC", "post_code": "27501"}
        fields, reason = addressnc_components(source)
        self.assertIsNone(reason)
        self.assertEqual(dict(fields)["street_name"], "NC 42")
        self.assertEqual(dict(fields)["street_number"], "0042")
        self.assertEqual(dict(fields)["city"], "TWO WORD CITY")
        self.assertEqual(source["post_comm"], "TWO  WORD CITY")
        source["st_premod"] = "OLD"
        self.assertEqual(addressnc_components(source)[1], "unmodeled_source_component:st_premod")

    def test_lexical_clues_do_not_prohibit_valid_name_and_road_values(self):
        components = [("first_name", "Al"), ("middle_name", "N."), ("last_name", "Bela"),
                      ("street_number", "42"), ("street_name", "NC 42"), ("street_type", "Highway"),
                      ("city", "Grove"), ("state", "NC"), ("postal_code", "27501")]
        record, gold = compose("x", components)
        self.assertTrue(validate_mapping({int(i): f for i, f in gold["mapping"].items()}, tokenize(record["raw"]), record["name_order"]).approved)
        one = tokenize("Ari Bela 42 NORTH Pine Street Grove NC 27501 USA")
        two = tokenize("Ari Bela 42 Cedar Pine Street Grove NC 27501 USA")
        self.assertNotEqual(signature(one, "en-US"), signature(two, "en-US"))

    def test_letter_direction_is_allowed_as_a_marked_unit_identifier(self):
        record, gold = compose("x", [("first_name", "Ari"), ("last_name", "Bela"),
                                     ("street_number", "42"), ("street_name", "Cedar"), ("street_type", "Street"),
                                     ("unit_type", "Apt"), ("unit_number", "N"), ("city", "Grove"),
                                     ("state", "NC"), ("postal_code", "27501")])
        self.assertTrue(validate_mapping({int(i): f for i, f in gold["mapping"].items()}, tokenize(record["raw"]), record["name_order"]).approved)

    def test_span_construction_preserves_unicode_and_internal_whitespace(self):
        record, gold = compose("x", [("first_name", "Ana-Mae"), ("last_name", "O\u2019Neil"),
                                     ("city", "Little\t Rock")], separator="  ")
        self.assertEqual(gold["fields"]["city"], "Little\t Rock")
        for span in gold["spans"]:
            self.assertEqual(record["raw"][span["start"]:span["end"]], gold["fields"][span["field"]])
        self.assertEqual(set(record), {"record_id", "raw", "locale", "name_order"})

    def test_gold_and_duplicate_input_cannot_leak_through_contract(self):
        record, gold = compose("x", [("first_name", "Ari"), ("last_name", "Bela")])
        gold.update(cohort="D3", split="development")
        leaked = {**record, "expected_mapping": gold["mapping"]}
        with self.assertRaises(ValueError):
            audit_rows([leaked], [gold])
        second_record, second_gold = copy.deepcopy(record), copy.deepcopy(gold)
        second_record["record_id"] = second_gold["record_id"] = "different-id"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_rows([record, second_record], [gold, second_gold])

    def test_source_jurisdiction_cannot_cross_splits(self):
        records, labels = [], []
        for index, split in enumerate(("development", "final")):
            record, gold = compose(str(index), [("first_name", f"Person{index}"), ("last_name", "Example")])
            gold.update(cohort="D2", split=split, source_group="same-county")
            records.append(record)
            labels.append(gold)
        with self.assertRaisesRegex(ValueError, "jurisdiction"):
            audit_rows(records, labels)

    def test_all_artifact_checksums_and_corpus_integrity(self):
        corpus = ROOT / "data/corpus-draft-v1"
        manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            self.assertEqual(hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])
        inputs, gold = [], []
        for split in ("development", "validation", "final"):
            inputs.extend(read_rows(corpus / f"inputs/{split}.jsonl"))
            gold.extend(read_rows(corpus / f"evaluator/{split}.labels.jsonl"))
        report = audit_rows(inputs, gold)
        self.assertEqual(report["records"], 20000)
        self.assertEqual(report["unique_fingerprints"], 20000)
        self.assertEqual(report["base_address_split_overlaps"], 0)
        self.assertEqual(report["D1_address_groups"], 50)

    def test_screen_is_only_development_with_registered_allocation(self):
        corpus = ROOT / "data/corpus-draft-v1"
        selection = read_rows(corpus / "screening/selection.jsonl")
        self.assertEqual(Counter(row["cohort"] for row in selection), {"D1": 200, "D2": 75, "D3": 25})
        self.assertTrue(all(row["split"] == "development" for row in selection))
        self.assertEqual(len({row["record_id"] for row in selection}), 300)
        dev = {row["record_id"] for row in read_rows(corpus / "inputs/development.jsonl")}
        self.assertTrue({row["record_id"] for row in selection} <= dev)
        labels = read_rows(corpus / "screening/labels.jsonl")
        d3 = [row for row in labels if row["cohort"] == "D3"]
        self.assertEqual(Counter(row["expected_status"] for row in d3), {"mapped": 15, "ambiguous": 5, "unsupported": 5})


if __name__ == "__main__":
    unittest.main()
