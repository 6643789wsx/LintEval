# Changelog

## 2026-10-14 — release layout v2 (reproducibility release)

**Repository restructure**

* Datasets moved from `data/` into two explicit folders:
  * `full/` — `linteval_full.parquet` (26 MB), `linteval_full.jsonl.part{1,2,3}` (78 MB each),
    `preview.json`
  * `lite/` — `linteval_lite.parquet` (1.9 MB), `linteval_lite.jsonl`, `demo_100.jsonl`,
    `preview.json`
* `preview.json` per split: three complete records (one per language) for schema inspection
  without downloading the data.
* `scripts/build_dataset_files.py` regenerates the Parquet files and previews from JSONL and can
  verify them (`--check`).
* README rewritten around a one-command smoke test.

**Fixes**

* `load_test_data()` no longer filters records by the per-record `split` field. That field
  describes the *problem-level* construction split, and filtering on it silently reduced
  LintEval-Lite from **498 to 68 samples** for the released file name. The released evaluation
  results were produced with 498 samples, so this restores the documented behaviour; the legacy
  filter is now applied only to raw, not-yet-split sources and reports how many records it drops.
* `scripts/smoke_test.py`: credentials are passed to the child process through the environment
  instead of the command line (they no longer appear in process listings or logs), and the key is
  masked in the printed summary.
* The evaluator API layer now tries `max_tokens` and falls back to `max_completion_tokens` (or
  vice versa) when an endpoint rejects the parameter, and the default `--api_timeout` is 300 s so
  slow endpoints such as PKU MaaS do not time out.
* `--model` is accepted as an alias of `--api_model_id`; `pku_maas_base_url`, `pku_maas_api_key`
  and `pku_maas_model_name` (upper- or lowercase) are read as defaults, with `gpt-6-luna` as the
  model id when none is given.
* `test_environment.py`, `sanity_check.py` and `split_dataset.py` updated to the new data paths.

**Additions**

* Python-parquet support in the evaluator (`--data_path … .parquet`).
* `requirements.txt` now lists every runtime dependency of the evaluation path
  (`requests`, `datasets`, `pyarrow`, …).

**Additions (this run)**

* `scripts/setup.sh` — one-command environment setup (local virtualenv, dependency install,
  system-tool check with ready-to-paste install hints). No root required.
* `Makefile` — `make setup / sanity / smoke / demo / eval-lite / verify / tables / help`.
* `scripts/verify_paper_metrics.py` — recomputes Pass@1, Reduction@P, New@P, ΔLine@P and
  LinePerFix@P from the released per-sample results and compares them with
  `docs/table/overall_performance.tex`; `--check-tables` additionally requires the LaTeX tables
  to regenerate byte-identically. Verified on all nine released models.
* README: setup/demo instructions, Make targets, metric-formula table (including the fact that
  Reduction@P is a corpus-level ratio and LinePerFix@P uses the count-based fixed-message count).

**Fixes (this run)**

* `_atomic_write_json()` is now thread-safe (unique temporary file per writer + a lock around
  the rename). Under six API workers the shared `.tmp` name made concurrent cache writes race,
  producing spurious ``FileNotFoundError`` retries and silently dropping cache entries, which
  would break resume-after-failure.
* `scripts/smoke_test.py` now distinguishes "pipeline completed" from "the model passed the
  tests"; a sample whose revision fails the unit tests is reported as a valid model result
  instead of a smoke-test failure.

**Verified end-to-end on this machine**

* `scripts/sanity_check.py`: C++/Python/Java linters and the testlib loop (3/3 tests passed).
* `scripts/smoke_test.py`: PKU MaaS `gpt-6-luna`, 1 sample, 32 generated tests, alerts 4 -> 1.
* `scripts/10_eval_models.py --data_path lite/demo_100.jsonl`: PKU MaaS `gpt-6-luna` on all 100
  demo samples -> Pass@1 67.0%, Reduction@P 65.4%, LinePerFix@P 6.4, 3,175 tests generated;
  result kept as `eval_results/demo_gpt-6-luna.json`.
* `scripts/verify_paper_metrics.py --check-tables`: all nine released models reproduce the
  paper metrics from per-sample data and `docs/table/*.tex` regenerate byte-identically.
* `bash scripts/setup.sh` then `./.venv/bin/python scripts/smoke_test.py`: a brand-new virtualenv
  runs the smoke test without further setup.

## 2026-08-21 — Initial LintEval benchmark release (`41988cd`)

First public release: 498-sample Lite split, 13,061-sample Full split (three JSONL shards),
linter wrappers, testlib validation loop, metrics, released per-sample results and paper tables.
Backed up on this machine as tag `backup-pre-reorg-20261014` plus
`LintEval_41988cd_20261014.tar.gz`.
