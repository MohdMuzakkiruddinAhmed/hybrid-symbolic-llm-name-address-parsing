# Reproducing the released study

## Environment and data

Use Python 3.12 or 3.13. The executed environment was Python 3.13.5; exact packages are pinned in `requirements-research.txt` and recorded in `results/research_environment.json`. Install optional packages in an isolated environment. Core tests require no external packages or credentials.

```sh
python scripts/restore_artifacts.py --dataset-only
python -m unittest discover -s tests -q
python scripts/verify_release.py --dataset-only
```

Archive SHA-256 hashes are checked before extraction, paths are bounded to the repository, and corpus checksums are verified afterwards. Source snapshots include NC OneMap metadata, source IDs, selected attributes, exact queries and terms. `python scripts/build_corpus.py` checks deterministic corpus reproduction using these snapshots.

## Stored LLM outputs

Download the results asset from the same GitHub release as the source. Place it in `artifacts/` or pass its path explicitly:

```sh
python scripts/restore_artifacts.py --results /path/to/llm-results-v0.5.0.zip
python -m pip install -r requirements-research.txt
python scripts/reproduce.py --replay
```

`--replay` re-evaluates seven policies across two response banks, one fixed 10,000-input order and four 2,000-input regimes with five seeds. It regenerates 294 policy evaluations. Omit that option to analyze the released policy outputs directly. Replay makes no model calls and is not live latency. Per-record primary scores, field-value metrics, paired 2,000-replicate cluster intervals, harmful reuse, representation collisions, model-assisted sensitivity and figures are written under `results/analysis/`.

The stored stronger-model check uses the same 250 inputs for all three backbones. Repeated-generation and paired live follow-ups were selected before their fresh outputs. Their saved artifacts reproduce their reported summaries; analysis does not call the services again.

## Native baselines

Saved grammar, address-parser composite and CRF predictions are included in the results asset. CRF weights are not distributed as a pickle; `python scripts/run_local_baselines.py --split validation` retrains from the 5,800 mapped development references and reselects the validation threshold. Exact recorded parameters and package versions are supplied. Running the final baseline afterwards requires the recorded training/feature hashes to match. Its supervision budget differs from LLM discovery.

## New paid inference

The runtime config disables all live models by default. The original profiles and generation arguments remain documented in `configs/bedrock_runtime.json` and saved bank manifests. A new paid run requires the account owner's AWS access, current verified prices and a separately controlled budget. `bedrock_preflight.py` followed by `verify_claude_rates.py` performs the documented access/rate checks without creating agreements or managed cloud resources. It must not be confused with offline reproduction.

The response-bank asset contains aggregate files, not thousands of per-record cache files. Use the offline scripts to reproduce results. Treat new generations as a new study/version; do not mix them with the published bank or silently tune the frozen parser on final outcomes. Unknown request charges remain reserved, and automatic SDK retries remain disabled.

On the original Windows environment, WMI-based OS-version detection could stall SDK initialization. `scripts/run_without_wmi.py` selects Python's existing OS-version fallback for that process only; it does not modify system settings or predictive code. The provided offline reproduction wrapper already uses it.
