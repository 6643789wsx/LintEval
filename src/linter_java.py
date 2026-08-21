"""
linter_java.py -- Java linter (PMD) wrapper.
"""

import subprocess
import json
import os
import re
import tempfile
import shutil
from typing import List, Dict, Optional
from pathlib import Path

PMD_BIN = os.environ.get("PMD_BIN") or shutil.which("pmd") or "pmd"

JAVAC_BIN = os.environ.get("JAVAC_BIN") or shutil.which("javac") or "javac"

# PMD rulesets - conservative, avoid naming/style
PMD_RULESETS = [
    "category/java/bestpractices.xml",
    "category/java/codestyle.xml",
    "category/java/design.xml",
    "category/java/errorprone.xml",
    "category/java/multithreading.xml",
    "category/java/performance.xml",
    "category/java/security.xml",
]

# Java category mapping (PMD ruleset "Category" to our standard categories)
# Error-prone / Performance / Refactor / Style / Other
PMD_CATEGORY_MAP = {
    "Best Practices": "style",
    "Code Style": "style",
    "Design": "refactor",
    "Error Prone": "error-prone",
    "Multithreading": "performance",
    "Performance": "performance",
    "Security": "error-prone",
    # Lowercase versions for safety
    "bestpractices": "style",
    "codestyle": "style",
    "design": "refactor",
    "errorprone": "error-prone",
    "multithreading": "performance",
    "performance": "performance",
    "security": "error-prone",
}

# Rules to suppress for competitive programming code
PMD_SUPPRESSED_RULES = {
    "NoPackage",           # Competitive programming code has no package
    "ShortClassName",      # Class names like "Main" or "a" are standard
    "ShortVariable",       # Short variable names are common in CP
    "ShortMethodName",     # Short method names are common in CP
    "UseUtilityClass",     # Main class has main(), not a utility class
    "SystemPrintln",       # System.out.println is standard in CP
    "CloseResource",       # Competitive programming rarely closes resources
    "LocalVariableCouldBeFinal",  # Too noisy for CP code
    "MethodArgumentCouldBeFinal", # Too noisy for CP code
    "OnlyOneReturn",       # CP code often has multiple returns
    "LiteralsFirstInComparisons", # Too noisy for CP
    "UseStdin",            # Scanner/System.in is standard in CP
    "AvoidLiteralsInIfCondition", # Too noisy for CP
    "CommentRequired",     # No comments expected in CP code
    "MissingSerialVersionUID",   # Not relevant for CP
}

# Priority threshold: only report violations with priority <= this value
# PMD priorities: 1 (highest) to 5 (lowest)
PMD_PRIORITY_THRESHOLD = 3


def get_category(rule_ruleset: str) -> str:
    """Map PMD rule ruleset (category) to our standard category.

    Args:
        rule_ruleset: The ruleset name from PMD output (e.g. "Error Prone", "Code Style").

    Returns:
        One of: bugprone, performance, modernize, readability, other
    """
    if not rule_ruleset:
        return "other"
    return PMD_CATEGORY_MAP.get(rule_ruleset, PMD_CATEGORY_MAP.get(rule_ruleset.lower(), "other"))


def _normalize_message_text(text: str) -> str:
    """Normalize a PMD message for identity comparison.

    Strips leading/trailing whitespace, collapses internal whitespace,
    and removes line/column numbers to make the identity line-independent.
    Preserves variable names for semantic accuracy (consistent with NewMsg-P).
    """
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


def parse_pmd_output(output: str) -> List[Dict]:
    """Parse PMD JSON output into structured messages.

    Each message is a dict with keys:
        tool:            "pmd"
        file:            source file path
        line:            line number (int)
        column:          column number (int)
        severity:        "warning" | "error"
        message_text:    the diagnostic message string
        check_name:      the PMD rule name (e.g. CloseResource)
        category:        mapped category (bugprone, performance, modernize, readability, other)
        message_identity: f"{check_name}::{normalized_message_text}" (line-independent)

    PMD JSON output structure:
    {
      "files": [
        {
          "filename": "...",
          "violations": [
            {
              "beginline": 5,
              "begincolumn": 13,
              "endline": 5,
              "endcolumn": 19,
              "description": "...",
              "rule": "RuleName",
              "ruleset": "Category Name",
              "priority": 3,
              ...
            }
          ]
        }
      ]
    }
    """
    messages: List[Dict] = []

    if not output or not output.strip():
        return messages

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return messages

    if not isinstance(data, dict):
        return messages

    files = data.get("files", [])
    if not isinstance(files, list):
        return messages

    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        file_path = file_entry.get("filename", "")
        violations = file_entry.get("violations", [])

        for v in violations:
            if not isinstance(v, dict):
                continue

            rule_name = v.get("rule", "")
            ruleset = v.get("ruleset", "")
            description = v.get("description", "")
            priority = v.get("priority", 5)
            begin_line = v.get("beginline", 0)
            begin_col = v.get("begincolumn", 0)

            # Skip suppressed rules
            if rule_name in PMD_SUPPRESSED_RULES:
                continue

            # Skip low-priority violations
            if priority > PMD_PRIORITY_THRESHOLD:
                continue

            # Determine severity from priority
            if priority <= 2:
                severity = "error"
            else:
                severity = "warning"

            normalized_text = _normalize_message_text(description)
            message_identity = f"{rule_name}::{normalized_text}"

            messages.append(
                {
                    "tool": "pmd",
                    "file": file_path,
                    "line": int(begin_line),
                    "column": int(begin_col),
                    "severity": severity,
                    "message_text": description,
                    "check_name": rule_name,
                    "category": get_category(ruleset),
                    "message_identity": message_identity,
                }
            )

    return messages


def run_pmd(code: str, rulesets: Optional[List[str]] = None, timeout: int = 30) -> List[Dict]:
    """Write code to temp file, run PMD, parse results.

    Command: pmd check -R rulesets -d tmp.java --format json

    The code is written as a .java file. For competitive programming,
    the class name is typically "Main" or "a" -- detected from code.

    Args:
        code:     Java source code string.
        rulesets: List of PMD ruleset paths. Uses PMD_RULESETS if None.
        timeout:  Maximum seconds to wait for PMD.

    Returns:
        A list of structured linter message dicts (see parse_pmd_output).
    """
    if rulesets is None:
        rulesets = PMD_RULESETS

    ruleset_str = ",".join(rulesets)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".java", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        cmd = [
            PMD_BIN,
            "check",
            "-R", ruleset_str,
            "-d", tmp_path,
            "--format", "json",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )

        # PMD writes JSON to stdout (warnings to stderr)
        output = result.stdout
        return parse_pmd_output(output)

    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _detect_class_name(code: str) -> Optional[str]:
    """Detect the public class name from Java source code.

    Looks for 'public class ClassName' pattern.
    Returns None if not found.
    """
    m = re.search(r'\bpublic\s+class\s+(\w+)', code)
    if m:
        return m.group(1)
    # Try non-public class declaration (must look like a real class definition)
    # Pattern: class Name followed by { or extends/implements
    m = re.search(r'\bclass\s+(\w+)\s*(?:extends|implements|\{)', code)
    if m:
        return m.group(1)
    return None


def compile_java(code: str, timeout: int = 30) -> tuple:
    """Compile Java code with javac.

    Tries: javac -source 17 tmp.java
    If class name doesn't match filename, extracts class name and renames file.

    Args:
        code:    Java source code string.
        timeout: Maximum compilation time in seconds.

    Returns:
        (success: bool, error_msg: str)
    """
    if not JAVAC_BIN:
        return (False, "javac not found -- JDK is not installed")

    class_name = _detect_class_name(code)
    if not class_name:
        return (False, "Could not detect class name in Java source")

    # Write the file with the correct name (class_name.java)
    tmp_dir = tempfile.mkdtemp(prefix="pmd_compile_")
    try:
        java_file = os.path.join(tmp_dir, f"{class_name}.java")
        with open(java_file, "w") as f:
            f.write(code)

        cmd = [
            JAVAC_BIN,
            "-source", "17",
            "-nowarn",
            java_file,
        ]

        try:
            result = subprocess.run(
                cmd,
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
            return (False, "Compilation timed out")
        except FileNotFoundError:
            return (False, f"javac not found at {JAVAC_BIN}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def count_by_category(messages: List[Dict]) -> Dict[str, int]:
    """Count messages by category.

    Returns a dict mapping category name to count.
    Includes all known categories plus 'other'.
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
