"""02_extract_linter_messages.py -- Run linter on each candidate, extract messages.

Supports C++ (clang-tidy), Python (pylint), and Java (PMD) via linter_factory.
Uses multiprocessing for parallel linting across candidates.

Usage:
  python scripts/02_extract_linter_messages.py \\
      --input data/intermediate/candidates.jsonl \\
      --output data/intermediate/candidates_with_linter.jsonl \\
      --config configs/linter_config.yaml \\
      [--debug_limit 10] [--resume] [--workers 8]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from src.linter_factory import (  # noqa: E402
    run_linter,
    compile_code,
    count_by_category,
)

logger = logging.getLogger("02_extract_linter_messages")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str | None) -> dict:
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        logger.info("Loaded config from %s", config_path)
        return cfg
    return {}


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def passes_filters(
    candidate: dict,
    min_messages: int,
    max_messages: int,
    min_loc: int,
    max_loc: int,
) -> tuple[bool, str]:
    code = candidate.get("code", "")
    loc = len([line for line in code.splitlines() if line.strip()])

    if loc < min_loc:
        return False, f"loc={loc} < min_loc={min_loc}"
    if loc > max_loc:
        return False, f"loc={loc} > max_loc={max_loc}"

    n_msgs = len(candidate.get("linter_messages", []))
    if n_msgs < min_messages:
        return False, f"messages={n_msgs} < min_messages={min_messages}"
    if n_msgs > max_messages:
        return False, f"messages={n_msgs} > max_messages={max_messages}"

    return True, ""


# ---------------------------------------------------------------------------
# Worker function (runs in subprocess)
# ---------------------------------------------------------------------------

def process_single_candidate(args_tuple):
    """Process a single candidate: compile + lint.

    Receives and returns a plain dict to avoid pickling issues.
    """
    (cand, language, cpp_standard, compile_timeout,
     linter_kwargs, min_loc, max_loc) = args_tuple

    sample_id = cand.get("sample_id", "unknown")
    code = cand.get("code", "")

    if not code or not code.strip():
        cand["compile_ok"] = False
        cand["compile_error"] = "empty code"
        cand["linter_messages"] = []
        cand["linter_category_counts"] = {}
        cand["linter_message_count"] = 0
        cand["passes_filters"] = False
        cand["filter_reason"] = "empty code"
        cand["code_hash"] = ""
        cand["loc"] = 0
        return cand

    # Compile / syntax check
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_path = os.path.join(tmpdir, "a.out")
        compile_kwargs = {}
        if language == "cpp":
            compile_kwargs = {"output_path": bin_path, "std": cpp_standard, "timeout": compile_timeout}
        elif language == "java":
            compile_kwargs = {"timeout": compile_timeout}
        compile_success, compile_error = compile_code(code, language, **compile_kwargs)

    cand["compile_ok"] = compile_success
    cand["compile_error"] = compile_error if not compile_success else ""

    # Run linter
    linter_messages = run_linter(code, language, **linter_kwargs)
    cand["linter_messages"] = linter_messages

    category_counts = count_by_category(linter_messages)
    cand["linter_category_counts"] = category_counts
    cand["linter_message_count"] = len(linter_messages)

    cand["code_hash"] = compute_hash(code)
    cand["loc"] = len([line for line in code.splitlines() if line.strip()])

    return cand


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run linter on each candidate and extract messages (multi-language, parallel)."
    )
    parser.add_argument("--input", type=str, required=True)
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--debug_limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log_dir", type=str, default="logs")
    parser.add_argument("--workers", type=int, default=8,
                        help="Number of parallel workers (default: 8).")
    args = parser.parse_args()

    setup_logging(args.log_dir, "02_extract_linter_messages")
    logger.info("Arguments: %s", vars(args))

    cfg = load_config(args.config)

    clang_tidy_timeout = cfg.get("clang_tidy_timeout", 30)
    compile_timeout = cfg.get("compile_timeout", 30)
    cpp_standard = cfg.get("cpp_standard", "c++17")
    checks = cfg.get("checks", None)

    min_messages = cfg.get("min_messages", 1)
    max_messages = cfg.get("max_messages", 200)
    min_loc = cfg.get("min_loc", 5)
    max_loc = cfg.get("max_loc", 500)

    candidates = load_jsonl(args.input)
    logger.info("Loaded %d candidates from %s", len(candidates), args.input)

    if args.debug_limit > 0:
        candidates = candidates[: args.debug_limit]
        logger.info("Debug limit: processing %d candidates.", len(candidates))

    # Resume support
    already_done: set[str] = set()
    existing_results: dict[str, dict] = {}
    if args.resume and os.path.isfile(args.output):
        existing_records = load_jsonl(args.output)
        for rec in existing_records:
            sid = rec.get("sample_id")
            if sid is not None:
                already_done.add(str(sid))
                existing_results[str(sid)] = rec
        logger.info("Resume mode: %d candidates already processed.", len(already_done))

    # Filter out already-done candidates
    todo = []
    for idx, cand in enumerate(candidates):
        sample_id = cand.get("sample_id", f"unknown_{idx}")
        if args.resume and str(sample_id) in already_done:
            continue
        todo.append(cand)

    logger.info("Processing %d candidates with %d workers", len(todo), args.workers)

    # Build work items
    work_items = []
    for cand in todo:
        language = cand.get("language", "cpp")
        linter_kwargs = {}
        if language == "cpp":
            linter_kwargs = {"checks": checks, "timeout": clang_tidy_timeout}
        work_items.append((
            cand, language, cpp_standard, compile_timeout,
            linter_kwargs, min_loc, max_loc,
        ))

    # Process in parallel
    results: list[dict] = list(existing_results.values())
    completed = 0
    compiled_ok = sum(1 for r in results if r.get("compile_ok"))
    compiled_fail = sum(1 for r in results if not r.get("compile_ok") and r.get("sample_id"))
    skipped = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_single_candidate, item): item[0]
            for item in work_items
        }

        for future in as_completed(futures):
            orig_cand = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                sample_id = orig_cand.get("sample_id", "unknown")
                logger.error("Worker failed for %s: %s", sample_id, exc)
                result = dict(orig_cand)
                result["compile_ok"] = False
                result["compile_error"] = str(exc)
                result["linter_messages"] = []
                result["linter_category_counts"] = {}
                result["linter_message_count"] = 0
                result["passes_filters"] = False
                result["filter_reason"] = f"worker_error: {exc}"
                result["code_hash"] = compute_hash(orig_cand.get("code", ""))
                result["loc"] = 0

            if result.get("compile_ok"):
                compiled_ok += 1
            elif not result.get("code", "").strip():
                skipped += 1
            else:
                compiled_fail += 1

            # Apply filters
            passes, reason = passes_filters(
                result, min_messages, max_messages, min_loc, max_loc
            )
            result["passes_filters"] = passes
            result["filter_reason"] = reason

            results.append(result)
            completed += 1

            if completed % 20 == 0 or completed == len(work_items):
                logger.info(
                    "Progress: %d/%d  (compiled_ok=%d, compiled_fail=%d, skipped=%d)",
                    completed, len(work_items), compiled_ok, compiled_fail, skipped,
                )

    # Save results
    output_path = Path(args.output)
    ensure_dir(output_path.parent)
    n_written = save_jsonl(results, str(output_path), dedup_key="sample_id")
    logger.info("Saved %d results to %s", n_written, output_path)

    # Summary
    total = len(results)
    n_compiled = sum(1 for r in results if r.get("compile_ok"))
    n_filtered = sum(1 for r in results if r.get("passes_filters"))
    avg_msgs = (
        sum(r.get("linter_message_count", 0) for r in results) / total
        if total > 0 else 0
    )
    logger.info("Summary:")
    logger.info("  Total candidates: %d", total)
    logger.info("  Compiled OK: %d (%.1f%%)", n_compiled, 100 * n_compiled / total if total else 0)
    logger.info("  Pass filters: %d (%.1f%%)", n_filtered, 100 * n_filtered / total if total else 0)
    logger.info("  Avg linter messages: %.1f", avg_msgs)
    logger.info("Done.")


if __name__ == "__main__":
    main()
