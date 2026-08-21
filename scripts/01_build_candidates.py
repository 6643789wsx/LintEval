"""01_build_candidates.py -- Load CodeContests+ data, build candidate submissions, split by problem_id.

Usage:
  python scripts/01_build_candidates.py \\
      --input data/raw/part-00000-of-00010.jsonl \\
      --output data/intermediate/candidates.jsonl \\
      --config configs/dataset_config.yaml \\
      [--debug_limit 10]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make src/ importable regardless of invocation directory.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import yaml  # noqa: E402

from src.utils import setup_logging, ensure_dir, save_jsonl, seed_all  # noqa: E402
from src.data_io import load_problems, build_candidates  # noqa: E402
from src.splitter import split_problems  # noqa: E402

logger = logging.getLogger("01_build_candidates")


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
        description="Load CodeContests+ data, build candidate submissions, and split by problem_id."
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Path to the input data file (.jsonl or .json).",
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to write the output candidates JSONL file.",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to the YAML config file (e.g. configs/dataset_config.yaml).",
    )
    parser.add_argument(
        "--debug_limit", type=int, default=0,
        help="If > 0, only process this many problems (for quick debugging).",
    )
    parser.add_argument(
        "--log_dir", type=str, default="logs",
        help="Directory for log files.",
    )
    args = parser.parse_args()

    # ---- Setup logging -----------------------------------------------------
    setup_logging(args.log_dir, "01_build_candidates")
    logger.info("Arguments: %s", vars(args))

    # ---- Load config -------------------------------------------------------
    cfg = load_config(args.config)

    max_submissions = cfg.get("max_submissions_per_problem", 1)
    languages = cfg.get("languages", cfg.get("language_filter", ["cpp"]))
    if isinstance(languages, str):
        languages = [languages]
    train_ratio = cfg.get("train_ratio", 0.7)
    valid_ratio = cfg.get("valid_ratio", 0.15)
    test_ratio = cfg.get("test_ratio", 0.15)
    random_seed = cfg.get("random_seed", 42)

    seed_all(random_seed)

    # ---- Load problems -----------------------------------------------------
    limit = args.debug_limit if args.debug_limit > 0 else 0
    problems = load_problems(args.input, limit=limit)
    logger.info("Loaded %d problems.", len(problems))

    # ---- Build candidates for each language --------------------------------
    all_candidates = []
    for language_filter in languages:
        problems_with_lang = []
        for prob in problems:
            has_lang = False
            for sub in prob.get("correct_submissions", []):
                lang = str(sub.get("language", "")).lower().strip()
                if language_filter.lower() in lang:
                    has_lang = True
                    break
            if has_lang:
                problems_with_lang.append(prob)

        logger.info(
            "Problems with %s correct submissions: %d / %d",
            language_filter, len(problems_with_lang), len(problems),
        )

        for prob in problems_with_lang:
            cands = build_candidates(
                prob,
                max_submissions_per_problem=max_submissions,
                language_filter=language_filter,
            )
            all_candidates.extend(cands)

    # Re-index with language-aware sample_ids to avoid cross-language collisions.
    pid_lang_idx: dict[tuple[str, str], int] = {}
    for cand in all_candidates:
        key = (cand.get("problem_id", ""), cand.get("language", "unknown"))
        idx = pid_lang_idx.get(key, 0)
        cand["sample_id"] = f"{key[0]}_{cand.get('language', 'unknown')}_{idx}"
        pid_lang_idx[key] = idx + 1

    logger.info("Built %d total candidates.", len(all_candidates))

    # ---- Split by problem_id -----------------------------------------------
    problem_ids = sorted(set(c["problem_id"] for c in all_candidates))
    logger.info("Unique problem IDs: %d", len(problem_ids))

    splits = split_problems(
        problem_ids,
        train_ratio=train_ratio,
        valid_ratio=valid_ratio,
        test_ratio=test_ratio,
        seed=random_seed,
    )

    # Build a lookup: problem_id -> split name
    pid_to_split: dict[str, str] = {}
    for split_name, pid_list in splits.items():
        for pid in pid_list:
            pid_to_split[pid] = split_name

    # Assign split to each candidate
    for cand in all_candidates:
        cand["split"] = pid_to_split.get(cand["problem_id"], "unknown")

    # ---- Statistics --------------------------------------------------------
    for split_name in ("train", "valid", "test"):
        count = sum(1 for c in all_candidates if c["split"] == split_name)
        logger.info("  %s: %d candidates", split_name, count)

    # ---- Save output -------------------------------------------------------
    output_path = Path(args.output)
    ensure_dir(output_path.parent)
    n_written = save_jsonl(all_candidates, str(output_path), dedup_key="sample_id")
    logger.info("Saved %d candidates to %s", n_written, output_path)

    logger.info("Done.")


if __name__ == "__main__":
    main()
