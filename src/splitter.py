"""Problem-level train / valid / test split.

IMPORTANT: Splitting is done at the *problem* level, not the *sample* level.
This prevents data leakage where different submissions of the same problem
end up in different splits.
"""

from __future__ import annotations

import random
from typing import Dict, List, Sequence

try:
    from utils import seed_all
except ImportError:
    from src.utils import seed_all


def split_problems(
    problem_ids: Sequence[str],
    train_ratio: float = 0.7,
    valid_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> Dict[str, List[str]]:
    """Split problem IDs into disjoint train / valid / test sets.

    The ratios are normalised so they sum to 1.0.  After assigning the
    requested number of problems to each split (rounded down), any remainder
    due to rounding is distributed to the train set.

    Args:
        problem_ids: A sequence of unique problem ID strings.
        train_ratio: Target fraction for the training set.
        valid_ratio: Target fraction for the validation set.
        test_ratio: Target fraction for the test set.
        seed: Random seed for reproducibility.

    Returns:
        Dict with keys ``"train"``, ``"valid"``, ``"test"``, each mapping to
        a list of problem ID strings.
    """
    # Normalise ratios.
    total_ratio = train_ratio + valid_ratio + test_ratio
    if total_ratio <= 0:
        raise ValueError("At least one ratio must be positive.")
    train_r = train_ratio / total_ratio
    valid_r = valid_ratio / total_ratio
    # test gets the remainder to avoid floating-point issues.

    # Deterministic shuffle.
    ids = list(problem_ids)
    seed_all(seed)
    random.shuffle(ids)

    n = len(ids)
    n_valid = int(n * valid_r)
    n_test = int(n * (1.0 - train_r - valid_r))
    n_train = n - n_valid - n_test

    # Slice in order: train | valid | test.
    train_ids = ids[:n_train]
    valid_ids = ids[n_train : n_train + n_valid]
    test_ids = ids[n_train + n_valid :]

    split: Dict[str, List[str]] = {
        "train": train_ids,
        "valid": valid_ids,
        "test": test_ids,
    }

    # Sanity checks.
    assert len(split["train"]) + len(split["valid"]) + len(split["test"]) == n, (
        "Split sizes do not add up to the total number of problems."
    )
    all_assigned = set(split["train"]) | set(split["valid"]) | set(split["test"])
    assert len(all_assigned) == n, (
        "Duplicate problem IDs detected across splits."
    )

    return split
