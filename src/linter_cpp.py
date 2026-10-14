"""C++ linter (clang-tidy) wrapper for code revision benchmark."""

import sys
import subprocess
import json
import re
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

_MISSING_BINARY_WARNED = False


def _warn_missing_binary() -> None:
    """Warn once (not per sample) when the linter binary cannot be executed.

    Without this, a missing clang-tidy silently yields zero alerts for every sample,
    which would silently corrupt the reported metrics.
    """
    global _MISSING_BINARY_WARNED
    if not _MISSING_BINARY_WARNED:
        _MISSING_BINARY_WARNED = True
        print(
            "WARNING: clang-tidy could not be executed (set CLANG_TIDY_BIN or put it on PATH). "
            "Linter messages will be EMPTY for this language.",
            file=sys.stderr,
        )


# Default clang-tidy checks - avoid naming rules
DEFAULT_CHECKS = [
    "bugprone-*",
    "performance-*",
    "modernize-use-nullptr",
    "modernize-use-emplace",
    "modernize-loop-convert",
    "readability-braces-around-statements",
    "readability-redundant-*",
    "readability-simplify-boolean-expr",
]

# Category mapping from clang-tidy check prefix to topic-based categories
# Error-prone / Performance / Refactor / Style / Other
CATEGORY_MAP = {
    "bugprone": "error-prone",
    "performance": "performance",
    "modernize": "refactor",
    "readability": "style",
}

CLANG_TIDY_BIN = os.environ.get("CLANG_TIDY_BIN") or shutil.which("clang-tidy") or "clang-tidy"

GPP_BIN = os.environ.get("GPP_BIN") or shutil.which("g++") or "g++"


def get_category(check_name: str) -> str:
    """Map clang-tidy check name to category.

    Extracts the prefix before the first '-' and maps it via CATEGORY_MAP.
    Returns 'other' if the prefix is not recognized.
    """
    if not check_name:
        return "other"
    prefix = check_name.split("-")[0]
    return CATEGORY_MAP.get(prefix, "other")


def _normalize_message_text(text: str) -> str:
    """Normalize a clang-tidy diagnostic message for identity comparison.

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


def parse_clang_tidy_output(output: str) -> List[Dict]:
    """Parse clang-tidy text output into structured messages.

    Each message is a dict with keys:
        tool:            "clang-tidy"
        file:            source file path (from output, often the temp file)
        line:            line number (int)
        column:          column number (int)
        severity:        "warning" | "error" | "note"
        message_text:    the diagnostic message string
        check_name:      the clang-tidy check name (e.g. readability-braces-around-statements)
        category:        mapped category (bugprone, performance, modernize, readability, other)
        message_identity: f"{check_name}::{normalized_message_text}" (line-independent)

    clang-tidy output lines look like:
        /path/file.cpp:5:13: warning: statement should be inside braces [readability-braces-around-statements]
    """
    messages: List[Dict] = []

    # Pattern for the main diagnostic line:
    # file:line:column: severity: message [check-name]
    # The check name is in square brackets at the end.
    main_pattern = re.compile(
        r"^(.+?):(\d+):(\d+):\s*(warning|error|fatal error):\s*(.+?)\s*\[([^\]]+)\]\s*$"
    )

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = main_pattern.match(line)
        if not m:
            continue

        file_path = m.group(1)
        line_no = int(m.group(2))
        col_no = int(m.group(3))
        severity = m.group(4).strip()
        msg_text = m.group(5).strip()
        check_name = m.group(6).strip()

        # Normalize severity
        if severity == "fatal error":
            severity = "error"

        normalized_text = _normalize_message_text(msg_text)
        message_identity = f"{check_name}::{normalized_text}"

        messages.append(
            {
                "tool": "clang-tidy",
                "file": file_path,
                "line": line_no,
                "column": col_no,
                "severity": severity,
                "message_text": msg_text,
                "check_name": check_name,
                "category": get_category(check_name),
                "message_identity": message_identity,
            }
        )

    return messages


def run_clang_tidy(
    code: str,
    checks: Optional[List[str]] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = 30,
) -> List[Dict]:
    """Write code to a temp file, run clang-tidy on it, and parse the output.

    Args:
        code:        The C++ source code as a string.
        checks:      List of clang-tidy check patterns. Uses DEFAULT_CHECKS if None.
        extra_args:  Additional arguments to pass to clang-tidy (e.g. ["--extra-arg=-std=c++17"]).
        timeout:     Maximum seconds to wait for clang-tidy.

    Returns:
        A list of structured linter message dicts (see parse_clang_tidy_output).
    """
    if checks is None:
        checks = DEFAULT_CHECKS

    checks_str = ",".join(checks)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cpp", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        cmd = [
            CLANG_TIDY_BIN,
            tmp_path,
            f"-checks={checks_str}",
            "--extra-arg=-std=c++17",
        ]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )

        # clang-tidy writes diagnostics to stderr
        combined_output = result.stdout + "\n" + result.stderr
        return parse_clang_tidy_output(combined_output)

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


def compile_cpp(
    code: str,
    output_path: str,
    std: str = "c++17",
    timeout: int = 30,
) -> tuple:
    """Compile C++ code with g++.

    Tries -static first; if that fails, falls back to dynamic linking.

    Args:
        code:        C++ source code string.
        output_path: Where to write the compiled binary.
        std:         C++ standard (default c++17).
        timeout:     Maximum compilation time in seconds.

    Returns:
        (success: bool, error_msg: str)
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cpp", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        # First attempt: static linking
        cmd_static = [
            GPP_BIN,
            f"-std={std}",
            "-O2",
            "-pipe",
            "-static",
            tmp_path,
            "-o",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd_static,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return (True, "")
        except subprocess.TimeoutExpired:
            return (False, "Compilation timed out (static)")
        except FileNotFoundError:
            return (False, f"g++ not found at {GPP_BIN}")

        # Fallback: dynamic linking
        cmd_dynamic = [
            GPP_BIN,
            f"-std={std}",
            "-O2",
            "-pipe",
            tmp_path,
            "-o",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd_dynamic,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return (True, "")
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                return (False, error_msg)
        except subprocess.TimeoutExpired:
            return (False, "Compilation timed out (dynamic)")
        except FileNotFoundError:
            return (False, f"g++ not found at {GPP_BIN}")

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def count_by_category(messages: List[Dict]) -> Dict[str, int]:
    """Count messages by category.

    Returns a dict mapping category name to count.
    Includes all known categories plus 'other'.
    """
    counts: Dict[str, int] = {cat: 0 for cat in CATEGORY_MAP.values()}
    counts["other"] = 0

    for msg in messages:
        cat = msg.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1

    return counts
