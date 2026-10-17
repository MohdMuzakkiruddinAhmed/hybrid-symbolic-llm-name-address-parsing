# Implemented architecture, protocol v0.5

The runtime receives four fields: `record_id`, `raw`, `locale`, and optional source-declared `name_order`. Family IDs, source groups, construction mappings and model-assisted reviews are evaluator-only data. The main scientific comparison matches the same name-convention gate in the per-record and proposed policies.

```mermaid
flowchart TD
    A[Raw record and declared source context] --> B[Input and source-convention gates]
    B -->|unsupported or unresolved name order| X[Abstain with reason]
    B --> C[Whitespace tokens with exact character spans]
    C --> D[Overlapping clues, shape and punctuation signature]
    D --> E{Known development collision?}
    E -->|yes| K[Discover without retaining a reusable rule]
    E -->|no| F{Memory lookup}
    F -->|quarantined| X
    F -->|one active rule| G[Apply mapping and revalidate]
    G -->|invalid| H[Quarantine rule]
    H --> X
    G -->|valid| V[Materialize 17 fields from source spans]
    F -->|miss or provisional| K
    K --> L[Check fresh rates and bounded request size]
    L --> M[Atomic stage and project reservation]
    M -->|insufficient allowance| X
    M --> N[Bedrock Converse with one SDK attempt]
    N --> O[Usage settlement or retained unknown reservation]
    N --> P[Strict JSON and token coverage checks]
    P -->|ambiguous, unsupported or invalid| X
    P --> Q[Typed-address and declared-name validation]
    Q -->|invalid| X
    Q -->|valid| R{Reusable signature?}
    R -->|no| V
    R -->|yes| S[Store distinct-input provisional evidence]
    S -->|conflicting mapping| H
    S -->|three distinct consistent inputs| T[Promote rule to active]
    S -->|fewer supports| V
    T --> V
```

The signature includes schema/tokenizer/encoder versions, locale, the name convention, overlapping clue alternatives, coarse token shapes and punctuation. It omits lexical identities and evaluator metadata. A match is a retrieval heuristic; it does not prove semantic equivalence.

SQLite stores rules, distinct raw-input fingerprints, admission events and validator/promotion-policy bindings. Existing memories with different validator versions are rejected. The production parser can discover observed conflicts, but an already active rule may prevent later discovery calls that would reveal a collision. The experiments measure that remaining propagation risk.

The project ledger preserves every reservation and settlement. A stage redistribution is allowed only as a recorded transaction within the unchanged USD 40 ceiling, with no requests in flight and no removal of committed charges. USD 10 remains outside that operational allocation. Provider errors without usable billing counts retain their full reservations. The ledger is not an AWS invoice.

## Data and reference separation

```mermaid
flowchart LR
    A[Controlled renderer] --> D[20,000 unique runtime inputs]
    B[AddressNC snapshots and use policy] --> D
    C[Safety and ambiguity constructions] --> D
    A --> E[Separate construction references]
    B --> E
    C --> E
    D --> F[Development, validation and final splits]
    F --> G[Bedrock response banks]
    F --> H[Fresh input-only model-assisted passes]
    H --> I[Consensus, ambiguity, disputes and review failures]
    E --> J[Offline source-reference scoring]
    G --> J
    G --> K[Fixed memory-policy replay]
    K --> J
    I --> L[Separate model-assisted sensitivity analysis]
    G --> L
```

model-assisted does not see the construction references or Bedrock predictions during annotation. Its two passes use the same model and can share errors. Source-reference agreement and model-assisted-reference sensitivity are reported separately; zero human annotations are claimed. The frozen parser receives neither reference during final inference.

## Comparators and execution

The seven response-bank policies are structural per-record inference, per-record inference with the matched name-convention gate, legacy V1/V2 caching, enriched-context support-one/support-three caching, and the proposed support-three policy with the development collision exclusion. Each order starts with empty memory.

Local comparators are a deterministic grammar, pretrained usaddress with the same declared person-name convention, and a CRF trained on 5,800 mapped development references. Its minimum-token-marginal threshold was selected on validation. A separate label-budget supplement uses validation only.

All main response-bank calls are actual paid provider requests. Policy replay records logical generations requested from those saved responses and makes zero extra provider calls. The separate paired live experiment measures fresh calls and actual parse latency on a declared 50-input recurrence workload.
