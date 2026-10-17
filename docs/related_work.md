# Related work and claim boundary

Checked against primary research/project sources on 2026-10-16. This is a targeted positioning review, not a systematic literature review.

| Work | Relevant established idea | Position of this study |
| --- | --- | --- |
| [EVAPORATE: Language Models Enable Simple Systems for Generating Structured Views of Heterogeneous Data Lakes](https://arxiv.org/abs/2304.09433) | LLM direct extraction and synthesized extraction functions have a cost/quality trade-off; candidate functions can be combined with weak supervision. | Reusable LLM extraction logic is established prior work. Our experiments isolate admission, coarse-key collisions and propagation in token-position rules. |
| [CACHE-ED2](https://www.amazon.science/publications/cache-ed2-compiling-llm-reasoning-into-reusable-extraction-programs-for-document-extraction-at-scale) | A document agent produces reusable extraction DSL programs, routes later documents to them, and incorporates analyst feedback. | General program caching and deterministic reuse are not claimed as new. Our scope is flat person/address strings and explicit admission/reuse diagnostics, without human feedback. |
| [Scout: Scalable Document Extraction via Data Similarity](https://arxiv.org/abs/2608.08261) | Document similarity and reusable extraction rules support scalable extraction. | Representation and routing costs belong in the comparison. This study measures failure when a compressed signature loses distinctions required by reference mappings. |
| [Selective Classification for Deep Neural Networks](https://arxiv.org/abs/1705.08500) | A classifier may abstain to trade coverage against error. | Report accepted error together with coverage. A low error rate obtained by rejecting many inputs is not automatically a better system. |
| [An Introduction to Conditional Random Fields](https://arxiv.org/abs/1011.4088) | Conditional sequence models provide a principled local tagging comparator. | Train a CRF only on development references and select its confidence threshold on validation; report its different supervision budget. |
| [DataMade usaddress](https://github.com/datamade/usaddress) | A maintained parser tags U.S. postal address components. | Evaluate the native address tagger with an explicitly documented person-name convention adapter; do not imply native arbitrary person-name parsing. |

The defensible contribution is a reproducible computational comparison of representation, admission, promotion and recurrence, including negative results and reference ambiguity. A broad claim to invent LLM-generated reusable extraction programs is unsupported by this review.

The corpus has 20,000 distinct inputs, but its controlled field sequences share 50 related address layouts, its external addresses come from one state/service, and its joint names are fictional. model-assisted review is correlated model-assisted evidence. These design facts restrict conclusions about operational distributions, linguistic generality, independent annotation and universal safety.

The trained local tagger is a substantive comparator. If it offers better coverage or reference agreement at zero cloud-inference cost, the manuscript must report that result and distinguish its 5,800 construction-labeled training records from discovery without supplied labels. The validation-only label-budget supplement is exploratory; it must not replace the frozen final baseline.
