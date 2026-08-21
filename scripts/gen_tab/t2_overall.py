from __future__ import annotations

from gen_tab._shared import (
    MODEL_GROUPS,
    format_metric_value,
    load_model_results,
    load_model_summary,
)

# Model display order in the open-source group
_OS_ORDER = [
    ("DeepSeek-v3.2", "DeepSeek-v3_2-128K"),
    ("Qwen2.5-Coder-32B", "Qwen2_5-Coder-32B-Instruct"),
    ("Qwen2.5-Coder-7B", "Qwen2_5-Coder-7B"),
    ("Qwen2.5-Coder-3B", "Qwen2_5-Coder-3B"),
    ("Qwen2.5-Coder-0.5B", "Qwen2_5-Coder-0_5B"),
    ("Llama-3.2-3B", "Llama-3_2-3B-Instruct"),
    ("Llama-3.2-1B", "Llama-3_2-1B-Instruct"),
]


def _fmt_pct(val: float, best: float | None) -> str:
    if val < 0:
        s = f"$-{abs(val):.1f}\\%$"
    else:
        s = f"{val:.1f}\\%"
    if best is not None and abs(val - best) < 0.05:
        return f"\\textbf{{{s}}}"
    return s


def _fmt_raw(val: float, best: float | None) -> str:
    s = f"{val:.1f}"
    if best is not None and abs(val - best) < 0.05:
        return f"\\textbf{{{s}}}"
    return s


def _compute_model(display: str, name: str) -> tuple | None:
    summary = load_model_summary(name)
    if not summary:
        return None
    results = load_model_results(name)
    total_new = total_orig = total_lines = n_pass = 0
    for r in results.values():
        if r.get("pass"):
            total_new += r.get("new_count", 0) or 0
            total_orig += r.get("in_total", 0) or 0
            total_lines += r.get("lineperfix_p_lines_changed", 0) or 0
            n_pass += 1
    return (
        display,
        summary.get("pass@1", 0) * 100,
        summary.get("avg_mrr_at_pass", 0) * 100,
        (total_new / total_orig * 100) if total_orig > 0 else 0,
        total_lines / n_pass if n_pass > 0 else 0,
        summary.get("lineperfix_p", 0),
    )


def generate_overall_performance_tex() -> str:
    # Collect model rows
    cs_rows = [_compute_model(d, n) for d, n in MODEL_GROUPS["closed_source"]]
    os_rows = [_compute_model(d, n) for d, n in _OS_ORDER]

    # Baselines
    rule_row = _compute_model("Rule-Based Fixers", "autofix_baseline")

    # Best across ALL models (including baselines)
    all_valid = [r for r in cs_rows + os_rows if r]
    if rule_row:
        all_valid.append(rule_row)

    def _best(rows, idx, higher):
        vals = [r[idx] for r in rows]
        return max(vals) if higher else min(vals)

    best = {i: _best(all_valid, i, i in (1, 2)) for i in range(1, 6)}

    lines = [
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\textwidth}{!}{%",
        "\\begin{tabular}{l ccccc}",
        "\\toprule",
        "\\textbf{Model} & \\textbf{Pass@1} ($\\uparrow$) & \\textbf{Reduction@P} ($\\uparrow$) & \\textbf{New@P} ($\\downarrow$) & \\textbf{$\\Delta$Line@P} ($\\downarrow$) & \\textbf{LinePerFix@P} ($\\downarrow$) \\\\",
        "\\midrule",
        "Copy-Original & 100.0\\% & 0.0\\% & 0.0\\% & 0.0 & -- \\\\",
    ]

    if rule_row:
        _, p, mr, nw, dl, lpm = rule_row
        lines.append(f"Rule-Based Fixers & {_fmt_pct(p, best[1])} & {_fmt_pct(mr, best[2])} & {_fmt_pct(nw, best[3])} & {_fmt_raw(dl, best[4])} & {_fmt_raw(lpm, best[5])} \\\\")

    lines.append("\\midrule")

    for row in cs_rows:
        if not row:
            continue
        _, p, mr, nw, dl, lpm = row
        lines.append(f"{row[0]} & {_fmt_pct(p, best[1])} & {_fmt_pct(mr, best[2])} & {_fmt_pct(nw, best[3])} & {_fmt_raw(dl, best[4])} & {_fmt_raw(lpm, best[5])} \\\\")

    lines.append("\\midrule")

    for row in os_rows:
        if not row:
            continue
        _, p, mr, nw, dl, lpm = row
        lines.append(f"{row[0]} & {_fmt_pct(p, best[1])} & {_fmt_pct(mr, best[2])} & {_fmt_pct(nw, best[3])} & {_fmt_raw(dl, best[4])} & {_fmt_raw(lpm, best[5])} \\\\")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}%",
        "}",
        "\\caption{Overall results on \\textbf{LintEval-Lite}. Reduction@P, New@P, $\\Delta$Line@P, and LinePerFix@P are computed only over passed instances. Best results per column are highlighted in \\textbf{boldface}.}",
        "\\label{tab:overall_performance}",
        "\\end{table*}",
    ])
    return "\n".join(lines)
