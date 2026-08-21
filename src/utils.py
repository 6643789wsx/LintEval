"""Utility functions for the C++ linter-guided code revision benchmark."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Union[str, Path], name: str) -> logging.Logger:
    """Set up rotating file + console logging.

    Args:
        log_dir: Directory where log files are written.
        name: Logger name (also used as log file basename).

    Returns:
        Configured logger instance.
    """
    log_dir = Path(log_dir)
    ensure_dir(log_dir)

    logger = logging.getLogger(name)
    # Avoid adding duplicate handlers if called multiple times.
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler -- 10 MB per file, keep 5 backups.
    log_file = log_dir / f"{name}.log"
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler -- INFO and above.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: Union[str, Path]) -> Path:
    """Create directory (and parents) if it does not exist (mkdir -p).

    Args:
        path: Directory path to create.

    Returns:
        The Path object.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# JSON / JSONL I/O
# ---------------------------------------------------------------------------

def load_jsonl(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Load a JSONL file (one JSON object per line).

    Blank lines are silently skipped.

    Args:
        path: Path to the JSONL file.

    Returns:
        List of dictionaries parsed from each line.
    """
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_no} in {path}: {exc}"
                ) from exc
    return records


def save_jsonl(
    data: List[Dict[str, Any]],
    path: Union[str, Path],
    dedup_key: str = "sample_id",
) -> int:
    """Save data as JSONL.  If the file already exists, append and deduplicate
    by *dedup_key*.

    Args:
        data: List of dicts to write.
        path: Destination JSONL path.
        dedup_key: Key used for deduplication when appending.

    Returns:
        Number of records written.
    """
    path = Path(path)
    ensure_dir(path.parent)

    existing: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        for rec in load_jsonl(path):
            key = rec.get(dedup_key)
            if key is not None:
                existing[str(key)] = rec

    # Merge -- new data wins on conflict.
    for rec in data:
        key = rec.get(dedup_key)
        if key is not None:
            existing[str(key)] = rec

    merged = list(existing.values())

    with open(path, "w", encoding="utf-8") as fh:
        for rec in merged:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return len(merged)


def load_json(path: Union[str, Path]) -> Any:
    """Load a JSON file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON content.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(
    data: Any,
    path: Union[str, Path],
    indent: int = 2,
) -> None:
    """Save data as a formatted JSON file.

    Args:
        data: Object to serialise.
        path: Destination JSON path.
        indent: Indentation level.
    """
    path = Path(path)
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def compute_hash(content: str) -> str:
    """Compute the SHA-256 hex digest of a string.

    Args:
        content: Input string.

    Returns:
        64-character hexadecimal hash.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Code extraction from LLM responses
# ---------------------------------------------------------------------------

def extract_code_from_response(response: str, language: str = "cpp") -> str:
    """Extract source code from an LLM response.

    Extraction strategy (first match wins):
      1. Language-specific named fenced block (```python, ```java, ```cpp, etc.)
      2. Generic ``` ... ``` fenced block
      3. Raw code detection via language-specific heuristics

    If none of the above matches, the full response stripped of leading/trailing
    whitespace is returned.

    Args:
        response: Raw LLM response text.
        language: Programming language ("cpp", "py3", "java").

    Returns:
        Extracted source code string.
    """
    text = response.strip()
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()

    # Language-specific fence names
    lang_fence_map = {
        "cpp": ["cpp", "c++"],
        "py3": ["python", "py", "python3"],
        "java": ["java"],
    }
    fence_names = lang_fence_map.get(language, ["cpp", "c++"])

    # Strategy 1: Named fenced blocks for this language.
    names_pattern = "|".join(re.escape(n) for n in fence_names)
    named_pattern = re.compile(
        rf"```(?:{names_pattern})\s*\n(.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    match = named_pattern.search(text)
    if match:
        return match.group(1).strip()

    # Strategy 2: Generic fenced block -- accept the first one found.
    generic_fence_pattern = re.compile(r"```\w*\s*\n(.*?)```", re.DOTALL)
    match = generic_fence_pattern.search(text)
    if match:
        return match.group(1).strip()

    # Strategy 3: Raw code detection via language heuristics.
    if language == "cpp" and _looks_like_cpp(text):
        return text
    if language == "py3" and _looks_like_python(text):
        return text
    if language == "java" and _looks_like_java(text):
        return text

    # Fallback: return the full stripped response.
    return text


def _looks_like_cpp(text: str) -> bool:
    """Heuristic: does the text look like C++ source code?"""
    cpp_markers = [
        "#include",
        "int main",
        "int main(",
        "using namespace",
        "std::",
        "vector<",
        "string ",
        "printf(",
        "scanf(",
        "cout",
        "cin",
        "long long",
        "return 0",
    ]
    lower = text.lower()
    return any(marker.lower() in lower for marker in cpp_markers)


def _looks_like_python(text: str) -> bool:
    """Heuristic: does the text look like Python source code?"""
    py_markers = [
        "def ",
        "import ",
        "from ",
        "print(",
        "input(",
        "if __name__",
        "class ",
        "range(",
        "map(",
        "list(",
    ]
    return any(m in text for m in py_markers)


def _looks_like_java(text: str) -> bool:
    """Heuristic: does the text look like Java source code?"""
    java_markers = [
        "public class",
        "public static void main",
        "import java.",
        "System.out",
        "Scanner",
        "private ",
        "protected ",
        "extends ",
        "implements ",
    ]
    return any(m in text for m in java_markers)


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def seed_all(seed: int = 42) -> None:
    """Set random seeds for reproducibility.

    Sets seeds for: Python random, NumPy.

    Args:
        seed: Integer seed value.
    """
    random.seed(seed)
    np.random.seed(seed)
    os.environ.setdefault("PYTHONHASHSEED", str(seed))
