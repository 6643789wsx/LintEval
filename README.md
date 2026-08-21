# LintEval: Linter-Guided Code Refactoring Benchmark

LintEval is a multi-language benchmark for evaluating whether large language models (LLMs) can **refactor code based on linter feedback while preserving functionality**.

**LintEval-Full**: 13,061 samples across C++ / Python / Java (3,999 problems, 171,662 lint alerts).
**LintEval-Lite**: a stratified 498-sample split used for model evaluation.

## What problem does this repository solve?

Static-analysis linters (clang-tidy, pylint, PMD) detect code-quality issues, but it is unclear whether LLMs can *act* on their alerts without breaking the code. Existing benchmarks measure code generation or repair, not *linter-guided refactoring* with functional verification.

LintEval asks a model to take original code + its linter messages, and produce a revised version that (1) removes or reduces the reported alerts and (2) still passes all unit tests.

## How does it work?

Each sample is a competitive-programming submission (from CodeContests+, based on Codeforces) that:

- compiles and passes all tests,
- carries at least one linter alert from one of five categories (error-prone, performance, refactor, style, other).

Evaluation of a model output is a three-step pipeline:

1. **Compile + test** — the revised code must compile (g++/javac/python3) and pass the generated unit tests, validated with a testlib-based generator/checker loop (`pass@1`).
2. **Re-lint** — the revised code is scanned again; the change in linter messages is measured.
3. **Metrics** — aggregated over passing samples only:

| Metric | Definition |
|---|---|
| Pass@1 | fraction of samples whose revised code passes all tests |
| Reduction@P | Σ(in − out) / Σ(in) over passed samples |
| New@P | Σ(newly introduced alerts) / Σ(in) over passed samples |
| ΔLine@P | average lines changed over passed samples |
| LinePerFix@P | Σ(lines changed) / Σ(alerts fixed) over passed samples |

## Main results (LintEval-Lite, 498 samples)

| Model | Pass@1 ↑ | Reduction@P ↑ | New@P ↓ | ΔLine@P ↓ | LinePerFix@P ↓ |
|---|---|---|---|---|---|
| Copy-Original | 100.0% | 0.0% | 0.0% | 0.0 | -- |
| Rule-Based Fixers | **76.3%** | 25.9% | **0.6%** | 71.4 | 20.4 |
| GPT-5.2 | 67.1% | 87.8% | 7.3% | 71.7 | 6.8 |
| GPT-5.4-mini | 68.3% | **90.4%** | 5.6% | 60.2 | **5.2** |
| DeepSeek-v3.2 | 57.6% | 73.0% | 6.7% | 45.4 | 5.5 |
| Qwen2.5-Coder-32B | 61.7% | 57.1% | 8.1% | 33.3 | 5.7 |
| Qwen2.5-Coder-7B | 53.0% | 24.7% | 12.7% | 32.5 | 8.9 |
| Qwen2.5-Coder-3B | 52.0% | 9.5% | 11.2% | 27.9 | 15.0 |
| Qwen2.5-Coder-0.5B | 48.8% | −1.2% | 10.5% | **17.2** | 21.5 |
| Llama-3.2-3B | 38.8% | 19.8% | 13.5% | 29.8 | 11.0 |
| Llama-3.2-1B | 33.7% | 0.5% | 13.8% | 23.5 | 19.6 |

Findings: large API models remove most alerts without breaking tests; smaller open models trade correctness for alert reduction, and can introduce new alerts (negative reduction).

All released per-sample results are in [`eval_results/`](eval_results/), and the paper tables are in [`docs/table/`](docs/table/). Run `python scripts/11_gen_paper_excel.py` to regenerate them.

## Repository structure

```
.
├── README.md                 # this file
├── setup_env.sh              # environment setup (auto-detects repo root)
├── requirements.txt          # Python dependencies
├── configs/                  # linter & dataset configuration (YAML)
├── src/                      # core library
│   ├── linter_{cpp,python,java}.py   # clang-tidy / pylint / PMD wrappers
│   ├── linter_factory.py     # unified linter dispatch
│   ├── test_runner_{cpp,multi}.py    # testlib compile + test validation loop
│   └── metrics.py            # Pass@1, Reduction@P, New@P, ΔLine@P, LinePerFix@P
├── scripts/
│   ├── test_environment.py   # verify environment
│   ├── sanity_check.py       # quick end-to-end check on demo_100
│   ├── 10_eval_models.py     # ★ main evaluation script (local vLLM / API)
│   ├── 01~05_*.py            # dataset construction pipeline (optional)
│   ├── 11_gen_paper_excel.py # regenerate LaTeX tables from eval_results
│   └── gen_tab/              # table generation modules
├── data/
│   ├── demo_100.jsonl        # 100-sample demo (stratified, eval format)
│   ├── linteval_lite_test.jsonl   # LintEval-Lite test set (498 samples)
│   ├── linteval_full.jsonl.part{1,2,3}  # LintEval-Full (13,061 samples, split
│   │                        # into 3 shards to stay under GitHub's 100 MB limit)
│   └── (linteval_full.jsonl  # merged locally via scripts/split_dataset.py --merge)
├── eval_results/             # released per-sample results for all models
├── tools/testlib.h           # required for C++ generator/checker compilation
└── docs/table/               # generated LaTeX tables
```

## Environment setup

System requirements: Python ≥ 3.8, `clang-tidy`, `g++`, `pylint`, PMD 7.x, `javac`/`java`.

```bash
# 1. Python dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Tool paths (optional — everything falls back to PATH lookups)
source setup_env.sh

# 3. Verify
python scripts/test_environment.py
```

PMD is not installed by pip; download it from <https://pmd.github.io/> (7.x) and either put `pmd` on PATH or set `PMD_BIN`.

## Running evaluation

### Quick sanity check (100-sample demo)

```bash
python scripts/sanity_check.py
```

This runs the linters, the metrics, and the testlib validation loop on `data/demo_100.jsonl` to confirm the environment works.

### Evaluate a model on the demo (100 samples)

```bash
# Local model via vLLM
python scripts/10_eval_models.py \
    --model_name Qwen2.5-Coder-7B \
    --model_path /path/to/Qwen2.5-Coder-7B-Instruct \
    --data_path data/demo_100.jsonl \
    --limit 100 --gpu 0

# API model (OpenAI-compatible, e.g. DeepSeek)
export DEEPSEEK_API_KEY=sk-xxx
python scripts/10_eval_models.py --deepseek \
    --data_path data/demo_100.jsonl --limit 100

# Or any OpenAI-compatible endpoint
python scripts/10_eval_models.py --custom_api \
    --api_key sk-xxx --base_url https://api.deepseek.com/v1 \
    --api_model_id deepseek-chat --api_display_name MyModel \
    --data_path data/demo_100.jsonl --limit 100
```

### Full evaluation (all data)

The default data path is `data/linteval_lite_test.jsonl` (the 498-sample test set):

```bash
python scripts/10_eval_models.py --model_name Qwen2.5-Coder-7B --model_path /path/to/model --gpu 0
python scripts/10_eval_models.py --deepseek          # API model, all 498 samples
python scripts/10_eval_models.py --custom_api --api_key sk-xxx --base_url ... --api_model_id ... 
```

To evaluate on the **full 13,061-sample dataset**, first merge the three shards
(they are line-aligned and byte-identical to the original file):

```bash
python scripts/split_dataset.py --merge
# or: cat data/linteval_full.jsonl.part{1,2,3} > data/linteval_full.jsonl
```

Then run:

```bash
python scripts/10_eval_models.py --model_name Qwen2.5-Coder-7B --model_path /path/to/model \
    --data_path data/linteval_full.jsonl
```

Key options of `10_eval_models.py`:

| Option | Meaning |
|---|---|
| `--model_name` / `--model_path` | local model to evaluate via vLLM |
| `--deepseek` | DeepSeek API (uses `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` env vars) |
| `--custom_api` | any OpenAI-compatible API (`--api_key/--base_url/--api_model_id/--api_display_name`) |
| `--data_path` | override the evaluation dataset (default: `data/linteval_lite_test.jsonl`) |
| `--limit N` | evaluate only the first N samples (e.g. `--limit 100`) |
| `--gpu` | `CUDA_VISIBLE_DEVICES` for vLLM |
| `--tp` | tensor-parallel size for vLLM |
| `--no_message` | ablation: prompt without linter messages |
| `--skip_baseline` | reuse an existing `eval_results/baseline.json` |
| `--resume_failed` | re-run only API-generation failures from an existing result file |

Results are written to `eval_results/{model_name}.json` (per-sample results + summary).

### Regenerate paper tables

```bash
python scripts/11_gen_paper_excel.py
```

Reads `eval_results/` and writes LaTeX tables to `docs/table/`.

## Reproducing the released results

The released `eval_results/*.json` were produced with greedy decoding (temperature 0.0, max 4,096 tokens). External tool versions slightly affect linter diagnostics; see the paper for the exact versions (clang-tidy 22.1, PMD 7.12.0, pylint 4.0.5, g++ 13.3/15.2, OpenJDK 21/23).

## Dataset construction (optional)

The full construction pipeline (CodeContests+ → candidates → linter messages → LLM revisions → validation → split) is provided in `scripts/01_build_candidates.py` … `scripts/04_validate_revisions.py`. The released splits are included in `data/`; you only need these scripts to rebuild from scratch.

## License & data

Code is MIT licensed (see [LICENSE](LICENSE)). The benchmark data is derived from CodeContests+ (based on Codeforces problems) and is released for research purposes; cite the original [CodeContests](https://github.com/deepmind/code_contests) dataset as well.

## Citation

If you find LintEval useful, please consider citing our paper once it is published:

```bibtex
@inproceedings{linteval2026,
  title     = {LintEval: Linter-Guided Code Refactoring Benchmark},
  author    = {Anonymous, EMNLP 2026},
  booktitle = {Proceedings of the 2026 Conference on Empirical Methods in Natural Language Processing},
  year      = {2026}
}
```

(We will update this entry with the final venue, authors, and DOI after acceptance.)
