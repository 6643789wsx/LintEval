"""
linter_python.py -- Python linter (pylint) wrapper.
"""

import sys
import subprocess
import json
import os
import re
import shutil
import tempfile
import ast
from typing import List, Dict, Optional
from pathlib import Path

_MISSING_BINARY_WARNED = False


def _warn_missing_binary() -> None:
    """Warn once (not per sample) when the linter binary cannot be executed.

    Without this, a missing pylint silently yields zero alerts for every sample,
    which would silently corrupt the reported metrics.
    """
    global _MISSING_BINARY_WARNED
    if not _MISSING_BINARY_WARNED:
        _MISSING_BINARY_WARNED = True
        print(
            "WARNING: pylint could not be executed (set PYLINT_BIN or put it on PATH). "
            "Linter messages will be EMPTY for this language.",
            file=sys.stderr,
        )


PYLINT_BIN = os.environ.get("PYLINT_BIN") or shutil.which("pylint") or "pylint"

# Category mapping: pylint native types → topic-based cross-language categories
# Error-prone / Performance / Refactor / Style / Other
PYLINT_CATEGORY_MAP = {
    "convention": "style",
    "refactor": "refactor",
    "warning": "performance",
    "error": "error-prone",
    "fatal": "error-prone",
    "information": "other",
}

# Disable W0311 (bad-indentation) - same as Python benchmark
PYLINT_DISABLE = "W0311"


def get_category(msg_type: str) -> str:
    """Map pylint message type to our category.

    Pylint message types are: convention (C), refactor (R), warning (W),
    error (E), fatal (F), information (I).
    """
    if not msg_type:
        return "other"
    return PYLINT_CATEGORY_MAP.get(msg_type, "other")


def _normalize_message_text(text: str) -> str:
    """Normalize a pylint message for identity comparison.

    Strips leading/trailing whitespace, collapses internal whitespace,
    and removes line/column numbers to make the identity line-independent.
    Preserves variable names for semantic accuracy (consistent with NewMsg-P).
    """
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text.strip())
    # Remove line/column references (e.g., "line 10", "(10:5)", "[10,5]")
    text = re.sub(r'\bline[:\s]*\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(\d+[:,\s]*\d*\)', '', text)
    text = re.sub(r'\[\d+[:,\s]*\d*\]', '', text)
    text = re.sub(r'\bat\s+line\s+\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcolumn[:\s]*\d+\b', '', text, flags=re.IGNORECASE)
    # Remove extra whitespace
    text = " ".join(text.split())
    return text.strip()


def parse_pylint_output(output: str) -> List[Dict]:
    """Parse pylint JSON output into structured messages.

    Each message is a dict with keys:
        tool:            "pylint"
        file:            source file path
        line:            line number (int)
        column:          column number (int)
        severity:        "warning" | "error" | "convention" | "refactor" | "fatal"
        message_text:    the diagnostic message string
        check_name:      the pylint symbol name (e.g. missing-function-docstring)
        category:        mapped category (bugprone, performance, modernize, readability, other)
        message_identity: f"{check_name}::{normalized_message_text}" (line-independent)

    Pylint JSON output is an array of objects with keys:
        type, module, obj, line, column, endLine, endColumn,
        path, symbol, message, message-id
    """
    messages: List[Dict] = []

    if not output or not output.strip():
        return messages

    try:
        items = json.loads(output)
    except json.JSONDecodeError:
        return messages

    # Pylint may return a dict wrapping a list, or just a list
    if isinstance(items, dict):
        items = items.get("messages", [items])
    if not isinstance(items, list):
        return messages

    for item in items:
        if not isinstance(item, dict):
            continue

        # Skip syntax errors -- those mean the code is broken, not a lint issue
        symbol = item.get("symbol", "")
        if symbol == "syntax-error":
            continue

        msg_type = item.get("type", "")
        msg_text = item.get("message", "")
        line_no = item.get("line", 0)
        col_no = item.get("column", 0)
        file_path = item.get("path", "")

        # Map severity for display
        severity = msg_type
        if msg_type == "error" or msg_type == "fatal":
            severity = "error"
        elif msg_type in ("convention", "refactor", "information"):
            severity = "warning"

        normalized_text = _normalize_message_text(msg_text)
        message_identity = f"{symbol}::{normalized_text}"

        messages.append(
            {
                "tool": "pylint",
                "file": file_path,
                "line": int(line_no),
                "column": int(col_no),
                "severity": severity,
                "message_text": msg_text,
                "check_name": symbol,
                "category": get_category(msg_type),
                "message_identity": message_identity,
            }
        )

    return messages


def run_pylint(code: str, disable: str = PYLINT_DISABLE, timeout: int = 30) -> List[Dict]:
    """Write code to temp file, run pylint with JSON output, parse results.

    Command: pylint tmp.py --output-format=json --disable=all
             --enable=C,R,W,E,F --disable=W0311

    Args:
        code:    Python source code string.
        disable: Comma-separated list of pylint message IDs to disable.
        timeout: Maximum seconds to wait for pylint.

    Returns:
        A list of structured linter message dicts (see parse_pylint_output).
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        cmd = [
            PYLINT_BIN,
            tmp_path,
            "--output-format=json",
            "--disable=all",
            "--enable=C,R,W,E,F",
            f"--disable={disable}",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )

        # Pylint writes JSON to stdout
        output = result.stdout
        return parse_pylint_output(output)

    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        _warn_missing_binary()
        return []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def compile_python(code: str) -> tuple:
    """Check Python syntax via ast.parse.

    Returns:
        (success: bool, error_msg: str)
    """
    try:
        ast.parse(code)
        return (True, "")
    except SyntaxError as e:
        error_msg = f"SyntaxError: {e.msg}"
        if e.lineno:
            error_msg += f" (line {e.lineno})"
        return (False, error_msg)
    except Exception as e:
        return (False, str(e))


def count_by_category(messages: List[Dict]) -> Dict[str, int]:
    """Count messages by category.

    Returns a dict mapping category name to count.
    Includes all known categories plus 'other'.
    """
    counts: Dict[str, int] = {cat: 0 for cat in PYLINT_CATEGORY_MAP.values()}
    counts["other"] = 0

    for msg in messages:
        cat = msg.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1

    return counts
