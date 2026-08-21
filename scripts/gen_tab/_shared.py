"""Shared constants and helpers for gen_tab modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

RESULT_DIR = _PROJECT_ROOT / "eval_results"
BASELINE_PATH = RESULT_DIR / "baseline.json"
LATEX_TABLE_DIR = _PROJECT_ROOT / "docs" / "table"

LANG_NAMES = {"cpp": "C++", "py3": "Python", "java": "Java"}
LANG_LINTERS = {"cpp": "clang-tidy", "py3": "Pylint", "java": "PMD"}

ALERT_COUNT_GROUPS = [
    ("1 alert", 1, 1),
    ("2--5 alerts", 2, 5),
    ("6--10 alerts", 6, 10),
    (">10 alerts", 11, 9999),
]

MODEL_GROUPS = {
    "closed_source": [
        ("GPT-5.2", "GPT-5_2"),
        ("GPT-5.4-mini", "GPT-5_4-mini"),
    ],
    "open_source_small": [
        ("Qwen2.5-Coder-0.5B", "Qwen2_5-Coder-0_5B"),
        ("Qwen2.5-Coder-3B", "Qwen2_5-Coder-3B"),
        ("Qwen2.5-Coder-7B", "Qwen2_5-Coder-7B"),
        ("Llama-3.2-1B", "Llama-3_2-1B-Instruct"),
        ("Llama-3.2-3B", "Llama-3_2-3B-Instruct"),
    ],
    "open_source_large": [
        ("DeepSeek-v3.2", "DeepSeek-v3_2-128K"),
        ("Qwen2.5-Coder-32B", "Qwen2_5-Coder-32B-Instruct"),
    ],
}

ALL_BASE_MODELS = (
    MODEL_GROUPS["closed_source"] +
    MODEL_GROUPS["open_source_large"] +
    MODEL_GROUPS["open_source_small"]
)

ABLATION_MODELS = [
    ("GPT-5.4-mini", "GPT-5_4-mini"),
    ("DeepSeek-v3.2", "DeepSeek-v3_2-128K"),
    ("Qwen2.5-Coder-0.5B", "Qwen2_5-Coder-0_5B"),
    ("Qwen2.5-Coder-7B", "Qwen2_5-Coder-7B"),
]

SFT_MODEL_CONFIGS = [
    {
        "label": "0.5B",
        "base": "Qwen2_5-Coder-0_5B",
        "variants": [
            ("A+L$\\rightarrow$A$'$", "finetuned_Qwen-05b_revision"),
            ("Q$\\rightarrow$A", "finetuned_Qwen-05b_codegen"),
            ("Q$\\rightarrow$A$'$", "finetuned_Qwen-05b_clean_codegen"),
        ],
    },
    {
        "label": "3B",
        "base": "Qwen2_5-Coder-3B",
        "variants": [
            ("A+L$\\rightarrow$A$'$", "finetuned_Qwen-3b_revision"),
            ("Q$\\rightarrow$A", "finetuned_Qwen-3b_codegen"),
            ("Q$\\rightarrow$A$'$", "finetuned_Qwen-3b_clean_codegen"),
        ],
    },
    {
        "label": "7B",
        "base": "Qwen2_5-Coder-7B",
        "variants": [
            ("A+L$\\rightarrow$A$'$", "finetuned_Qwen-7b_revision"),
            ("Q$\\rightarrow$A", "finetuned_Qwen-7b_codegen"),
            ("Q$\\rightarrow$A$'$", "finetuned_Qwen-7b_clean_codegen"),
        ],
    },
]


# Only separate closed-source from open-source
_GROUP_LAST = {
    MODEL_GROUPS["closed_source"][-1][1],   # GPT-5_4-mini
}


def needs_group_separator(model_name: str) -> bool:
    """True if this model is the last in its group — insert \\midrule after it."""
    return model_name in _GROUP_LAST


def load_baseline() -> List[Dict]:
    return json.load(open(BASELINE_PATH))


def load_model_summary(model_name: str) -> Optional[Dict]:
    json_path = RESULT_DIR / f"{model_name}.json"
    if not json_path.exists():
        return None
    with open(json_path, 'r') as f:
        data = json.load(f)

    # Handle baseline.json which is a flat list of results
    if isinstance(data, list):
        results = data
        summary = {}
    else:
        summary = dict(data.get("summary", {}))
        results = data.get("results", [])

    # Recalculate LinePerFix@P: include ALL pass samples in numerator and denominator
    # Numerator: sum of lines_changed for all pass samples
    # Denominator: sum of fixed_count (original alerts removed) for all pass samples
    total_lines = 0
    total_fixed = 0
    total_new = 0
    total_orig = 0
    total_net_reduction = 0
    n_pass = 0
    for r in results:
        if r.get("pass"):
            in_t = r.get("in_total", 0) or 0
            out_t = r.get("out_total", 0) or 0
            lines_changed = r.get("lpm_p_lines_changed", 0) or 0
            fixed_count = count_based_fixed(r)
            total_lines += lines_changed
            total_fixed += fixed_count
            total_new += r.get("new_msg_count", 0) or 0
            total_orig += in_t
            total_net_reduction += (in_t - out_t)
            n_pass += 1
    lineperfix_p = total_lines / total_fixed if total_fixed > 0 else 0
    # Corpus-level New@P: sum(New) / sum(|L|) * 100
    new_msg_pct = (total_new / total_orig * 100) if total_orig > 0 else 0
    avg_lines = total_lines / n_pass if n_pass > 0 else 0
    # Corpus-level Reduction@P: sum(Fixed - New) / sum(|L|) = sum(in - out) / sum(in)
    corpus_reduction = total_net_reduction / total_orig if total_orig > 0 else 0

    if summary:
        summary["lineperfix_p"] = lineperfix_p
        summary["new_msg_pct_at_pass"] = new_msg_pct
        summary["avg_lines_at_pass"] = avg_lines
        summary["avg_mrr_at_pass"] = corpus_reduction
    return summary


def count_based_fixed(r: Dict) -> int:
    """Count-consistent fixed-message count, derived from stored scalars.

    Equals what the corrected ``compute_fixed_messages`` produces:
    ``fixed = original_total - revised_total + new`` (clamped at 0). Replaces the
    legacy set-based ``lpm_p_fixed_count`` so LinePerFix@P uses the SAME
    (count-based) identity as Reduction@P and New@P.
    """
    o = r.get("in_total") or 0
    if o <= 0:
        return 0
    val = o - (r.get("out_total") or 0) + (r.get("new_msg_count") or 0)
    return val if val > 0 else 0


def load_model_results(model_name: str) -> Dict[str, Dict]:
    json_path = RESULT_DIR / f"{model_name}.json"
    if not json_path.exists():
        return {}
    with open(json_path, 'r') as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("results", [])
    results = {}
    for item in items:
        sample_id = item["sample_id"]
        results[sample_id] = {
            "pass": item.get("pass", False),
            "reduction_at_pass": item.get("mrr_at_pass", 0),
            "new_count": item.get("new_msg_count", 0),
            "lineperfix_p_lines_changed": item.get("lpm_p_lines_changed", 0),
            "lineperfix_p_fixed_count": count_based_fixed(item),
            "lineperfix_p_has_fix": item.get("lpm_p_has_fix", False),
            "out_total": item.get("out_total"),
            "in_total": item.get("in_total"),
        }
    return results


def format_metric_value(value: Optional[float], best: Optional[float], is_pct: bool = True) -> str:
    """Format a metric value and bold the best value in the column."""
    if value is None:
        return "--"
    if best is not None and abs(value - best) < 0.01:
        return f"\\textbf{{{value:.1f}\\%}}" if is_pct else f"\\textbf{{{value:.1f}}}"
    return f"{value:.1f}\\%" if is_pct else f"{value:.1f}"


def _compute_metrics_from_results(model_name: str):
    """Compute New@P and DeltaLine@P from individual results."""
    results = load_model_results(model_name)
    if not results:
        return None, None
    total_new = 0; total_orig = 0; total_lc = 0; n_pass = 0
    for sid, r in results.items():
        if r.get("pass"):
            total_new += r.get("new_count", 0) or 0
            total_orig += r.get("in_total", 0) or 0
            total_lc += r.get("lineperfix_p_lines_changed", 0) or 0
            n_pass += 1
    new_p = (total_new / total_orig * 100) if total_orig > 0 else 0
    delta_line = total_lc / n_pass if n_pass > 0 else 0
    return new_p, delta_line
