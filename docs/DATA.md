# Data

The released datasets, their file layout, record schema and loading instructions. Running the
benchmark is documented in [SETUP.md](../SETUP.md); metrics and paper results in
[REPRODUCE.md](REPRODUCE.md).

## Splits

| Split | Samples | Problems | Languages | Alerts |
|---|---:|---:|---|---:|
| **LintEval-Full** (`full/`) | 13,061 | 3,999 | C++ / Python / Java | 171,662 |
| **LintEval-Lite** (`lite/`) | 498 | — | C++ (244) / Python (203) / Java (51) | stratified evaluation split |

LintEval is a multi-language benchmark for *linter-guided refactoring*: each sample is a
compilable, test-passing competitive-programming submission together with the static-analysis
messages it triggers. A model must return a revised version that (1) removes or reduces those
messages and (2) still compiles and passes every generated unit test.

Samples are derived from CodeContests+ (Codeforces problems) with testlib-based
generators/checkers, so correctness is verified by actually running the code.

The datasets are also published on HuggingFace:
**https://huggingface.co/datasets/deepbreath7/LintEval** — `lite`, `demo` and `full` configs
(JSONL + Parquet), together with the released per-sample results (`eval_results/`) and the
paper tables (`docs/table/`).

## Files

```
full/
├── linteval_full.parquet        # 26 MB  – 13,061 samples (recommended)
├── linteval_full.jsonl.part1    # 78 MB  ┐ three line-aligned shards, each < GitHub's
├── linteval_full.jsonl.part2    # 78 MB  ├ 100 MB per-file limit; concatenate to get
├── linteval_full.jsonl.part3    # 78 MB  ┘ a single linteval_full.jsonl (233 MB)
└── preview.json                 # 3 full records (one per language)
lite/
├── linteval_lite.parquet        # 1.9 MB – 498 samples
├── linteval_lite.jsonl          # 11 MB
├── demo_100.jsonl               # 100-sample stratified demo (quick experiments)
└── preview.json                 # 3 full records (one per language)
```

`preview.json` lets you inspect the schema (including the nested linter messages and test
harness code) without downloading anything.

## Loading

```python
# Parquet (recommended)
from datasets import load_dataset
full = load_dataset("parquet", data_files="full/linteval_full.parquet", split="train")
lite = load_dataset("parquet", data_files="lite/linteval_lite.parquet", split="train")

# or pandas / plain JSONL
import pandas as pd, json
df = pd.read_parquet("lite/linteval_lite.parquet")
records = [json.loads(l) for l in open("lite/linteval_lite.jsonl", encoding="utf-8")]
```

```python
# directly from the Hugging Face Hub
from datasets import load_dataset
lite = load_dataset("deepbreath7/LintEval", "lite", split="train")
demo = load_dataset("deepbreath7/LintEval", "demo", split="train")
full = load_dataset("deepbreath7/LintEval", "full", split="train")        # or streaming=True
```

```bash
# rebuild the Parquet files and previews from the JSONL sources
python scripts/build_dataset_files.py
python scripts/build_dataset_files.py --check     # verify without writing
# merge the three full-dataset shards
python scripts/split_dataset.py --merge           # -> full/linteval_full.jsonl
```

## Record schema (26 fields)

| Field | Type | Description |
|---|---|---|
| `sample_id` | str | unique id, e.g. `p00364_py3_0` |
| `problem_id` | str | source problem id |
| `language` | str | `cpp` \| `py3` \| `java` |
| `code` | str | the original submission (**input**) |
| `linter_messages` | list[dict] | alerts for `code`: `tool`, `line`, `column`, `severity`, `message`, `check`/`rule` |
| `linter_message_count` | int | number of alerts for `code` |
| `original_loc` | int | lines of code |
| `compile_ok` | bool | `code` compiles |
| `source`, `title` | str | provenance (Codeforces) |
| `generator`, `generator_cmd`, `checker`, `validator` | str | testlib harness; `generator_cmd` are the generator invocations |
| `revised_code`, `raw_response`, `tokens_used` | str/str/int | **reference revision** produced by DeepSeek-v3.2 and its raw response |
| `error`, `extraction_ok`, `revision_error` | misc | reference-revision diagnostics |
| `pass_at_1`, `validation_error` | bool/misc | reference revision passed compile + tests |
| `original_messages`, `revised_messages` | list[dict] | alerts before/after the reference revision |
| `metrics` | dict | reference-revision metrics (MRR, new messages, line churn, per-category counts) |
| `split` | str | **problem-level** construction split of the source problem (`train`/`valid`/`test`) |

Two notes on the released files:

* `split` is provenance for the *problem*, **not** the evaluation split. Every record of the file
  you pass is evaluated; never filter on this field (see `CHANGELOG.md`).
* Nested fields are stored with a unified Arrow schema, so a key that is absent for a given record
  (e.g. a linter category with no alerts) appears as `null` in Parquet. Values are unchanged.

The reference revision fields (`revised_code`, `metrics`, …) are provided for analysis and for the
baselines reported in the paper; a model submission is **never** given them at inference time.

## License and data provenance

Code is MIT licensed ([LICENSE](../LICENSE)). The benchmark data derives from
[CodeContests+](https://github.com/deepmind/code_contests) (based on Codeforces problems) and is
released for research purposes; please cite CodeContests alongside LintEval. The reference
revisions were generated by DeepSeek-v3.2 through an OpenAI-compatible API.
