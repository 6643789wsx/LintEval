"""05_compute_metrics.py -- Compute all metrics for validated revisions.

Reads the validated revisions JSONL, runs clang-tidy on each revised code,
computes per-sample metrics, and saves both per-sample and aggregate results.

Usage:
  python scripts/05_compute_metrics.py \
      --input data/intermediate/validated_revisions.jsonl \
      --output data/intermediate/metrics.jsonl \
      [--debug_limit 10]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Make src/ importable regardless of working directory.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from utils import setup_logging, ensure_dir, load_jsonl, save_jsonl, load_json, save_json
from linter_cpp import run_clang_tidy, count_by_category, DEFAULT_CHECKS
from metrics import compute_sample_metrics, aggregate_metrics, CATEGORIES

logger = logging.getLogger("05_compute_metrics")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute metrics for validated revisions.",
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=str(_PROJECT_ROOT / "data" / "intermediate" / "validated_revisions.jsonl"),
        help="Path to validated revisions JSONL file.",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(_PROJECT_ROOT / "data" / "intermediate" / "metrics.jsonl"),
        help="Path to write per-sample metrics JSONL.",
    )
    parser.add_argument(
        "--aggregate_output",
        type=str,
        default=str(_PROJECT_ROOT / "data" / "intermediate" / "aggregate_metrics.json"),
        help="Path to write aggregate metrics JSON.",
    )
    parser.add_argument(
        "--checks",
        nargs="*",
        default=None,
        help="Clang-tidy checks to use. Defaults to DEFAULT_CHECKS from linter_cpp.",
    )
    parser.add_argument(
        "--clang_tidy_timeout",
        type=int,
        default=30,
        help="Timeout in seconds for each clang-tidy run.",
    )
    parser.add_argument(
        "--debug_limit",
        type=int,
        default=0,
        help="If > 0, only process this many samples (for debugging).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip samples that already have results in the output file.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def compute_metrics_for_sample(
    record: Dict[str, Any],
    checks: List[str] | None = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Compute metrics for a single validated revision record.

    Runs clang-tidy on the revised code, then calls compute_sample_metrics().

    Args:
        record: A dict from validated_revisions.jsonl. Expected keys:
            - revised_code (str): extracted revised code
            - code (str): original code
            - original_messages (list): linter messages on the original code
            - pass_at_1 (bool): whether the revision passed validation
            - sample_id (str): unique identifier
        checks: Clang-tidy checks to use.
        timeout: Clang-tidy timeout.

    Returns:
        The record augmented with computed metrics.
    """
    sample_id = record.get("sample_id", "unknown")
    original_code = record.get("code", "")
    revised_code = record.get("revised_code", "")
    original_messages = record.get("original_messages", [])
    # Backward/forward compatibility:
    # - 04_validate_revisions.py stores validation under record["validation"]["pass_at_1"]
    # - Some intermediate files may also have pass_at_1 at top-level or under metrics.
    pass_at_1 = bool(
        record.get("pass_at_1")
        or (record.get("validation") or {}).get("pass_at_1")
        or (record.get("metrics") or {}).get("pass_at_1")
    )

    # If no revised code was extracted, we cannot compute metrics.
    if not revised_code or not revised_code.strip():
        logger.warning("Sample %s: no revised code -- skipping metrics.", sample_id)
        record["metrics_status"] = "skipped_no_revised_code"
        record["revised_messages"] = []
        record["metrics"] = None
        return record

    # Run clang-tidy on the revised code.
    logger.debug("Sample %s: running clang-tidy on revised code.", sample_id)
    try:
        revised_messages = run_clang_tidy(
            revised_code,
            checks=checks,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("Sample %s: clang-tidy failed: %s", sample_id, exc)
        revised_messages = []

    record["revised_messages"] = revised_messages

    # Compute per-sample metrics.
    metrics = compute_sample_metrics(
        original_code=original_code,
        revised_code=revised_code,
        original_messages=original_messages,
        revised_messages=revised_messages,
        pass_at_1=pass_at_1,
    )

    record["metrics"] = metrics
    record["metrics_status"] = "computed"

    # Flatten key metrics to top-level for easy JSONL inspection.
    record["mrr_at_pass"] = metrics.get("mrr_at_pass")
    record["new_msg_per_sample_at_pass"] = metrics.get("new_msg_per_sample_at_pass")
    record["new_messages_count"] = metrics.get("new_messages_count")
    record["old_messages_remaining"] = metrics.get("old_messages_remaining")
    record["patch_count"] = metrics.get("patch_count")
    record["lint_error_count"] = metrics.get("lint_error_count")
    record["redundancy_p"] = metrics.get("redundancy_p")
    record["lpm_p"] = metrics.get("lpm_p")
    record["line_churn_at_pass"] = metrics.get("line_churn_at_pass")
    record["revised_total_messages"] = metrics.get("revised_total_messages")
    record["original_loc"] = metrics.get("original_loc")
    record["revised_loc"] = metrics.get("revised_loc")
    record["added_lines"] = metrics.get("added_lines")
    record["deleted_lines"] = metrics.get("deleted_lines")

    return record


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    """Main entry point.

    Returns:
        Dict with summary information (total, computed, skipped, aggregate).
    """
    args = parse_args(argv)

    # Setup logging.
    log_dir = _PROJECT_ROOT / "outputs" / "logs"
    global logger
    logger = setup_logging(log_dir, "05_compute_metrics")

    logger.info("=" * 60)
    logger.info("Starting metrics computation.")
    logger.info("Input:  %s", args.input)
    logger.info("Output: %s", args.output)
    logger.info("=" * 60)

    # Load validated revisions.
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        raise FileNotFoundError(f"Input file not found: {input_path}")

    records = load_jsonl(input_path)
    logger.info("Loaded %d validated revision records.", len(records))

    if args.debug_limit > 0:
        records = records[: args.debug_limit]
        logger.info("Debug limit: processing %d records.", len(records))

    # Resume support: skip already-processed sample_ids.
    completed_ids: set[str] = set()
    existing_results: List[Dict[str, Any]] = []
    output_path = Path(args.output)

    if args.resume and output_path.exists():
        existing_results = load_jsonl(output_path)
        for rec in existing_results:
            sid = rec.get("sample_id")
            if sid is not None:
                completed_ids.add(str(sid))
        logger.info(
            "Resume mode: %d existing results loaded, %d sample IDs to skip.",
            len(existing_results),
            len(completed_ids),
        )

    # Resolve checks.
    checks = args.checks if args.checks else DEFAULT_CHECKS

    # Process each record.
    results: List[Dict[str, Any]] = list(existing_results)
    computed = 0
    skipped = 0

    for idx, record in enumerate(records):
        sample_id = record.get("sample_id", "")

        # Resume: skip already done.
        if args.resume and str(sample_id) in completed_ids:
            logger.debug("Skipping already-computed sample: %s", sample_id)
            skipped += 1
            continue

        logger.info(
            "Processing %d/%d: sample_id=%s",
            idx + 1,
            len(records),
            sample_id,
        )

        augmented = compute_metrics_for_sample(
            record,
            checks=checks,
            timeout=args.clang_tidy_timeout,
        )
        results.append(augmented)
        computed += 1

        # Periodic save every 50 samples.
        if computed % 50 == 0:
            logger.info("Periodic save: %d samples computed so far.", computed)
            save_jsonl(results, output_path)

    # Final save of per-sample metrics.
    ensure_dir(output_path.parent)
    save_jsonl(results, output_path)
    logger.info("Saved %d per-sample metric records to %s", len(results), output_path)

    # Compute aggregate metrics per split (train/valid/test).
    split_groups: Dict[str, List[Dict[str, Any]]] = {"train": [], "valid": [], "test": [], "unknown": []}
    for rec in results:
        metrics = rec.get("metrics")
        if metrics is None:
            continue
        split = rec.get("split", "unknown")
        if split not in split_groups:
            split = "unknown"
        split_groups[split].append(metrics)

    aggregate_summary: Dict[str, Any] = {}
    for split_name, split_metrics in split_groups.items():
        if not split_metrics:
            continue
        agg = aggregate_metrics(split_metrics, passed_only=True)
        aggregate_summary[split_name] = agg

    # Save aggregate summary.
    aggregate_path = Path(args.aggregate_output)
    save_json(aggregate_summary, aggregate_path)
    logger.info("Saved aggregate metrics to %s", aggregate_path)

    # Print summary.
    summary = {
        "total_records": len(records),
        "total_results": len(results),
        "computed": computed,
        "skipped_resume": skipped,
        "aggregate_file": str(aggregate_path),
        "per_sample_file": str(output_path),
        "aggregate_summary": aggregate_summary,
    }

    logger.info("=" * 60)
    logger.info("Metrics computation complete.")
    logger.info("  Records processed: %d", computed)
    logger.info("  Total results:     %d", len(results))
    for split_name, agg in aggregate_summary.items():
        logger.info("  Split '%s': n_samples=%d, pass_rate=%.2f%%",
                     split_name,
                     agg.get("n_samples", 0),
                     (agg.get("pass_rate", 0) or 0) * 100)
    logger.info("=" * 60)

    return summary


if __name__ == "__main__":
    main()
