from __future__ import annotations

from gen_tab._shared import LATEX_TABLE_DIR


def generate_dataset_statistics_tex() -> str:
    lines = [
        "% ============================================================",
        "% Placement: Main Text (Section 2 - Dataset)",
        "% ============================================================",
        "% T1: Dataset Statistics",
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{lr}",
        "\\toprule",
        "\\textbf{Metric} & \\textbf{Value} \\\\",
        "\\midrule",
        "Unique problems & 3,999 \\\\",
        "Samples & 13,061 \\\\",
        "Total lint alerts & 171,662 \\\\",
        "Avg. alerts per sample & 13.1 \\\\",
        "Avg. LOC per sample & 61.0 \\\\",
        "Unique alert types & 396 \\\\",
        "\\midrule",
        "\\multicolumn{2}{l}{\\textit{Language counts}} \\\\",
        "C++ & 6,165 \\\\",
        "Python & 4,221 \\\\",
        "Java & 2,675 \\\\",
        "\\midrule",
        "\\multicolumn{2}{l}{\\textit{Alert category distribution}} \\\\",
        "Error-prone & 18,434 \\\\",
        "Performance & 17,776 \\\\",
        "Refactor & 17,977 \\\\",
        "Style & 115,458 \\\\",
        "Other & 2,017 \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Dataset statistics for \\textbf{LintEval}. The dataset contains 13,061 competitive-programming samples across three languages, each annotated with lint alerts.}",
        "\\label{tab:dataset_statistics}",
        "\\end{table}",
    ]
    return "\n".join(lines)
