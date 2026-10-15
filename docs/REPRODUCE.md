# Evaluation and reproduction

The evaluation method, the metric definitions and how the released paper numbers are
reproduced. Running commands and environment setup live in [SETUP.md](../SETUP.md).

## Metrics

Computed over samples that pass compile + tests:

| Metric | Definition |
|---|---|
| Pass@1 | fraction of samples whose revised code compiles and passes all generated tests |
| Reduction@P / MRR@P | Σ(in − out) / Σ(in) over passed samples |
| New@P | newly introduced alerts / alerts in the original code |
| ΔLine@P | average number of changed lines |
| LinePerFix@P | changed lines per alert fixed |

The metric definitions used for the paper (identical to `scripts/gen_tab/_shared.py`) are:

| Metric | Formula (over the samples that pass compile + tests) |
|---|---|
| Reduction@P | `Σ(in − out) / Σ(in)` — corpus level, not a mean of per-sample ratios |
| New@P | `Σ(new alerts) / Σ(in)` |
| ΔLine@P | `Σ lines changed / n_passed` |
| LinePerFix@P | `Σ lines changed / Σ fixed`, `fixed = max(0, in − out + new)` |

`eval_results/*.json` stores every quantity these formulas need (`in_total`, `out_total`,
`new_msg_count`, `lpm_p_lines_changed`, `pass`), so metrics are always recomputable offline.

## Released per-sample results

`eval_results/*.json` contains the per-sample results behind the paper tables; regenerate the
LaTeX tables with:

```bash
python scripts/11_gen_paper_excel.py     # -> docs/table/*.tex
```

Results are written to `eval_results/<model>.json`:

```json
{"model": "...", "total_entries": 498, "timestamp": "...",
 "summary": {"pass@1": 0.57, "avg_mrr_at_pass": 0.61, "new_msg_per_sample_at_pass": 0.70,
             "lpm_p": 5.95, "line_churn_at_pass": 0.99, "mrr_at_pass_by_category": {...}},
 "results": [{"sample_id": "...", "language": "cpp", "pass": true, "in_total": 6, "out_total": 2,
              "new_msg_count": 1, "mrr_at_pass": 1.0, "added_lines": 3, "deleted_lines": 2, ...}]}
```

Every record keeps the raw model output, the extracted code, the number of generated/passed
tests, the alert counts before/after and the token usage, so the numbers can be audited
per sample.

## Metric consistency check

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

## Main results (LintEval-Lite, 498 samples)

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

## Reference revisions

Reference revisions were produced with greedy decoding (temperature 0.0, max 4,096 tokens).
Linter versions slightly change diagnostics; the paper reports clang-tidy 22.1, PMD 7.12.0,
pylint 4.0.5, g++ 13.3/15.2, OpenJDK 21/23.
