#!/usr/bin/env python3
"""Regenerate the released dataset artifacts (Parquet + JSON preview) from JSONL.

The repository ships the datasets in two folders:

    full/   LintEval-Full   (13,061 samples, 3,999 problems)
    lite/   LintEval-Lite   (498 samples, stratified)

Each folder contains the dataset in JSONL and Parquet, plus a small `preview.json`
with the first records of every language so that people can inspect the schema
without downloading anything.

This script rebuilds the Parquet files and the previews from the JSONL sources and
verifies that the record count is preserved.

Usage:
    python scripts/build_dataset_files.py                # rebuild everything
    python scripts/build_dataset_files.py --check        # verify only, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PREVIEW_PER_LANGUAGE = 1
GITHUB_FILE_LIMIT_MB = 95  # stay below GitHub's 100 MB blob limit


def jsonl_paths(folder: Path) -> list[Path]:
    """Return the JSONL sources of a split, merged file first."""
    merged = folder / f"linteval_{folder.name}.jsonl"
    if merged.exists():
        return [merged]
    parts = sorted(folder.glob("linteval_*.jsonl.part*"))
    if not parts:
        raise FileNotFoundError(f"No JSONL sources found in {folder}")
    return parts


def read_jsonl(paths: list[Path]) -> list[dict]:
    records: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def parquet_sources(folder: Path) -> list[Path]:
    """Parquet files of a split, including sharded ``*.parquet.partN`` files."""
    files = list(folder.glob("*.parquet")) + list(folder.glob("*.parquet.part*"))
    return sorted(files)


def build_parquet(folder: Path, records: list[dict], check_only: bool) -> dict:
    from datasets import Dataset

    dataset = Dataset.from_list(records)
    single_target = folder / f"linteval_{folder.name}.parquet"
    info = {"records": len(records), "columns": len(dataset.column_names)}

    if check_only:
        return info

    # Remove previously generated parquet shards so the folder stays canonical.
    for stale in parquet_sources(folder):
        stale.unlink()

    dataset.to_parquet(str(single_target))
    size_mb = single_target.stat().st_size / 1024**2
    if size_mb <= GITHUB_FILE_LIMIT_MB:
        info["parquet_files"] = [single_target.name]
        info["largest_parquet_mb"] = round(size_mb, 1)
        return info

    # Too large for a single GitHub blob: shard into equal row blocks.
    single_target.unlink()
    import math

    num_shards = math.ceil(size_mb / GITHUB_FILE_LIMIT_MB)
    for index in range(num_shards):
        shard = dataset.shard(num_shards=num_shards, index=index, contiguous=True)
        target = folder / f"linteval_{folder.name}.parquet.part{index + 1}"
        shard.to_parquet(str(target))
    files = sorted(p.name for p in parquet_sources(folder))
    info["parquet_files"] = files
    info["largest_parquet_mb"] = round(
        max(p.stat().st_size for p in parquet_sources(folder)) / 1024**2, 1
    )
    return info


def build_preview(folder: Path, records: list[dict], check_only: bool) -> dict:
    per_language: dict[str, int] = {}
    preview: list[dict] = []
    for record in records:
        language = record.get("language", "unknown")
        if per_language.get(language, 0) < PREVIEW_PER_LANGUAGE:
            preview.append(record)
            per_language[language] = per_language.get(language, 0) + 1
    if not check_only:
        target = folder / "preview.json"
        with target.open("w", encoding="utf-8") as handle:
            json.dump(preview, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return {"preview_records": len(preview), "preview_languages": sorted(per_language)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = parser.parse_args()

    report: dict[str, dict] = {}
    failed = False
    for name in ("full", "lite"):
        folder = REPO_ROOT / name
        if not folder.is_dir():
            print(f"MISSING folder: {folder}")
            failed = True
            continue
        sources = jsonl_paths(folder)
        records = read_jsonl(sources)
        expected = 13061 if name == "full" else 498
        entry = {
            "jsonl_sources": [p.name for p in sources],
            **build_parquet(folder, records, args.check),
            **build_preview(folder, records, args.check),
        }
        if len(records) != expected:
            print(f"WARNING {name}: {len(records)} records, expected {expected}")
            failed = True
        report[name] = entry

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check:
        for name, entry in report.items():
            files = entry.get("parquet_files") or [p.name for p in parquet_sources(REPO_ROOT / name)]
            if not files:
                print(f"CHECK FAILED: no parquet in {name}/")
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
