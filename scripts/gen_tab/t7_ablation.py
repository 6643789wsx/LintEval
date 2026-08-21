from __future__ import annotations

from gen_tab._shared import (
    ABLATION_MODELS,
    load_model_summary,
    _compute_metrics_from_results,
)

_EPS = 0.005

# For each metric pair: True = higher is better, False = lower is better
_METRIC_DIRECTION = {
    "pass": True,
    "mrp": True,
    "new": False,
    "dl": False,
    "lpm": False,
}


def _fmt(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.1f}"


def _arrow(wo_val: float, w_val: float, higher_is_better: bool) -> str:
    diff = wo_val - w_val
    if abs(diff) < _EPS:
        return ""
    if higher_is_better:
        return r" \textcolor{green!70!black}{$\uparrow$}" if diff > 0 else r" \textcolor{red!70!black}{$\downarrow$}"
    else:
        return r" \textcolor{green!70!black}{$\downarrow$}" if diff < 0 else r" \textcolor{red!70!black}{$\uparrow$}"


def generate_ablation_tex() -> str:
    rows = []
    for model_display, model_name in ABLATION_MODELS:
        with_summary = load_model_summary(model_name)
        no_summary = load_model_summary(f"{model_name}_no_msg")

        w_new_p, w_dl = _compute_metrics_from_results(model_name)
        wo_new_p, wo_dl = _compute_metrics_from_results(f"{model_name}_no_msg")

        if with_summary:
            rows.append({
                "model": model_display,
                "w_pass": with_summary.get("pass@1", 0) * 100,
                "w_mrp": with_summary.get("avg_mrr_at_pass", 0) * 100,
                "w_new": w_new_p or 0,
                "w_dl": w_dl or 0,
                "w_lpm": with_summary.get("lineperfix_p", 0),
                "wo_pass": no_summary.get("pass@1", 0) * 100 if no_summary else None,
                "wo_mrp": no_summary.get("avg_mrr_at_pass", 0) * 100 if no_summary else None,
                "wo_new": wo_new_p or 0,
                "wo_dl": wo_dl or 0,
                "wo_lpm": no_summary.get("lineperfix_p", 0) if no_summary else None,
            })

    if not rows:
        return "% No ablation data available yet."

    lines = [
        "% ============================================================",
        "% Ablation: With-Alerts vs Without-Alerts",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\linewidth}{!}{",
        "\\begin{tabular}{lcccccccccc}",
        "\\toprule",
        " & \\multicolumn{5}{c}{\\textbf{With Alerts}} & \\multicolumn{5}{c}{\\textbf{No Alerts}} \\\\",
        "\\cmidrule(lr){2-6} \\cmidrule(lr){7-11}",
        "\\textbf{Model} & Pass@1 & Reduction@P & New@P & $\\Delta$Line@P & LinePerFix@P & Pass@1 & Reduction@P & New@P & $\\Delta$Line@P & LinePerFix@P \\\\",
        "\\midrule",
    ]

    pairs = [
        ("pass", "w_pass", "wo_pass"),
        ("mrp", "w_mrp", "wo_mrp"),
        ("new", "w_new", "wo_new"),
        ("dl", "w_dl", "wo_dl"),
        ("lpm", "w_lpm", "wo_lpm"),
    ]

    for r in rows:
        cells = []
        # With Alerts columns: plain values
        for _, w_key, _ in pairs:
            cells.append(_fmt(r[w_key]))

        # No Alerts columns: value + arrow comparing to With Alerts
        for metric_key, w_key, wo_key in pairs:
            w_val = r[w_key]
            wo_val = r[wo_key]
            if wo_val is not None and w_val is not None:
                cells.append(_fmt(wo_val) + _arrow(wo_val, w_val, _METRIC_DIRECTION[metric_key]))
            else:
                cells.append("--")

        lines.append(f"{r['model']} & " + " & ".join(cells) + " \\\\")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        "\\caption{Ablation study on the impact of lint alert conditioning. \\textit{With Alerts}: full input with lint diagnostics; \\textit{No Alerts}: input without lint alert messages. Arrows in the No Alerts columns compare against the With Alerts baseline: \\textcolor{green!70!black}{$\\uparrow$}/\\textcolor{green!70!black}{$\\downarrow$} = improvement; \\textcolor{red!70!black}{$\\uparrow$}/\\textcolor{red!70!black}{$\\downarrow$} = degradation.}",
        "\\label{tab:ablation_alerts}",
        "\\end{table*}",
    ])
    return "\n".join(lines)
