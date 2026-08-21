from __future__ import annotations

from gen_tab._shared import LATEX_TABLE_DIR


def generate_cross_language_mapping_tex() -> str:
    """Generate taxonomy mapping table: categories, counts, and linter rule families."""
    lines = [
        "% ============================================================",
        "% Placement: Main Text (Section 2 - Taxonomy)",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{lc lll}",
        "\\toprule",
        "\\textbf{Category} & \\textbf{Lint Alerts} & \\textbf{C++ (clang-tidy)} & \\textbf{Python (Pylint)} & \\textbf{Java (PMD)} \\\\",
        "\\midrule",
        "Error-prone & 18,434  & \\texttt{bugprone-*}    & \\texttt{error}      & \\texttt{Error Prone}, \\texttt{Security} \\\\",
        "Performance & 17,776  & \\texttt{performance-*} & \\texttt{performance}& \\texttt{Performance}, \\texttt{Multithreading} \\\\",
        "Refactor    & 17,977  & \\texttt{modernize-*}   & \\texttt{refactor}   & \\texttt{Design} \\\\",
        "Style       & 115,458 & \\texttt{readability-*} & \\texttt{convention} & \\texttt{Code Style}, \\texttt{Best Practices} \\\\",
        "Other       & 2,017   & \\texttt{other}         & \\texttt{other}      & \\texttt{other} \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Cross-language taxonomy of lint alert categories in LintEval. Counts show the number of alerts in each diagnostic category. Representative rule families illustrate how each category maps to language-specific linter conventions.}",
        "\\label{tab:cross_language_mapping}",
        "\\end{table*}",
    ]
    return "\n".join(lines)
