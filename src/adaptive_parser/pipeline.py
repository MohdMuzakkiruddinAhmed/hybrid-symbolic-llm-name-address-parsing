"""One-record routing. Evaluator labels are never passed to the proposer."""

from .contracts import InputRecord, Prediction, empty_fields
from .materialize import materialize
from .tokenization import signature, tokenize
from .validation import input_reasons, parse_proposal, validate_mapping


class Parser:
    def __init__(self, memory, proposer, unsafe_signatures=(), require_name_convention=False):
        self.memory = memory
        self.proposer = proposer
        self.unsafe_signatures = frozenset(unsafe_signatures)
        self.require_name_convention = require_name_convention

    def parse(self, record: InputRecord) -> Prediction:
        tokens = tokenize(record.raw)
        prediction = Prediction(record.record_id, record.raw, "abstained", "input_gate",
                                empty_fields(record.record_id), tokens)
        prediction.reasons = input_reasons(record, tokens)
        if prediction.reasons:
            return prediction
        if self.require_name_convention and record.name_order is None:
            prediction.route = "name_convention_gate"
            prediction.reasons = ["name_order_not_declared"]
            return prediction
        key = signature(tokens, record.locale, record.name_order)
        prediction.signature = key
        reusable = key not in self.unsafe_signatures
        state, rule = self.memory.lookup(key) if reusable else ("miss", None)
        if state == "blocked":
            prediction.route = "blocked_memory"
            prediction.reasons = ["conflicting_or_quarantined_rule"]
            return prediction
        if state == "hit":
            mapping = rule["mapping"]
            prediction.rule_id = rule["id"]
            prediction.route = "memory"
            validation = validate_mapping(mapping, tokens, record.name_order)
            if not validation.approved:
                self.memory.quarantine(key, ";".join(validation.reasons))
                prediction.reasons = list(validation.reasons)
                return prediction
        else:
            prediction.route = self.proposer.route
            if not reusable:
                prediction.route += ":memory_disabled"
            try:
                response = self.proposer.propose(record, tokens)
                prediction.usage = response.get("usage", {})
                proposal = parse_proposal(response["text"])
                prediction.format_deviations = list(proposal.format_deviations)
            except Exception as exc:
                prediction.status = "failed"
                prediction.reasons = [f"proposal_failure:{type(exc).__name__}"]
                return prediction
            if proposal.status != "mapped":
                prediction.reasons = [f"model_{proposal.status}", proposal.reason]
                return prediction
            mapping = proposal.mapping
            validation = validate_mapping(mapping, tokens, record.name_order)
            if not validation.approved:
                prediction.reasons = list(validation.reasons)
                return prediction
            if reusable:
                prediction.rule_id, memory_status = self.memory.observe(key, mapping, record.record_id, record.raw)
            else:
                memory_status = "not_retained_known_collision"
            if memory_status == "quarantined":
                prediction.reasons = ["conflicting_mapping_not_promoted"]
                return prediction
        prediction.fields, prediction.spans = materialize(record, tokens, mapping)
        prediction.mapping = mapping
        prediction.status = "accepted"
        prediction.reasons = []
        return prediction
