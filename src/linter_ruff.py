"""Python linter (ruff) wrapper for code revision benchmark -- held-out linter."""

import subprocess
import json
import os
import shutil
import re
import tempfile
from typing import List, Dict, Optional

# Ruff binary
RUFF_BIN = os.environ.get("RUFF_BIN") or shutil.which("ruff") or "ruff"

# Version pinned for reproducibility
RUFF_VERSION = "0.12.0"

# Ruff rule prefix -> LintEval category
PREFIX_CATEGORY_MAP = {
    "E": "style",          # pycodestyle errors (indentation, whitespace)
    "W": "style",          # pycodestyle warnings
    "F": "error-prone",    # pyflakes (undefined names, unused imports)
    "C": "refactor",       # mccabe complexity + flake8-comprehensions
    "N": "style",          # pep8-naming
    "UP": "refactor",      # pyupgrade
    "B": "error-prone",    # flake8-bugbear
    "A": "error-prone",    # flake8-builtins
    "SIM": "refactor",     # flake8-simplify
    "PERF": "performance", # perflint
    "RUF": "other",        # ruff-specific
}


def get_category(code: str) -> str:
    """Map a ruff rule code (e.g. 'F841') to a category via prefix.

    Extracts the alphabetic prefix and looks it up in PREFIX_CATEGORY_MAP.
    Returns 'other' if the prefix is not recognized.
    """
    if not code:
        return "other"
    # Extract leading alphabetic prefix (e.g. "F" from "F841", "SIM" from "SIM101")
    prefix_match = re.match(r'^([A-Z]+)', code)
    if prefix_match:
        prefix = prefix_match.group(1)
        return PREFIX_CATEGORY_MAP.get(prefix, "other")
    return "other"


def _normalize_message_text(text: str) -> str:
    """Normalize a ruff message for identity comparison.

    Strips leading/trailing whitespace, collapses internal whitespace,
    and removes line/column numbers to make the identity line-independent.
    """
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r'\bline[:\s]*\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(\d+[:,\s]*\d*\)', '', text)
    text = re.sub(r'\[\d+[:,\s]*\d*\]', '', text)
    text = re.sub(r'\bat\s+line\s+\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcolumn[:\s]*\d+\b', '', text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    return text.strip()


def parse_ruff_output(output: str) -> List[Dict]:
    """Parse ruff JSON output into structured messages.

    Ruff JSON output format: array of objects with keys:
        filename, location (dict with row, column), code, message

    Each returned message is a dict with keys:
        tool, file, line, column, severity, message_text, check_name,
        category, message_identity
    """
    messages: List[Dict] = []

    if not output or not output.strip():
        return messages

    try:
        items = json.loads(output)
    except json.JSONDecodeError:
        return messages

    if not isinstance(items, list):
        return messages

    for item in items:
        if not isinstance(item, dict):
            continue

        file_path = item.get("filename", "")
        location = item.get("location", {})
        line_no = location.get("row", 0) if isinstance(location, dict) else 0
        col_no = location.get("column", 0) if isinstance(location, dict) else 0
        code = item.get("code", "")
        msg_text = item.get("message", "")

        normalized_text = _normalize_message_text(msg_text)
        message_identity = f"{code}::{normalized_text}"

        # Determine severity from code prefix
        # F-prefixed and B/A-prefixed are error-prone -> "error", others -> "warning"
        category = get_category(code)
        if category == "error-prone":
            severity = "error"
        else:
            severity = "warning"

        messages.append(
            {
                "tool": "ruff",
                "tool_version": RUFF_VERSION,
                "file": file_path,
                "line": int(line_no),
                "column": int(col_no),
                "severity": severity,
                "message_text": msg_text,
                "check_name": code,
                "category": category,
                "message_identity": message_identity,
                "raw_record": item,
            }
        )

    return messages


def run_ruff(code: str, timeout: int = 30) -> List[Dict]:
    """Write code to a temp file, run ruff on it, and parse the output.

    Command: ruff check tmp.py --select E,W,F,C,N,UP,B,A,SIM,PERF,RUF
             --ignore E501 --output-format=json 2>&1

    Args:
        code:    The Python source code as a string.
        timeout: Maximum seconds to wait for ruff.

    Returns:
        A list of structured linter message dicts. On tool failure, returns
        a single-element list with a tool_error entry.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        cmd = [
            RUFF_BIN,
            "check",
            tmp_path,
            "--select", "E,W,F,C,N,UP,B,A,SIM,PERF,RUF",
            "--ignore", "E501",
            "--output-format=json",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )

        # ruff writes JSON to stdout
        output = result.stdout
        return parse_ruff_output(output)

    except subprocess.TimeoutExpired:
        return [
            {
                "tool": "ruff",
                "tool_version": RUFF_VERSION,
                "file": "",
                "line": 0,
                "column": 0,
                "severity": "error",
                "message_text": "ruff timed out",
                "check_name": "tool_error",
                "category": "tool_error",
                "message_identity": "tool_error::ruff timed out",
                "raw_record": {"error": "ruff timed out"},
            }
        ]
    except FileNotFoundError:
        return [
            {
                "tool": "ruff",
                "tool_version": RUFF_VERSION,
                "file": "",
                "line": 0,
                "column": 0,
                "severity": "error",
                "message_text": f"ruff not found at {RUFF_BIN}",
                "check_name": "tool_error",
                "category": "tool_error",
                "message_identity": f"tool_error::ruff not found at {RUFF_BIN}",
                "raw_record": {"error": f"ruff not found at {RUFF_BIN}"},
            }
        ]
    except Exception as exc:
        return [
            {
                "tool": "ruff",
                "tool_version": RUFF_VERSION,
                "file": "",
                "line": 0,
                "column": 0,
                "severity": "error",
                "message_text": str(exc),
                "check_name": "tool_error",
                "category": "tool_error",
                "message_identity": f"tool_error::{exc}",
                "raw_record": {"error": str(exc)},
            }
        ]
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def count_by_category(messages: List[Dict]) -> Dict[str, int]:
    """Count messages by category.

    Returns a dict mapping category name to count.
    Includes all five standard categories plus 'other'.
    """
    counts: Dict[str, int] = {
        "error-prone": 0,
        "performance": 0,
        "refactor": 0,
        "style": 0,
        "other": 0,
    }

    for msg in messages:
        cat = msg.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1

    return counts
