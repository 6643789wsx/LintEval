#!/usr/bin/env python3
"""One-command end-to-end smoke test.

Runs a single LintEval sample through the full pipeline:
    prompt -> API call -> code extraction -> re-lint -> compile + unit tests -> metrics

It defaults to the PKU MaaS endpoint and the ``gpt-6-luna`` model, reading the
credentials from the environment:

    pku_maas_base_url / PKU_MAAS_BASE_URL
    pku_maas_api_key  / PKU_MAAS_API_KEY
    pku_maas_model_name / PKU_MAAS_MODEL_NAME   (optional, default: gpt-6-luna)

Usage:
    export pku_maas_base_url=https://chat.pku.edu.cn/v1
    export pku_maas_api_key=sk-...
    python scripts/smoke_test.py                       # 1 Python sample
    python scripts/smoke_test.py --language java
    python scripts/smoke_test.py --model gpt-6-luna --keep-input
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LITE_JSONL = REPO_ROOT / "lite" / "linteval_lite.jsonl"
RESULT_DIR = REPO_ROOT / "eval_results"


def env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


def pick_sample(language: str, out_path: Path) -> dict:
    with LITE_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("language") == language:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with out_path.open("w", encoding="utf-8") as out:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                return record
    raise SystemExit(f"No sample with language={language!r} found in {LITE_JSONL}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="py3", choices=["py3", "java", "cpp"],
                        help="language of the sample to smoke-test (default: py3)")
    parser.add_argument("--model", default="", help="model id (default: $pku_maas_model_name or gpt-6-luna)")
    parser.add_argument("--api-timeout", type=int, default=300, help="per-request timeout in seconds")
    parser.add_argument("--keep-input", action="store_true", help="keep the 1-sample input file")
    args = parser.parse_args()

    base_url = env_first("pku_maas_base_url", "PKU_MAAS_BASE_URL", "CUSTOM_BASE_URL")
    api_key = env_first("pku_maas_api_key", "PKU_MAAS_API_KEY", "CUSTOM_API_KEY")
    model = args.model or env_first("pku_maas_model_name", "PKU_MAAS_MODEL_NAME") or "gpt-6-luna"

    print("=" * 64)
    print("LintEval smoke test")
    print("=" * 64)
    print(f"base_url : {base_url or 'NOT SET'}")
    print(f"api_key  : {'set (...) ' + api_key[-4:] if api_key else 'NOT SET'}")
    print(f"model    : {model}")
    print(f"sample   : first {args.language} record of lite/linteval_lite.jsonl")
    print()

    if not base_url or not api_key:
        print("Missing credentials. Export them first, e.g.:")
        print("  export pku_maas_base_url=https://chat.pku.edu.cn/v1")
        print("  export pku_maas_api_key=sk-...")
        return 2

    smoke_input = RESULT_DIR / "_smoke_input.jsonl"
    record = pick_sample(args.language, smoke_input)
    print(f"sample_id={record.get('sample_id')}  problem={record.get('problem_id')}  "
          f"original linter messages={record.get('linter_message_count')}")

    # Credentials are passed through the environment (never on the command line),
    # so they do not show up in process listings or logs.
    child_env = dict(os.environ)
    child_env["CUSTOM_API_KEY"] = api_key
    child_env["CUSTOM_BASE_URL"] = base_url
    cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "10_eval_models.py"),
        "--custom_api",
        "--model", model,
        "--api_display_name", f"smoke_{model}",
        "--data_path", str(smoke_input),
        "--limit", "1",
        "--api_timeout", str(args.api_timeout),
    ]
    print("\n$ " + " ".join(cmd) + "\n")
    completed = subprocess.run(cmd, cwd=REPO_ROOT, env=child_env)

    result_path = RESULT_DIR / f"smoke_{model.replace('.', '_').replace(' ', '_')}.json"
    print()
    if not result_path.exists():
        print(f"Smoke test FAILED: expected result file not found: {result_path}")
        return 1

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    entry = (payload.get("results") or [{}])[0]
    print("=" * 64)
    print("Smoke test summary")
    print("=" * 64)
    print(f"  model            : {summary.get('model', model)}")
    print(f"  samples          : {payload.get('total_entries')}")
    print(f"  compile + tests  : {'PASS' if entry.get('pass') else 'FAIL'}")
    print(f"  tests generated  : {entry.get('tests_generated')}")
    print(f"  linter messages  : {entry.get('in_total')} -> {entry.get('out_total')} "
          f"(new: {entry.get('new_msg_count')})")
    print(f"  pass@1           : {summary.get('pass@1')}")
    print(f"  MRR@P            : {summary.get('avg_mrr_at_pass')}")
    ok = completed.returncode == 0 and entry.get("pass") is not None
    print("=" * 64)
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED (see output above)")
    if not args.keep_input and smoke_input.exists():
        smoke_input.unlink()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
