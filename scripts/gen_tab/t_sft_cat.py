"""SFT alert category breakdown table (appendix).

Shows per-category fixed alert counts and actual new alert totals for SFT models
at 3B, supporting the mechanism analysis in Section 4.4.
"""

from __future__ import annotations

import json
from collections import defaultdict

from gen_tab._shared import RESULT_DIR

CATEGORIES = ["error-prone", "performance", "refactor", "style", "other"]
CAT_DISPLAY = ["E-prone", "Perf", "Refac", "Style"]
CAT_COLS = ["error-prone", "performance", "refactor", "style"]

MODELS_3B = [
    ("Base", "Qwen2_5-Coder-3B"),
    ("A+L$\\rightarrow$A$'$", "finetuned_Qwen-3b_revision"),
    ("Q$\\rightarrow$A", "finetuned_Qwen-3b_codegen"),
    ("Q$\\rightarrow$A$'$", "finetuned_Qwen-3b_clean_codegen"),
]


def _compute_breakdown() -> list:
    """Return list of (display_label, fixed_by_cat, total_fixed, total_new_actual)."""
    baseline = json.load(open(RESULT_DIR / "baseline.json"))
    bl_by_sid = {b["sample_id"]: b for b in baseline}

    rows = []
    for display, model_name in MODELS_3B:
        with open(RESULT_DIR / f"{model_name}.json") as f:
            data = json.load(f)
        results = {r["sample_id"]: r for r in data["results"]}

        fixed_by_cat = defaultdict(int)
        total_new_actual = 0

        for sid, r in results.items():
            if not r.get("pass"):
                continue
            bl = bl_by_sid.get(sid)
            if not bl:
                continue
            bl_cats = bl.get("categories", {})
            out_cats = r.get("out_categories", {})

            for cat in CATEGORIES:
                orig = bl_cats.get(cat, 0)
                out = out_cats.get(cat, 0)
                if orig > out:
                    fixed_by_cat[cat] += orig - out

            # Use actual new_msg_count from evaluation (accurate)
            total_new_actual += r.get("new_msg_count", 0) or 0

        total_fixed = sum(fixed_by_cat[c] for c in CATEGORIES)
        rows.append((display, dict(fixed_by_cat), total_fixed, total_new_actual))

    return rows


def generate_sft_alert_category_breakdown_tex() -> str:
    rows = _compute_breakdown()

    lines = [
        "% ============================================================",
        "% Placement: Appendix (supports Section 4.4 mechanism analysis)",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{l rrrr rr r}",
        "\\toprule",
        "& \\multicolumn{4}{c}{\\textbf{Fixed alerts by category}}"
        " & \\textbf{\\#Fix}"
        " & \\textbf{\\#New}"
        " & \\textbf{Fix/New} \\\\",
        "\\cmidrule(lr){2-5}",
        "\\textbf{Format (3B)}"
        " & E-prone & Perf & Refac & Style"
        " & Total & Actual & Ratio \\\\",
        "\\midrule",
    ]

    for display, fixed, tf, tn in rows:
        ratio = f"{tf / tn:.1f}$\\times$" if tn > 0 else "--"
        f_cells = " & ".join(f"{fixed.get(c, 0)}" for c in CAT_COLS)
        lines.append(
            f"{display} & {f_cells} & {tf} & {tn} & {ratio} \\\\"
        )

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Per-category alert breakdown for 3B SFT models (Qwen2.5-Coder-3B). "
        "\\emph{Fixed} counts denote original alerts removed per category. "
        "\\#New is the total newly introduced alerts from the evaluation pipeline. "
        "The ``Other'' category is omitted ($<3\\%$ of alerts). "
        "Fix/New Ratio shows how many alerts are fixed per new alert introduced.}",
        "\\label{app:sft_alert_category_breakdown}",
        "\\end{table*}",
    ])
    return "\n".join(lines)
