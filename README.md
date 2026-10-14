> **Accepted at EMNLP 2026 Findings** — *LintEval: Benchmarking LLMs on Linter-Guided File Refactoring*.

# LintEval: Linter-Guided Code Refactoring Benchmark

[![Dataset on HuggingFace](https://img.shields.io/badge/%F0%9F%A4%97%20Dataset-deepbreath7%2FLintEval-yellow)](https://huggingface.co/datasets/deepbreath7/LintEval)

**Can a model fix the warnings a linter reports without breaking the code?**

LintEval is a multi-language benchmark for *linter-guided refactoring*: each sample is a
compilable, test-passing competitive-programming submission together with the static-analysis
messages it triggers. A model must return a revised version that (1) removes or reduces those
messages and (2) still compiles and passes every generated unit test.

| Split | Samples | Problems | Languages | Alerts |
|---|---:|---:|---|---:|
| **LintEval-Full** (`full/`) | 13,061 | 3,999 | C++ / Python / Java | 171,662 |
| **LintEval-Lite** (`lite/`) | 498 | — | C++ (244) / Python (203) / Java (51) | stratified evaluation split |

Samples are derived from CodeContests+ (Codeforces problems) with testlib-based
generators/checkers, so correctness is verified by actually running the code.

The datasets are also published on HuggingFace:
**https://huggingface.co/datasets/deepbreath7/LintEval** — `lite`, `demo` and `full` configs
(JSONL + Parquet), together with the released per-sample results (`eval_results/`) and the
paper tables (`docs/table/`).

---

## Quickstart

```bash
git clone https://gh-proxy.com/https://github.com/6643789wsx/LintEval.git && cd LintEval
# or: git clone https://github.com/6643789wsx/LintEval.git && cd LintEval
bash scripts/setup.sh                   # venv + deps + tool check  (or: make setup)

# credentials for any OpenAI-compatible endpoint (PKU MaaS shown here)
export pku_maas_base_url=https://chat.pku.edu.cn/v1
export pku_maas_api_key=sk-...

python scripts/smoke_test.py            # 1 sample, full pipeline, ~30 s
```

`scripts/setup.sh` never needs root: it creates `.venv`, installs `requirements.txt`,
checks the system tools and prints ready-to-paste install commands for anything missing.
`requirements.txt` lists the supported dependency ranges; `requirements.lock.txt` pins the exact
versions that were verified end-to-end (clone → `make setup` → `make check/sanity/verify` →
`make smoke`). Use the lock file when you need a reproducible environment:

```bash
pip install -r requirements.lock.txt    # exact verified versions
```
Only `pylint` is required for the Python smoke; add `clang-tidy` (C++), PMD + `javac`
(Java) and `g++` when you evaluate those languages.

Common entry points (also available as `make <target>`):

| Command | What it does |
|---|---|
| `make setup` | create `.venv`, install deps, check tools |
| `make sanity` | end-to-end pipeline check, no API key needed (~1 min) |
| `make smoke` | one-sample end-to-end smoke test |
| `make demo LIMIT=10` | evaluate 10 samples of the demo split |
| `make eval-lite` | evaluate the 498-sample lite split |
| `make verify` | recompute the paper metrics from released per-sample results |
| `make tables` | regenerate `docs/table/*.tex` |
| `make help` | list all targets |

Real output of the smoke test:

```
sample_id=p00364_py3_0  problem=p00364  original linter messages=4
  API 1/1 (17s, ETA 0s)
Smoke test summary
  model            : smoke_gpt-6-luna
  samples          : 1
  compile + tests  : PASS
  tests generated  : 32
  linter messages  : 4 -> 1 (new: 1)
  pass@1           : 1.0
  MRR@P            : 0.75
SMOKE TEST PASSED
```

The smoke test runs *generation → code extraction → re-lint → compile → unit tests → metrics* on
one sample of `lite/linteval_lite.jsonl`. It reads its credentials from the environment, so no
key ever appears on the command line:

| Variable | Meaning | Default |
|---|---|---|
| `pku_maas_base_url` / `PKU_MAAS_BASE_URL` | OpenAI-compatible base URL | — |
| `pku_maas_api_key` / `PKU_MAAS_API_KEY` | API key | — |
| `pku_maas_model_name` / `PKU_MAAS_MODEL_NAME` | model id | `gpt-6-luna` |

`scripts/smoke_test.py --language java|cpp` switches language; `--model` overrides the model id.
`CUSTOM_API_KEY` / `CUSTOM_BASE_URL` / `CUSTOM_MODEL_ID` and `DEEPSEEK_API_KEY` are accepted too.

---

## Verified end-to-end runs

The pipeline in this repository was executed on the released data with both an API model and
local vLLM models. Two reproducible runs are worth quoting here because they cover all three
languages and the full metric stack:

| Run | Samples | Result |
|---|---|---|
| `scripts/smoke_test.py --language py3` | 1 | pipeline OK, 32 generated tests, alerts 4 → 1, Pass@1 = 100% |
| `scripts/10_eval_models.py --custom_api --model gpt-6-luna --data_path lite/demo_100.jsonl` | 100 | Pass@1 = **67.0%**, Reduction@P = 65.4%, LinePerFix@P = 6.4, 3,175 tests generated |
| `scripts/sanity_check.py` | demo subset | linters OK (C++ 95 / Python 3 / Java 35 alerts on the first demo records), testlib compile → 3/3 tests passed |

Per-language outcome of the 100-sample demo run (`gpt-6-luna`, greedy decoding):

| Language | Passed | Test failures | Compile failures |
|---|---:|---:|---:|
| C++ | 22 | 9 | 2 |
| Java | 28 | 4 | 1 |
| Python | 17 | 16 | 1 |

Every record keeps the raw model output, the extracted code, the number of generated/passed
tests, the alert counts before/after and the token usage, so the numbers can be audited
per sample.

---

## Data

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

### Loading

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

```bash
# rebuild the Parquet files and previews from the JSONL sources
python scripts/build_dataset_files.py
python scripts/build_dataset_files.py --check     # verify without writing
# merge the three full-dataset shards
python scripts/split_dataset.py --merge           # -> full/linteval_full.jsonl
```

### Record schema (26 fields)

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

---

## Evaluation

Everything is driven by `scripts/10_eval_models.py` (and the `scripts/smoke_test.py` wrapper).

### Hosted models (any OpenAI-compatible API)

```bash
# PKU MaaS with gpt-6-luna (default when PKU_MAAS_* are set)
export pku_maas_base_url=https://chat.pku.edu.cn/v1
export pku_maas_api_key=sk-...
python scripts/10_eval_models.py --custom_api --model gpt-6-luna \
    --data_path lite/linteval_lite.jsonl --limit 100

# DeepSeek
export DEEPSEEK_API_KEY=sk-...
python scripts/10_eval_models.py --deepseek --data_path lite/linteval_lite.jsonl

# any other OpenAI-compatible endpoint
python scripts/10_eval_models.py --custom_api \
    --base_url https://api.example.com/v1 --api_key sk-... \
    --api_model_id my-model --data_path lite/linteval_lite.jsonl
```

### Local models (vLLM)

```bash
python scripts/10_eval_models.py --model_name Qwen2.5-Coder-7B \
    --model_path /path/to/Qwen2.5-Coder-7B-Instruct \
    --data_path lite/linteval_lite.jsonl --gpu 0 --tp 1
```

### Full dataset (13,061 samples)

```bash
python scripts/split_dataset.py --merge                       # once
python scripts/10_eval_models.py --custom_api --model gpt-6-luna \
    --data_path full/linteval_full.jsonl                        # or full/linteval_full.parquet
```

### Key options

| Option | Meaning |
|---|---|
| `--custom_api` | evaluate any OpenAI-compatible endpoint |
| `--model` / `--api_model_id` | model id sent to the endpoint |
| `--data_path` | `.jsonl` **or** `.parquet`, any split |
| `--limit N`, `--n_workers N`, `--api_timeout S` | sample cap, concurrency, per-request timeout (default 300 s) |
| `--model_name` + `--model_path`, `--gpu`, `--tp` | local vLLM evaluation |
| `--deepseek` | DeepSeek via `DEEPSEEK_API_KEY` |
| `--no_message`, `--ablation_mode=...` | ablations (no alerts / rule-only / message-only / shuffled) |
| `--resume_failed` | re-run only API-generation failures of an existing result file |

Results are written to `eval_results/<model>.json`:

```json
{"model": "...", "total_entries": 498, "timestamp": "...",
 "summary": {"pass@1": 0.57, "avg_mrr_at_pass": 0.61, "new_msg_per_sample_at_pass": 0.70,
             "lpm_p": 5.95, "line_churn_at_pass": 0.99, "mrr_at_pass_by_category": {...}},
 "results": [{"sample_id": "...", "language": "cpp", "pass": true, "in_total": 6, "out_total": 2,
              "new_msg_count": 1, "mrr_at_pass": 1.0, "added_lines": 3, "deleted_lines": 2, ...}]}
```

### Metrics

Computed over samples that pass compile + tests:

| Metric | Definition |
|---|---|
| Pass@1 | fraction of samples whose revised code compiles and passes all generated tests |
| Reduction@P / MRR@P | Σ(in − out) / Σ(in) over passed samples |
| New@P | newly introduced alerts / alerts in the original code |
| ΔLine@P | average number of changed lines |
| LinePerFix@P | changed lines per alert fixed |

---

## Environment

Python ≥ 3.8 plus these system tools (each is found on `PATH` or via env vars
`CLANG_TIDY_BIN`, `PYLINT_BIN`, `PMD_BIN`, `JAVAC_BIN`, `GPP_BIN`, `TESTLIB_INCLUDE`):

| Language | Linter | Compiler/runtime |
|---|---|---|
| C++ | `clang-tidy` | `g++` |
| Python | `pylint` (installed by `requirements.txt`) | `python3` |
| Java | [PMD](https://pmd.github.io/) 7.x | `javac`, `java` |

```bash
source setup_env.sh              # exports tool paths + PYTHONPATH
python scripts/test_environment.py   # verifies packages, tools and repository layout
python scripts/sanity_check.py       # end-to-end pipeline check without any API call
```

The Python smoke needs only `pylint`; C++ smoke additionally needs `clang-tidy`.

---

## Reproducing the released numbers

`eval_results/*.json` contains the per-sample results behind the paper tables; regenerate them with

```bash
python scripts/11_gen_paper_excel.py     # -> docs/table/*.tex
```

### Metric consistency check

`scripts/verify_paper_metrics.py` recomputes Pass@1, Reduction@P, New@P, ΔLine@P and
LinePerFix@P **from the per-sample records only** and compares them with the values printed in
`docs/table/overall_performance.tex` (it can additionally regenerate every LaTeX table and
require a byte-identical match):

```bash
python scripts/verify_paper_metrics.py --check-tables
```

```
Model                            Pass@1      Reduction@P          New@P        DLine@P     LinePerFix@P
GPT-5.2                   67.1% / 67.1%    87.8% / 87.8%      7.3% / 7.3%      71.7 / 71.7        6.8 / 6.8
DeepSeek-v3.2             57.6% / 57.6%    73.0% / 73.0%      6.7% / 6.7%      45.4 / 45.4        5.5 / 5.5
Qwen2.5-Coder-32B         61.6% / 61.7%    57.1% / 57.1%      8.1% / 8.1%      33.3 / 33.3        5.7 / 5.7
...
RESULT: PASS - per-sample results reproduce every paper metric and the LaTeX tables.
```

The metric definitions used for the paper (identical to `scripts/gen_tab/_shared.py`) are:

| Metric | Formula (over the samples that pass compile + tests) |
|---|---|
| Reduction@P | `Σ(in − out) / Σ(in)` — corpus level, not a mean of per-sample ratios |
| New@P | `Σ(new alerts) / Σ(in)` |
| ΔLine@P | `Σ lines changed / n_passed` |
| LinePerFix@P | `Σ lines changed / Σ fixed`, `fixed = max(0, in − out + new)` |

`eval_results/*.json` stores every quantity these formulas need (`in_total`, `out_total`,
`new_msg_count`, `lpm_p_lines_changed`, `pass`), so metrics are always recomputable offline.

Reference revisions were produced with greedy decoding (temperature 0.0, max 4,096 tokens).
Linter versions slightly change diagnostics; the paper reports clang-tidy 22.1, PMD 7.12.0,
pylint 4.0.5, g++ 13.3/15.2, OpenJDK 21/23.

### Main results (LintEval-Lite, 498 samples)

| Model | Pass@1 ↑ | Reduction@P ↑ | New@P ↓ | ΔLine@P ↓ | LinePerFix@P ↓ |
|---|---|---|---|---|---|
| Copy-Original | 100.0% | 0.0% | 0.0% | 0.0 | — |
| Rule-Based Fixers | **76.3%** | 25.9% | **0.6%** | 71.4 | 20.4 |
| GPT-5.2 | 67.1% | 87.8% | 7.3% | 71.7 | 6.8 |
| GPT-5.4-mini | 68.3% | **90.4%** | 5.6% | 60.2 | **5.2** |
| DeepSeek-v3.2 | 57.6% | 73.0% | 6.7% | 45.4 | 5.5 |
| Qwen2.5-Coder-32B | 61.7% | 57.1% | 8.1% | 33.3 | 5.7 |
| Qwen2.5-Coder-7B | 53.0% | 24.7% | 12.7% | 32.5 | 8.9 |
| Qwen2.5-Coder-0.5B | 48.8% | −1.2% | 10.5% | **17.2** | 21.5 |
| Llama-3.2-1B | 33.7% | 0.5% | 13.8% | 23.5 | 19.6 |

---

## Publishing the datasets to the Hugging Face Hub

```bash
pip install -U huggingface_hub
huggingface-cli login

# two dataset repositories, mirroring the folder layout
huggingface-cli upload <user>/LintEval-full full/ --repo-type dataset
huggingface-cli upload <user>/LintEval-lite lite/ --repo-type dataset
```

Every file is already Hub-ready: Parquet for `load_dataset("<user>/LintEval-lite")`, JSONL for
streaming consumers, `preview.json` for quick inspection.

---

## Repository layout

```
├── README.md                  this file
├── CHANGELOG.md               release history
├── Makefile                   one-command entry points
├── LICENSE                    MIT
├── requirements.txt
├── setup_env.sh               tool paths + PYTHONPATH
├── scripts/setup.sh           one-command environment setup
├── configs/                   linter and dataset configuration
├── src/                       linter wrappers, testlib runner, metrics, prompts
├── scripts/
│   ├── smoke_test.py          ★ one-command end-to-end check (PKU MaaS / gpt-6-luna)
│   ├── 10_eval_models.py      ★ main evaluator (API + vLLM)
│   ├── build_dataset_files.py regenerate Parquet + preview.json
│   ├── split_dataset.py       split/merge the full JSONL
│   ├── test_environment.py    environment check
│   ├── sanity_check.py        pipeline check without API
│   ├── verify_paper_metrics.py recompute paper metrics from per-sample results
│   ├── 11_gen_paper_excel.py  regenerate LaTeX tables
│   └── 01…05_*.py             optional dataset-construction pipeline
├── tools/testlib.h            required for C++ generator/checker compilation
├── full/  lite/               released datasets (Parquet + JSONL + preview)
├── eval_results/              released per-sample results
└── docs/table/                generated LaTeX tables
```

---

## License and data provenance

Code is MIT licensed ([LICENSE](LICENSE)). The benchmark data derives from
[CodeContests+](https://github.com/deepmind/code_contests) (based on Codeforces problems) and is
released for research purposes; please cite CodeContests alongside LintEval. The reference
revisions were generated by DeepSeek-v3.2 through an OpenAI-compatible API.

## Citation

```bibtex
@inproceedings{linteval2026,
  title     = {LintEval: Linter-Guided Code Refactoring Benchmark},
  author    = {Anonymous, EMNLP 2026},
  booktitle = {Proceedings of the 2026 Conference on Empirical Methods in Natural Language Processing},
  year      = {2026}
}
```

We will update this entry with the final venue, authors, and DOI after acceptance.
