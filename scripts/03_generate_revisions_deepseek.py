"""03_generate_revisions_deepseek.py -- Call DeepSeek API to generate revised code.

Supports multi-language (C++, Python, Java) with threaded batch processing.

Usage:
  python scripts/03_generate_revisions_deepseek.py \\
      --input data/intermediate/candidates_with_linter.jsonl \\
      --output data/intermediate/revisions.jsonl \\
      --config configs/deepseek_config.yaml \\
      [--debug_limit 10] [--dry_run] [--resume] [--workers 8]
"""

from __future__ import annotations

import argparse
import json
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

from src.utils import (  # noqa: E402
    setup_logging,
    ensure_dir,
    load_jsonl,
    save_jsonl,
    extract_code_from_response,
)
from src.deepseek_client import DeepSeekReviser  # noqa: E402
from src.prompt_templates import (  # noqa: E402
    format_linter_messages,
    build_revision_prompt,
)

logger = logging.getLogger("03_generate_revisions_deepseek")


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call DeepSeek API to generate revised code (multi-language, parallel)."
    )
    parser.add_argument("--input", type=str, required=True)
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--debug_limit", type=int, default=0)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=8,
                        help="Number of concurrent API calls (default: 8).")
    parser.add_argument("--api_key", type=str, default=None)
    parser.add_argument("--base_url", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max_tokens", type=int, default=8192)
    parser.add_argument("--log_dir", type=str, default="logs")
    args = parser.parse_args()

    # ---- Setup logging -----------------------------------------------------
    setup_logging(args.log_dir, "03_generate_revisions_deepseek")
    logger.info("Arguments: %s", vars(args))

    # ---- Load optional YAML config -----------------------------------------
    cfg: dict = {}
    if args.config and os.path.isfile(args.config):
        import yaml
        with open(args.config, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        logger.info("Loaded config from %s", args.config)

    # ---- Load candidates with linter messages ------------------------------
    candidates = load_jsonl(args.input)
    logger.info("Loaded %d candidates from %s", len(candidates), args.input)

    # ---- Filter: only with messages > 0 (skip compile check for non-C++) ----
    eligible = []
    for cand in candidates:
        language = cand.get("language", "cpp")
        if language == "cpp" and not cand.get("compile_ok", False):
            continue
        if cand.get("linter_message_count", 0) <= 0:
            continue
        eligible.append(cand)

    logger.info(
        "Eligible candidates (compile_ok[cpp] + messages > 0): %d / %d",
        len(eligible),
        len(candidates),
    )

    if args.debug_limit > 0:
        eligible = eligible[: args.debug_limit]
        logger.info("Debug limit: processing %d candidates.", len(eligible))

    # ---- Dry-run mode ------------------------------------------------------
    if args.dry_run:
        logger.info("=== DRY RUN MODE ===")
        for idx, cand in enumerate(eligible[:5]):
            sample_id = cand.get("sample_id", f"unknown_{idx}")
            code = cand.get("code", "")
            messages = cand.get("linter_messages", [])
            language = cand.get("language", "cpp")
            prompt = build_revision_prompt(code, messages, language=language)
            logger.info("--- Sample %s (lang=%s) ---", sample_id, language)
            logger.info("Code length: %d chars", len(code))
            logger.info("Linter messages: %d", len(messages))
            logger.info("Prompt (first 300 chars):\n%s", prompt[1]["content"][:300])
            logger.info("")
        logger.info("Dry run complete. No API calls were made.")
        return

    # ---- Initialise DeepSeek client ----------------------------------------
    api_key = args.api_key or cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    base_url = args.base_url or cfg.get("base_url")
    model = args.model or cfg.get("model")

    reviser = DeepSeekReviser(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    logger.info(
        "DeepSeekReviser initialised  model=%s  base_url=%s",
        reviser.model,
        reviser.base_url,
    )

    # ---- Build samples for batch API ---------------------------------------
    samples = []
    for cand in eligible:
        samples.append({
            "sample_id": cand.get("sample_id", ""),
            "problem_id": cand.get("problem_id", ""),
            "split": cand.get("split", "unknown"),
            "language": cand.get("language", "cpp"),
            "code": cand.get("code", ""),
            "linter_messages": cand.get("linter_messages", []),
            "linter_message_count": cand.get("linter_message_count", 0),
            "original_loc": cand.get("loc", cand.get("original_loc", 0)),
            "compile_ok": cand.get("compile_ok", False),
            "source": cand.get("source", ""),
            "title": cand.get("title", ""),
            "generator": cand.get("generator", ""),
            "generator_cmd": cand.get("generator_cmd", ""),
            "checker": cand.get("checker", ""),
            "validator": cand.get("validator", ""),
        })

    # ---- Run batch with threaded concurrency --------------------------------
    output_path = Path(args.output)
    ensure_dir(output_path.parent)

    if args.resume:
        results = reviser.generate_batch(samples, str(output_path), n_workers=args.workers)
    else:
        # Remove existing output file for fresh start
        if output_path.exists():
            output_path.unlink()
        results = reviser.generate_batch(samples, str(output_path), n_workers=args.workers)

    # ---- Post-process: extract code and add metadata -----------------------
    final_results = []
    for rec in results:
        raw_response = rec.get("raw_response", "")
        revised_code = rec.get("revised_code")
        error = rec.get("error")

        extraction_ok = revised_code is not None and bool(str(revised_code).strip())
        if revised_code is None:
            revised_code = ""

        final_results.append({
            **rec,
            "revised_code": revised_code,
            "extraction_ok": extraction_ok,
            "revision_error": error,
        })

    # Rewrite with full results
    n_written = save_jsonl(final_results, str(output_path), dedup_key="sample_id")
    logger.info("Final output: %d records written to %s", n_written, output_path)

    extracted = sum(1 for r in final_results if r.get("extraction_ok"))
    errors = sum(1 for r in final_results if r.get("error"))
    logger.info("Summary: %d extracted, %d errors out of %d total", extracted, errors, len(final_results))
    logger.info("Done.")


if __name__ == "__main__":
    main()
