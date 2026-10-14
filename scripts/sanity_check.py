#!/usr/bin/env python3
"""
Sanity check for LintEval.

Runs a quick end-to-end verification on the demo dataset to ensure:
  1. Linters work for C++ / Python / Java
  2. Metrics can be computed
  3. The testlib-based validation loop (compile + generate tests + run + check) works
  4. LaTeX table generation modules can be imported

Usage:
    python scripts/sanity_check.py
"""

import json
import sys
import tempfile
from pathlib import Path

# Paths are always resolved relative to this file, so the script can be run
# from any working directory.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from linter_factory import run_linter  # noqa: E402
from metrics import compute_line_churn  # noqa: E402
from test_runner_multi import validate_submission_multi  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("LintEval Sanity Check")
    print("=" * 60)
    print()

    # ---- 1. Load demo data (eval format) ----
    demo_file = PROJECT_ROOT / "lite" / "demo_100.jsonl"
    if not demo_file.exists():
        print(f"Error: demo data not found: {demo_file}")
        return 1
    samples = [json.loads(line) for line in open(demo_file, encoding="utf-8") if line.strip()]
    print(f"Loaded {len(samples)} demo samples from {demo_file}")
    print()

    # ---- 2. Linters ----
    print("Testing Linters:")
    print("-" * 60)
    tested = set()
    ok_linters = True
    for sample in samples:
        lang = sample.get("language")
        if lang in ("cpp", "py3", "java") and lang not in tested:
            code = sample.get("code", "")
            try:
                msgs = run_linter(code, lang)
                print(f"  OK  {lang:>4}: {len(msgs)} linter messages")
            except Exception as e:
                print(f"  FAIL {lang:>4}: linter failed: {e}")
                ok_linters = False
            tested.add(lang)
    if not tested:
        print("  FAIL: no samples found for cpp/py3/java in demo data")
        ok_linters = False
    print()

    # ---- 3. Metrics ----
    print("Testing Metrics:")
    print("-" * 60)
    original = "int main(){ return 0; }\n"
    revised = "int main() {\n    return 0;\n}\n"
    churn = compute_line_churn(original, revised)
    print(f"  OK line churn computed: {churn}")
    print()

    # ---- 4. testlib validation loop (compile + tests) ----
    print("Testing testlib Validation Loop:")
    print("-" * 60)
    val_ok = True
    for sample in samples:
        if sample.get("language") != "cpp":
            continue
        problem = {
            "solution": sample.get("code", ""),
            "generator": sample.get("generator", ""),
            "checker": sample.get("checker", ""),
            "generator_cmds": sample.get("generator_cmd", ""),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_submission_multi(
                code=sample.get("code", ""),
                language="cpp",
                problem=problem,
                work_dir=tmpdir,
                testlib_include=str(PROJECT_ROOT / "tools"),
                max_tests=3,
                timeout_compile=30,
                timeout_run=5,
            )
        print(f"  OK {sample.get('sample_id')}: compile_ok={result.get('compile_ok')}, "
              f"tests={result.get('tests_generated')}, passed={result.get('tests_passed')}")
        if result.get("errors"):
            print(f"    errors: {result['errors'][:2]}")
        val_ok = val_ok and result.get("compile_ok", False)
        break  # one sample is enough for the sanity check
    print()

    # ---- 5. Table generation imports ----
    print("Testing Table Generation:")
    print("-" * 60)
    try:
        from gen_tab.generate_all_tables import main as gen_main  # noqa: F401
        print("  OK gen_tab modules importable")
    except Exception as e:
        print(f"  FAIL error importing gen_tab: {e}")
    print()

    print("=" * 60)
    all_ok = ok_linters and val_ok
    print("Sanity Check Complete!")
    print(f"  - Linters: {'OK' if ok_linters else 'FAILED'}")
    print(f"  - Metrics: OK")
    print(f"  - Validation loop: {'OK' if val_ok else 'FAILED'}")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
