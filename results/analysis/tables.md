# Final construction-reference results

All rows use the same 10,000 final inputs. These are source/construction-reference agreements; human annotations: zero.

| Model | Method | Accepted | Exact records | Accepted error | Logical generations |
| --- | --- | ---: | ---: | ---: | ---: |
| nova | per_record_structural | 8704 | 8475 | 2.63% | 9900 |
| nova | per_record_context_gate | 8505 | 8475 | 0.35% | 9700 |
| nova | legacy_v1 | 8447 | 7610 | 9.91% | 1809 |
| nova | legacy_v2 | 8447 | 7610 | 9.91% | 1809 |
| nova | context_support1 | 9042 | 9021 | 0.23% | 2217 |
| nova | context_support3 | 8664 | 8645 | 0.22% | 4236 |
| nova | proposed | 8664 | 8646 | 0.21% | 4329 |
| haiku45 | per_record_structural | 9284 | 9016 | 2.89% | 9900 |
| haiku45 | per_record_context_gate | 9090 | 9016 | 0.81% | 9700 |
| haiku45 | legacy_v1 | 8480 | 7763 | 8.46% | 1771 |
| haiku45 | legacy_v2 | 8478 | 7791 | 8.10% | 1773 |
| haiku45 | context_support1 | 9419 | 9350 | 0.73% | 1992 |
| haiku45 | context_support3 | 9216 | 9168 | 0.52% | 4114 |
| haiku45 | proposed | 9216 | 9168 | 0.52% | 4207 |
| local | grammar | 9581 | 9455 | 1.32% | 0 |
| local | usaddress_composite | 8792 | 8740 | 0.59% | 0 |
| local | crf | 9591 | 9574 | 0.18% | 0 |

Logical generations are policy requests in replay, not additional provider calls. The stored response banks incurred their separately reported actual generation costs. Local CRF uses 5,800 construction-labeled development records; its supervision differs from LLM-only discovery.
