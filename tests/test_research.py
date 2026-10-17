"""Research accounting checks, distinct from empirical accuracy claims."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.cli import FixtureProposer
from adaptive_parser.contracts import InputRecord
from adaptive_parser.datasets import compose
from adaptive_parser.memory import RuleMemory
from adaptive_parser.pipeline import Parser
from adaptive_parser.replay import run_policy
from adaptive_parser.research import score


class ResearchTests(unittest.TestCase):
    def test_accepted_ambiguous_reference_counts_as_an_error(self):
        record, gold = compose("a", [("first_name", "Ari"), ("last_name", "Bela")])
        gold.update(cohort="D3", expected_status="ambiguous")
        prediction = {"record_id": "a", "status": "accepted", "mapping": gold["mapping"], "fields": gold["fields"]}
        result = score([prediction], [gold])
        self.assertEqual(result["accepted_errors"], 1)
        self.assertEqual(result["incorrect_acceptances_on_nonmapped_reference"], 1)
        self.assertIsNone(result["exact_record_accuracy_on_mapped_reference"])

    def test_research_name_context_gate_does_not_call_a_provider(self):
        fixture = json.loads((ROOT / "data/development/engineering_fixtures.json").read_text(encoding="utf-8"))[0]
        provider = FixtureProposer([fixture])
        memory = RuleMemory(":memory:")
        try:
            prediction = Parser(memory, provider, require_name_convention=True).parse(InputRecord(fixture["record_id"], fixture["raw"]))
            self.assertEqual(prediction.status, "abstained")
            self.assertEqual(prediction.route, "name_convention_gate")
            self.assertEqual(provider.calls, 0)
        finally:
            memory.close()

    def test_replay_counts_three_distinct_discoveries_before_reuse(self):
        fixtures = json.loads((ROOT / "data/development/engineering_fixtures.json").read_text(encoding="utf-8"))[:4]
        records = [{"record_id": f["record_id"], "raw": f["raw"], "locale": "en-US", "name_order": "given_middle_family"} for f in fixtures]
        bank = {f["record_id"]: {"text": f["response_text"], "usage": {"estimated_usd": "0.001"}} for f in fixtures}
        predictions, routing = run_policy(records, bank, "proposed")
        self.assertEqual(routing["logical_generations"], 3)
        self.assertEqual(routing["memory_hits"], 1)
        self.assertEqual(routing["live_inference_calls"], 0)
        self.assertTrue(all(p["status"] == "accepted" for p in predictions))

    def test_replay_never_counts_an_unknown_charge_as_free(self):
        record = {"record_id": "a", "raw": "Ari Bela 42 Cedar Street Grove AR 72032 USA", "locale": "en-US", "name_order": "given_middle_family"}
        _, routing = run_policy([record], {"a": {"error": "TimeoutError"}}, "per_record_structural")
        self.assertIsNone(routing["replay_requested_cost_estimate_usd"])
        self.assertEqual(routing["unknown_cost_logical_generations"], 1)


if __name__ == "__main__":
    unittest.main()
