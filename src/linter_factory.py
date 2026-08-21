"""
linter_factory.py -- Unified linter interface for all languages.

Dispatches to the correct linter module based on language string.
Supported languages: 'cpp', 'py3', 'py2', 'java'
"""

from typing import List, Dict, Tuple, Optional

# Support both `from src.linter_factory` and `from linter_factory` import styles
try:
    from linter_cpp import (
        run_clang_tidy as _run_cpp,
        compile_cpp as _compile_cpp,
        count_by_category as _count_cpp,
    )
    from linter_python import (
        run_pylint as _run_python,
        compile_python as _compile_python,
        count_by_category as _count_python,
    )
    from linter_java import (
        run_pmd as _run_java,
        compile_java as _compile_java,
        count_by_category as _count_java,
    )
except ImportError:
    from src.linter_cpp import (
        run_clang_tidy as _run_cpp,
        compile_cpp as _compile_cpp,
        count_by_category as _count_cpp,
    )
    from src.linter_python import (
        run_pylint as _run_python,
        compile_python as _compile_python,
        count_by_category as _count_python,
    )
    from src.linter_java import (
        run_pmd as _run_java,
        compile_java as _compile_java,
        count_by_category as _count_java,
    )

# Canonical language name mapping
_LANGUAGE_ALIASES = {
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
    "py3": "py3",
    "python": "py3",
    "python3": "py3",
    "py": "py3",
    "py2": "py2",
    "python2": "py2",
    "java": "java",
}


def _normalize_language(language: str) -> str:
    """Normalize a language string to its canonical form."""
    return _LANGUAGE_ALIASES.get(language.lower().strip(), language.lower().strip())


def run_linter(code: str, language: str, **kwargs) -> List[Dict]:
    """Run the appropriate linter for the given language.

    Args:
        code:     Source code string.
        language: 'cpp', 'py3', 'py2', 'java' (case-insensitive).
        **kwargs: Additional arguments forwarded to the language-specific linter.

    Returns:
        List of structured linter message dicts. Each dict has keys:
        tool, file, line, column, severity, message_text, check_name,
        category, message_identity.
    """
    lang = _normalize_language(language)

    if lang == "cpp":
        return _run_cpp(code, **kwargs)
    elif lang in ("py3", "py2"):
        return _run_python(code, **kwargs)
    elif lang == "java":
        return _run_java(code, **kwargs)
    else:
        raise ValueError(
            f"Unsupported language: '{language}'. "
            f"Supported: cpp, py3, py2, java"
        )


def compile_code(code: str, language: str, **kwargs) -> Tuple[bool, str]:
    """Compile/check syntax for the given language.

    Args:
        code:     Source code string.
        language: 'cpp', 'py3', 'py2', 'java' (case-insensitive).
        **kwargs: Additional arguments forwarded to the language-specific compiler.
            For cpp: output_path (str, required)
            For java: timeout (int, default 30)

    Returns:
        (success: bool, error_msg: str)
    """
    lang = _normalize_language(language)

    if lang == "cpp":
        output_path = kwargs.pop("output_path", "/tmp/a.out")
        return _compile_cpp(code, output_path=output_path, **kwargs)
    elif lang in ("py3", "py2"):
        return _compile_python(code)
    elif lang == "java":
        return _compile_java(code, **kwargs)
    else:
        raise ValueError(
            f"Unsupported language: '{language}'. "
            f"Supported: cpp, py3, py2, java"
        )


def count_by_category(messages: List[Dict]) -> Dict[str, int]:
    """Count messages by category (works for all languages).

    The category is read from each message's 'category' field.
    Returns a dict with all five standard categories plus 'other'.
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
