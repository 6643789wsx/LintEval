"""Category-wise performance table (appendix - full metrics per category).

Uses corpus-level per-category computation consistent with overall metrics:
- Reduction@P(cat) = sum(orig_cat - out_cat) / sum(orig_cat) over pass samples
- New@P(cat) = sum(new_alerts in cat) / sum(orig_cat) over pass samples
- Pass@1(cat) = n_pass_with_cat / n_total_with_cat (samples having ≥1 alert in cat)

LinePerFix@P is omitted because lines-changed cannot be attributed to specific categories.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from gen_tab._shared import (
    ALL_BASE_MODELS,
    RESULT_DIR,
    format_metric_value,
    needs_group_separator,
)

CATEGORIES = ["error-prone", "performance", "refactor", "style", "other"]
CATEGORY_DISPLAY = {
    "error-prone": "Error-prone",
    "performance": "Performance",
    "refactor": "Refactor",
    "style": "Style",
    "other": "Other",
}


def _load_raw_results(model_name: str) -> List[Dict]:
    json_path = RESULT_DIR / f"{model_name}.json"
    if not json_path.exists():
        return []
    with open(json_path, "r") as f:
        data = json.load(f)
    return data.get("results", []) if isinstance(data, dict) else data


def _load_baseline() -> List[Dict]:
    with open(RESULT_DIR / "baseline.json") as f:
        return json.load(f)


def compute_category_metrics(results: List[Dict], baseline: List[Dict]) -> Dict[str, Dict]:
    """Compute per-category metrics using corpus-level aggregation."""
    bl_by_sid = {b["sample_id"]: b for b in baseline}

    cat_acc = defaultdict(lambda: {
        "n_total": 0,
        "n_pass_total": 0,
        "orig_sum": 0,
        "out_sum": 0,
        "new_sum": 0,
    })

    for r in results:
        sid = r.get("sample_id", "")
        bl = bl_by_sid.get(sid)
        if not bl:
            continue
        bl_cats = bl.get("categories", {})
        out_cats = r.get("out_categories", {})
        is_pass = r.get("pass", False)

        for cat in CATEGORIES:
            orig = bl_cats.get(cat, 0)
            if orig > 0:
                cat_acc[cat]["n_total"] += 1
                cat_acc[cat]["n_pass_total"] += 1 if is_pass else 0

        if is_pass:
            for cat in CATEGORIES:
                out = out_cats.get(cat, 0)
                orig = bl_cats.get(cat, 0)
                cat_acc[cat]["orig_sum"] += orig
                cat_acc[cat]["out_sum"] += out
                if out > orig:
                    cat_acc[cat]["new_sum"] += out - orig

    metrics = {}
    for cat in CATEGORIES:
        acc = cat_acc[cat]
        n_total = acc["n_total"]
        orig_sum = acc["orig_sum"]
        out_sum = acc["out_sum"]

        pass1 = acc["n_pass_total"] / n_total * 100 if n_total > 0 else 0
        reduction_p = (orig_sum - out_sum) / orig_sum * 100 if orig_sum > 0 else 0
        new_p = acc["new_sum"] / orig_sum * 100 if orig_sum > 0 else 0

        metrics[cat] = {
            "pass@1": pass1,
            "reduction_p": reduction_p,
            "new_p": new_p,
        }

    return metrics


def generate_category_performance_full_tex() -> str:
    baseline = _load_baseline()

    all_cat_metrics = {}
    for model_display, model_name in ALL_BASE_MODELS:
        results = _load_raw_results(model_name)
        if results:
            all_cat_metrics[model_display] = compute_category_metrics(results, baseline)

    if not all_cat_metrics:
        return "% No category data available."

    best_vals = {}
    for cat in CATEGORIES:
        best_vals[cat] = {
            "pass@1": 0,
            "reduction_p": -float("inf"),
            "new_p": float("inf"),
        }
        for model_display, metrics in all_cat_metrics.items():
            if cat in metrics:
                m = metrics[cat]
                best_vals[cat]["pass@1"] = max(best_vals[cat]["pass@1"], m["pass@1"])
                best_vals[cat]["reduction_p"] = max(best_vals[cat]["reduction_p"], m["reduction_p"])
                best_vals[cat]["new_p"] = min(best_vals[cat]["new_p"], m["new_p"])

    lines = [
        "% ============================================================",
        "% Table: Full Category-wise Performance (Appendix)",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\textwidth}{!}{",
        "\\begin{tabular}{l" + "ccc" * len(CATEGORIES) + "}",
        "\\toprule",
    ]

    header1 = ""
    for cat in CATEGORIES:
        header1 += f" & \\multicolumn{{3}}{{c}}{{\\textbf{{{CATEGORY_DISPLAY[cat]}}}}}"
    header1 += " \\\\"
    lines.append(header1)

    header2 = "\\textbf{Model}"
    for _ in CATEGORIES:
        header2 += " & Pass@1 & Reduction@P & New@P"
    header2 += " \\\\"
    lines.append(header2)
    lines.append("\\midrule")

    for model_display, model_name in ALL_BASE_MODELS:
        if model_display not in all_cat_metrics:
            continue
        metrics = all_cat_metrics[model_display]
        row = [model_display]
        for cat in CATEGORIES:
            if cat in metrics:
                m = metrics[cat]
                bv = best_vals[cat]
                row.append(format_metric_value(m["pass@1"], bv["pass@1"]))
                row.append(format_metric_value(m["reduction_p"], bv["reduction_p"]))
                row.append(format_metric_value(m["new_p"], bv["new_p"]))
            else:
                row.extend(["--", "--", "--"])
        lines.append(" & ".join(row) + " \\\\")
        if needs_group_separator(model_name):
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        "\\caption{Full category-wise performance on LintEval-Lite. "
        "Pass@1 is computed over samples having $\\geq 1$ alert in the corresponding category; "
        "Reduction@P and New@P use corpus-level aggregation over passed instances.}",
        "\\label{app:category_performance_full}",
        "\\end{table*}",
    ])

    return "\n".join(lines)
