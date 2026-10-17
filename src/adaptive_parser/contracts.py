"""Runtime contracts deliberately exclude evaluator gold and family metadata."""

from dataclasses import asdict, dataclass, field

SCHEMA_FIELDS = (
    "record_id", "prefix_title", "first_name", "middle_name", "last_name",
    "suffix", "street_number", "pre_directional", "street_name", "street_type",
    "post_directional", "unit_type", "unit_number", "city", "state",
    "postal_code", "country",
)
TOKEN_FIELDS = frozenset(SCHEMA_FIELDS) - {"record_id"}
NAME_FIELDS = frozenset(("prefix_title", "first_name", "middle_name", "last_name", "suffix"))
SCHEMA_VERSION = "person-us-address-v1"


@dataclass(frozen=True)
class InputRecord:
    record_id: str
    raw: str
    locale: str = "en-US"
    name_order: str | None = None

    def __post_init__(self):
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("record_id must be a nonempty string")
        if not isinstance(self.raw, str) or not isinstance(self.locale, str):
            raise ValueError("raw and locale must be strings")
        if self.name_order not in (None, "given_middle_family"):
            raise ValueError("unsupported source-declared name convention")


@dataclass(frozen=True)
class Token:
    index: int
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Proposal:
    status: str
    mapping: dict[int, str] = field(default_factory=dict)
    reason: str = ""
    format_deviations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Validation:
    approved: bool
    reasons: tuple[str, ...] = ()


@dataclass
class Prediction:
    record_id: str
    raw: str
    status: str
    route: str
    fields: dict
    tokens: list[Token]
    mapping: dict[int, str] = field(default_factory=dict)
    spans: dict[str, list[dict]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    rule_id: int | None = None
    signature: str | None = None
    validator_version: str = "structural-v0.5-typed-streets"
    usage: dict = field(default_factory=dict)
    format_deviations: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def empty_fields(record_id: str) -> dict:
    return {key: record_id if key == "record_id" else None for key in SCHEMA_FIELDS}
