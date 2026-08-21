"""Generate grounding ablation table: diagnostic grounding of linter alerts.

Compares 6 prompt variants on 3 representative models:
  - Full: standard alerts with rule ID, message text, and line number
  - No Alerts: generic code improvement prompt
  - Shuffled Alerts: alerts from a DIFFERENT file (same language)
  - Rule-Only: only rule IDs, no diagnostic text
  - Message-Only: diagnostic text without line numbers
  - Location-Only: only line numbers, no rule/message

Usage:
    python scripts/gen_tab/t7b_grounding_ablation.py [--output path]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from gen_tab._shared import (
    RESULT_DIR,
    LATEX_TABLE_DIR,
    load_model_summary,
    _compute_metrics_from_results,
)

# Representative models for ablation
REPRESENTATIVE_MODELS: List[Tuple[str, str]] = [
    ("GPT-5.4-mini", "GPT-5_4-mini"),
    ("DeepSeek-v3.2", "DeepSeek-v3_2-128K"),
    ("Qwen2.5-Coder-7B", "Qwen2_5-Coder-7B"),
]

# Ablation variants: (label, suffix, description)
ABLATION_VARIANTS: List[Tuple[str, str, str]] = [
    ("Full (Standard)", "", "standard alerts with rule ID, message text, and line number"),
    ("No Alerts", "_no_msg", "generic code improvement prompt without any linter messages"),
    ("Shuffled Alerts", "_shuffled", "alerts from a different file in the same language"),
    ("Rule-Only", "_rule_only", "only rule IDs (check\\_name), no diagnostic text"),
    ("Message-Only", "_message_only", "diagnostic text without line numbers"),
    ("Location-Only", "_location_only", "only line numbers and severity, no rule ID or message"),
]

_EPS = 0.005


def _fmt(val: Optional[float], best: Optional[float] = None, is_pct: bool = True) -> str:
    """Format a value, optionally bolding the best."""
    if val is None:
        return "--"
    s = f"{val:.1f}\\%" if is_pct else f"{val:.1f}"
    if best is not None and abs(val - best) < _EPS:
        return f"\\textbf{{{s}}}"
    return s


def _compute_variant_metrics(model_name: str, suffix: str):
    """Load summary + detailed metrics for a specific ablation variant."""
    result_name = f"{model_name}{suffix}"
    summary = load_model_summary(result_name)
    new_p, dl = _compute_metrics_from_results(result_name)
    return {
        "summary": summary,
        "new_p": new_p,
        "delta_line": dl,
    }


def generate_grounding_ablation_tex() -> str:
    """Generate the diagnostic grounding ablation LaTeX table."""
    # Collect all data
    rows: List[Dict] = []
    for model_display, model_name in REPRESENTATIVE_MODELS:
        for variant_label, suffix, _desc in ABLATION_VARIANTS:
            data = _compute_variant_metrics(model_name, suffix)
            summary = data["summary"]
            if summary:
                rows.append({
                    "model": model_display,
                    "variant": variant_label,
                    "suffix": suffix,
                    "pass": summary.get("pass@1", 0) * 100,
                    "reduction": summary.get("avg_mrr_at_pass", 0) * 100,
                    "new": data["new_p"] or 0,
                    "delta_line": data["delta_line"] or 0,
                    "lpm": summary.get("lineperfix_p", 0),
                })

    if not rows:
        return "% No grounding ablation data available yet. Run with --ablation_mode first."

    # Find best per-model for bolding
    models_seen: Dict[str, List[Dict]] = {}
    for r in rows:
        models_seen.setdefault(r["model"], []).append(r)

    best_per_model: Dict[str, Dict[str, float]] = {}
    for model, model_rows in models_seen.items():
        best = {}
        best["pass"] = max(r["pass"] for r in model_rows)
        best["reduction"] = max(r["reduction"] for r in model_rows)
        best["new"] = min(r["new"] for r in model_rows)
        best["delta_line"] = min(r["delta_line"] for r in model_rows)
        best["lpm"] = min(r["lpm"] for r in model_rows)
        best_per_model[model] = best

    lines = [
        "% ============================================================",
        "% Table: Diagnostic Grounding Ablation",
        "% ============================================================",
        "\\begin{table*}[t]",
        "\\centering",
        "\\small",
        "\\resizebox{\\linewidth}{!}{",
        "\\begin{tabular}{ll ccccc}",
        "\\toprule",
        "\\textbf{Model} & \\textbf{Prompt Variant} & \\textbf{Pass@1} & \\textbf{Reduction@P} & \\textbf{New@P} & \\textbf{$\\Delta$Line@P} & \\textbf{LinePerFix@P} \\\\",
        "\\midrule",
    ]

    for model_display, model_name in REPRESENTATIVE_MODELS:
        model_rows = [r for r in rows if r["model"] == model_display]
        if not model_rows:
            continue
        model_best = best_per_model[model_display]

        for idx, r in enumerate(model_rows):
            is_first = (idx == 0)

            pass_s = _fmt(r["pass"], model_best["pass"], is_pct=True)
            red_s = _fmt(r["reduction"], model_best["reduction"], is_pct=True)
            new_s = _fmt(r["new"], model_best["new"], is_pct=True)
            dl_s = _fmt(r["delta_line"], model_best["delta_line"], is_pct=False)
            lpm_s = _fmt(r["lpm"], model_best["lpm"], is_pct=False)

            if is_first:
                n_rows = len(model_rows)
                m_cell = f"\\multirow{{{n_rows}}}{{*}}{{{model_display}}}"
            else:
                m_cell = ""

            lines.append(
                f"{m_cell} & {r['variant']} & {pass_s} & {red_s} & {new_s} & {dl_s} & {lpm_s} \\\\"
            )

        lines.append("\\midrule")

    # Remove trailing midrule
    if lines[-1] == "\\midrule":
        lines.pop()

    # Caption note
    caption = (
        "Diagnostic grounding ablation: how different representations of linter alerts affect "
        "model performance. \\textit{Full (Standard)}: complete alerts with rule ID, message text, "
        "and line number. \\textit{Shuffled Alerts}: each sample receives alerts from a different "
        "file of the same language, testing whether the model grounds specific diagnostics. "
        "\\textit{Rule-Only}: rule ID only, no diagnostic description. "
        "\\textit{Message-Only}: diagnostic text without line numbers. "
        "\\textit{Location-Only}: line numbers and severity only, no rule ID or message. "
        "\\textbf{Bold} marks the best value per metric per model."
    )

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "}",
        f"\\caption{{{caption}}}",
        "\\label{tab:grounding_ablation}",
        "\\end{table*}",
    ])
    return "\n".join(lines)


def main() -> None:
    output_path = LATEX_TABLE_DIR / "grounding_ablation.tex"
    if len(sys.argv) > 2 and sys.argv[1] == "--output":
        output_path = Path(sys.argv[2])

    tex = generate_grounding_ablation_tex()
    LATEX_TABLE_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(tex)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
