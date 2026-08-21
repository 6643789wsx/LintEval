from __future__ import annotations

import json
from typing import Dict, List

from gen_tab._shared import (
    ALL_BASE_MODELS,
    RESULT_DIR,
    LATEX_TABLE_DIR,
    needs_group_separator,
    count_based_fixed,
)

_EPS = 0.001


def _load_raw_results(model_name: str) -> List[Dict]:
    json_path = RESULT_DIR / f"{model_name}.json"
    if not json_path.exists():
        return []
    with open(json_path, 'r') as f:
        data = json.load(f)
    return data.get("results", []) if isinstance(data, dict) else data


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0


def _analyze_failure_cases(results: List[Dict]) -> Dict:
    passed = [r for r in results if r.get("pass", False)]
    failed = [r for r in results if not r.get("pass", False)]

    pass_in_sum = sum(r.get("in_total", 0) for r in passed)
    pass_net = sum(r.get("in_total", 0) - r.get("out_total", 0) for r in passed)
    pass_new_sum = sum(r.get("new_msg_count", 0) for r in passed)
    pass_lc = sum(r.get("lpm_p_lines_changed", 0) or 0 for r in passed)
    pass_fx = sum(count_based_fixed(r) for r in passed)

    fail_in_sum = sum(r.get("in_total", 0) for r in failed)
    fail_net = sum(r.get("in_total", 0) - r.get("out_total", 0) for r in failed)
    fail_new_sum = sum(r.get("new_msg_count", 0) for r in failed)
    fail_lc = sum(r.get("lpm_p_lines_changed", 0) or 0 for r in failed)
    fail_fx = sum(count_based_fixed(r) for r in failed)

    pass_metrics = {
        "count": len(passed),
        "rate": len(passed) / len(results) if results else 0,
        "avg_reduction": _safe_div(pass_net, pass_in_sum),
        "avg_new": _safe_div(pass_new_sum, pass_in_sum),
        "avg_dline": pass_lc / len(passed) if passed else 0,
        "avg_lpm": pass_lc / pass_fx if pass_fx else 0,
    }
    failure_metrics = {
        "count": len(failed),
        "avg_reduction": _safe_div(fail_net, fail_in_sum),
        "avg_new": _safe_div(fail_new_sum, fail_in_sum),
        "avg_dline": fail_lc / len(failed) if failed else 0,
        "avg_lpm": fail_lc / fail_fx if fail_fx else 0,
    }
    return {"pass": pass_metrics, "failure": failure_metrics, "total": len(results)}


def _fmt_pct(val: float, decimals: int = 1) -> str:
    return f"{val * 100:.{decimals}f}\\%"


def _arrow(fail_val: float, pass_val: float, higher_is_better: bool) -> str:
    diff = fail_val - pass_val
    if abs(diff) < _EPS:
        return ""
    if higher_is_better:
        return r" \textcolor{green!70!black}{$\uparrow$}" if diff > 0 else r" \textcolor{red!70!black}{$\downarrow$}"
    else:
        return r" \textcolor{green!70!black}{$\downarrow$}" if diff < 0 else r" \textcolor{red!70!black}{$\uparrow$}"


def _bold(s: str, val: float, best: float) -> str:
    if abs(val - best) < _EPS:
        return f"\\textbf{{{s}}}"
    return s


def generate_failure_analysis_tex() -> str:
    all_analysis = {}
    for _, model_name in ALL_BASE_MODELS:
        results = _load_raw_results(model_name)
        if results:
            all_analysis[model_name] = _analyze_failure_cases(results)

    if not all_analysis:
        return "% No failure analysis data available yet."

    # Standard column order: Reduction → New → ΔLine → LinePerFix
    raw = {}  # model_name -> (p_red, p_new, p_dl, p_lpm, f_red, f_new, f_dl, f_lpm)
    for _, model_name in ALL_BASE_MODELS:
        if model_name not in all_analysis:
            continue
        a = all_analysis[model_name]
        p, f = a["pass"], a["failure"]
        raw[model_name] = (p["avg_reduction"], p["avg_new"], p["avg_dline"], p["avg_lpm"],
                           f["avg_reduction"], f["avg_new"], f["avg_dline"], f["avg_lpm"])

    best_pr = max(v[0] for v in raw.values())
    best_pn = min(v[1] for v in raw.values())
    best_pd = min(v[2] for v in raw.values())
    best_pl = min(v[3] for v in raw.values())
    best_fr = max(v[4] for v in raw.values())
    best_fn = min(v[5] for v in raw.values())
    best_fd = min(v[6] for v in raw.values())
    best_fl = min(v[7] for v in raw.values())

    lines = [
        "% ============================================================",
        "% Table: Failure Case Analysis",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\linewidth}{!}{",
        "\\begin{tabular}{l cccc cccc}",
        "\\toprule",
        "& \\multicolumn{4}{c}{\\textbf{Pass Cases}} & \\multicolumn{4}{c}{\\textbf{Failure Cases}} \\\\",
        "\\cmidrule(lr){2-5} \\cmidrule(lr){6-9}",
        "\\textbf{Model} & \\textbf{Reduction@P} & \\textbf{New@P} & \\textbf{$\\Delta$Line@P} & \\textbf{LinePerFix@P} & \\textbf{Reduction@F} & \\textbf{New@F} & \\textbf{$\\Delta$Line@F} & \\textbf{LinePerFix@F} \\\\",
        "\\midrule",
    ]

    for model_display, model_name in ALL_BASE_MODELS:
        if model_name not in all_analysis:
            continue
        p_red, p_new, p_dl, p_lpm, f_red, f_new, f_dl, f_lpm = raw[model_name]

        p_red_s = _bold(_fmt_pct(p_red), p_red, best_pr) if p_red != 0 else "N/A"
        p_new_s = _bold(_fmt_pct(p_new), p_new, best_pn) if p_new != 0 else "0"
        p_dl_s = _bold(f"{p_dl:.1f}", p_dl, best_pd) if p_dl != 0 else "N/A"
        p_lpm_s = _bold(f"{p_lpm:.1f}", p_lpm, best_pl) if p_lpm != 0 else "N/A"

        f_red_base = _fmt_pct(f_red) if f_red != 0 else "N/A"
        f_new_base = _fmt_pct(f_new) if f_new != 0 else "0"
        f_dl_base = f"{f_dl:.1f}" if f_dl != 0 else "N/A"
        f_lpm_base = f"{f_lpm:.1f}" if f_lpm != 0 else "N/A"

        f_red_s = _bold(f_red_base, f_red, best_fr) + (_arrow(f_red, p_red, True) if f_red != 0 else "")
        f_new_s = _bold(f_new_base, f_new, best_fn) + (_arrow(f_new, p_new, False) if f_new != 0 else "")
        f_dl_s = _bold(f_dl_base, f_dl, best_fd) + (_arrow(f_dl, p_dl, False) if f_dl != 0 else "")
        f_lpm_s = _bold(f_lpm_base, f_lpm, best_fl) + (_arrow(f_lpm, p_lpm, False) if f_lpm != 0 else "")

        lines.append(f"{model_display} & {p_red_s} & {p_new_s} & {p_dl_s} & {p_lpm_s} & {f_red_s} & {f_new_s} & {f_dl_s} & {f_lpm_s} \\\\")

        if needs_group_separator(model_name):
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        "\\caption{Editing behavior of passed and failed refactoring attempts. \\texttt{@P} metrics are computed over $S_{\\text{pass}}$; \\texttt{@F} metrics are computed over failed instances for diagnostic analysis only. Arrows indicate whether the failure-case value is higher or lower than the pass-case value. \\textbf{Bold} marks the best value per column.}",
        "\\label{tab:failure_analysis}",
        "\\end{table*}",
    ])
    return "\n".join(lines)
