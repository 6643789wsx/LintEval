"""Language-wise performance tables (T3 main + A1 appendix)."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from gen_tab._shared import (
    ALL_BASE_MODELS,
    LANG_NAMES,
    LATEX_TABLE_DIR,
    format_metric_value,
    needs_group_separator,
)


def compute_language_metrics(baseline: List[Dict], model_results: Dict) -> Dict[str, Dict]:
    lang_data = defaultdict(lambda: {
        "pass": 0, "total": 0, "reduction_sum": 0, "new_sum": 0,
        "lineperfix_lines_sum": 0, "lineperfix_fixed_sum": 0, "orig_msg_sum": 0
    })

    for item in baseline:
        sample_id = item["sample_id"]
        lang = item["language"]
        lang_data[lang]["total"] += 1

        if sample_id in model_results:
            result = model_results[sample_id]
            if result.get("pass", False):
                lang_data[lang]["pass"] += 1
                mrr = result.get("reduction_at_pass") or 0
                new_msg = result.get("new_count") or 0
                in_t = result.get("in_total") or item.get("total", 0)
                out_t = result.get("out_total") or 0
                lines_changed = result.get("lineperfix_p_lines_changed") or 0
                fixed_count = result.get("lineperfix_p_fixed_count") or 0
                orig_msg = in_t
                lang_data[lang]["reduction_sum"] += (in_t - out_t)
                lang_data[lang]["new_sum"] += new_msg
                # LinePerFix@P: include ALL pass samples
                lang_data[lang]["lineperfix_lines_sum"] += lines_changed
                lang_data[lang]["lineperfix_fixed_sum"] += fixed_count
                lang_data[lang]["orig_msg_sum"] += orig_msg

    metrics = {}
    for lang, data in lang_data.items():
        n_pass = data["pass"]
        n_total = data["total"]
        if n_pass > 0:
            new_msg_ratio = (data["new_sum"] / data["orig_msg_sum"] * 100) if data["orig_msg_sum"] > 0 else 0
            lpm_p = data["lineperfix_lines_sum"] / data["lineperfix_fixed_sum"] if data["lineperfix_fixed_sum"] > 0 else 0
            metrics[lang] = {
                "pass@1": n_pass / n_total * 100,
                "reduction_p": data["reduction_sum"] / data["orig_msg_sum"] * 100 if data["orig_msg_sum"] > 0 else 0,
                "new_p": new_msg_ratio,
                "lineperfix_p": lpm_p,
            }
        else:
            metrics[lang] = {"pass@1": 0, "reduction_p": 0, "new_p": 0, "lineperfix_p": 0}

    return metrics


def generate_language_performance_main_tex(all_lang_metrics: Dict[str, Dict[str, Dict]]) -> str:
    best_vals = {lang: {"pass@1": 0, "reduction_p": -float('inf')} for lang in ["cpp", "py3", "java"]}

    for model_display, metrics in all_lang_metrics.items():
        for lang in ["cpp", "py3", "java"]:
            if lang in metrics:
                m = metrics[lang]
                best_vals[lang]["pass@1"] = max(best_vals[lang]["pass@1"], m["pass@1"])
                best_vals[lang]["reduction_p"] = max(best_vals[lang]["reduction_p"], m["reduction_p"])

    lines = [
        "% ============================================================",
        "% Placement: Main Text (Section 4.2 - Language Analysis)",
        "% ============================================================",
        "% T3: Language-wise Performance (Main Text - Selected Metrics)",
        "% Pass@1 and Reduction@P by programming language",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\begin{adjustbox}{max width=\\textwidth}",
        "\\begin{tabular}{lcccccc}",
        "\\toprule",
        "& \\multicolumn{2}{c}{\\textbf{C++}} & \\multicolumn{2}{c}{\\textbf{Python}} & \\multicolumn{2}{c}{\\textbf{Java}} \\\\",
        "\\cmidrule(lr){2-3} \\cmidrule(lr){4-5} \\cmidrule(lr){6-7}",
        "\\textbf{Model} & Pass@1 & Reduction@P & Pass@1 & Reduction@P & Pass@1 & Reduction@P \\\\",
        "\\midrule",
    ]

    for model_display, model_name in ALL_BASE_MODELS:
        if model_display not in all_lang_metrics:
            continue
        metrics = all_lang_metrics[model_display]
        row = [model_display]
        for lang in ["cpp", "py3", "java"]:
            if lang in metrics:
                m = metrics[lang]
                bv = best_vals[lang]
                p1_bold = abs(m['pass@1'] - bv['pass@1']) < 0.01
                mr_bold = abs(m['reduction_p'] - bv['reduction_p']) < 0.01
                p1_str = f"\\textbf{{{m['pass@1']:.1f}\\%}}" if p1_bold else f"{m['pass@1']:.1f}\\%"
                mr_str = f"\\textbf{{{m['reduction_p']:.1f}\\%}}" if mr_bold else f"{m['reduction_p']:.1f}\\%"
                row.extend([p1_str, mr_str])
            else:
                row.extend(["--", "--"])
        lines.append(" & ".join(row) + " \\\\")
        if needs_group_separator(model_name):
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{adjustbox}",
        "\\caption{Pass@1 and Reduction@P by programming language on LintEval-Lite. Best results per column are in \\textbf{bold}.}",
        "\\label{tab:language_performance}",
        "\\end{table*}",
    ])

    return "\n".join(lines)


def generate_language_performance_appendix_tex(all_lang_metrics: Dict[str, Dict[str, Dict]]) -> str:
    best_vals = {lang: {"pass@1": 0, "reduction_p": -float('inf'), "new_p": float('inf'), "lineperfix_p": float('inf')} for lang in ["cpp", "py3", "java"]}

    for model_display, metrics in all_lang_metrics.items():
        for lang in ["cpp", "py3", "java"]:
            if lang in metrics:
                m = metrics[lang]
                best_vals[lang]["pass@1"] = max(best_vals[lang]["pass@1"], m["pass@1"])
                best_vals[lang]["reduction_p"] = max(best_vals[lang]["reduction_p"], m["reduction_p"])
                best_vals[lang]["new_p"] = min(best_vals[lang]["new_p"], m["new_p"])
                best_vals[lang]["lineperfix_p"] = min(best_vals[lang]["lineperfix_p"], m["lineperfix_p"])

    lines = [
        "% ============================================================",
        "% Placement: Appendix (Section A - Full Results)",
        "% ============================================================",
        "% A1: Full Language-wise Performance (All Four Metrics)",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\textwidth}{!}{",
        "\\begin{tabular}{lcccccccccccc}",
        "\\toprule",
        "& \\multicolumn{4}{c}{\\textbf{C++}} & \\multicolumn{4}{c}{\\textbf{Python}} & \\multicolumn{4}{c}{\\textbf{Java}} \\\\",
        "\\cmidrule(lr){2-5} \\cmidrule(lr){6-9} \\cmidrule(lr){10-13}",
        "\\textbf{Model} & Pass@1 & Reduction@P & New@P & LinePerFix@P & Pass@1 & Reduction@P & New@P & LinePerFix@P & Pass@1 & Reduction@P & New@P & LinePerFix@P \\\\",
        "\\midrule",
    ]

    for model_display, model_name in ALL_BASE_MODELS:
        if model_display not in all_lang_metrics:
            continue
        metrics = all_lang_metrics[model_display]
        row = [model_display]
        for lang in ["cpp", "py3", "java"]:
            if lang in metrics:
                m = metrics[lang]
                bv = best_vals[lang]
                p1_str = format_metric_value(m["pass@1"], bv["pass@1"])
                mr_str = format_metric_value(m["reduction_p"], bv["reduction_p"])
                new_str = format_metric_value(m["new_p"], bv["new_p"])
                lpm_str = format_metric_value(m["lineperfix_p"], bv["lineperfix_p"], is_pct=False)
                row.extend([p1_str, mr_str, new_str, lpm_str])
            else:
                row.extend(["--", "--", "--", "--"])
        lines.append(" & ".join(row) + " \\\\")
        if needs_group_separator(model_name):
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        "\\caption{Full language-wise performance on LintEval-Lite. All four metrics (Pass@1, Reduction@P, New@P, LinePerFix@P) are reported for C++, Python, and Java. Best results per column are in \\textbf{bold}.}",
        "\\label{app:language_full}",
        "\\end{table*}",
    ])

    return "\n".join(lines)
