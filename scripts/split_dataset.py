#!/usr/bin/env python3
"""Split / merge the full LintEval dataset.

GitHub enforces a 100 MB per-file limit, while ``data/linteval_full.jsonl`` is
~233 MB. To ship the full dataset in the repository we store it as three
line-aligned, size-balanced shards:

    data/linteval_full.jsonl.part1
    data/linteval_full.jsonl.part2
    data/linteval_full.jsonl.part3

Usage:
    # Split the (existing) full file into shards:
    python scripts/split_dataset.py --split

    # Merge shards back into a single JSONL for evaluation:
    python scripts/split_dataset.py --merge
    # or: cat data/linteval_full.jsonl.part{1,2,3} > data/linteval_full.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = PROJECT_ROOT / "data" / "linteval_full.jsonl"
DEFAULT_N_SHARDS = 3


def split_file(path: Path, n_shards: int) -> None:
    total = path.stat().st_size
    target = total / n_shards
    print(f"Splitting {path} ({total/1024/1024:.1f} MB) into {n_shards} shards ...")

    out_paths = []
    for i in range(1, n_shards + 1):
        p = path.with_name(f"{path.name}.part{i}")
        out_paths.append(p)
        p.unlink(missing_ok=True)

    cur_shard = 1
    cur_fh = open(out_paths[0], "wb")
    cur_bytes = 0
    n_lines = 0
    with open(path, "rb") as fh:
        for line in fh:
            cur_fh.write(line)
            cur_bytes += len(line)
            n_lines += 1
            # Move to the next shard once the current one reaches the target
            # size, as long as we still have shards left.
            if cur_shard < n_shards and cur_bytes >= target:
                cur_fh.close()
                print(f"  {out_paths[cur_shard-1].name}: {cur_bytes/1024/1024:.1f} MB")
                cur_fh = open(out_paths[cur_shard], "wb")
                cur_shard += 1
                cur_bytes = 0
    cur_fh.close()
    print(f"  {out_paths[cur_shard-1].name}: {cur_bytes/1024/1024:.1f} MB")
    print(f"Done. {n_lines} lines across {n_shards} shards.")

    # Sanity: merged shards must reproduce the original byte-for-byte.
    ok = True
    with open(path, "rb") as fh:
        for p in out_paths:
            chunk = p.read_bytes()
            ref = fh.read(len(chunk))
            if chunk != ref:
                ok = False
    print(f"Shard order sanity check: {'OK' if ok else 'FAILED'}")


def merge_shards(path: Path, n_shards: int) -> None:
    parts = [path.with_name(f"{path.name}.part{i}") for i in range(1, n_shards + 1)]
    missing = [str(p) for p in parts if not p.exists()]
    if missing:
        print(f"Missing shards: {missing}")
        sys.exit(1)
    with open(path, "wb") as out:
        for p in parts:
            out.write(p.read_bytes())
    print(f"Merged {n_shards} shards -> {path} ({path.stat().st_size/1024/1024:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", action="store_true", help="split the full JSONL into shards")
    parser.add_argument("--merge", action="store_true", help="merge shards back into the full JSONL")
    parser.add_argument("--data", type=str, default=str(DEFAULT_DATA), help="path to the full JSONL")
    parser.add_argument("--n_shards", type=int, default=DEFAULT_N_SHARDS, help="number of shards")
    args = parser.parse_args()

    data_path = Path(args.data)
    if args.split:
        if not data_path.exists():
            print(f"Data file not found: {data_path}")
            sys.exit(1)
        split_file(data_path, args.n_shards)
    elif args.merge:
        merge_shards(data_path, args.n_shards)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
