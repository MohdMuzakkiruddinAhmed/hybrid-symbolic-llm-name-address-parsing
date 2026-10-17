"""Fixed response-bank comparators. Replay is never live inference latency."""

from .contracts import InputRecord, empty_fields
from .legacy import validate_v1, validate_v2
from .materialize import materialize
from .memory import RuleMemory
from .pipeline import Parser
from .research import validate_response
from .tokenization import legacy_code, tokenize
from .validation import input_reasons, parse_proposal


class BankProposer:
    route = "bank_replay"

    def __init__(self, bank):
        self.bank, self.calls, self.cost, self.unknown_costs = bank, 0, 0.0, 0

    def propose(self, record, tokens):
        self.calls += 1
        response = self.bank[record.record_id]
        self.cost += float(response.get("usage", {}).get("estimated_usd", 0))
        self.unknown_costs += response.get("usage", {}).get("estimated_usd") is None
        if response.get("error"):
            raise ValueError("saved_generation_failed")
        return response


def run_policy(records, bank, policy, collision_signatures=()):
    if policy not in ("per_record_structural", "per_record_context_gate", "legacy_v1", "legacy_v2", "context_support1", "context_support3", "proposed"):
        raise ValueError("unknown replay policy")
    proposer = BankProposer(bank)
    predictions, legacy_memory = [], {}
    memory = RuleMemory(":memory:", support=1 if policy == "context_support1" else 3)
    parser = Parser(memory, proposer,
                    unsafe_signatures=collision_signatures if policy == "proposed" else (),
                    require_name_convention=policy in ("proposed", "context_support1", "context_support3"))
    try:
        for row in records:
            record, tokens = InputRecord(**row), tokenize(row["raw"])
            if policy in ("context_support1", "context_support3", "proposed"):
                predictions.append(parser.parse(record).to_dict())
                continue
            base = {"record_id": record.record_id, "status": "abstained", "mapping": {},
                    "fields": empty_fields(record.record_id), "route": "input_gate", "reasons": []}
            reasons = input_reasons(record, tokens)
            if reasons or (policy == "per_record_context_gate" and record.name_order is None):
                base["reasons"] = reasons or ["name_order_not_declared"]
                predictions.append(base)
                continue
            if policy.startswith("per_record"):
                try:
                    response = proposer.propose(record, tokens)
                except ValueError:
                    response = {"error": "saved_generation_failed"}
                prediction = validate_response(record, response)
                prediction["route"] = "bank_replay"
                predictions.append(prediction)
                continue
            key = "".join(legacy_code(t.text) for t in tokens)
            base["route"] = "bank_replay"
            mapping = legacy_memory.get(key)
            route = "memory" if mapping else "bank_replay"
            if mapping is None:
                try:
                    proposal = parse_proposal(proposer.propose(record, tokens)["text"])
                    if proposal.status != "mapped":
                        base["reasons"] = ["model_" + proposal.status]
                        predictions.append(base)
                        continue
                    approved, errors = (validate_v1 if policy == "legacy_v1" else validate_v2)(proposal.mapping, [t.text for t in tokens])
                    if not approved:
                        base["reasons"] = errors
                        predictions.append(base)
                        continue
                    mapping = proposal.mapping
                    legacy_memory[key] = mapping
                except (ValueError, KeyError, TypeError):
                    base["status"] = "failed"
                    predictions.append(base)
                    continue
            fields, spans = materialize(record, tokens, mapping)
            predictions.append({"record_id": record.record_id, "status": "accepted", "route": route,
                                "mapping": {str(i): field for i, field in mapping.items()}, "fields": fields, "spans": spans})
        # Dataclass serialization preserves integer mapping keys until JSON;
        # normalize all policies consistently before reference comparison.
        for prediction in predictions:
            prediction["mapping"] = {str(i): field for i, field in prediction.get("mapping", {}).items()}
        return predictions, {"logical_generations": proposer.calls,
                             "replay_requested_cost_estimate_usd": proposer.cost if not proposer.unknown_costs else None,
                             "observed_response_cost_lower_bound_usd": proposer.cost,
                             "unknown_cost_logical_generations": proposer.unknown_costs,
                             "memory_hits": sum(p.get("route") == "memory" for p in predictions),
                             "active_rules": memory.db.execute("SELECT COUNT(*) FROM rules WHERE status='active'").fetchone()[0],
                             "quarantined_rules": memory.db.execute("SELECT COUNT(*) FROM rules WHERE status='quarantined'").fetchone()[0],
                             "live_inference_calls": 0, "memory_initialized": "empty for every order/policy",
                             "latency_interpretation": "Local replay only; provider latency must not be inferred"}
    finally:
        memory.close()
