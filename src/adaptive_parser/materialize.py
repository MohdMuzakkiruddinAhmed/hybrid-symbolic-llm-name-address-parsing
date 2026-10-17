"""Extract values directly from source spans without filling absent fields."""

from .contracts import InputRecord, TOKEN_FIELDS, Token, empty_fields


def materialize(record: InputRecord, tokens: list[Token], mapping: dict[int, str]):
    fields = empty_fields(record.record_id)
    spans = {}
    for label in sorted(TOKEN_FIELDS):
        selected = [t for t in tokens if mapping[t.index] == label]
        if not selected:
            continue
        # Contiguity is checked by the gate. Preserve the original intervening
        # whitespace and punctuation rather than normalizing away source data.
        start, end = selected[0].start, selected[-1].end
        fields[label] = record.raw[start:end]
        spans[label] = [{"start": t.start, "end": t.end, "text": t.text} for t in selected]
    return fields, spans
