"""04_validate_revisions.py -- Validate revised code by compiling and running test cases.

Usage:
  python scripts/04_validate_revisions.py \\
      --input data/intermediate/revisions.jsonl \\
      --output data/intermediate/validated_revisions.jsonl \\
      --config configs/linter_config.yaml \\
      [--debug_limit 10] [--resume]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Make src/ importable regardless of invocation directory.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import yaml  # noqa: E402

from src.utils import (  # noqa: E402
    setup_logging,
    ensure_dir,
    load_jsonl,
    save_jsonl,
    compute_hash,
)
from src.linter_cpp import (  # noqa: E402
    run_clang_tidy,
    compile_cpp,
    count_by_category,
    parse_clang_tidy_output,
)
from src.test_runner_cpp import (  # noqa: E402
    compile_solution,
    validate_submission,
    DEFAULT_TESTLIB_INCLUDE,
)
from src.metrics import compute_sample_metrics  # noqa: E402

logger = logging.getLogger("04_validate_revisions")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str | None) -> dict:
    """Load YAML config, returning an empty dict if no path given."""
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        logger.info("Loaded config from %s", config_path)
        return cfg
    return {}


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate revised code by compiling, running linter, and executing test cases."
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Path to the input revisions JSONL file.",
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to write the validated output JSONL file.",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to the YAML linter config file (e.g. configs/linter_config.yaml).",
    )
    parser.add_argument(
        "--debug_limit", type=int, default=0,
        help="If > 0, only process this many revisions (for quick debugging).",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint: skip already-processed sample_ids.",
    )
    parser.add_argument(
        "--testlib_include", type=str, default=None,
        help="Path to directory containing testlib.h.",
    )
    parser.add_argument(
        "--max_tests", type=int, default=100,
        help="Maximum number of test cases to generate per problem.",
    )
    parser.add_argument(
        "--timeout_compile", type=int, default=30,
        help="Compilation timeout in seconds.",
    )
    parser.add_argument(
        "--timeout_run", type=int, default=5,
        help="Runtime timeout per test case in seconds.",
    )
    parser.add_argument(
        "--clang_tidy_timeout", type=int, default=30,
        help="Clang-tidy timeout in seconds.",
    )
    parser.add_argument(
        "--log_dir", type=str, default="logs",
        help="Directory for log files.",
    )
    args = parser.parse_args()

    # ---- Setup logging -----------------------------------------------------
    setup_logging(args.log_dir, "04_validate_revisions")
    logger.info("Arguments: %s", vars(args))

    # ---- Load config -------------------------------------------------------
    cfg = load_config(args.config)

    checks = cfg.get("checks", None)
    clang_tidy_timeout = args.clang_tidy_timeout or cfg.get("clang_tidy_timeout", 30)
    compile_timeout = args.timeout_compile or cfg.get("compile_timeout", 30)
    run_timeout = args.timeout_run or cfg.get("run_timeout", 5)
    testlib_include = args.testlib_include or cfg.get(
        "testlib_include", DEFAULT_TESTLIB_INCLUDE
    )
    max_tests = args.max_tests
    cpp_standard = cfg.get("cpp_standard", "c++17")

    # ---- Load revisions ----------------------------------------------------
    revisions = load_jsonl(args.input)
    logger.info("Loaded %d revisions from %s", len(revisions), args.input)

    # Filter to only revisions with extracted code
    valid_revisions = []
    for rev in revisions:
        revised_code = rev.get("revised_code")
        if revised_code and revised_code.strip():
            valid_revisions.append(rev)
        else:
            logger.debug(
                "Skipping sample_id=%s: no revised_code.",
                rev.get("sample_id", "unknown"),
            )

    logger.info(
        "Revisions with extracted code: %d / %d",
        len(valid_revisions),
        len(revisions),
    )

    if args.debug_limit > 0:
        valid_revisions = valid_revisions[: args.debug_limit]
        logger.info("Debug limit: processing %d revisions.", len(valid_revisions))

    # ---- Resume support ----------------------------------------------------
    already_done: set[str] = set()
    existing_results: dict[str, dict] = {}
    if args.resume and os.path.isfile(args.output):
        existing_records = load_jsonl(args.output)
        for rec in existing_records:
            sid = rec.get("sample_id")
            if sid is not None:
                already_done.add(str(sid))
                existing_results[str(sid)] = rec
        logger.info(
            "Resume mode: %d revisions already validated.", len(already_done)
        )

    # ---- Process each revision ---------------------------------------------
    results: list[dict] = []
    pass_count = 0
    fail_count = 0
    compile_fail_count = 0

    for idx, rev in enumerate(valid_revisions):
        sample_id = rev.get("sample_id", f"unknown_{idx}")

        # Skip if already done (resume)
        if args.resume and str(sample_id) in already_done:
            results.append(existing_results[str(sample_id)])
            # Count already-done results
            if existing_results[str(sample_id)].get("validation", {}).get("pass_at_1"):
                pass_count += 1
            else:
                fail_count += 1
            continue

        original_code = rev.get("code", "")
        original_messages = rev.get("linter_messages", [])
        revised_code = rev.get("revised_code", "")

        logger.info(
            "Validating [%d/%d] sample_id=%s", idx + 1, len(valid_revisions), sample_id
        )

        # ------------------------------------------------------------------
        # Step 1: Compile revised code
        # ------------------------------------------------------------------
        with tempfile.TemporaryDirectory() as tmpdir:
            revised_bin = os.path.join(tmpdir, "revised")
            compile_ok, compile_error = compile_solution(
                revised_code,
                revised_bin,
                timeout=compile_timeout,
            )

        if not compile_ok:
            logger.warning(
                "Revised code compilation failed for sample_id=%s: %s",
                sample_id,
                compile_error[:200],
            )
            compile_fail_count += 1

            # Compute metrics with empty revised messages
            metrics = compute_sample_metrics(
                original_code, revised_code, original_messages, [], False
            )

            result = {
                **rev,
                "validation": {
                    "compile_ok": False,
                    "compile_error": compile_error,
                    "tests_generated": 0,
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "pass_at_1": False,
                    "checker_available": False,
                    "generator_available": False,
                    "test_details": [],
                    "errors": [f"Compilation failed: {compile_error[:500]}"],
                },
                "revised_linter_messages": [],
                "revised_linter_message_count": 0,
                "revised_linter_category_counts": {},
                "metrics": metrics,
            }
            results.append(result)
            fail_count += 1
            continue

        # ------------------------------------------------------------------
        # Step 2: Run clang-tidy on revised code
        # ------------------------------------------------------------------
        revised_linter_messages = run_clang_tidy(
            revised_code,
            checks=checks,
            timeout=clang_tidy_timeout,
        )
        revised_category_counts = count_by_category(revised_linter_messages)
        revised_msg_count = len(revised_linter_messages)

        # ------------------------------------------------------------------
        # Step 3: Build problem dict for validate_submission
        # ------------------------------------------------------------------
        # The original code serves as the oracle solution. We also need
        # generator, checker, generator_cmd from the candidate record.
        problem_dict = {
            "solution": original_code,
            "generator": rev.get("generator", ""),
            "checker": rev.get("checker", ""),
            "generator_cmds": rev.get("generator_cmd", ""),
            "examples": _extract_examples(rev),
        }

        # ------------------------------------------------------------------
        # Step 4: Run full validation pipeline
        # ------------------------------------------------------------------
        with tempfile.TemporaryDirectory() as work_dir:
            validation = validate_submission(
                code=revised_code,
                problem=problem_dict,
                work_dir=work_dir,
                testlib_include=testlib_include,
                max_tests=max_tests,
                timeout_compile=compile_timeout,
                timeout_run=run_timeout,
            )

        pass_at_1 = validation.get("pass_at_1", False)
        if pass_at_1:
            pass_count += 1
        else:
            fail_count += 1

        # ------------------------------------------------------------------
        # Step 5: Compute metrics
        # ------------------------------------------------------------------
        metrics = compute_sample_metrics(
            original_code=original_code,
            revised_code=revised_code,
            original_messages=original_messages,
            revised_messages=revised_linter_messages,
            pass_at_1=pass_at_1,
        )

        # ------------------------------------------------------------------
        # Build result record
        # ------------------------------------------------------------------
        result = {
            **rev,
            "validation": validation,
            "revised_linter_messages": revised_linter_messages,
            "revised_linter_message_count": revised_msg_count,
            "revised_linter_category_counts": revised_category_counts,
            "original_messages": original_messages,
            "revised_code_hash": compute_hash(revised_code),
            "metrics": metrics,
        }
        results.append(result)

        # Progress logging
        if (idx + 1) % 5 == 0 or (idx + 1) == len(valid_revisions):
            logger.info(
                "Progress: %d/%d  pass=%d  fail=%d  compile_fail=%d",
                idx + 1,
                len(valid_revisions),
                pass_count,
                fail_count,
                compile_fail_count,
            )

    # ---- Save results ------------------------------------------------------
    output_path = Path(args.output)
    ensure_dir(output_path.parent)

    # If resuming, merge with existing
    if args.resume and existing_results:
        for rec in results:
            sid = rec.get("sample_id")
            if sid is not None:
                existing_results[str(sid)] = rec
        merged = list(existing_results.values())
    else:
        merged = results

    n_written = save_jsonl(merged, str(output_path), dedup_key="sample_id")
    logger.info("Saved %d validated results to %s", n_written, output_path)

    # ---- Summary -----------------------------------------------------------
    total = len(merged)
    n_pass = sum(
        1
        for r in merged
        if r.get("validation", {}).get("pass_at_1", False)
    )
    n_compile_ok = sum(
        1
        for r in merged
        if r.get("validation", {}).get("compile_ok", False)
    )
    n_has_metrics = sum(1 for r in merged if "metrics" in r)

    # Compute aggregate MRR for passing samples
    passing_mrrs = []
    for r in merged:
        m = r.get("metrics", {})
        if m.get("pass_at_1") and m.get("mrr_at_pass") is not None:
            passing_mrrs.append(m["mrr_at_pass"])

    avg_mrr = sum(passing_mrrs) / len(passing_mrrs) if passing_mrrs else None

    logger.info("Summary:")
    logger.info("  Total revisions: %d", total)
    logger.info("  Compile OK: %d (%.1f%%)", n_compile_ok, 100 * n_compile_ok / total if total else 0)
    logger.info("  Pass@1: %d (%.1f%%)", n_pass, 100 * n_pass / total if total else 0)
    logger.info("  With metrics: %d", n_has_metrics)
    if avg_mrr is not None:
        logger.info("  Avg MRR@Pass: %.4f (n=%d)", avg_mrr, len(passing_mrrs))
    logger.info("Done.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_examples(revision: dict) -> list[dict]:
    """Try to extract example test cases from the revision record.

    Looks for an 'examples' field in the revision dict, or returns an
    empty list if not found. The problem description field may contain
    examples in some data formats, but here we rely on pre-extracted fields.
    """
    # If examples were stored directly on the record
    examples = revision.get("examples", [])
    if examples:
        return examples

    # Try to parse from problem description (basic extraction)
    description = revision.get("description", "")
    if description:
        return _parse_examples_from_description(description)

    return []


def _parse_examples_from_description(description: str) -> list[dict]:
    """Attempt to extract example input/output pairs from a problem description.

    This is a best-effort heuristic. Returns an empty list if parsing fails.
    """
    examples: list[dict] = []
    # Common patterns: "Input:", "Output:", "Example 1:", etc.
    # This is intentionally simple -- complex descriptions may not parse well.
    lines = description.split("\n")

    current_input: list[str] = []
    current_output: list[str] = []
    mode = None  # "input" or "output"

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if lower.startswith("input") and ":" in stripped:
            # Save previous example if complete
            if mode == "output" and (current_input or current_output):
                examples.append({
                    "input": "\n".join(current_input).strip(),
                    "output": "\n".join(current_output).strip(),
                })
                current_input = []
                current_output = []
            mode = "input"
            # Rest of line after colon is part of input
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                current_input.append(rest)
        elif lower.startswith("output") and ":" in stripped:
            mode = "output"
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                current_output.append(rest)
        elif mode == "input":
            # If we hit a blank line and then non-input/output text, stop input
            if stripped:
                current_input.append(stripped)
        elif mode == "output":
            if stripped:
                current_output.append(stripped)

    # Save final example
    if current_input or current_output:
        examples.append({
            "input": "\n".join(current_input).strip(),
            "output": "\n".join(current_output).strip(),
        })

    return examples


if __name__ == "__main__":
    main()
