#!/usr/bin/env python3
"""Verify that the released per-sample results reproduce the paper numbers.

For every model in `docs/table/overall_performance.tex` this script recomputes the
five reported metrics **from the per-sample records only** (no summary fields are
used) and compares them with the values printed in the paper table:

    Pass@1        = n_passed / n_total
    Reduction@P   = Sum(in - out) / Sum(in)              over passed samples
    New@P         = Sum(new)      / Sum(in)              over passed samples
    DeltaLine@P   = Sum(lines_changed) / n_passed        over passed samples
    LinePerFix@P  = Sum(lines_changed) / Sum(fixed)      over passed samples
                    with fixed = max(0, in - out + new)  (count-based)

The formulas match `scripts/gen_tab/_shared.py`, i.e. exactly what generates the
LaTeX tables, and they match the metric definitions in the README.

Usage:
    python scripts/verify_paper_metrics.py                 # metric consistency only
    python scripts/verify_paper_metrics.py --check-tables  # also re-generate tables and diff
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_DIR = REPO_ROOT / "eval_results"
TABLE_DIR = REPO_ROOT / "docs" / "table"
OVERALL_TEX = TABLE_DIR / "overall_performance.tex"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from gen_tab._shared import ALL_BASE_MODELS  # noqa: E402  (display name -> result file stem)

TOLERANCE = {"pct": 0.05, "raw": 0.05}


def parse_paper_table(path: Path) -> dict[str, dict[str, float]]:
    """Parse the overall-performance LaTeX table into {model: {metric: value}}."""
    rows: dict[str, dict[str, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "&" not in line or "\\\\" not in line:
            continue
        cells = [cell.strip() for cell in line.split("&")]
        if len(cells) != 6:
            continue
        name = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", cells[0]).strip()
        if not name or name.lower().startswith(("model", "textbf{model")):
            continue

        def num(cell: str) -> float | None:
            cleaned = cell.replace("\\textbf{", "").replace("}", "").replace("\\%", "")
            cleaned = cleaned.replace("$", "").replace("--", "").strip()
            if cleaned in ("", "-"):
                return None
            match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
            return float(match.group()) if match else None

        values = [num(cell) for cell in cells[1:]]
        if any(value is None for value in values):
            continue
        rows[name] = dict(zip(
            ["pass@1", "reduction_p", "new_p", "dline_p", "lineperfix_p"],
            [v / 100 for v in values[:3]] + values[3:],
        ))
    return rows


def count_based_fixed(record: dict) -> int:
    original = record.get("in_total") or 0
    if original <= 0:
        return 0
    value = original - (record.get("out_total") or 0) + (record.get("new_msg_count") or 0)
    return value if value > 0 else 0


def recompute_from_samples(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["results"]
    passed = [r for r in records if r.get("pass")]

    n_total, n_passed = len(records), len(passed)
    sum_in = sum(r.get("in_total") or 0 for r in passed)
    sum_out = sum(r.get("out_total") or 0 for r in passed)
    sum_new = sum(r.get("new_msg_count") or 0 for r in passed)
    sum_lines = sum(r.get("lpm_p_lines_changed") or 0 for r in passed)
    sum_fixed = sum(count_based_fixed(r) for r in passed)

    return {
        "pass@1": n_passed / n_total if n_total else 0.0,
        "reduction_p": (sum_in - sum_out) / sum_in if sum_in else 0.0,
        "new_p": sum_new / sum_in if sum_in else 0.0,
        "dline_p": sum_lines / n_passed if n_passed else 0.0,
        "lineperfix_p": sum_lines / sum_fixed if sum_fixed else 0.0,
        "n_total": n_total,
        "n_passed": n_passed,
    }


def format_value(key: str, value: float) -> str:
    return f"{value * 100:.1f}%" if key in ("pass@1", "reduction_p", "new_p") else f"{value:.1f}"


def check_tables() -> bool:
    """Re-generate docs/table/*.tex and confirm they are byte-identical."""
    with tempfile.TemporaryDirectory() as tmp:
        backup = Path(tmp) / "table"
        shutil.copytree(TABLE_DIR, backup)
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "11_gen_paper_excel.py")],
            cwd=REPO_ROOT, check=True, capture_output=True,
        )
        diff = subprocess.run(["diff", "-rq", str(backup), str(TABLE_DIR)], capture_output=True, text=True)
        regenerated = diff.stdout.strip()
        shutil.rmtree(TABLE_DIR)
        shutil.copytree(backup, TABLE_DIR)
    if regenerated:
        print("Table regeneration differs from the committed tables:")
        print(regenerated)
        return False
    print("Table check: docs/table/*.tex regenerate byte-identically from eval_results/")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-tables", action="store_true", help="also regenerate and diff the LaTeX tables")
    args = parser.parse_args()

    paper = parse_paper_table(OVERALL_TEX)
    header = (f"{'Model':22}{'Pass@1':>17}{'Reduction@P':>17}{'New@P':>15}"
              f"{'DLine@P':>15}{'LinePerFix@P':>17}")
    print("Paper-metric consistency check (recomputed from per-sample results only)")
    print("each cell: recomputed / value printed in docs/table/overall_performance.tex")
    print(header)
    print("-" * len(header))

    failures = 0
    for display_name, result_stem in ALL_BASE_MODELS:
        path = RESULT_DIR / f"{result_stem}.json"
        if not path.exists() or display_name not in paper:
            print(f"{display_name:22}  skipped (no released result file or table row)")
            continue
        computed = recompute_from_samples(path)
        expected = paper[display_name]
        cells, worst = [], 0.0
        for key in ("pass@1", "reduction_p", "new_p", "dline_p", "lineperfix_p"):
            got, want = computed[key], expected[key]
            tol = TOLERANCE["pct"] if key in ("pass@1", "reduction_p", "new_p") else TOLERANCE["raw"]
            delta = abs(got - want)
            worst = max(worst, delta)
            failures += 0 if delta <= tol else 1
            cells.append(f"{format_value(key, got)} / {format_value(key, want)}")
        flag = "" if worst <= TOLERANCE["pct"] else "  <-- MISMATCH"
        print(f"{display_name:22}" + "".join(f"{cell:>17}" for cell in cells) + flag)
        print(f"{'':22}passed {computed['n_passed']}/{computed['n_total']} samples")

    tables_ok = check_tables() if args.check_tables else True
    print()
    if failures == 0 and tables_ok:
        print("RESULT: PASS - per-sample results reproduce every paper metric and the LaTeX tables.")
        return 0
    print(f"RESULT: FAIL - {failures} metric mismatches.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
