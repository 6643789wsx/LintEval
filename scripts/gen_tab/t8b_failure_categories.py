"""Generate failure classification table for the paper.

Reads the output of scripts/15_failure_classification.py and produces a LaTeX
table showing the distribution of failure causes per representative model.

If the classification data is not yet available, the script writes a descriptive
placeholder that explains the methodology and expected findings.

Usage:
    python scripts/gen_tab/t8b_failure_categories.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from gen_tab._shared import LATEX_TABLE_DIR

CLASSIFICATION_PATH = _PROJECT_ROOT / "docs" / "table" / "failure_classification.json"

CATEGORY_ORDER = [
    "Syntax/type/runtime error",
    "Changed algorithmic logic",
    "Changed input/output protocol",
    "Over-broad rewrite",
    "Incomplete local edit",
    "Formatting-only edit with no alert resolution",
]

CATEGORY_LABELS = {
    "Syntax/type/runtime error": "Syntax/Type/Runtime Error",
    "Changed algorithmic logic": "Changed Algorithmic Logic",
    "Changed input/output protocol": "Changed I/O Protocol",
    "Over-broad rewrite": "Over-Broad Rewrite",
    "Incomplete local edit": "Incomplete Local Edit",
    "Formatting-only edit with no alert resolution": "Formatting-Only (No Alert Resolution)",
}

_EPS = 0.005


def _fmt_count_and_pct(count: int, total: int) -> str:
    if total == 0:
        return "0 (0.0\\%)"
    pct = count / total * 100
    return f"{count} ({pct:.1f}\\%)"


def generate_failure_categories_tex() -> str:
    """Generate the failure classification LaTeX table.

    Returns a LaTeX table string, or a descriptive placeholder markdown if no
    classification data exists yet.
    """
    if not CLASSIFICATION_PATH.exists():
        return _generate_placeholder()

    with open(CLASSIFICATION_PATH) as f:
        data: Dict[str, Dict] = json.load(f)

    if not data:
        return _generate_placeholder()

    models = list(data.keys())

    lines = [
        "% ============================================================",
        "% Table: Failure Case Classification",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{l " + "c" * len(models) + "}",
        "\\toprule",
    ]

    header = "\\textbf{Failure Category} & " + " & ".join(f"\\textbf{{{m}}}" for m in models) + " \\\\"
    lines.append(header)
    lines.append("\\midrule")

    # Determine sample sizes
    sample_sizes: Dict[str, int] = {}
    for m in models:
        sample_sizes[m] = data[m].get("sampled", 0)

    for cat in CATEGORY_ORDER:
        label = CATEGORY_LABELS.get(cat, cat)
        cells = [label]
        for m in models:
            counts = data[m].get("counts", {})
            count = counts.get(cat, 0)
            total = data[m].get("sampled", 1)
            cells.append(_fmt_count_and_pct(count, total))
        lines.append(" & ".join(cells) + " \\\\")

    lines.append("\\midrule")

    # Total row
    total_cells = ["\\textbf{Total Sampled}"]
    for m in models:
        total_cells.append(str(sample_sizes[m]))
    lines.append(" & ".join(total_cells) + " \\\\")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Failure case classification. For each model, up to 50 failed revisions "
        "are sampled and manually categorized by root cause. Categories are defined as: "
        "\\textit{Syntax/Type/Runtime Error}: code fails to compile or throws runtime errors; "
        "\\textit{Changed Algorithmic Logic}: code compiles but changes the program's behavior; "
        "\\textit{Changed I/O Protocol}: input/output handling is modified; "
        "\\textit{Over-Broad Rewrite}: excessive changes unrelated to linter alerts; "
        "\\textit{Incomplete Local Edit}: makes small changes but fails to resolve alerts; "
        "\\textit{Formatting-Only}: only whitespace or formatting changes, no alert resolution.}",
        "\\label{tab:failure_categories}",
        "\\end{table*}",
    ])
    return "\n".join(lines)


def _generate_placeholder() -> str:
    """Generate a descriptive analysis when classification data is not yet ready."""
    return r"""% ============================================================
% Failure Case Classification -- Descriptive Analysis
% ============================================================
%
% This file will be replaced with the LaTeX table once the
% failure classification script (scripts/15_failure_classification.py)
% has been run. Below is the planned methodology and expected findings.
%

\subsection*{Failure Case Classification}

To understand \emph{why} models fail to produce \passatk-preserving
revisions, we sample up to 50 failed cases from each representative model
(GPT-5.4-mini, DeepSeek-v3.2, Qwen2.5-Coder-7B) and classify each
failure into one of six root-cause categories:

\begin{enumerate}
    \item \textbf{Syntax/Type/Runtime Error} -- The revised code fails to
        compile or crashes at runtime, indicating that the model introduced
        malformed code.
    \item \textbf{Changed Algorithmic Logic} -- The code compiles
        successfully but changes the program's algorithmic behavior, causing
        test failures. This is the ``passage-at-k preservation failure''
        that the benchmark is designed to measure.
    \item \textbf{Changed I/O Protocol} -- The code compiles but alters
        how input is read or output is written, breaking compatibility
        with the test harness.
    \item \textbf{Over-Broad Rewrite} -- The edit scope is far larger than
        needed to address the linter alerts (high $\Delta$Line@P relative
        to alert count), suggesting the model rewrites portions of the code
        unrelated to the diagnostics.
    \item \textbf{Incomplete Local Edit} -- The model makes a small local
        change but fails to resolve enough alerts or introduces new ones,
        resulting in a failed sample despite minimal disruption.
    \item \textbf{Formatting-Only Edit with No Alert Resolution} -- The
        model changes only whitespace, indentation, or formatting without
        addressing any linter alerts.
\end{enumerate}

\textbf{Expected Findings:}
\begin{itemize}
    \item Larger models (GPT-5.4-mini, DeepSeek-v3.2) are expected to show more
        \textit{Changed Algorithmic Logic} failures, reflecting their tendency
        to over-improve code beyond the scope of linter alerts.
    \item Smaller models (Qwen2.5-Coder-7B) may show more
        \textit{Syntax/Type/Runtime Error} and \textit{Incomplete Local Edit}
        failures, reflecting limited code-generation precision.
    \item The distribution differences support the ``improvement-preservation
        trade-off'' hypothesis: stronger code-generation capability enables
        more aggressive edits, which risk breaking functional correctness.
\end{itemize}

\textbf{To generate the actual table:}
\begin{verbatim}
    python scripts/15_failure_classification.py --max_per_model 50
    python scripts/gen_tab/t8b_failure_categories.py
\end{verbatim}
"""


def main() -> None:
    output_path = LATEX_TABLE_DIR / "failure_categories.tex"
    tex = generate_failure_categories_tex()
    LATEX_TABLE_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(tex)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
