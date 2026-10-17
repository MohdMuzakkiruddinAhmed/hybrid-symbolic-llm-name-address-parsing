# Paper and artifact guide

**A Hybrid Symbolic–LLM Framework for Adaptive Name and Address Parsing through Token-Mask Knowledge Acquisition and Deterministic Reuse**

Adeeba Tarannum, Muzakkiruddin Ahmed Mohammed, Shames Al Mandalawi, and John R. Talburt

Center for Advanced Research in Entity Resolution and Information Quality (ERIQ), University of Arkansas at Little Rock, Little Rock, AR 72204, USA

## Research question

Can a parser acquire token-position mappings from an LLM, admit them under symbolic constraints and reuse them deterministically while measuring both avoided inference and incorrect reuse? The implemented framework treats the model output as a proposal. Reuse requires structural validation, declared source context, three distinct supporting inputs and conflict handling. A matching signature remains a heuristic rather than proof of semantic equivalence.

## Implemented system

The [architecture](system_architecture.md) describes input gates, token spans, overlapping token clues, context signatures, model discovery, validators, provisional memory, promotion and quarantine. The implementation and frozen checksums are in `src/adaptive_parser/` and `configs/experiment_protocol.json`. The legacy 30-record reference is retained in `legacy/pilot_reference.py` to support the pilot regression checks.

## Evaluation evidence

The corpus contains 20,000 distinct records: 10,000 controlled inputs, 6,000 North Carolina addresses paired with fictional people, 2,000 safety/ambiguity inputs and 2,000 known-family inputs with fresh lexical content. Development, validation and final partitions contain 6,000, 4,000 and 10,000 records. [Dataset coverage](dataset_coverage.md) explains construction, source geography, layout grouping and reference limitations.

Saved Amazon Bedrock response banks support matched policy replay for Amazon Nova 2 Lite and Claude Haiku 4.5, with a 250-record Claude Sonnet comparison. Seven policies per backbone, fixed stream conditions, three local baselines, repeated generations and a separate 50-record live recurrence follow-up are supplied. The results asset preserves model text, token usage and predictions; [reproduction instructions](REPRODUCING.md) explain how to restore it and regenerate the analysis without provider calls.

Proposed-policy replay discovery requests fall by 55.37% for Nova and 56.63% for Haiku against matched context-gated per-record parsing. On the 10,000 final inputs, Nova accepts 8,664 records with 8,646 exact source-reference matches; Haiku accepts 9,216 with 9,168 exact matches. The supervised CRF accepts 9,591 with 9,574 exact matches, the strongest aggregate coverage/error operating point among the supplied methods. See the [complete results](../results/analysis/tables.md).

## Reference and claim boundaries

Primary references come from construction and source components. A separate two-pass model-assisted audit covers 2,000 final inputs; the human annotation count is zero. Its 98.3% status agreement is agreement between model-assisted passes. Disputes, ambiguity and review failures remain explicit. [Annotation documentation](ANNOTATION.md) records the review model and method.

Five harmful memory reuse events occur per proposed-policy backbone. Recurrence savings approach 99% in the engineered recurring regime and about 2% in the long tail. The study does not establish universally safe reuse, arbitrary name disambiguation, production savings or superiority to supervised extraction. External address coverage is limited to one state and aggregation service. These boundaries are part of interpreting the released evidence.

## Publication scope

This software release supplies reproducibility artifacts, citation metadata and an MIT license for original project material. Third-party address components and dependencies retain their own terms in [third-party notices](../THIRD_PARTY_NOTICES.md). No journal acceptance, manuscript DOI or public preregistration is claimed. The original manuscript and editorial conversation are not bundled as a publication-ready paper.
