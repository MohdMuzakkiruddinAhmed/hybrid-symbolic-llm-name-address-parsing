# Dataset coverage and reference provenance

Version 0.5, 2026-10-16. All 20,000 records have passed machine integrity and deterministic reproduction checks. Protocol 0.5 is locally frozen, including predictive/annotation source hashes and final IDs. The user replaced the unavailable human-annotation workflow with input-only model-assisted review. Human annotations: zero. Original source/construction labels and immutable historical review metadata remain unchanged. Allocation is defined in `configs/research_plan.json`; hashes and realized counts are in `data/corpus-draft-v1/manifest.json`.

## Structural coverage

Build a registry of actual semantic field sequences and formatting grammars before generating the 10,000 D1 records. The target is 400 defensible groups with 25 records each. Do not count a new first name, street value, title spelling, or punctuation-only alias as a new independent semantic structure.

The draft registry contains 400 distinct token-field sequences: eight name layouts crossed with 50 address layouts. Eight title/middle-initial/suffix combinations share each address layout and stay in the same split. The 50 address groups are split 20/10/20, giving 160/80/160 field sequences. Street names have one to three words, cities one to three words, and directionals and units change the semantic sequence. Punctuation, whitespace and lexical substitutions do not add families. These are compositions of known primitives, not 400 independent phenomena. Use the coarser address group for D1 uncertainty estimates.

All inspected legacy layouts are assigned to development. The D4 rows intentionally reuse the 160 development field sequences with separate lexical pools, 80 families with 13 rows and 80 with 12. Do not merge this known-family result into novel-layout accuracy.

| Dimension | Variants to register | Diagnostic question |
| --- | --- | --- |
| Name components | Title, middle component, generational suffix, missing optional components | Does the field sequence change? |
| Compound names | Multi-token given, middle, or family spans; particles | Can the boundary be identified from observable input? |
| Name order | Given-first, family-first with observable separators, ambiguous order | Is the distinction recoverable without hidden template labels? |
| Street components | Pre/post directionals, multi-token names, optional type | Does the same clue mask admit different mappings? |
| Unit components | Marker and identifier, alphanumeric unit, omitted unit | Can the number be confused with building/ZIP? |
| Locality | One/multi-token city, state abbreviation ambiguity, ZIP+4 | Are semantic spans and numeric roles preserved? |
| Formatting | Whitespace, commas, periods, case, Unicode punctuation | Is this a perturbation of an existing family rather than a new family? |
| Missing/noisy input | Missing components, OCR-like substitutions, contradictory clues | Should the parser abstain? |

Record each proposed family's `family_id`, field sequence, grammar, observable discriminators, admissible interpretations, source grouping, and rationale. Split related variants together. If there are fewer than 400 justified groups, report the real number and revise uncertainty calculations before freezing; keep 10,000 rows without pretending lexical variants are independent families.

## Lexical and source coverage

D1 names and address values need recorded lexical-pool provenance. Keep final identities and near duplicates out of development supports. D2 samples 6,000 structured external addresses across documented jurisdictions/source providers, then creates explicitly fictional name-address combinations. Raw real-world joint records, if obtained, form a separately declared cohort. Do not use an LLM to generate the evaluation gold.

Implemented pools are author-created syllable combinations and word lists in `scripts/build_corpus.py`, with separate development, validation, final-novel and final-known banks. These are not observed people, deliverability-verified controlled addresses, or a representative sample of cultural naming practices. Repeated fictional name identities can occur within a split and must not be treated as independent observed people.

The external draft uses [NC OneMap AddressNC](https://www.nconemap.gov/datasets/nconemap::addressnc-points-addressnc/about) under its [public-use policy](https://www.nconemap.gov/pages/terms). Source metadata, exact policy content, object-ID inventories, selected attributes, sample queries and checksums are preserved under `data/sources/addressnc-v1/`. It is one aggregation service in one state, not independent-provider transfer. Development uses Jackson/Wake/Guilford; validation Buncombe/Durham/Cumberland; final Mecklenburg/Forsyth/New Hanover/Union/Orange/Alamance. Each county contributes 500 records selected by a seeded hash ordering of public object IDs. Of 6,253 examined candidates, 253 were excluded under the recorded scope. Equal county quotas are not population-representative sampling.

Source fields map directly to semantic address components; our parser and its clue lexicons do not create these labels. Preserve the source attributes separately. Record whitespace collapsing, fictional-name prepending and country appending as rendering transformations. Do not drop records because a current parser rejects them. Exclusions cover missing required components, unsupported number shapes, unmodeled modifiers/building/floor/lot/suffix fields, and undeclared unit boundaries. This restricts the external task to the declared component ontology. Source components do not establish raw-text semantic uniqueness; the separately labeled model-assisted audit measures sensitivity to an alternative model-assisted interpretation.

D3's 2,000 inputs target 1,200 uniquely interpretable hard cases, 400 ambiguous cases, and 400 unsupported/insufficient cases. Candidate-mapping corruptions are additional correlated decisions, not new records. D4 contributes 2,000 new lexical realizations of development structures and is reported as known-family evaluation.

The corpus realizes those D3 counts. Its 12 mapped hard-case types cover initials, lexical clue collisions, Unicode/hyphens, numeric roads/units, multiword cities/countries, ZIP+4, alphanumeric house numbers, and post-directionals. Ambiguous names have multiple admissible mappings and no arbitrary unique gold. Unsupported examples cover PO boxes, non-U.S. locale, missing ZIP and missing house number. Four incorrect proposals plus one correct proposal per mapped D3 input produce 6,000 decisions over 1,200 base input IDs. Final safety inputs are generator-authored, with no claim of independent human authorship or adjudication. All 1,000 final D3 inputs receive the separate model-assisted audit.

## Realized generation and freeze workflow

1. Pilot the annotation conventions on development inputs using fresh input-only model-assisted sessions; preserve earlier prompt versions and disagreements.
2. Acquire source data and record source-specific licenses, checksums, and field mappings.
3. Assign structural/source groups and lexical identity pools to splits.
4. Generate rows with separate runtime inputs and evaluator-only labels.
5. Audit duplicates, source-span fidelity, ambiguity, and split arithmetic locally.
6. Lock the final manifest and withhold final labels from parser development.

The 300-record development screen exists under `data/corpus-draft-v1/screening/`: 200 D1, 75 D2 (25 per development county), and 25 D3 (15 mapped, five ambiguous, five unsupported). Selection preceded model outputs. Labels passed span, field, duplicate and split integrity checks. Nova/Haiku screened all 300 and Sonnet a fixed 150 subset. The six-record Nova engineering smoke is separate. Historical blank human forms remain in `annotation/pilot-v1/`; actual model-assisted outputs are in `annotation/model-assisted-v2/`.

## Development findings and remaining limits

All 20,000 raw inputs are unique under NFKC/case/whitespace normalization. No original pilot or engineering fixture is counted in the corpus. Fictional identities, related D1 address layouts, source jurisdictions and component-normalized base addresses have no unintended cross-split overlap. The latter is not complete fuzzy/geospatial duplicate detection. Runtime inputs contain only `record_id`, `raw`, `locale`, and the source-declared `name_order`; labels and source/family groups are stored separately.

The name convention is a runtime feature and part of the prompt and memory signature. The gate enforces that convention only when supplied. Expanded runtime aliases follow [USPS Publication 28 street suffixes](https://pe.usps.com/text/pub28/28apc_002.htm) and [directionals](https://pe.usps.com/text/pub28/28api_007.htm); legacy lexicons are preserved for the historical baseline. Clue words may still be lexical road/city/unit values; for example a marked unit can be `N` and a declared middle initial can be `N.`.

Development diagnostics admitted all 5,800 mapped construction labels and rejected all 1,200 deliberately incorrect D3 candidates after tuning. These are not independent accuracy estimates. One signature still corresponds to different source/construction mappings, retained in `results/development_collision_catalog.jsonl`; the proposed policy bypasses reuse and retention for that signature. This is a development-observed exclusion, not an exhaustive collision guarantee.

The final model-assisted audit covers 1,000 preselected D2 inputs and all 1,000 D3 inputs in two fresh passes, with no construction labels or evaluated-model answers. All 2,000 pairs are valid: 1,442 identical mapped, 324 ambiguous, 34 disputed, 100 unsupported and 100 insufficient. Status agreement is 98.3%; the same model's passes are correlated. Construction references remain primary and model-assisted consensus supplies a separately labeled sensitivity analysis. See `annotation/model-assisted-v2/final_audit/summary.json` and `results/analysis/model_assisted_sensitivity.json`.

Primary scope limits remain one external provider/state, fictional joint person/address records, related synthetic layouts, supplied name conventions and no independent human verification. Multi-provider and naturally observed joint-record validation remain future work; they are not silently counted as completed data collection.
