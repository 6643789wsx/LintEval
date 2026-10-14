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

## 2026-08-21 — Initial LintEval benchmark release (`41988cd`)

First public release: 498-sample Lite split, 13,061-sample Full split (three JSONL shards),
linter wrappers, testlib validation loop, metrics, released per-sample results and paper tables.
Backed up on this machine as tag `backup-pre-reorg-20261014` plus
`LintEval_41988cd_20261014.tar.gz`.
