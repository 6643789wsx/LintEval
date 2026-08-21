from __future__ import annotations

from gen_tab._shared import (
    SFT_MODEL_CONFIGS,
    LATEX_TABLE_DIR,
    load_model_summary,
    _compute_metrics_from_results,
    format_metric_value,
)


def generate_sft_results_tex() -> str:
    all_data = []
    for mc in SFT_MODEL_CONFIGS:
        group_data = []
        base_s = load_model_summary(mc["base"])
        _, base_dl = _compute_metrics_from_results(mc["base"])
        if base_s:
            p = base_s.get("pass@1", 0) * 100
            mr = base_s.get("avg_mrr_at_pass", 0) * 100
            nm = base_s.get("new_msg_pct_at_pass", 0)
            dl = base_dl or 0
            lpm_p = base_s.get("lineperfix_p", 0)
            group_data.append(("Base", p, mr, nm, dl, lpm_p))

        for fmt_label, model_name in mc["variants"]:
            s = load_model_summary(model_name)
            _, dl = _compute_metrics_from_results(model_name)
            if s:
                p = s.get("pass@1", 0) * 100
                mr = s.get("avg_mrr_at_pass", 0) * 100
                nm = s.get("new_msg_pct_at_pass", 0)
                dl_v = dl or 0
                lpm_p = s.get("lineperfix_p", 0)
                group_data.append((fmt_label, p, mr, nm, dl_v, lpm_p))

        all_data.append((mc["label"], group_data))

    lines = [
        "% ============================================================",
        "% Placement: Main Text (Section 5 - SFT Experiments)",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{llccccc}",
        "\\toprule",
        "\\textbf{Model} & \\textbf{Format} & \\textbf{Pass@1} & \\textbf{Reduction@P} & \\textbf{New@P} & \\textbf{$\\Delta$Line@P} & \\textbf{LinePerFix@P} \\\\",
        "\\midrule",
    ]

    for i, (label, group_data) in enumerate(all_data):
        if not group_data:
            continue

        best_p = max(d[1] for d in group_data)
        best_mr = max(d[2] for d in group_data)
        best_nm = min(d[3] for d in group_data)
        best_dl = min(d[4] for d in group_data)
        best_lpm = min(d[5] for d in group_data)

        for j, (fmt_label, p, mr, nm, dl_v, lpm_p) in enumerate(group_data):
            p_str = format_metric_value(p, best_p)
            mr_str = format_metric_value(mr, best_mr)
            nm_str = format_metric_value(nm, best_nm)
            dl_str = format_metric_value(dl_v, best_dl, is_pct=False)
            lpm_str = format_metric_value(lpm_p, best_lpm, is_pct=False)

            if j == 0:
                lines.append(f"\\multirow{{4}}{{*}}{{{label}}} & {fmt_label} & {p_str} & {mr_str} & {nm_str} & {dl_str} & {lpm_str} \\\\")
            else:
                lines.append(f" & {fmt_label} & {p_str} & {mr_str} & {nm_str} & {dl_str} & {lpm_str} \\\\")

        if i < len(all_data) - 1:
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Effect of training data format on \\textbf{LintEval-Lite}. Three Qwen2.5-Coder sizes (0.5B, 3B, 7B) are fine-tuned with formats A+L$\\rightarrow$A$'$, Q$\\rightarrow$A, and Q$\\rightarrow$A$'$. \\textbf{Bold} marks the best value per model group.}",
        "\\label{tab:sft_results}",
        "\\end{table*}",
    ])
    return "\n".join(lines)
