"""Prompt templates for DeepSeek revision generation.

Provides system / user message templates and helper functions for formatting
linter messages and building complete chat prompts.  Supports C++, Python,
and Java.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Language-specific prompt fragments
# ---------------------------------------------------------------------------

_LANG_INFO = {
    "cpp": {
        "lang_name": "C++17",
        "linter_name": "clang-tidy",
        "suppress_comment": "NOLINT",
        "source_file": "C++17 source file",
        "include_note": "includes or global variables",
    },
    "py3": {
        "lang_name": "Python 3",
        "linter_name": "pylint",
        "suppress_comment": "pylint: disable",
        "source_file": "Python 3 source file",
        "include_note": "imports",
    },
    "py2": {
        "lang_name": "Python 2",
        "linter_name": "pylint",
        "suppress_comment": "pylint: disable",
        "source_file": "Python source file",
        "include_note": "imports",
    },
    "java": {
        "lang_name": "Java",
        "linter_name": "PMD",
        "suppress_comment": "NOPMD",
        "source_file": "Java source file",
        "include_note": "imports or class declarations",
    },
}


def _get_lang_info(language: str) -> Dict[str, str]:
    lang = language.lower().strip()
    if lang in ("c++", "cxx", "cc"):
        lang = "cpp"
    elif lang in ("python", "python3"):
        lang = "py3"
    elif lang == "python2":
        lang = "py2"
    return _LANG_INFO.get(lang, _LANG_INFO["cpp"])


# ---------------------------------------------------------------------------
# Prompt strings (default: C++)
# ---------------------------------------------------------------------------

SYSTEM_MSG: str = (
    "You are revising an existing C++17 competitive programming submission "
    "based on linter messages. Your task is to produce a revised version of "
    "the code that preserves the original behaviour while addressing as many "
    "linter warnings as possible. You must NOT rewrite the solution from "
    "scratch. You must NOT add NOLINT or other suppression comments. Output "
    "only the revised C++17 source code with no explanations."
)

REVISION_PROMPT_TEMPLATE: str = """\
You are revising an existing C++17 competitive programming submission based on linter messages.

This code is assumed to be functionally correct. Your task is not to solve the programming problem from scratch. Your task is to revise the existing code so that it preserves the original behavior while reducing the reported linter messages.

Requirements:
1. Preserve the program's stdin/stdout behavior.
2. Preserve the algorithmic logic unless a very small local change is necessary.
3. Do not rewrite the solution from scratch.
4. Do not remove required includes or global variables if they are needed.
5. Do not add NOLINT, linter-disabling comments, or suppressions.
6. Do not introduce new linter messages if avoidable.
7. Prefer minimal local edits.
8. The output must be a complete C++17 source file.
9. Output only the revised code. Do not include explanations or markdown fences.

Original code:
<CODE>
{code}
</CODE>

Linter messages:
<LINTER_MESSAGES>
{messages}
</LINTER_MESSAGES>

Return only the revised C++17 code."""


def build_lang_system_msg(language: str) -> str:
    info = _get_lang_info(language)
    return (
        f"You are revising an existing {info['lang_name']} competitive programming submission "
        f"based on {info['linter_name']} linter messages. Your task is to produce a revised "
        f"version of the code that preserves the original behaviour while addressing as many "
        f"linter warnings as possible. You must NOT rewrite the solution from scratch. You must "
        f"NOT add {info['suppress_comment']} or other suppression comments. Output only the "
        f"revised {info['lang_name']} source code with no explanations."
    )


def build_lang_prompt_template(language: str) -> str:
    info = _get_lang_info(language)
    return f"""\
You are revising an existing {info['lang_name']} competitive programming submission based on {info['linter_name']} linter messages.

This code is assumed to be functionally correct. Your task is not to solve the programming problem from scratch. Your task is to revise the existing code so that it preserves the original behavior while reducing the reported linter messages.

Requirements:
1. Preserve the program's stdin/stdout behavior.
2. Preserve the algorithmic logic unless a very small local change is necessary.
3. Do not rewrite the solution from scratch.
4. Do not remove required {info['include_note']} if they are needed.
5. Do not add {info['suppress_comment']}, linter-disabling comments, or suppressions.
6. Do not introduce new linter messages if avoidable.
7. Prefer minimal local edits.
8. The output must be a complete {info['source_file']}.
9. Output only the revised code. Do not include explanations or markdown fences.

Original code:
<CODE>
{{code}}
</CODE>

Linter messages:
<LINTER_MESSAGES>
{{messages}}
</LINTER_MESSAGES>

Return only the revised {info['lang_name']} code."""


# Evaluation prompt templates (identical to revision -- kept as aliases for
# clarity in calling code).
EVAL_SYSTEM_MSG: str = SYSTEM_MSG
EVAL_USER_TEMPLATE: str = REVISION_PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_linter_messages(messages: List[Dict[str, Any]]) -> str:
    """Format linter messages for inclusion in the prompt.

    Each message dict should contain:
        check_name   -- e.g. ``"modernize-use-auto"``
        message_text -- human-readable description
        line         -- line number (int or None)
        severity     -- e.g. ``"warning"``, ``"error"``

    Args:
        messages: List of linter message dicts.

    Returns:
        A formatted multi-line string, one message per line.
    """
    if not messages:
        return "(no linter messages)"

    lines: List[str] = []
    for msg in messages:
        check = msg.get("check_name", "unknown-check")
        text = msg.get("message_text", "")
        line_no = msg.get("line")
        severity = msg.get("severity", "warning")

        location = f"line {line_no}" if line_no is not None else "unknown line"
        formatted = f"[{severity}] {location}: [{check}] {text}"
        lines.append(formatted)

    return "\n".join(lines)


def build_generic_improve_prompt(
    code: str,
    language: str = "cpp",
) -> List[Dict[str, str]]:
    """Build a generic improvement prompt WITHOUT linter messages.

    Used for the no-message ablation experiment to test whether LLM
    improvements come from linter guidance vs. general code-cleaning priors.

    Args:
        code: Original source code.
        language: Source language ('cpp', 'py3', 'java').

    Returns:
        List of chat message dicts.
    """
    info = _get_lang_info(language)
    system_msg = (
        f"You are improving an existing {info['lang_name']} competitive programming submission. "
        f"Your task is to produce a revised version of the code that preserves "
        f"the original behaviour while following best coding practices. "
        f"You must NOT rewrite the solution from scratch. You must NOT add "
        f"{info['suppress_comment']} or other suppression comments. Output only the "
        f"revised {info['lang_name']} source code with no explanations."
    )
    user_content = f"""\
You are improving an existing {info['lang_name']} competitive programming submission.

This code is assumed to be functionally correct. Your task is not to solve the programming problem from scratch. Your task is to revise the existing code so that it preserves the original behavior while following best coding practices and reducing any code quality issues.

Requirements:
1. Preserve the program's stdin/stdout behavior.
2. Preserve the algorithmic logic unless a very small local change is necessary.
3. Do not rewrite the solution from scratch.
4. Do not remove required {info['include_note']} if they are needed.
5. Do not add {info['suppress_comment']}, linter-disabling comments, or suppressions.
6. Prefer minimal local edits.
7. The output must be a complete {info['source_file']}.
8. Output only the revised code. Do not include explanations or markdown fences.

Original code:
<CODE>
{code}
</CODE>

Return only the revised {info['lang_name']} code."""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


def build_revision_prompt(
    code: str,
    messages: List[Dict[str, Any]],
    language: str = "cpp",
) -> List[Dict[str, str]]:
    """Build the full prompt for the DeepSeek chat API.

    Args:
        code: Original source code.
        messages: List of linter message dicts (see
            :func:`format_linter_messages`).
        language: Source language ('cpp', 'py3', 'java').

    Returns:
        List of chat message dicts suitable for the DeepSeek API::

            [
                {"role": "system", "content": "..."},
                {"role": "user",   "content": "..."},
            ]
    """
    formatted_messages = format_linter_messages(messages)
    template = build_lang_prompt_template(language)
    system_msg = build_lang_system_msg(language)

    user_content = template.format(
        code=code,
        messages=formatted_messages,
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Diagnostic Grounding Ablation: prompt variants
# ---------------------------------------------------------------------------


def _build_ablation_template(language: str, variant_description: str) -> str:
    """Shared template builder for ablation prompts.

    Args:
        language: Source language ('cpp', 'py3', 'java').
        variant_description: Extra instruction describing the modified alert
            format (e.g. "only rule IDs are shown, not the diagnostic text").

    Returns:
        A str.format template with {code} and {messages} placeholders.
    """
    info = _get_lang_info(language)
    return f"""\
You are revising an existing {info['lang_name']} competitive programming submission based on {info['linter_name']} linter messages.

This code is assumed to be functionally correct. Your task is not to solve the programming problem from scratch. Your task is to revise the existing code so that it preserves the original behavior while reducing the reported linter messages.

Note: in this version, {variant_description}.

Requirements:
1. Preserve the program's stdin/stdout behavior.
2. Preserve the algorithmic logic unless a very small local change is necessary.
3. Do not rewrite the solution from scratch.
4. Do not remove required {info['include_note']} if they are needed.
5. Do not add {info['suppress_comment']}, linter-disabling comments, or suppressions.
6. Do not introduce new linter messages if avoidable.
7. Prefer minimal local edits.
8. The output must be a complete {info['source_file']}.
9. Output only the revised code. Do not include explanations or markdown fences.

Original code:
<CODE>
{{code}}
</CODE>

Linter messages:
<LINTER_MESSAGES>
{{messages}}
</LINTER_MESSAGES>

Return only the revised {info['lang_name']} code."""


# ---- Formatting helpers for ablated message representations ----

def format_rule_only(messages: List[Dict[str, Any]]) -> str:
    """Format linter messages showing ONLY the rule ID, no diagnostic text.

    Output format: ``[severity] line N: [rule_id]``
    """
    if not messages:
        return "(no linter messages)"
    lines: List[str] = []
    for msg in messages:
        severity = msg.get("severity", "warning")
        line_no = msg.get("line")
        check = msg.get("check_name", "unknown-check")
        location = f"line {line_no}" if line_no is not None else "unknown line"
        lines.append(f"[{severity}] {location}: [{check}]")
    return "\n".join(lines)


def format_message_only(messages: List[Dict[str, Any]]) -> str:
    """Format linter messages showing diagnostic text WITHOUT line numbers.

    Output format: ``[severity] [rule_id] diagnostic text``
    """
    if not messages:
        return "(no linter messages)"
    lines: List[str] = []
    for msg in messages:
        severity = msg.get("severity", "warning")
        check = msg.get("check_name", "unknown-check")
        text = msg.get("message_text", "")
        lines.append(f"[{severity}] [{check}] {text}")
    return "\n".join(lines)


def format_location_only(messages: List[Dict[str, Any]]) -> str:
    """Format linter messages showing ONLY location, no rule ID or diagnostic text.

    Output format: ``[severity] line N: linter issue detected``
    """
    if not messages:
        return "(no linter messages)"
    lines: List[str] = []
    for msg in messages:
        severity = msg.get("severity", "warning")
        line_no = msg.get("line")
        location = f"line {line_no}" if line_no is not None else "unknown line"
        lines.append(f"[{severity}] {location}: linter issue detected")
    return "\n".join(lines)


# ---- Ablation prompt builders ----

def build_shuffled_alert_prompt(
    code: str,
    shuffled_messages: List[Dict[str, Any]],
    language: str = "cpp",
) -> List[Dict[str, str]]:
    """Build prompt with linter alerts from the SAME language but a DIFFERENT file.

    This tests whether the model grounds specific diagnostics vs. merely
    using alerts as a general "improve this" signal.

    Args:
        code: Original source code.
        shuffled_messages: Linter messages from a DIFFERENT file in the same
            language (pre-shuffled by the caller).
        language: Source language ('cpp', 'py3', 'java').

    Returns:
        List of chat message dicts.
    """
    info = _get_lang_info(language)
    system_msg = build_lang_system_msg(language)
    formatted = format_linter_messages(shuffled_messages)
    template = build_lang_prompt_template(language)
    user_content = template.format(code=code, messages=formatted)
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


def build_rule_only_prompt(
    code: str,
    messages: List[Dict[str, Any]],
    language: str = "cpp",
) -> List[Dict[str, str]]:
    """Build prompt with only rule IDs (check_name), no diagnostic text.

    Tests whether the model needs the human-readable message to understand
    what the issue is.
    """
    info = _get_lang_info(language)
    system_msg = build_lang_system_msg(language)
    formatted = format_rule_only(messages)
    template = _build_ablation_template(
        language,
        "only the linter rule ID is shown for each message; the diagnostic "
        "description has been removed",
    )
    user_content = template.format(code=code, messages=formatted)
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


def build_message_only_prompt(
    code: str,
    messages: List[Dict[str, Any]],
    language: str = "cpp",
) -> List[Dict[str, str]]:
    """Build prompt with diagnostic text but NO line numbers.

    Tests whether the model needs location information to ground its edits.
    """
    info = _get_lang_info(language)
    system_msg = build_lang_system_msg(language)
    formatted = format_message_only(messages)
    template = _build_ablation_template(
        language,
        "the linter messages include the rule ID and diagnostic text but "
        "line numbers have been removed",
    )
    user_content = template.format(code=code, messages=formatted)
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


def build_location_only_prompt(
    code: str,
    messages: List[Dict[str, Any]],
    language: str = "cpp",
) -> List[Dict[str, str]]:
    """Build prompt with only line locations, no rule ID or diagnostic text.

    Tests whether the model can identify and fix issues from position alone.
    """
    info = _get_lang_info(language)
    system_msg = build_lang_system_msg(language)
    formatted = format_location_only(messages)
    template = _build_ablation_template(
        language,
        "only the line number and severity are shown; the rule ID and "
        "diagnostic description have been removed",
    )
    user_content = template.format(code=code, messages=formatted)
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]
