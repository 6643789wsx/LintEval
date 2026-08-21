"""Data I/O utilities for CodeContests+ format.

Handles loading problems, building candidate submissions, and managing
intermediate results for the C++ linter-guided code revision benchmark.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from utils import load_json, load_jsonl, save_jsonl
except ImportError:
    from src.utils import load_json, load_jsonl, save_jsonl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Problem loading
# ---------------------------------------------------------------------------

def load_problems(
    input_path: Union[str, Path],
    limit: int = 0,
) -> List[Dict[str, Any]]:
    """Load problems from a JSON or JSONL file.

    Each problem dict is expected to contain (at minimum) the following keys:

        source, id, title, description, time_limit, memory_limit,
        validator, generator, generator_cmd, checker,
        correct_submissions, incorrect_submissions

    The function is tolerant of missing optional keys and will leave them as
    empty lists / None values when absent.

    Args:
        input_path: Path to a ``.json`` (single object or list) or ``.jsonl``
            file.
        limit: If > 0, return at most this many problems.

    Returns:
        List of normalised problem dictionaries.
    """
    input_path = Path(input_path)
    suffix = input_path.suffix.lower()

    if suffix == ".jsonl":
        raw_records = load_jsonl(input_path)
    elif suffix == ".json":
        data = load_json(input_path)
        if isinstance(data, list):
            raw_records = data
        elif isinstance(data, dict):
            # Some datasets wrap problems under a top-level key.
            for candidate_key in ("problems", "data", "items", "records"):
                if candidate_key in data and isinstance(data[candidate_key], list):
                    raw_records = data[candidate_key]
                    break
            else:
                # Single problem wrapped as a dict.
                raw_records = [data]
        else:
            raise ValueError(f"Unexpected JSON structure in {input_path}")
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")

    problems = [_normalise_problem(rec) for rec in raw_records]

    if limit > 0:
        problems = problems[:limit]

    logger.info("Loaded %d problems from %s", len(problems), input_path)
    return problems


def _normalise_problem(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in defaults for a problem record so downstream code can rely on
    consistent keys."""
    problem: Dict[str, Any] = {
        "source": raw.get("source", ""),
        "id": raw.get("id", raw.get("problem_id", "")),
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "time_limit": raw.get("time_limit"),
        "memory_limit": raw.get("memory_limit"),
        "validator": raw.get("validator", ""),
        "generator": raw.get("generator", ""),
        "generator_cmd": raw.get("generator_cmd", ""),
        "checker": raw.get("checker", ""),
        "correct_submissions": raw.get("correct_submissions", []),
        "incorrect_submissions": raw.get("incorrect_submissions", []),
    }
    return problem


# ---------------------------------------------------------------------------
# Candidate building
# ---------------------------------------------------------------------------

def build_candidates(
    problem: Dict[str, Any],
    max_submissions_per_problem: int = 1,
    language_filter: str = "cpp",
) -> List[Dict[str, Any]]:
    """From a single problem, build candidate submissions.

    A candidate is a flat dictionary suitable for downstream processing:

        sample_id, problem_id, submission_index, language, code,
        source, title, time_limit, memory_limit,
        generator, generator_cmd, checker, validator

    Candidates are drawn from ``correct_submissions`` (preferred) and
    ``incorrect_submissions`` (as fallback).

    Args:
        problem: A normalised problem dict (as returned by
            :func:`load_problems`).
        max_submissions_per_problem: Maximum number of candidates to sample
            from this problem.
        language_filter: Only include submissions whose ``language`` field
            matches this value (case-insensitive).

    Returns:
        List of candidate dicts.
    """
    problem_id = str(problem.get("id", ""))
    candidates: List[Dict[str, Any]] = []

    # Gather all eligible submissions (correct first, then incorrect).
    all_submissions: List[Dict[str, Any]] = []
    for submission in problem.get("correct_submissions", []):
        all_submissions.append(("correct", submission))
    for submission in problem.get("incorrect_submissions", []):
        all_submissions.append(("incorrect", submission))

    for category, submission in all_submissions:
        lang = str(submission.get("language", "")).lower().strip()
        if language_filter.lower() not in lang:
            continue

        code = submission.get("code", submission.get("solution", ""))
        if not code or not code.strip():
            continue

        candidate = {
            "sample_id": f"{problem_id}_{len(candidates)}",
            "problem_id": problem_id,
            "submission_index": len(candidates),
            "language": lang,
            "code": code,
            "category": category,
            "source": problem.get("source", ""),
            "title": problem.get("title", ""),
            "time_limit": problem.get("time_limit"),
            "memory_limit": problem.get("memory_limit"),
            "generator": problem.get("generator", ""),
            "generator_cmd": problem.get("generator_cmd", ""),
            "checker": problem.get("checker", ""),
            "validator": problem.get("validator", ""),
        }
        candidates.append(candidate)

    # Sample if we have more than requested.
    if max_submissions_per_problem > 0 and len(candidates) > max_submissions_per_problem:
        random.shuffle(candidates)
        candidates = candidates[:max_submissions_per_problem]

    # Re-index after potential sampling.
    for idx, cand in enumerate(candidates):
        cand["sample_id"] = f"{problem_id}_{idx}"
        cand["submission_index"] = idx

    return candidates


# ---------------------------------------------------------------------------
# Intermediate results (resume support)
# ---------------------------------------------------------------------------

def load_intermediate(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Load intermediate JSONL results for resume support.

    If the file does not exist, returns an empty list.

    Args:
        path: Path to the intermediate JSONL file.

    Returns:
        List of result dicts.
    """
    path = Path(path)
    if not path.exists():
        logger.info("No intermediate file at %s -- starting fresh.", path)
        return []

    try:
        records = load_jsonl(path)
        logger.info("Loaded %d intermediate records from %s", len(records), path)
        return records
    except Exception as exc:
        logger.warning("Could not load intermediate file %s: %s", path, exc)
        return []


def save_intermediate(
    data: List[Dict[str, Any]],
    path: Union[str, Path],
) -> None:
    """Save intermediate results (overwrite mode).

    Args:
        data: List of result dicts to write.
        path: Destination JSONL path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as fh:
        for rec in data:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info("Saved %d intermediate records to %s", len(data), path)
