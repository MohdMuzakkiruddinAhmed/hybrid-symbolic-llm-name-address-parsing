"""Build the 20,000-record DRAFT corpus offline from checked source snapshots.

This does not certify labels, freeze a protocol, or execute final-test inference.
Human review remains pending. Runtime inputs and evaluator-only labels are split.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_parser.datasets import DATASET_VERSION, addressnc_components, audit_rows, compose, registry
from adaptive_parser.tokenization import input_fingerprint

OUTPUT = ROOT / "data/corpus-draft-v1"
SOURCE_MANIFEST = ROOT / "data/sources/addressnc-v1/manifest.json"
SEED = 20261016
SPLITS = ("development", "validation", "final")
LEXICAL = {
    "development": {"given": "Ari Bela Cora Davi Eli Fara Gina Hali Ira Jora".split(),
                    "family": "Bel Car Del Fen Gar Hel Kel Mer Nor Pel".split(),
                    "street": "Cedar Willow Maple Amber Brook Clear Silver Meadow Birch Orchard".split(),
                    "city": "Alder Grove Vale Ridge Glen Spring Fair Haven Briar Hollow".split()},
    "validation": {"given": "Kali Lira Mira Neli Orla Pari Rina Savi Tali Umi".split(),
                   "family": "Ral Sel Tal Vel Wal Yel Zan Ber Der Fer".split(),
                   "street": "Juniper Cypress Hazel Aspen Sycamore Copper Laurel Forest Cotton Fern".split(),
                   "city": "Juniper Creek Bay Hill Crest Green Ash Cedar Mill Park".split()},
    "final": {"given": "Vara Wali Xara Yani Zira Asha Bina Cala Dara Eira".split(),
              "family": "Gin Hin Jin Kin Lin Min Nin Pin Rin Sin".split(),
              "street": "Hemlock Magnolia Redwood Tamarack Beech Fir Linden Acacia Pecan Poplar".split(),
              "city": "Cliff Water Pine Field Rose Summit Lake Stone Sun Bluff".split()},
    "final_known": {"given": "Feli Gala Hana Inga Jana Kara Lena Mona Nora Oona".split(),
                    "family": "Ton Von Won Yon Zor Bor Cor Dor For Gor".split(),
                    "street": "Hawthorn Dogwood Spruce Walnut Hickory Elm Sequoia Tulip Locust Mahogany".split(),
                    "city": "River Bend Grand Upper Lower Mount Oak Plain Port View".split()},
}
GIVEN_END = "an el ia on en ra is ul ya in".split()
FAMILY_END = "aro eri ino oro uni ala ele ili olo ulu".split()


def names(bank, number):
    pool = LEXICAL[bank]
    first_index, last_index = number % 100, (number * 37 + number // 100) % 100
    return [("first_name", pool["given"][first_index // 10] + GIVEN_END[first_index % 10]),
            ("last_name", pool["family"][last_index // 10] + FAMILY_END[last_index % 10])]


def identity(components):
    words = [value.casefold() for field, value in components if field in ("first_name", "last_name")]
    return hashlib.sha256("|".join(words).encode()).hexdigest()


def words(bank, dimension, size, number):
    pool = LEXICAL[bank][dimension]
    return " ".join(pool[(number + 3 * i) % len(pool)] for i in range(size))


def controlled(family, index, number, bank):
    name, address = family["name_layout"], family["address_layout"]
    pair = names(bank, number)
    components = ([("prefix_title", ("Dr.", "Mr", "Ms.")[index % 3])] if name["title"] else [])
    components += [pair[0]]
    if name["middle_initial"]:
        components.append(("middle_name", ("A.", "R.", "K.", "J.", "L.")[index % 5]))
    components.append(pair[1])
    if name["suffix"]:
        components.append(("suffix", ("Jr", "II", "III")[index % 3]))
    components.append(("street_number", str(1000 + number if bank != "final_known" else 60000 + number)))
    if address["pre_directional"]:
        components.append(("pre_directional", ("N", "SE", "W")[index % 3]))
    components.extend([("street_name", words(bank, "street", address["street_words"], number)),
                       ("street_type", ("Street", "Rd", "Avenue", "Dr", "Lane")[index % 5])])
    if address["post_directional"]:
        components.append(("post_directional", ("SW", "E", "NW")[index % 3]))
    if address["unit"]:
        components.extend([("unit_type", ("Apt", "Suite", "Unit")[index % 3]),
                           ("unit_number", str(1 + number % 90) + ("B" if index % 2 else ""))])
    components.extend([("city", words(bank, "city", address["city_words"], number // 7)),
                       ("state", "AR"), ("postal_code", str(72000 + number % 1000)), ("country", "USA")])
    return components


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode()
    if path.exists() and path.read_bytes() != body:
        raise ValueError(f"refusing to overwrite a different dataset artifact: {path}")
    if not path.exists():
        path.write_bytes(body)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(body).hexdigest(),
            "records": len(rows), "bytes": len(body)}


def candidates(gold):
    good = gold["mapping"]
    yield {"record_id": gold["record_id"], "candidate_id": "correct", "expected_admission": True, "mapping": good}
    for a, b, label in (("first_name", "last_name", "name_role_swap"),
                        ("street_name", "city", "street_city_swap"),
                        ("street_number", "postal_code", "numeric_role_swap")):
        bad = {i: b if value == a else a if value == b else value for i, value in good.items()}
        if bad == good:
            raise ValueError("corruption did not change mapping")
        yield {"record_id": gold["record_id"], "candidate_id": label,
               "expected_admission": False, "mapping": bad}
    yield {"record_id": gold["record_id"], "candidate_id": "missing_position", "expected_admission": False,
           "mapping": {i: value for i, value in good.items() if i != "0"}}


def build():
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    for entry in source_manifest["snapshots"] + [source_manifest["selected_addresses"]]:
        if hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("source snapshot checksum failure")
    source_rows = [json.loads(line) for line in (ROOT / source_manifest["selected_addresses"]["path"]).read_text(encoding="utf-8").splitlines()]
    families = registry()
    inputs, labels = [], []
    serial = Counter()

    def add(record, gold, cohort, split, components=None, **metadata):
        gold.update(cohort=cohort, split=split, **metadata)
        if components:
            gold["identity_id"] = identity(components)
        inputs.append(record)
        labels.append(gold)

    for family in families:
        split = family["split"]
        for index in range(25):
            serial[split] += 1
            components = controlled(family, index, serial[split], split)
            record, gold = compose(f"D1-{split}-{serial[split]:05}", components,
                                   separator=(" ", "  ", "\t", "\n", " ")[index % 5])
            if list(gold["mapping"].values()) != family["field_sequence"]:
                raise ValueError("rendering changed declared semantic sequence")
            add(record, gold, "D1", split, components, family_id=family["family_id"],
                address_group=family["address_group"], ontology="controlled_single_token_names")

    for row in source_rows:
        split = row["split"]
        serial[split] += 1
        address, reason = addressnc_components(row["attributes"])
        if reason:
            raise ValueError("source selection no longer passes declared scope")
        components = names(split, serial[split]) + address
        record, gold = compose(f"D2-{split}-{row['source_id'].split(':')[-1]}", components)
        gold["label_basis"] = "source_component_derived_address_and_fictional_name_rendering"
        add(record, gold, "D2", split, components, source_id=row["source_id"], source_group=row["source_group"],
            fictional_person=True, real_person_address_association=False,
            transformations=["collapse component whitespace", "prepend fictional name", "append declared USA country"],
            source_fields={"street_number": "add_number", "pre_directional": "st_predir", "street_name": "st_name",
                           "street_type": "st_postyp", "post_directional": "st_posdir", "unit_type": "unit_type",
                           "unit_number": "unit", "city": "post_comm", "state": "state", "postal_code": "post_code"})

    subtype_names = ("directional_middle_initial", "state_like_given_name", "title_road_type_overlap",
                     "number_leading_street_name", "unicode_hyphen_name", "three_word_city",
                     "two_word_country", "zip_plus_four", "alphanumeric_house_number",
                     "three_word_street", "post_directional", "numeric_unit")
    for split, total in (("development", 500), ("validation", 500), ("final", 1000)):
        for index in range(total):
            serial[split] += 1
            pair = names(split, serial[split])
            components = pair + [("street_number", str(30000 + serial[split])),
                                 ("street_name", words(split, "street", 1, index)), ("street_type", "Street"),
                                 ("city", words(split, "city", 1, index)), ("state", "AR"),
                                 ("postal_code", str(72000 + index % 1000)), ("country", "USA")]
            status = "mapped" if index < total * 3 // 5 else "ambiguous" if index < total * 4 // 5 else "unsupported"
            subtype, locale = "", "en-US"
            if status == "mapped":
                subtype = subtype_names[index % 12]
                if subtype == "directional_middle_initial":
                    components.insert(1, ("middle_name", "N."))
                elif subtype == "state_like_given_name":
                    components[0] = ("first_name", "Al")
                elif subtype == "title_road_type_overlap":
                    components.insert(0, ("prefix_title", "Dr."))
                    components = [(f, "Dr" if f == "street_type" else v) for f, v in components]
                elif subtype == "number_leading_street_name":
                    components = [(f, "42nd" if f == "street_name" else v) for f, v in components]
                elif subtype == "unicode_hyphen_name":
                    components[0] = ("first_name", pair[0][1] + "-Mae")
                    components[1] = ("last_name", "O\u2019" + pair[1][1])
                elif subtype == "three_word_city":
                    components = [(f, words(split, "city", 3, index) if f == "city" else v) for f, v in components]
                elif subtype == "two_word_country":
                    components[-1] = ("country", "United States")
                elif subtype == "zip_plus_four":
                    components[-2] = ("postal_code", components[-2][1] + "-0123")
                elif subtype == "alphanumeric_house_number":
                    components[2] = ("street_number", components[2][1] + "A")
                elif subtype == "three_word_street":
                    components = [(f, words(split, "street", 3, index) if f == "street_name" else v) for f, v in components]
                elif subtype == "post_directional":
                    components.insert(5, ("post_directional", "SW"))
                elif subtype == "numeric_unit":
                    components[5:5] = [("unit_type", "Apt"), ("unit_number", str(100 + index))]
            elif status == "ambiguous":
                subtype = "undeclared_name_order" if index % 2 == 0 else "middle_or_compound_family_boundary"
                if index % 2:
                    components.insert(1, ("middle_name", "Kai"))
            else:
                subtype = ("po_box", "unsupported_locale", "missing_postal_code", "missing_street_number")[index % 4]
                if subtype == "po_box":
                    components = [(f, "PO Box " + v if f == "street_number" else v) for f, v in components if f not in ("street_name", "street_type")]
                elif subtype == "unsupported_locale":
                    locale = "en-GB"
                    components[-4:] = [("city", "London"), ("postal_code", "SW1A 1AA"), ("country", "UK")]
                elif subtype == "missing_postal_code":
                    components = [(f, v) for f, v in components if f != "postal_code"]
                else:
                    components = [(f, v) for f, v in components if f != "street_number"]
            record, gold = compose(f"D3-{split}-{index + 1:04}", components,
                                   name_order=None if status == "ambiguous" else "given_middle_family", locale=locale)
            gold["expected_status"] = status
            if status == "ambiguous":
                first = gold["mapping"]
                second = ({i: "last_name" if field == "first_name" else "first_name" if field == "last_name" else field
                           for i, field in first.items()} if index % 2 == 0 else
                          {i: "last_name" if field == "middle_name" else field for i, field in first.items()})
                gold["admissible_mappings"] = [first, second]
            if status != "mapped":
                gold["mapping"], gold["fields"], gold["spans"] = {}, {}, []
            add(record, gold, "D3", split, components, safety_subtype=subtype,
                annotation_note="Draft construction-based status; independent human interpretation review pending")

    dev_families = [family for family in families if family["split"] == "development"]
    for family_index, family in enumerate(dev_families):
        # 80 families x 13 + 80 x 12 = 2,000, selected by fixed registry order.
        for index in range(13 if family_index < 80 else 12):
            serial["final_known"] += 1
            components = controlled(family, index, serial["final_known"], "final_known")
            record, gold = compose(f"D4-final-{serial['final_known']:04}", components)
            add(record, gold, "D4", "final", components, family_id=family["family_id"],
                address_group=family["address_group"], intentional_development_family_overlap=True)

    report = audit_rows(inputs, labels)
    plan = json.loads((ROOT / "configs/research_plan.json").read_text(encoding="utf-8"))
    expected = {f"{cohort['id']}/{split}": cohort[split] for cohort in plan["dataset"]["cohorts"] for split in SPLITS if cohort[split]}
    if report["records"] != 20000 or report["counts"] != expected:
        raise ValueError("corpus allocation differs from registered plan")
    d3_counts = Counter(g["expected_status"] for g in labels if g["cohort"] == "D3")
    if d3_counts != {"mapped": 1200, "ambiguous": 400, "unsupported": 400}:
        raise ValueError("D3 status allocation changed")
    # Legacy and engineering inputs are excluded from the 20,000 new records.
    exclusions = set()
    fixtures = json.loads((ROOT / "data/development/engineering_fixtures.json").read_text(encoding="utf-8"))
    exclusions.update(input_fingerprint(row["raw"]) for row in fixtures)
    for line in (ROOT / "results/pilot_audit/benchmark.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        exclusions.add(input_fingerprint(row["raw_record"]))
    if any(g["fingerprint"] in exclusions for g in labels):
        raise ValueError("new corpus overlaps legacy/engineering input")
    files = [write_jsonl(OUTPUT / "registry/families.jsonl", families)]
    by_id = {r["record_id"]: (r, g) for r, g in zip(inputs, labels)}
    for split in SPLITS:
        selected = sorted([(r, g) for r, g in zip(inputs, labels) if g["split"] == split], key=lambda pair: pair[0]["record_id"])
        files.append(write_jsonl(OUTPUT / f"inputs/{split}.jsonl", [r for r, _ in selected]))
        files.append(write_jsonl(OUTPUT / f"evaluator/{split}.labels.jsonl", [g for _, g in selected]))
        proposals = [candidate for _, g in selected if g["cohort"] == "D3" and g["expected_status"] == "mapped" for candidate in candidates(g)]
        files.append(write_jsonl(OUTPUT / f"evaluator/{split}.validator_candidates.jsonl", proposals))
    # Fixed screen: one row from every D1 development family, then 40 second rows.
    screen = []
    d1 = [g for g in labels if g["cohort"] == "D1" and g["split"] == "development"]
    for family in dev_families:
        screen.append(next(g["record_id"] for g in d1 if g["family_id"] == family["family_id"]))
    for family in dev_families[:40]:
        screen.append([g["record_id"] for g in d1 if g["family_id"] == family["family_id"]][1])
    for county in ("JACKSON", "WAKE", "GUILFORD"):
        eligible = [g["record_id"] for g in labels if g.get("source_group") == f"addressnc:{county}"]
        random.Random(f"{SEED}|{county}").shuffle(eligible)
        screen.extend(eligible[:25])
    for status, quota in (("mapped", 15), ("ambiguous", 5), ("unsupported", 5)):
        # Keep all twelve hard-case types and the unsupported subtypes represented.
        eligible = [g["record_id"] for g in labels if g["cohort"] == "D3" and g["split"] == "development" and g["expected_status"] == status]
        screen.extend(eligible[:quota])
    random.Random(SEED).shuffle(screen)
    if len(screen) != 300 or len(set(screen)) != 300:
        raise ValueError("invalid screening selection")
    files.append(write_jsonl(OUTPUT / "screening/inputs.jsonl", [by_id[rid][0] for rid in screen]))
    files.append(write_jsonl(OUTPUT / "screening/labels.jsonl", [by_id[rid][1] for rid in screen]))
    files.append(write_jsonl(OUTPUT / "screening/selection.jsonl", [{"record_id": rid, "cohort": by_id[rid][1]["cohort"], "split": "development"} for rid in screen]))
    report.update(dataset_version=DATASET_VERSION, D3_status_counts=dict(d3_counts),
                  screening_records=300, screening_cohorts={"D1": 200, "D2": 75, "D3": 25},
                  validator_decisions=6000, independent_unique_validator_inputs=1200,
                  final_model_inference_executed=False, legacy_and_engineering_overlap=0,
                  source_manifest=SOURCE_MANIFEST.relative_to(ROOT).as_posix(),
                  source_manifest_sha256=hashlib.sha256(SOURCE_MANIFEST.read_bytes()).hexdigest(),
                  builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  lexical_pool_provenance="Author-created syllable combinations and word lists in scripts/build_corpus.py; fictional people and controlled addresses",
                  limitations=["All labels and ambiguity statuses await independent human review",
                               "D1 has 400 token-field sequences but only 50 address layouts and 8 name layouts; related variants grouped by address layout",
                               "D1 split tests compositions/lengths, not 400 independent linguistic phenomena",
                               "D2 is rendered North Carolina county transfer, not naturally observed joint records or independent-provider transfer",
                               "No arbitrary unique mapping is assigned to ambiguous D3 records",
                               "Draft corpus generated before human annotation pilot; not frozen final-test evidence"], files=files)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = OUTPUT / "manifest.json"
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if manifest.exists():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if existing["files"] != files or existing["source_manifest_sha256"] != report["source_manifest_sha256"]:
            raise ValueError("draft artifact content changed; use a versioned output directory")
        # Preserve the original construction manifest and its original code hash.
        # Reproduction verifies every artifact; newer audit metadata goes in a
        # separate report rather than rewriting historical generation provenance.
        verification = {key: value for key, value in report.items() if key != "files"}
        verification["reproduced_artifacts"] = len(files)
        verification["dataset_helpers_sha256"] = hashlib.sha256((ROOT / "src/adaptive_parser/datasets.py").read_bytes()).hexdigest()
        (ROOT / "results/corpus_reproduction.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    else:
        manifest.write_text(body, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("records", "unique_fingerprints", "counts", "D1_families", "source_jurisdictions", "integrity_status", "screening_records", "independent_annotation_status")}, indent=2))


if __name__ == "__main__":
    build()
