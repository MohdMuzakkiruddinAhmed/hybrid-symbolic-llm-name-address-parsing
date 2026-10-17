# Publication release v0.5.1

Packaging patch: install the recorded `botocore==1.42.73` dependency before running mocked Bedrock adapter tests in clean environments. CI and quick-start instructions include this step. The frozen protocol v0.5.0 predictive implementation, corpus and LLM result archives remain unchanged. The original v0.5.0 tag and assets remain available.

Reproducibility companion for **A Hybrid Symbolic–LLM Framework for Adaptive Name and Address Parsing through Token-Mask Knowledge Acquisition and Deterministic Reuse**, by Adeeba Tarannum, Muzakkiruddin Ahmed Mohammed, Shames Al Mandalawi, and John R. Talburt, ERIQ, University of Arkansas at Little Rock.

Original project code and documentation are MIT licensed. AddressNC source components retain their own public-use terms and attribution; see `THIRD_PARTY_NOTICES.md`.

Download `llm-results-v0.5.0.zip` into `artifacts/` and follow the README to restore and reproduce results without new model calls. `adaptive-parsing-research-v0.5.1.zip` is the checksummed source distribution and includes the corpus archive. `SHA256SUMS.txt` records the two distribution archive digests.

- Exact frozen parser, validation, memory, replay and baseline implementation.
- 20,000 distinct inputs and source provenance; 6,000/4,000/10,000 development/validation/final split.
- Two 10,000-input final LLM banks and a matched 250-input Sonnet check, with development/validation outputs.
- Three local baselines, 294 policy evaluations, repeated generations and actual paired live measurements.
- Two-pass model-assisted review of 2,000 final audit inputs; zero human labels and unresolved disagreements retained.
- Analysis, figures, 47 core tests, an offline CI workflow and checksummed archives.

The supervised CRF has the strongest observed aggregate coverage/error operating point. Adaptive reuse reduces replay discovery requests by 55–57% relative to matched per-record parsing. Long-tail savings are about 2%; this release does not establish production savings or general semantic safety.

Dataset archive SHA-256: `ceae91d1ebaa44fa71a278ee4a48727fa002a22a6a8a4938b2b5b7c6918dcbe0`

Results asset SHA-256: `66167654e45822992e722c3e2b53aa2d5a21c807f029128010d644557517bd38`

Historical AWS usage/rate estimate: $30.521921, including retained unknown reservations. Annotation-engine usage is separate; estimates are not an AWS invoice.
