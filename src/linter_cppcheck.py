"""C++ linter (cppcheck) wrapper for code revision benchmark -- held-out linter."""

import subprocess
import json
import os
import re
import tempfile
from typing import List, Dict, Optional

# Cppcheck binary
CPPCHECK_BIN = os.environ.get("CPPCHECK_BIN", "cppcheck")

# Version pinned for reproducibility
CPPCHECK_VERSION = "1.87"

# Cppcheck severity -> LintEval category
SEVERITY_CATEGORY_MAP = {
    "error": "error-prone",
    "warning": "error-prone",
    "style": "style",
    "performance": "performance",
    "portability": "other",
    "information": "other",
}

# Check ID prefix fallback mapping (from config)
PREFIX_CATEGORY_MAP = {
    "bugprone": "error-prone",
    "unusedVariable": "error-prone",
    "uninitvar": "error-prone",
    "nullPointer": "error-prone",
    "arrayIndexOutOfBounds": "error-prone",
    "memoryLeak": "error-prone",
    "resourceLeak": "error-prone",
    "duplicateCondition": "error-prone",
    "redundantAssignment": "style",
    "variableScope": "refactor",
    "constParameter": "performance",
    "constVariable": "performance",
    "passedByValue": "performance",
    "stlIfStrFind": "performance",
    "useStlAlgorithm": "refactor",
}

# Template format for cppcheck output parsing
# {file}:{line}:{column}: [{id}] [{severity}] {message}
_CPPCHECK_TEMPLATE = "{file}:{line}:{column}: [{id}] [{severity}] {message}"


def get_category(severity: str, check_id: str) -> str:
    """Map cppcheck severity (with check-id prefix fallback) to category.

    Uses severity first; if severity maps to 'other', falls back to
    PREFIX_CATEGORY_MAP based on the check ID prefix.
    """
    if severity and severity in SEVERITY_CATEGORY_MAP:
        cat = SEVERITY_CATEGORY_MAP[severity]
        if cat != "other":
            return cat

    # Fallback: check ID prefix
    if check_id:
        for prefix, cat in PREFIX_CATEGORY_MAP.items():
            if check_id.startswith(prefix):
                return cat

    return SEVERITY_CATEGORY_MAP.get(severity, "other")


def _normalize_message_text(text: str) -> str:
    """Normalize a cppcheck message for identity comparison.

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


def parse_cppcheck_output(output: str) -> List[Dict]:
    """Parse cppcheck template-formatted output into structured messages.

    Template format: {file}:{line}:{column}: [{id}] [{severity}] {message}

    Also handles JSON output if available (newer cppcheck versions).

    Each returned message is a dict with keys:
        tool, file, line, column, severity, message_text, check_name,
        category, message_identity
    """
    messages: List[Dict] = []

    if not output or not output.strip():
        return messages

    # Try JSON parsing first (for newer cppcheck versions)
    try:
        items = json.loads(output)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                file_path = item.get("file", "")
                line_no = item.get("line", 0)
                col_no = item.get("column", 0)
                severity = item.get("severity", "")
                msg_text = item.get("message", "")
                check_id = item.get("id", "")
                if not msg_text and not check_id:
                    continue
                normalized_text = _normalize_message_text(msg_text)
                message_identity = f"{check_id}::{normalized_text}"
                messages.append({
                    "tool": "cppcheck",
                    "tool_version": CPPCHECK_VERSION,
                    "file": file_path,
                    "line": int(line_no),
                    "column": int(col_no),
                    "severity": severity if severity else "warning",
                    "message_text": msg_text,
                    "check_name": check_id,
                    "category": get_category(severity, check_id),
                    "message_identity": message_identity,
                    "raw_record": item,
                })
            return messages
    except json.JSONDecodeError:
        pass

    # Fallback: parse template-formatted output
    # Pattern: /path/file.cpp:5:13: [checkId] [severity] message text
    pattern = re.compile(
        r'^(.+?):(\d+):(\d+):\s*\[([^\]]*)\]\s*\[([^\]]*)\]\s*(.+)$'
    )

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Skip "Checking ..." progress lines
        if line.startswith("Checking "):
            continue

        m = pattern.match(line)
        if not m:
            continue

        file_path = m.group(1)
        line_no = int(m.group(2))
        col_no = int(m.group(3))
        check_id = m.group(4).strip()
        severity = m.group(5).strip()
        msg_text = m.group(6).strip()

        # Skip "nofile" entries (informational, not tied to code)
        if file_path == "nofile":
            continue

        # Skip information-only entries with no real check ID
        if not check_id and not msg_text:
            continue

        # Skip unmatched suppression notices
        if check_id == "unmatchedSuppression":
            continue

        normalized_text = _normalize_message_text(msg_text)
        message_identity = f"{check_id}::{normalized_text}"

        messages.append({
            "tool": "cppcheck",
            "tool_version": CPPCHECK_VERSION,
            "file": file_path,
            "line": line_no,
            "column": col_no,
            "severity": severity if severity else "warning",
            "message_text": msg_text,
            "check_name": check_id,
            "category": get_category(severity, check_id),
            "message_identity": message_identity,
            "raw_record": raw_line,
        })

    return messages


def run_cppcheck(code: str, timeout: int = 30) -> List[Dict]:
    """Write code to a temp file, run cppcheck on it, and parse the output.

    Command: cppcheck tmp.cpp --enable=all --suppress=unusedFunction
             --suppress=missingInclude --language=c++
             --template='{file}:{line}:{column}: [{id}] [{severity}] {message}'

    Args:
        code:    The C++ source code as a string.
        timeout: Maximum seconds to wait for cppcheck.

    Returns:
        A list of structured linter message dicts. On tool failure, returns
        a single-element list with a tool_error entry.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cpp", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        cmd = [
            CPPCHECK_BIN,
            tmp_path,
            "--enable=all",
            "--suppress=unusedFunction",
            "--suppress=missingInclude",
            "--language=c++",
            f"--template={_CPPCHECK_TEMPLATE}",
            "--quiet",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )

        # cppcheck writes diagnostics to stderr with --quiet
        output = result.stderr
        if not output.strip():
            output = result.stdout + "\n" + result.stderr

        return parse_cppcheck_output(output)

    except subprocess.TimeoutExpired:
        return [{
            "tool": "cppcheck",
            "tool_version": CPPCHECK_VERSION,
            "file": "",
            "line": 0,
            "column": 0,
            "severity": "error",
            "message_text": "cppcheck timed out",
            "check_name": "tool_error",
            "category": "tool_error",
            "message_identity": "tool_error::cppcheck timed out",
            "raw_record": {"error": "cppcheck timed out"},
        }]
    except FileNotFoundError:
        return [{
            "tool": "cppcheck",
            "tool_version": CPPCHECK_VERSION,
            "file": "",
            "line": 0,
            "column": 0,
            "severity": "error",
            "message_text": f"cppcheck not found at {CPPCHECK_BIN}",
            "check_name": "tool_error",
            "category": "tool_error",
            "message_identity": f"tool_error::cppcheck not found at {CPPCHECK_BIN}",
            "raw_record": {"error": f"cppcheck not found at {CPPCHECK_BIN}"},
        }]
    except Exception as exc:
        return [{
            "tool": "cppcheck",
            "tool_version": CPPCHECK_VERSION,
            "file": "",
            "line": 0,
            "column": 0,
            "severity": "error",
            "message_text": str(exc),
            "check_name": "tool_error",
            "category": "tool_error",
            "message_identity": f"tool_error::{exc}",
            "raw_record": {"error": str(exc)},
        }]
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
