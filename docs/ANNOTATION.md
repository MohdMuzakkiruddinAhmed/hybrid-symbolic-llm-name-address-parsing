# Model assisted annotation audit

Primary evaluation labels come from construction fields or preserved external address components. They are not human annotations. The audit is a separately reported alternative-reference sensitivity analysis.

## Realized method

- Review model: configured `gpt-6.1-sol`; scaled passes use medium reasoning.
- Development pilot: 50 inputs, two fresh passes. Prompt clarification was restricted to development; the final method was fixed before final evaluation.
- Final selection: 1,000 D2 inputs selected by a fixed hash and all 1,000 final D3 inputs. Each input receives two reviews in fresh input-only sessions, with 100-input batches.
- Review input: raw string, zero-based tokens, locale, declared name convention and opaque temporary IDs. Construction/source labels, family/source groups, evaluated Bedrock answers and the other pass's answers are not supplied.
- Review output: mapped/ambiguous/unsupported/insufficient status, compact token-field labels, admissible alternatives and notes. Invalid outputs remain failures; construction answers are never used to fill them.
- Reconciliation: identical mapped outputs form consensus. Disputed or ambiguous inputs do not receive an invented unique mapping. Original source/construction labels remain unchanged.

The released asset retains both pass outputs, original input-only prompts, output schemas, raw model answers, selections and neutral batch metadata under `annotation/model-assisted-v2/`. Session-specific identifiers and local launcher/authentication logs are excluded. The exposed method does not depend on a particular command-line interface.

Run `python scripts/reconcile_model_reviews.py final_audit` to reproduce the consensus summary from the two released passes. Prompt/schema files can be used to conduct a new review through an independently selected model interface; a new model/interface run is a new annotation experiment rather than an exact repeat of the stored outputs.

## Final audit outcomes

There are 2,000 valid review pairs: 1,442 identical mapped, 324 consensus ambiguous, 34 disputed, 100 unsupported and 100 insufficient. Status agreement is 1,966/2,000 = 98.3%. Human annotations: zero. The same model's fresh passes are correlated and can share systematic errors; agreement is not inter-human reliability or a semantic correctness guarantee.

The source/construction and model-assisted references differ on 158 audited rows. The conservative sensitivity analysis requires abstention on ambiguous/disputed inputs and reports its denominators separately. Review outcomes did not tune the frozen predictive code.
