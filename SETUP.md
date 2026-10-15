# Setup and running LintEval

Environment installation, dependencies, credentials and the commands used to run the benchmark.
The data format is documented in [docs/DATA.md](docs/DATA.md); metrics and the reproduction of the
released numbers in [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Quickstart

```bash
git clone https://github.com/6643789wsx/LintEval.git && cd LintEval
bash scripts/setup.sh                   # venv + deps + tool check  (or: make setup)

# credentials for any OpenAI-compatible endpoint (PKU MaaS shown as an example)
export pku_maas_base_url=https://chat.pku.edu.cn/v1
export pku_maas_api_key=sk-...

python scripts/smoke_test.py            # 1 sample, full pipeline, ~30 s
```

If `github.com` is unreachable from your network, the same repository is mirrored at
`https://gh-proxy.com/https://github.com/6643789wsx/LintEval.git`.

`scripts/setup.sh` never needs root: it creates `.venv`, installs `requirements.txt`, checks the
system tools and prints ready-to-paste install commands for anything missing.
`requirements.txt` lists the supported dependency ranges; `requirements.lock.txt` pins the exact
versions that were verified end-to-end (clone → `make setup` → `make check/sanity/verify` →
`make smoke`). Use the lock file when you need a reproducible environment:

```bash
pip install -r requirements.lock.txt    # exact verified versions
```

Only `pylint` is required for the Python smoke; add `clang-tidy` (C++), PMD + `javac` (Java) and
`g++` when you evaluate those languages.

## Commands (also available as `make <target>`)

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

## Smoke test

Real output of `python scripts/smoke_test.py`:

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

## Environment

Python ≥ 3.8 plus these system tools (each is found on `PATH` or via env vars
`CLANG_TIDY_BIN`, `PYLINT_BIN`, `PMD_BIN`, `JAVAC_BIN`, `GPP_BIN`, `TESTLIB_INCLUDE`):

| Language | Linter | Compiler/runtime |
|---|---|---|
| C++ | `clang-tidy` | `g++` |
| Python | `pylint` (installed by `requirements.txt`) | `python3` |
| Java | [PMD](https://pmd.github.io/) 7.x | `javac`, `java` |

```bash
source setup_env.sh                  # exports tool paths + PYTHONPATH
python scripts/test_environment.py   # verifies packages, tools and repository layout
python scripts/sanity_check.py       # end-to-end pipeline check without any API call
```

The Python smoke needs only `pylint`; the C++ smoke additionally needs `clang-tidy`.

## Running the evaluation

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

Results are written to `eval_results/<model>.json`; the file format and the released results are
described in [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Repository layout

```
├── README.md                  paper landing page
├── SETUP.md                   this file
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

## Maintainers: publishing to the Hugging Face Hub

The datasets are published as the single dataset repository
[`deepbreath7/LintEval`](https://huggingface.co/datasets/deepbreath7/LintEval), which mirrors this
folder layout (`lite/`, `demo`, `full/`, `eval_results/`, `docs/table/`):

```bash
pip install -U huggingface_hub
huggingface-cli login
huggingface-cli upload deepbreath7/LintEval . --repo-type dataset
```

Every file is already Hub-ready: Parquet for `load_dataset("deepbreath7/LintEval", ...)` and JSONL
for streaming consumers.
