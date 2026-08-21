"""Alert-count impact tables (T5 main + A2 appendix)."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from gen_tab._shared import (
    ALL_BASE_MODELS,
    ALERT_COUNT_GROUPS,
    LATEX_TABLE_DIR,
    format_metric_value,
    needs_group_separator,
)


def compute_alert_count_metrics(baseline: List[Dict], model_results: Dict) -> Dict[str, Dict]:
    group_data = defaultdict(lambda: {"pass": 0, "total": 0, "reduction_sum": 0, "new_sum": 0, "lineperfix_lines_sum": 0, "lineperfix_fixed_sum": 0, "orig_msg_sum": 0})

    for item in baseline:
        sample_id = item["sample_id"]
        n_alerts = item["total"]

        for group_name, min_w, max_w in ALERT_COUNT_GROUPS:
            if min_w <= n_alerts <= max_w:
                group_data[group_name]["total"] += 1
                if sample_id in model_results:
                    result = model_results[sample_id]
                    if result.get("pass", False):
                        group_data[group_name]["pass"] += 1
                        mrr = result.get("reduction_at_pass") or 0
                        new_msg = result.get("new_count") or 0
                        in_t = result.get("in_total") or item.get("total", 0)
                        out_t = result.get("out_total") or 0
                        lines_changed = result.get("lineperfix_p_lines_changed") or 0
                        fixed_count = result.get("lineperfix_p_fixed_count") or 0
                        orig_msg = in_t
                        group_data[group_name]["reduction_sum"] += (in_t - out_t)
                        group_data[group_name]["new_sum"] += new_msg
                        # LinePerFix@P: include ALL pass samples
                        group_data[group_name]["lineperfix_lines_sum"] += lines_changed
                        group_data[group_name]["lineperfix_fixed_sum"] += fixed_count
                        group_data[group_name]["orig_msg_sum"] += orig_msg
                break

    metrics = {}
    for group_name, data in group_data.items():
        n_pass = data["pass"]
        n_total = data["total"]
        if n_pass > 0:
            new_msg_ratio = (data["new_sum"] / data["orig_msg_sum"] * 100) if data["orig_msg_sum"] > 0 else 0
            lpm_p = data["lineperfix_lines_sum"] / data["lineperfix_fixed_sum"] if data["lineperfix_fixed_sum"] > 0 else 0
            metrics[group_name] = {
                "pass@1": n_pass / n_total * 100,
                "reduction_p": data["reduction_sum"] / data["orig_msg_sum"] * 100 if data["orig_msg_sum"] > 0 else 0,
                "new_p": new_msg_ratio,
                "lineperfix_p": lpm_p,
            }
        else:
            metrics[group_name] = {"pass@1": 0, "reduction_p": 0, "new_p": 0, "lineperfix_p": 0}

    return metrics


def generate_alert_count_main_tex(all_alert_metrics: Dict[str, Dict[str, Dict]]) -> str:
    best_vals = {g: {"pass@1": 0, "reduction_p": -float('inf')} for g, _, _ in ALERT_COUNT_GROUPS}

    for model_display, metrics in all_alert_metrics.items():
        for group_name, _, _ in ALERT_COUNT_GROUPS:
            if group_name in metrics:
                m = metrics[group_name]
                best_vals[group_name]["pass@1"] = max(best_vals[group_name]["pass@1"], m["pass@1"])
                best_vals[group_name]["reduction_p"] = max(best_vals[group_name]["reduction_p"], m["reduction_p"])

    lines = [
        "% ============================================================",
        "% Placement: Main Text (Section 4.4 - Alert Count Analysis)",
        "% ============================================================",
        "% T5: Alert Count Impact (Main Text - Pass@1 and Reduction@P)",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\textwidth}{!}{",
        "\\begin{tabular}{lcccccccc}",
        "\\toprule",
        "& \\multicolumn{2}{c}{\\textbf{1 alert}} & \\multicolumn{2}{c}{\\textbf{2--5 alerts}} & \\multicolumn{2}{c}{\\textbf{6--10 alerts}} & \\multicolumn{2}{c}{\\textbf{$>$10 alerts}} \\\\",
        "\\cmidrule(lr){2-3} \\cmidrule(lr){4-5} \\cmidrule(lr){6-7} \\cmidrule(lr){8-9}",
        "\\textbf{Model} & Pass@1 & Reduction@P & Pass@1 & Reduction@P & Pass@1 & Reduction@P & Pass@1 & Reduction@P \\\\",
        "\\midrule",
    ]

    for model_display, model_name in ALL_BASE_MODELS:
        if model_display not in all_alert_metrics:
            continue
        metrics = all_alert_metrics[model_display]
        row = [model_display]
        for group_name, _, _ in ALERT_COUNT_GROUPS:
            if group_name in metrics:
                m = metrics[group_name]
                bv = best_vals[group_name]
                p1_str = format_metric_value(m["pass@1"], bv["pass@1"])
                mr_str = format_metric_value(m["reduction_p"], bv["reduction_p"])
                row.extend([p1_str, mr_str])
            else:
                row.extend(["--", "--"])
        lines.append(" & ".join(row) + " \\\\")
        if needs_group_separator(model_name):
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        "\\caption{Impact of initial alert count on model performance across LintEval-Lite. Best results per column are in \\textbf{bold}.}",
        "\\label{tab:alert_count}",
        "\\end{table*}",
    ])
    return "\n".join(lines)


def generate_alert_count_appendix_tex(all_alert_metrics: Dict[str, Dict[str, Dict]]) -> str:
    best_vals = {g: {"pass@1": 0, "reduction_p": -float('inf'), "new_p": float('inf'), "lineperfix_p": float('inf')} for g, _, _ in ALERT_COUNT_GROUPS}
    for model_display, metrics in all_alert_metrics.items():
        for group_name, _, _ in ALERT_COUNT_GROUPS:
            if group_name in metrics:
                m = metrics[group_name]
                best_vals[group_name]["pass@1"] = max(best_vals[group_name]["pass@1"], m["pass@1"])
                best_vals[group_name]["reduction_p"] = max(best_vals[group_name]["reduction_p"], m["reduction_p"])
                best_vals[group_name]["new_p"] = min(best_vals[group_name]["new_p"], m["new_p"])
                best_vals[group_name]["lineperfix_p"] = min(best_vals[group_name]["lineperfix_p"], m["lineperfix_p"])

    lines = [
        "% ============================================================",
        "% Placement: Appendix (Section A - Full Results)",
        "% ============================================================",
        "% A2: Full Alert Count Impact (All Four Metrics)",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\textwidth}{!}{",
        "\\begin{tabular}{lcccccccccccccccc}",
        "\\toprule",
        "& \\multicolumn{4}{c}{\\textbf{1 alert}} & \\multicolumn{4}{c}{\\textbf{2--5 alerts}} & \\multicolumn{4}{c}{\\textbf{6--10 alerts}} & \\multicolumn{4}{c}{\\textbf{$>$10 alerts}} \\\\",
        "\\cmidrule(lr){2-5} \\cmidrule(lr){6-9} \\cmidrule(lr){10-13} \\cmidrule(lr){14-17}",
        "\\textbf{Model} & Pass@1 & Reduction@P & New@P & LinePerFix@P & Pass@1 & Reduction@P & New@P & LinePerFix@P & Pass@1 & Reduction@P & New@P & LinePerFix@P & Pass@1 & Reduction@P & New@P & LinePerFix@P \\\\",
        "\\midrule",
    ]

    for model_display, model_name in ALL_BASE_MODELS:
        if model_display not in all_alert_metrics:
            continue
        metrics = all_alert_metrics[model_display]
        row = [model_display]
        for group_name, _, _ in ALERT_COUNT_GROUPS:
            if group_name in metrics:
                m = metrics[group_name]
                bv = best_vals[group_name]
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
        "\\caption{Full alert-count breakdown on LintEval-Lite. All four metrics are reported for each alert-count bin. Best results per column are in \\textbf{bold}.}",
        "\\label{app:alert_count_full}",
        "\\end{table*}",
    ])
    return "\n".join(lines)
