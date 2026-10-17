"""Behavioral checks for extraction, abstention, persistence, and request budgets."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adaptive_parser.budget import BudgetExceeded, SpendingLedger, usd_to_micros
from adaptive_parser.cli import FixtureProposer
from adaptive_parser.contracts import InputRecord
from adaptive_parser.discovery import BedrockProposer, build_prompt
from adaptive_parser.evaluation import evaluate
from adaptive_parser.materialize import materialize
from adaptive_parser.legacy import validate_v1, validate_v2
from adaptive_parser.memory import RuleMemory
from adaptive_parser.pipeline import Parser
from adaptive_parser.tokenization import clues, signature, tokenize
from adaptive_parser.validation import parse_proposal, validate_mapping

FIXTURES = json.loads((ROOT / "data/development/engineering_fixtures.json").read_text(encoding="utf-8"))


class CoreTests(unittest.TestCase):
    def test_lossless_unicode_and_whitespace_spans(self):
        raw = "  O’Neil\t452  Main Street\nLittle Rock "
        tokens = tokenize(raw)
        self.assertEqual([raw[t.start:t.end] for t in tokens], [t.text for t in tokens])
        self.assertEqual(tokens[0].text, "O’Neil")
        self.assertEqual(tokens[0].start, 2)

    def test_overlapping_clues_preserve_ambiguity(self):
        self.assertEqual(clues("Dr."), {"P", "F"})
        self.assertEqual(clues("MS"), {"P", "T"})

    def test_signature_reuses_structure_but_preserves_punctuation(self):
        one, two = (tokenize(FIXTURES[i]["raw"]) for i in (0, 1))
        self.assertEqual(signature(one, "en-US"), signature(two, "en-US"))
        punctuated = tokenize(FIXTURES[0]["raw"].replace("Patel", "Patel,"))
        self.assertNotEqual(signature(one, "en-US"), signature(punctuated, "en-US"))

    def test_runtime_contract_excludes_gold(self):
        with self.assertRaises(TypeError):
            InputRecord("x", "raw", gold_mapping={})
        prompt = build_prompt(InputRecord("secret-evaluator-family", FIXTURES[0]["raw"]), tokenize(FIXTURES[0]["raw"]))
        self.assertNotIn("expected_mapping", prompt)
        self.assertNotIn("secret-evaluator-family", prompt)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            parse_proposal('{"status":"mapped","mapping":{"0":"first_name","0":"last_name"}}')

    def test_only_exact_json_fence_is_normalized_and_recorded(self):
        fenced = "```json\n" + FIXTURES[0]["response_text"] + "\n```"
        result = parse_proposal(fenced)
        self.assertEqual(result.format_deviations, ("markdown_fence_removed",))
        with self.assertRaises(ValueError):
            parse_proposal(fenced, normalize_fence=False)
        with self.assertRaises(ValueError):
            parse_proposal("Explanation before the object.\n" + fenced)

    def test_normalization_does_not_fill_missing_positions(self):
        result = parse_proposal('```json\n{"status":"mapped","mapping":{"0":"first_name"}}\n```')
        self.assertFalse(validate_mapping(result.mapping, tokenize(FIXTURES[0]["raw"])).approved)

    def test_malformed_schema_types_are_rejected_without_hash_errors(self):
        for text in ('[]', '{"status":"mapped","mapping":{"0":[]}}',
                     '{"status":"mapped","mapping":{"00":"first_name"}}',
                     '{"status":"ambiguous","mapping":{"0":"first_name"}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_proposal(text)

    def test_unordered_json_positions_are_valid(self):
        mapping = dict(reversed(list(parse_proposal(FIXTURES[5]["response_text"]).mapping.items())))
        self.assertTrue(validate_mapping(mapping, tokenize(FIXTURES[5]["raw"])).approved)

    def test_structural_gate_rejects_city_and_numeric_swaps(self):
        fixture = FIXTURES[0]
        good = parse_proposal(fixture["response_text"]).mapping
        for first, second in ((3, 5), (2, 7)):
            bad = dict(good)
            bad[first], bad[second] = bad[second], bad[first]
            self.assertFalse(validate_mapping(bad, tokenize(fixture["raw"])).approved)

    def test_mississippi_is_not_forced_to_be_a_title(self):
        raw = "Maya Patel 452 Oak Street Gulfport MS 39501 USA"
        mapping = parse_proposal(FIXTURES[0]["response_text"]).mapping
        self.assertTrue(validate_mapping(mapping, tokenize(raw)).approved)

    def test_multitoken_materializer_preserves_internal_spacing(self):
        raw = FIXTURES[5]["raw"].replace("Little Rock", "Little\t Rock")
        mapping = parse_proposal(FIXTURES[5]["response_text"]).mapping
        fields, spans = materialize(InputRecord("multi", raw), tokenize(raw), mapping)
        self.assertEqual(fields["city"], "Little\t Rock")
        self.assertIsNone(fields["middle_name"])
        self.assertEqual(len(fields), 17)
        self.assertEqual(len(spans["city"]), 2)

    def test_memory_support_excludes_duplicate_input_with_new_id(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = RuleMemory(Path(directory) / "memory.sqlite3", support=3)
            try:
                key = signature(tokenize(FIXTURES[0]["raw"]), "en-US")
                mapping = parse_proposal(FIXTURES[0]["response_text"]).mapping
                memory.observe(key, mapping, "one", FIXTURES[0]["raw"])
                memory.observe(key, mapping, "renamed", FIXTURES[0]["raw"])
                memory.observe(key, mapping, "two", FIXTURES[1]["raw"])
                self.assertEqual(memory.lookup(key)[0], "miss")
                memory.observe(key, mapping, "three", FIXTURES[2]["raw"])
                self.assertEqual(memory.lookup(key)[0], "hit")
            finally:
                memory.close()

    def test_restart_and_conflict_quarantine(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            key = signature(tokenize(FIXTURES[0]["raw"]), "en-US")
            mapping = parse_proposal(FIXTURES[0]["response_text"]).mapping
            memory = RuleMemory(path, support=1)
            memory.observe(key, mapping, "one", FIXTURES[0]["raw"])
            memory.close()
            memory = RuleMemory(path, support=1)
            try:
                self.assertEqual(memory.lookup(key)[0], "hit")
                bad = dict(mapping)
                bad[0], bad[1] = bad[1], bad[0]
                memory.observe(key, bad, "two", FIXTURES[1]["raw"])
                self.assertEqual(memory.lookup(key)[0], "blocked")
            finally:
                memory.close()
            with self.assertRaises(ValueError):
                RuleMemory(path, support=3)

    def test_engineering_fixture_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = RuleMemory(Path(directory) / "memory.sqlite3")
            proposer = FixtureProposer(FIXTURES)
            try:
                parser = Parser(memory, proposer)
                predictions = [parser.parse(InputRecord(f["record_id"], f["raw"])) for f in FIXTURES]
                metrics = evaluate(predictions, FIXTURES)
                self.assertEqual(metrics["status_matches"], 10)
                self.assertEqual(metrics["checked_field_values_exact"], 6)
                self.assertEqual(metrics["memory_hits"], 1)
                self.assertEqual(proposer.calls, 7)
                self.assertEqual(predictions[3].route, "memory")
            finally:
                memory.close()

    def test_legacy_approvals_match_the_original_150_cases(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from audit_pilot import FAMILY_SPECS, load_selected_definitions
        original = load_selected_definitions()
        cases = 0
        for family, rows, fields in FAMILY_SPECS:
            for rid, raw in original[rows]:
                record = original["make_record"](rid, family, raw, original[fields])
                gold = record["gold_mapping"]
                proposals = [gold, original["make_semantic_swap"](gold),
                             original["make_clue_violation"](gold, record["clue_codes"]),
                             original["make_missing_position"](gold), original["make_invalid_schema"](gold)]
                for proposal in proposals:
                    for current, previous in ((validate_v1, "validate_real_mapping"), (validate_v2, "validate_mapping_v2")):
                        self.assertEqual(current(proposal, record["tokens"])[0],
                                         original[previous](proposal, record["tokens"], record["clue_codes"])[0])
                    cases += 1
        self.assertEqual(cases, 150)


class BudgetTests(unittest.TestCase):
    def test_stage_redistribution_preserves_charges_and_invalidates_old_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            ledger = SpendingLedger(path, 1, {"a": 0.5, "b": 0.5})
            attempt = ledger.reserve("a", "test", 0.1)
            with self.assertRaises(ValueError):
                ledger.reallocate_stages({"a": 0.7, "b": 0.3}, "test")
            ledger.settle(attempt, 0.05)
            ledger.reallocate_stages({"a": 0.7, "b": 0.3}, "measured token usage; same total ceiling")
            with self.assertRaisesRegex(ValueError, "stale"):
                ledger.reserve("a", "test", 0.1)
            ledger.close()
            revised = SpendingLedger(path, 1, {"a": 0.7, "b": 0.3})
            self.assertEqual(revised.summary()["committed_estimate_usd"], 0.05)
            self.assertEqual(revised.db.execute("SELECT COUNT(*) FROM budget_policy_events").fetchone()[0], 1)
            revised.close()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "spending.sqlite3"
        self.ledger = SpendingLedger(self.path, 40, {"screening": 1})

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_pending_and_uncertain_requests_consume_budget(self):
        attempt = self.ledger.reserve("screening", "test", ".7")
        self.ledger.uncertain(attempt, "timeout")
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("screening", "test", ".4")
        self.assertEqual(self.ledger.total(), 700000)

    def test_settlement_releases_only_unused_reservation(self):
        attempt = self.ledger.reserve("screening", "test", ".7")
        self.ledger.settle(attempt, ".01", "public-request-id")
        self.ledger.reserve("screening", "test", ".9")
        self.assertEqual(self.ledger.total(), 910000)

    def test_rounding_never_undercounts_fractional_microdollars(self):
        self.assertEqual(usd_to_micros("0.0000001"), 1)
        with self.assertRaises(ValueError):
            usd_to_micros("NaN")

    def test_reservations_are_atomic_across_connections(self):
        def reserve_one(_):
            ledger = SpendingLedger(self.path, 40, {"screening": 1})
            try:
                try:
                    ledger.reserve("screening", "test", ".6")
                    return True
                except BudgetExceeded:
                    return False
            finally:
                ledger.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(reserve_one, range(2))), 1)

    def test_overrun_is_persisted_and_halts_future_requests(self):
        attempt = self.ledger.reserve("screening", "test", ".1")
        with self.assertRaises(BudgetExceeded):
            self.ledger.settle(attempt, ".2")
        self.assertEqual(self.ledger.total(), 200000)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("screening", "test", ".1")

    def test_ledger_cannot_be_reset_with_a_different_budget(self):
        with self.assertRaises(ValueError):
            SpendingLedger(self.path, 40, {"screening": 2})


class BedrockAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = SpendingLedger(Path(self.temp.name) / "budget.sqlite3", 40, {"screening": 1})
        self.model = {"enabled": True, "rates_verified": True, "region": "us-east-1", "model_id": "test-model",
                      "price_verified_utc": datetime.now(timezone.utc).isoformat(),
                      "input_usd_per_million": 1, "output_usd_per_million": 2,
                      "reservation_input_usd_per_million": 1, "reservation_output_usd_per_million": 2,
                      "reservation_input_tokens": 1000, "max_output_tokens": 512}
        self.record = InputRecord("adapter", FIXTURES[0]["raw"])

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def client(self, stop="end_turn", error=None):
        class Fake:
            meta = SimpleNamespace(region_name="us-east-1")
            calls = 0
            def converse(inner, **request):
                inner.calls += 1
                if error:
                    raise error
                return {"usage": {"inputTokens": 100, "outputTokens": 40},
                        "stopReason": stop, "ResponseMetadata": {"RequestId": "fake"},
                        "output": {"message": {"content": [{"reasoningContent": {}}, {"text": FIXTURES[0]["response_text"]}]}}}
        return Fake()

    def test_success_records_usage_and_extracts_text(self):
        client = self.client()
        proposer = BedrockProposer(client, self.ledger, self.model, "screening")
        response = proposer.propose(self.record, tokenize(self.record.raw))
        self.assertEqual(parse_proposal(response["text"]).status, "mapped")
        self.assertEqual(self.ledger.total(), 216)
        self.assertEqual(client.calls, 1)

    def test_no_dispatch_after_budget_failure(self):
        self.ledger.reserve("screening", "other", 1)
        client = self.client()
        with self.assertRaises(BudgetExceeded):
            BedrockProposer(client, self.ledger, self.model, "screening").propose(self.record, tokenize(self.record.raw))
        self.assertEqual(client.calls, 0)

    def test_timeout_keeps_reservation_and_does_not_retry(self):
        client = self.client(error=TimeoutError())
        with self.assertRaises(TimeoutError):
            BedrockProposer(client, self.ledger, self.model, "screening").propose(self.record, tokenize(self.record.raw))
        self.assertEqual(client.calls, 1)
        self.assertEqual(self.ledger.summary()["states"], {"uncertain": 1})
        self.assertGreater(self.ledger.total(), 0)

    def test_truncation_is_charged_but_not_accepted(self):
        proposer = BedrockProposer(self.client(stop="max_tokens"), self.ledger, self.model, "screening")
        with self.assertRaises(ValueError):
            proposer.propose(self.record, tokenize(self.record.raw))
        self.assertGreater(self.ledger.total(), 0)

    def test_unverified_rates_block_adapter(self):
        self.model["rates_verified"] = False
        with self.assertRaises(ValueError):
            BedrockProposer(self.client(), self.ledger, self.model, "screening")

    def test_oversize_bounded_request_is_rejected_before_dispatch_or_reservation(self):
        self.model["max_request_utf8_bytes"] = 1
        client = self.client()
        with self.assertRaisesRegex(ValueError, "bounded-input"):
            BedrockProposer(client, self.ledger, self.model, "screening").propose(self.record, tokenize(self.record.raw))
        self.assertEqual(client.calls, 0)
        self.assertEqual(self.ledger.total(), 0)

    def test_cache_tokens_are_included_in_conservative_settlement(self):
        client = self.client()
        original = client.converse
        def cached(**request):
            result = original(**request)
            result["usage"].update(cacheReadInputTokens=10, cacheWriteInputTokens=20)
            return result
        client.converse = cached
        proposer = BedrockProposer(client, self.ledger, self.model, "screening")
        proposer.propose(self.record, tokenize(self.record.raw))
        self.assertEqual(self.ledger.total(), usd_to_micros(proposer.cost(150, 40)))

    def test_stale_rate_verification_blocks_dispatch(self):
        self.model["price_verified_utc"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        client = self.client()
        with self.assertRaises(ValueError):
            BedrockProposer(client, self.ledger, self.model, "screening")
        self.assertEqual(client.calls, 0)


if __name__ == "__main__":
    unittest.main()
