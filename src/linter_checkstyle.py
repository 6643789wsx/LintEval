"""Java linter (checkstyle) wrapper for code revision benchmark -- held-out linter."""

import subprocess
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

# Checkstyle JAR and Java binary
# Set CHECKSTYLE_JAR / CHECKSTYLE_CONFIG to point at your checkstyle distribution.
CHECKSTYLE_JAR = os.environ.get("CHECKSTYLE_JAR", "")
CHECKSTYLE_CONFIG = os.environ.get("CHECKSTYLE_CONFIG", "")
JAVA_BIN = os.environ.get("JAVA_BIN") or shutil.which("java") or "java"

# Version pinned for reproducibility
CHECKSTYLE_VERSION = "9.3"

# Checkstyle module prefix -> LintEval category
MODULE_CATEGORY_MAP = {
    "com.puppycrawl.tools.checkstyle.checks.blocks": "style",
    "com.puppycrawl.tools.checkstyle.checks.coding": "error-prone",
    "com.puppycrawl.tools.checkstyle.checks.design": "refactor",
    "com.puppycrawl.tools.checkstyle.checks.header": "other",
    "com.puppycrawl.tools.checkstyle.checks.imports": "style",
    "com.puppycrawl.tools.checkstyle.checks.indentation": "style",
    "com.puppycrawl.tools.checkstyle.checks.javadoc": "other",
    "com.puppycrawl.tools.checkstyle.checks.metrics": "performance",
    "com.puppycrawl.tools.checkstyle.checks.modifier": "style",
    "com.puppycrawl.tools.checkstyle.checks.naming": "style",
    "com.puppycrawl.tools.checkstyle.checks.regexp": "other",
    "com.puppycrawl.tools.checkstyle.checks.sizes": "refactor",
    "com.puppycrawl.tools.checkstyle.checks.whitespace": "style",
    "com.puppycrawl.tools.checkstyle.checks.annotation": "other",
}

# Checks to suppress for competitive programming code (simple class names)
SUPPRESSED_CHECKS = {
    "NoPackageCheck",
    "MissingJavadocMethodCheck",
    "MissingJavadocTypeCheck",
    "HiddenFieldCheck",
}


def get_category(source: str) -> str:
    """Map a checkstyle check source (FQ class name) to a category.

    Looks up the longest matching prefix in MODULE_CATEGORY_MAP.
    Returns 'other' if no prefix matches.
    """
    if not source:
        return "other"

    best_match = ""
    best_cat = "other"
    for prefix, cat in MODULE_CATEGORY_MAP.items():
        if source.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_cat = cat

    return best_cat


def _simple_check_name(source: str) -> str:
    """Extract the simple class name from a fully-qualified check source.

    E.g. 'com.puppycrawl.tools.checkstyle.checks.coding.DefaultComesLastCheck'
         -> 'DefaultComesLastCheck'
    """
    if not source:
        return ""
    return source.rsplit(".", 1)[-1]


def _normalize_message_text(text: str) -> str:
    """Normalize a checkstyle message for identity comparison.

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


def _detect_class_name(code: str) -> Optional[str]:
    """Detect the public class name from Java source code.

    Looks for 'public class ClassName' pattern.
    Falls back to any 'class Name' declaration.
    Returns None if not found.
    """
    m = re.search(r'\bpublic\s+class\s+(\w+)', code)
    if m:
        return m.group(1)
    # Try non-public class declaration
    m = re.search(r'\bclass\s+(\w+)\s*(?:extends|implements|\{)', code)
    if m:
        return m.group(1)
    return None


def parse_checkstyle_output(xml_output: str) -> List[Dict]:
    """Parse checkstyle XML output into structured messages.

    Checkstyle XML format:
        <checkstyle version="...">
          <file name="path/to/File.java">
            <error line="5" column="13" severity="warning"
                   message="..." source="com.puppycrawl.tools.checkstyle.checks.coding.DefaultComesLastCheck"/>
          </file>
        </checkstyle>

    Each returned message is a dict with keys:
        tool, file, line, column, severity, message_text, check_name,
        category, message_identity
    """
    messages: List[Dict] = []

    if not xml_output or not xml_output.strip():
        return messages

    try:
        root = ET.fromstring(xml_output)
    except ET.ParseError:
        return messages

    for file_elem in root.findall("file"):
        file_path = file_elem.get("name", "")

        for error_elem in file_elem.findall("error"):
            line_no = error_elem.get("line", "0")
            col_no = error_elem.get("column", "0")
            severity = error_elem.get("severity", "warning")
            msg_text = error_elem.get("message", "")
            source = error_elem.get("source", "")

            simple_name = _simple_check_name(source)

            # Skip suppressed checks
            if simple_name in SUPPRESSED_CHECKS:
                continue

            normalized_text = _normalize_message_text(msg_text)
            message_identity = f"{simple_name}::{normalized_text}"

            messages.append(
                {
                    "tool": "checkstyle",
                    "tool_version": CHECKSTYLE_VERSION,
                    "file": file_path,
                    "line": int(line_no),
                    "column": int(col_no),
                    "severity": severity,
                    "message_text": msg_text,
                    "check_name": simple_name,
                    "category": get_category(source),
                    "message_identity": message_identity,
                    "raw_record": {
                        "line": line_no,
                        "column": col_no,
                        "severity": severity,
                        "message": msg_text,
                        "source": source,
                    },
                }
            )

    return messages


def run_checkstyle(code: str, timeout: int = 30) -> List[Dict]:
    """Write code to a temp file, run checkstyle on it, and parse the output.

    The temp file is named {ClassName}.java to match Java's filename-classname
    requirement. Uses the bundled google_checks config.

    Command: java -jar checkstyle-9.3.jar -c google_checks -f xml tmp.java 2>&1

    Args:
        code:    The Java source code as a string.
        timeout: Maximum seconds to wait for checkstyle.

    Returns:
        A list of structured linter message dicts. On tool failure, returns
        a single-element list with a tool_error entry.
    """
    class_name = _detect_class_name(code)
    if not class_name:
        class_name = "Main"

    tmp_dir = tempfile.mkdtemp(prefix="checkstyle_")
    try:
        java_file = os.path.join(tmp_dir, f"{class_name}.java")
        with open(java_file, "w") as f:
            f.write(code)

        cmd = [
            JAVA_BIN,
            "-jar", CHECKSTYLE_JAR,
            "-c", CHECKSTYLE_CONFIG,
            "-f", "xml",
            java_file,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )

        # Checkstyle writes XML to stdout
        output = result.stdout
        return parse_checkstyle_output(output)

    except subprocess.TimeoutExpired:
        return [
            {
                "tool": "checkstyle",
                "tool_version": CHECKSTYLE_VERSION,
                "file": "",
                "line": 0,
                "column": 0,
                "severity": "error",
                "message_text": "checkstyle timed out",
                "check_name": "tool_error",
                "category": "tool_error",
                "message_identity": "tool_error::checkstyle timed out",
                "raw_record": {"error": "checkstyle timed out"},
            }
        ]
    except FileNotFoundError:
        return [
            {
                "tool": "checkstyle",
                "tool_version": CHECKSTYLE_VERSION,
                "file": "",
                "line": 0,
                "column": 0,
                "severity": "error",
                "message_text": f"java not found at {JAVA_BIN}",
                "check_name": "tool_error",
                "category": "tool_error",
                "message_identity": f"tool_error::java not found at {JAVA_BIN}",
                "raw_record": {"error": f"java not found at {JAVA_BIN}"},
            }
        ]
    except Exception as exc:
        return [
            {
                "tool": "checkstyle",
                "tool_version": CHECKSTYLE_VERSION,
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
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
