"""Metrics calculation for the C++ linter-guided code revision benchmark.

Provides functions to compute MRR, new message counts, redundancy,
line churn, per-category metrics, and aggregate statistics across samples.
"""

import re
from difflib import SequenceMatcher
from collections import Counter
from typing import Dict, List, Optional

CATEGORIES = ["error-prone", "performance", "refactor", "style", "other"]


def sanitize_message(message: str) -> str:
    """Sanitize message content by removing line/column numbers.
    
    This prevents line shifts from being counted as new messages,
    while preserving variable names and other semantic content.
    
    Args:
        message: Original message text from linter.
        
    Returns:
        Sanitized message with line/column info removed.
    """
    if not message:
        return ""
    
    # Remove patterns like "line 10", "line: 10", "(10:5)", "[10,5]"
    msg = re.sub(r'\bline[:\s]*\d+\b', '', message, flags=re.IGNORECASE)
    msg = re.sub(r'\(\d+[:,\s]*\d*\)', '', msg)
    msg = re.sub(r'\[\d+[:,\s]*\d*\]', '', msg)
    msg = re.sub(r'\bat\s+line\s+\d+\b', '', msg, flags=re.IGNORECASE)
    msg = re.sub(r'\bcolumn[:\s]*\d+\b', '', msg, flags=re.IGNORECASE)
    
    # Remove extra whitespace
    msg = " ".join(msg.split())
    
    return msg.strip()


def compute_mrr(original_total: int, revised_total: int) -> Optional[float]:
    """Compute MRR@Pass (Message Reduction Rate).

    MRR@Pass = (original_total - revised_total) / original_total

    Args:
        original_total: Number of linter messages in the original code.
        revised_total:  Number of linter messages in the revised code.

    Returns:
        Float between -inf and 1.0, or None if original_total == 0.
        Positive values mean messages were reduced.
        Negative values mean new messages appeared.
    """
    if original_total == 0:
        return None
    return (original_total - revised_total) / original_total


def compute_new_messages(
    original_messages: List[Dict],
    revised_messages: List[Dict],
) -> int:
    """Count new messages introduced by the revision.

    Uses (check_name, sanitized_message_content) as identity to be robust
    against line shifts while detecting when a model replaces one diagnostic
    instance with another of the same type (masking effect).
    
    The identity combines:
    - check_name: The linter rule type (e.g., "bugprone-unused-variable")
    - sanitized_content: Message text with line/column numbers removed
    
    This prevents:
    1. False positives from line shifts (same message, different line)
    2. False negatives from masking (different messages, same type)

    Args:
        original_messages: List of linter message dicts from the original code.
        revised_messages:  List of linter message dicts from the revised code.

    Returns:
        Total count of new messages introduced.
    """
    orig_counts: Counter = Counter()
    rev_counts: Counter = Counter()

    for msg in original_messages:
        # Create identity as (check_name, sanitized_content)
        check_name = msg.get("check_name", "")
        content = msg.get("message_text", "")
        if check_name:
            identity = (check_name, sanitize_message(content))
            orig_counts[identity] += 1

    for msg in revised_messages:
        check_name = msg.get("check_name", "")
        content = msg.get("message_text", "")
        if check_name:
            identity = (check_name, sanitize_message(content))
            rev_counts[identity] += 1

    # Calculate new messages: for each identity, if revised count > original count
    new_total = 0
    all_identities = set(orig_counts.keys()) | set(rev_counts.keys())
    for identity in all_identities:
        orig_c = orig_counts.get(identity, 0)
        rev_c = rev_counts.get(identity, 0)
        delta = rev_c - orig_c
        if delta > 0:
            new_total += delta

    return new_total


def compute_line_churn(original_code: str, revised_code: str) -> Optional[float]:
    """Compute Line Churn = (added_lines + deleted_lines) / original_LOC.

    Uses difflib.SequenceMatcher on lines.

    Args:
        original_code: Original source code string.
        revised_code:  Revised source code string.

    Returns:
        Float >= 0, or None if original has 0 lines.
    """
    orig_lines = original_code.splitlines(keepends=True)
    rev_lines = revised_code.splitlines(keepends=True)

    if len(orig_lines) == 0:
        return None

    sm = SequenceMatcher(None, orig_lines, rev_lines)
    added = 0
    deleted = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            deleted += i2 - i1
            added += j2 - j1
        elif tag == "delete":
            deleted += i2 - i1
        elif tag == "insert":
            added += j2 - j1

    return (added + deleted) / len(orig_lines)


def compute_patch_count(original_code: str, revised_code: str) -> int:
    """Count the number of edit hunks between original and revised code.

    This is used as a proxy for the number of search-and-replace blocks
    generated by the model.
    """
    orig_lines = original_code.splitlines(keepends=True)
    rev_lines = revised_code.splitlines(keepends=True)

    sm = SequenceMatcher(None, orig_lines, rev_lines)
    return sum(1 for tag, *_ in sm.get_opcodes() if tag != "equal")


def compute_fixed_messages(
    original_messages: List[Dict],
    revised_messages: List[Dict],
) -> int:
    """Count the number of successfully fixed linter messages.

    Uses the SAME (check_name, sanitized_content) identity as
    :func:`compute_new_messages`, so the counts are consistent:
    ``fixed_count - new_count == original_total - revised_total``
    (i.e. ``Reduction == FixedRate - NewRate``).

    fixed_count = sum over identities of max(0, orig_count - revised_count).

    Args:
        original_messages: List of linter message dicts from original code.
        revised_messages:  List of linter message dicts from revised code.

    Returns:
        Number of message instances that were fixed (present in original,
        absent in reduced multiplicity in revised).
    """
    orig_counts: Counter = Counter()
    rev_counts: Counter = Counter()
    for msg in original_messages:
        check_name = msg.get("check_name", "")
        if check_name:
            orig_counts[(check_name, sanitize_message(msg.get("message_text", "")))] += 1
    for msg in revised_messages:
        check_name = msg.get("check_name", "")
        if check_name:
            rev_counts[(check_name, sanitize_message(msg.get("message_text", "")))] += 1
    return sum(max(0, oc - rev_counts.get(k, 0)) for k, oc in orig_counts.items())


def compute_lpm_p_sample(
    original_messages: List[Dict],
    revised_messages: List[Dict],
    added_lines: int,
    deleted_lines: int,
) -> Dict:
    """Compute LPM-P related values for a single sample.

    LPM-P (Lines Per Message) measures how many lines of code need to be changed
    to fix one linter message.

    For aggregation, we return:
    - lines_changed: total lines modified (added + deleted)
    - fixed_count: number of successfully fixed messages

    The final LPM-P is computed via micro-average:
    LPM-P = Σ lines_changed / Σ fixed_count

    Args:
        original_messages: List of linter message dicts from original code.
        revised_messages:  List of linter message dicts from revised code.
        added_lines:       Number of lines added by the revision.
        deleted_lines:     Number of lines deleted by the revision.

    Returns:
        Dict with:
            - lines_changed: total lines modified
            - fixed_count: number of fixed messages
            - has_fix: whether any message was fixed (fixed_count > 0)
    """
    lines_changed = added_lines + deleted_lines
    fixed_count = compute_fixed_messages(original_messages, revised_messages)

    return {
        "lines_changed": lines_changed,
        "fixed_count": fixed_count,
        "has_fix": fixed_count > 0,
    }


def compute_fix_redundancy(
    original_code: str,
    revised_code: str,
    original_messages: List[Dict],
) -> tuple[int, int, float]:
    """Compute patch count, lint error count, and redundancy indicator.
    
    Fix Redundancy is defined as I(P_i > E_i), where P_i is the number of
    patches generated for a sample and E_i is the number of lint errors
    detected on the original code.
    
    A patch is defined as a contiguous block of lines that were modified.
    We check if the model modified lines outside of the error lines reported
    by the linter. If so, the repair is considered redundant.
    
    Args:
        original_code: Original source code string.
        revised_code: Revised source code string.
        original_messages: List of linter message dicts from original code.
            Each message should have a 'line' field indicating the error line.
    
    Returns:
        Tuple of (patch_count, lint_error_count, redundancy_indicator)
    """
    # Extract error lines from original messages
    error_lines = set()
    for msg in original_messages:
        line = msg.get("line")
        if line is not None:
            error_lines.add(line)
    
    # Compare original and revised code to find modified lines
    orig_lines = original_code.splitlines(keepends=True)
    rev_lines = revised_code.splitlines(keepends=True)
    
    sm = SequenceMatcher(None, orig_lines, rev_lines)
    
    # Count patches (contiguous blocks of modifications)
    patch_count = sum(1 for tag, *_ in sm.get_opcodes() if tag != "equal")
    
    # Track which lines were modified (in original line numbering)
    modified_lines = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            # Lines i1+1 to i2 in original were modified (1-indexed)
            for line_num in range(i1 + 1, i2 + 1):
                modified_lines.add(line_num)
    
    # Check if any modified line is outside of error lines
    lines_outside_errors = modified_lines - error_lines
    
    # If there are modifications outside error lines, it's redundant
    redundancy = 1.0 if len(lines_outside_errors) > 0 else 0.0
    
    lint_error_count = len(original_messages)
    
    return patch_count, lint_error_count, redundancy


def _count_lines_diff(original_code: str, revised_code: str) -> tuple:
    """Compute added and deleted line counts separately.

    Returns (added_lines, deleted_lines).
    """
    orig_lines = original_code.splitlines(keepends=True)
    rev_lines = revised_code.splitlines(keepends=True)

    sm = SequenceMatcher(None, orig_lines, rev_lines)
    added = 0
    deleted = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            deleted += i2 - i1
            added += j2 - j1
        elif tag == "delete":
            deleted += i2 - i1
        elif tag == "insert":
            added += j2 - j1

    return added, deleted


def compute_category_mrr(
    original_messages: List[Dict],
    revised_messages: List[Dict],
) -> Dict[str, float]:
    """Compute per-category MRR@Pass.

    For each category:
        MRR_cat = (orig_cat_count - revised_cat_count) / orig_cat_count

    Categories where orig_cat_count == 0 are skipped.

    Args:
        original_messages: Linter messages from original code.
        revised_messages:  Linter messages from revised code.

    Returns:
        Dict mapping category name to MRR float. Categories with 0 original
        messages are omitted.
    """
    orig_counts: Counter = Counter()
    rev_counts: Counter = Counter()

    for msg in original_messages:
        cat = msg.get("category", "other")
        orig_counts[cat] += 1

    for msg in revised_messages:
        cat = msg.get("category", "other")
        rev_counts[cat] += 1

    result: Dict[str, float] = {}
    for cat in CATEGORIES:
        orig_c = orig_counts.get(cat, 0)
        if orig_c == 0:
            continue
        rev_c = rev_counts.get(cat, 0)
        result[cat] = (orig_c - rev_c) / orig_c

    return result


def _category_counts(messages: List[Dict]) -> Dict[str, int]:
    """Count messages per category, ensuring all CATEGORIES are present."""
    counts: Dict[str, int] = {cat: 0 for cat in CATEGORIES}
    for msg in messages:
        cat = msg.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def compute_sample_metrics(
    original_code: str,
    revised_code: str,
    original_messages: List[Dict],
    revised_messages: List[Dict],
    pass_at_1: bool,
) -> Dict:
    """Compute all metrics for a single sample.

    Args:
        original_code:      Original C++ source code.
        revised_code:       Revised C++ source code.
        original_messages:  Linter messages from original code.
        revised_messages:   Linter messages from revised code.
        pass_at_1:          Whether the revised code passes all tests.

    Returns:
        Dict with all metric values. MRR/NewMsg/LineChurn are computed
        regardless of pass_at_1 but are most meaningful when pass_at_1=True.
    """
    original_total = len(original_messages)
    revised_total = len(revised_messages)

    # Messages remaining from original (identities that still appear in revised)
    orig_identities: Counter = Counter()
    for msg in original_messages:
        identity = msg.get("message_identity", "")
        if identity:
            orig_identities[identity] += 1

    rev_identities: Counter = Counter()
    for msg in revised_messages:
        identity = msg.get("message_identity", "")
        if identity:
            rev_identities[identity] += 1

    old_remaining = 0
    for identity, orig_count in orig_identities.items():
        rev_count = rev_identities.get(identity, 0)
        old_remaining += min(orig_count, rev_count)

    new_messages_count = compute_new_messages(original_messages, revised_messages)

    mrr = compute_mrr(original_total, revised_total)
    patch_count, lint_error_count, redundancy_p = compute_fix_redundancy(
        original_code,
        revised_code,
        original_messages,
    )
    line_churn = compute_line_churn(original_code, revised_code)
    category_mrr = compute_category_mrr(original_messages, revised_messages)

    orig_loc = len(original_code.splitlines())
    rev_loc = len(revised_code.splitlines())

    added_lines, deleted_lines = _count_lines_diff(original_code, revised_code)

    lpm_p_data = compute_lpm_p_sample(
        original_messages,
        revised_messages,
        added_lines,
        deleted_lines,
    )

    original_category_counts = _category_counts(original_messages)
    revised_category_counts = _category_counts(revised_messages)

    return {
        "original_total_messages": original_total,
        "revised_total_messages": revised_total,
        "old_messages_remaining": old_remaining,
        "new_messages_count": new_messages_count,
        "mrr_at_pass": mrr,
        "new_msg_per_sample_at_pass": float(new_messages_count),
        "patch_count": patch_count,
        "lint_error_count": lint_error_count,
        "redundancy_p": redundancy_p,
        "lpm_p_lines_changed": lpm_p_data["lines_changed"],
        "lpm_p_fixed_count": lpm_p_data["fixed_count"],
        "lpm_p_has_fix": lpm_p_data["has_fix"],
        "line_churn_at_pass": line_churn,
        "original_loc": orig_loc,
        "revised_loc": rev_loc,
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "category_mrr": category_mrr,
        "original_category_counts": original_category_counts,
        "revised_category_counts": revised_category_counts,
        "pass_at_1": pass_at_1,
    }


def aggregate_metrics(
    sample_metrics: List[Dict],
    passed_only: bool = True,
) -> Dict:
    """Aggregate metrics across samples.

    Args:
        sample_metrics: List of dicts from compute_sample_metrics.
        passed_only:    If True, only include samples where pass_at_1 is True.

    Returns:
        Summary dict with:
            - n_samples:       total number of input samples
            - n_passed:        number of passing samples
            - pass_rate:       fraction of samples that passed
            - avg_mrr_at_pass:         mean MRR across qualifying samples
            - avg_new_msg_at_pass:     mean new messages count
            - avg_redundancy_p:       mean redundancy indicator
            - lpm_p:                  micro-average LPM-P (lines per message fixed)
            - avg_line_churn_at_pass:  mean line churn
            - category_mrr:    dict of per-category average MRR
            - avg_original_messages:   mean original message count
            - avg_revised_messages:    mean revised message count
            - avg_old_remaining:       mean old messages remaining
            - avg_original_loc:        mean original LOC
            - avg_revised_loc:         mean revised LOC
    """
    n_total = len(sample_metrics)
    if n_total == 0:
        return {
            "n_samples": 0,
            "n_passed": 0,
            "pass_rate": 0.0,
            "avg_mrr_at_pass": None,
            "avg_new_msg_at_pass": None,
            "avg_redundancy_p": None,
            "lpm_p": None,
            "avg_line_churn_at_pass": None,
            "category_mrr": {},
            "avg_original_messages": None,
            "avg_revised_messages": None,
            "avg_old_remaining": None,
            "avg_original_loc": None,
            "avg_revised_loc": None,
        }

    # Filter samples
    passing_samples = [s for s in sample_metrics if s.get("pass_at_1", False)]
    n_passed = len(passing_samples)
    pass_rate = n_passed / n_total

    if passed_only:
        pool = passing_samples
    else:
        pool = list(sample_metrics)

    pool_size = len(pool)

    if pool_size == 0:
        return {
            "n_samples": n_total,
            "n_passed": n_passed,
            "pass_rate": pass_rate,
            "avg_mrr_at_pass": None,
            "avg_new_msg_at_pass": None,
            "avg_redundancy_p": None,
            "lpm_p": None,
            "avg_line_churn_at_pass": None,
            "category_mrr": {},
            "avg_original_messages": None,
            "avg_revised_messages": None,
            "avg_old_remaining": None,
            "avg_original_loc": None,
            "avg_revised_loc": None,
        }

    # Aggregate scalar metrics
    mrr_values = [s["mrr_at_pass"] for s in pool if s["mrr_at_pass"] is not None]
    avg_mrr = sum(mrr_values) / len(mrr_values) if mrr_values else None

    avg_new_msg = sum(s["new_msg_per_sample_at_pass"] for s in pool) / pool_size

    redundancy_values = [s["redundancy_p"] for s in pool if s.get("redundancy_p") is not None]
    avg_redundancy = sum(redundancy_values) / len(redundancy_values) if redundancy_values else None

    lpm_p_total_lines = sum(
        s["lpm_p_lines_changed"] for s in pool if s.get("lpm_p_has_fix", False)
    )
    lpm_p_total_fixed = sum(
        s["lpm_p_fixed_count"] for s in pool if s.get("lpm_p_has_fix", False)
    )
    lpm_p = lpm_p_total_lines / lpm_p_total_fixed if lpm_p_total_fixed > 0 else None

    churn_values = [s["line_churn_at_pass"] for s in pool if s["line_churn_at_pass"] is not None]
    avg_churn = sum(churn_values) / len(churn_values) if churn_values else None

    avg_orig_msg = sum(s["original_total_messages"] for s in pool) / pool_size
    avg_rev_msg = sum(s["revised_total_messages"] for s in pool) / pool_size
    avg_old_remaining = sum(s["old_messages_remaining"] for s in pool) / pool_size
    avg_orig_loc = sum(s["original_loc"] for s in pool) / pool_size
    avg_rev_loc = sum(s["revised_loc"] for s in pool) / pool_size

    # Aggregate per-category MRR
    category_mrr_agg: Dict[str, List[float]] = {cat: [] for cat in CATEGORIES}
    for s in pool:
        cat_mrr = s.get("category_mrr", {})
        for cat in CATEGORIES:
            if cat in cat_mrr:
                category_mrr_agg[cat].append(cat_mrr[cat])

    category_mrr_avg: Dict[str, float] = {}
    for cat in CATEGORIES:
        values = category_mrr_agg[cat]
        if values:
            category_mrr_avg[cat] = sum(values) / len(values)

    return {
        "n_samples": n_total,
        "n_passed": n_passed,
        "pass_rate": pass_rate,
        "avg_mrr_at_pass": avg_mrr,
        "avg_new_msg_at_pass": avg_new_msg,
        "avg_redundancy_p": avg_redundancy,
        "lpm_p": lpm_p,
        "avg_line_churn_at_pass": avg_churn,
        "category_mrr": category_mrr_avg,
        "avg_original_messages": avg_orig_msg,
        "avg_revised_messages": avg_rev_msg,
        "avg_old_remaining": avg_old_remaining,
        "avg_original_loc": avg_orig_loc,
        "avg_revised_loc": avg_rev_loc,
    }
