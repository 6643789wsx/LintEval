"""
10_eval_models.py - Evaluate base/finetuned models on the C++ linter-guided
code revision benchmark test split.

Reads held-out test instances, generates revised code using vLLM (for local
models) or API (for DeepSeek), then computes:
  - Pass@1: compile + test pass
  - MRR@Pass: message reduction rate on passed samples
  - New Msg./Sample@Pass: new messages per passed sample
  - LPM-P: lines per message reduction on passed samples
  - Category-level MRR

Usage:
  python scripts/10_eval_models.py --model_name X --model_path Y [--gpu 0]
  python scripts/10_eval_models.py --all [--gpu 0]
  python scripts/10_eval_models.py --deepseek
  python scripts/10_eval_models.py --merged [--gpu 0]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Make src/ importable regardless of invocation directory.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.utils import extract_code_from_response  # noqa: E402
from src.prompt_templates import (  # noqa: E402
    SYSTEM_MSG,
    REVISION_PROMPT_TEMPLATE,
    build_revision_prompt,
    build_generic_improve_prompt,
    build_shuffled_alert_prompt,
    build_rule_only_prompt,
    build_message_only_prompt,
    build_location_only_prompt,
    format_linter_messages,
)
from src.linter_factory import (  # noqa: E402
    run_linter,
    compile_code,
    count_by_category,
)
from src.test_runner_multi import validate_submission_multi  # noqa: E402
from src.metrics import (  # noqa: E402
    CATEGORIES,
    compute_mrr,
    compute_new_messages,
    compute_patch_count,
    compute_line_churn,
    compute_category_mrr,
    compute_sample_metrics,
    aggregate_metrics,
    compute_lpm_p_sample,
    compute_fixed_messages,
)

# ============================================================
# Paths & Constants
# ============================================================

BENCHMARK_DIR = _PROJECT_ROOT
# Default evaluation dataset: LintEval-Lite (498 samples).
# Override with --data_path to evaluate another split (e.g. the full 13,061-sample set).
DATA_PATH = BENCHMARK_DIR / "data" / "linteval_lite_test.jsonl"
RESULT_DIR = BENCHMARK_DIR / "eval_results"
OUTPUTS_DIR = BENCHMARK_DIR / "outputs"
TESTLIB_INCLUDE = str(BENCHMARK_DIR / "tools")

BASE_MODELS = {
    "Qwen2.5-Coder-0.5B": "/path/to/Qwen2.5-Coder-0.5B-Instruct",
    "Qwen2.5-Coder-3B": "/path/to/Qwen2.5-Coder-3B-Instruct",
    "Qwen2.5-Coder-7B": "/path/to/Qwen2.5-Coder-7B-Instruct",
}

DEEPSEEK_CONFIG = {
    "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
    "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    "model_id": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    "display_name": "DeepSeek",
}

CUSTOM_API_CONFIG = {
    "api_key": "",
    "base_url": "",
    "model_id": "",
    "display_name": "",
}


# ============================================================
# Data Loading
# ============================================================

def load_test_data(path: Path, limit: int = 0) -> List[Dict]:
    """Load test data from JSONL.

    For v3_test_eval.jsonl (pre-filtered v3 test set), load all records.
    For validated_revisions.jsonl, filter to split=='test'.
    """
    is_v3_eval = "v3_test_eval" in path.name
    records: List[Dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if is_v3_eval or rec.get("split") == "test" or "split" not in rec:
                records.append(rec)
    if limit > 0:
        records = records[:limit]
    return records


# ============================================================
# Baseline Computation
# ============================================================

def _baseline_one(args_tuple):
    """Worker for single baseline computation (top-level for pickling)."""
    i, entry = args_tuple
    code = entry.get("code", "")
    language = entry.get("language", "cpp")
    if not code or not code.strip():
        return {
            "index": i,
            "sample_id": entry.get("sample_id", f"unknown_{i}"),
            "language": language,
            "loc": 0,
            "messages": [],
            "total": 0,
            "categories": {cat: 0 for cat in CATEGORIES},
        }
    msgs = run_linter(code, language)
    cats = count_by_category(msgs)
    return {
        "index": i,
        "sample_id": entry.get("sample_id", f"unknown_{i}"),
        "language": language,
        "loc": len(code.splitlines()),
        "messages": msgs,
        "total": len(msgs),
        "categories": cats,
    }


def compute_baseline(data: List[Dict], n_workers: int = 8) -> List[Dict]:
    """Run linter on original code for each test sample (multi-language, parallel)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    t0 = time.time()
    baselines: List[Dict] = [None] * len(data)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_baseline_one, (i, entry)): i for i, entry in enumerate(data)}
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            baselines[idx] = future.result()
            done += 1
            if done % 50 == 0:
                elapsed = time.time() - t0
                eta = elapsed / done * (len(data) - done)
                print(f"  baseline {done}/{len(data)} ({elapsed:.0f}s, ETA {eta:.0f}s)")

    print(f"Baseline done: {time.time()-t0:.1f}s")
    return baselines


def compute_table1(baselines: List[Dict]) -> Dict:
    """Compute benchmark statistics from baselines."""
    n = len(baselines)
    if n == 0:
        return {}

    locs = [b["loc"] for b in baselines]
    all_msgs: List[Dict] = []
    for b in baselines:
        all_msgs.extend(b["messages"])

    unique_types = set(m.get("check_name", "") for m in all_msgs if m.get("check_name"))
    cats = {cat: 0 for cat in CATEGORIES}
    for m in all_msgs:
        cat = m.get("category", "")
        if cat in cats:
            cats[cat] += 1

    return {
        "# Samples": n,
        "Avg. LOC": round(sum(locs) / n, 1) if n > 0 else 0,
        "# Total linter messages": len(all_msgs),
        "Avg. linter messages per sample": round(len(all_msgs) / n, 2) if n > 0 else 0,
        "# Message types": len(unique_types),
        "# Bugprone": cats.get("bugprone", 0),
        "# Performance": cats.get("performance", 0),
        "# Modernize": cats.get("modernize", 0),
        "# Readability": cats.get("readability", 0),
        "# Other": cats.get("other", 0),
    }


# ============================================================
# Prompt Building
# ============================================================

# Module-level state for ablation experiments
_ABLATION_MODE: str = "full"  # "full" | "no_message" | "shuffled" | "rule_only" | "message_only" | "location_only"
_SHUFFLED_MSG_POOL: Dict[str, List[List[Dict]]] = {}  # lang -> list of message lists for shuffled-alert


def _build_shuffled_pool(baselines: List[Dict], data: List[Dict]) -> None:
    """Pre-build shuffled message pool: for each language, collect all per-sample
    message lists. The shuffled prompt for sample i uses a randomly rotated
    non-self message list from the same language."""
    global _SHUFFLED_MSG_POOL
    import random
    random.seed(42)
    _SHUFFLED_MSG_POOL = {}
    n = min(len(baselines), len(data))
    for i in range(n):
        lang = data[i].get("language", "cpp")
        _SHUFFLED_MSG_POOL.setdefault(lang, []).append(baselines[i].get("messages", []))


def _get_shuffled_messages(sample_index: int, language: str) -> List[Dict]:
    """Get linter messages from a DIFFERENT file in the same language."""
    import random
    random.seed(42 + sample_index)
    pool = _SHUFFLED_MSG_POOL.get(language, [])
    if len(pool) <= 1:
        return pool[0] if pool else []
    # Pick a random non-self entry
    candidates = [m for j, m in enumerate(pool) if j != sample_index]
    if not candidates:
        return pool[0]
    return random.choice(candidates)


def build_user_message(original_code: str, linter_messages: List[Dict], language: str = "cpp") -> str:
    """Build the user message for the revision prompt."""
    formatted = format_linter_messages(linter_messages)
    from src.prompt_templates import build_lang_prompt_template
    template = build_lang_prompt_template(language)
    return template.format(
        code=original_code,
        messages=formatted,
    )


def build_chat_messages(original_code: str, linter_messages: List[Dict],
                        language: str = "cpp", sample_index: int = 0) -> List[Dict[str, str]]:
    """Build the full chat messages list for the model.

    Args:
        original_code: The source code to revise.
        linter_messages: Linter messages for THIS file (unused in shuffled mode).
        language: Source language ('cpp', 'py3', 'java').
        sample_index: Index of the current sample (needed for shuffled mode).
    """
    if _ABLATION_MODE == "no_message":
        return build_generic_improve_prompt(original_code, language=language)
    elif _ABLATION_MODE == "shuffled":
        shuffled = _get_shuffled_messages(sample_index, language)
        return build_shuffled_alert_prompt(original_code, shuffled, language=language)
    elif _ABLATION_MODE == "rule_only":
        return build_rule_only_prompt(original_code, linter_messages, language=language)
    elif _ABLATION_MODE == "message_only":
        return build_message_only_prompt(original_code, linter_messages, language=language)
    elif _ABLATION_MODE == "location_only":
        return build_location_only_prompt(original_code, linter_messages, language=language)
    else:
        return build_revision_prompt(original_code, linter_messages, language=language)


# ============================================================
# Evaluation Helpers
# ============================================================

def empty_result(index: int, sample_id: str, language: str = "cpp") -> Dict:
    """Return an empty result dict for failed extraction."""
    return {
        "index": index,
        "sample_id": sample_id,
        "language": language,
        "pass": False,
        "compile_ok": False,
        "out_total": 0,
        "out_categories": {cat: 0 for cat in CATEGORIES},
        "new_msg_count": 0,
        "mrr_at_pass": None,
        "line_churn": None,
        "generated_tokens": 0,
    }


def evaluate_single_response(
    index: int,
    sample_id: str,
    response_text: str,
    gen_tokens: int,
    original_code: str,
    original_messages: List[Dict],
    entry: Dict,
) -> Dict:
    """Evaluate a single model response.

    Extracts code, compiles, runs unit tests via generator/checker,
    runs linter, computes metrics.
    """
    language = entry.get("language", "cpp")

    # Extract code from response
    revised_code = extract_code_from_response(response_text, language=language)

    if not revised_code or not revised_code.strip():
        return empty_result(index, sample_id, language)

    # Run full test validation (compile + generate tests + run + check)
    with tempfile.TemporaryDirectory() as tmpdir:
        problem = {
            "solution": original_code,
            "generator": entry.get("generator", ""),
            "checker": entry.get("checker", ""),
            "generator_cmds": entry.get("generator_cmd", ""),
        }
        val_result = validate_submission_multi(
            code=revised_code,
            language=language,
            problem=problem,
            work_dir=tmpdir,
            testlib_include=TESTLIB_INCLUDE,
            max_tests=100,
            timeout_compile=30,
            timeout_run=5,
        )

    compile_ok = val_result.get("compile_ok", False)
    pass_at_1 = val_result.get("pass_at_1", False)
    tests_generated = val_result.get("tests_generated", 0)
    tests_passed = val_result.get("tests_passed", 0)
    tests_failed = val_result.get("tests_failed", 0)

    if not compile_ok:
        compile_error = "; ".join(val_result.get("errors", ["Unknown compile error"]))
        return {
            "index": index,
            "sample_id": sample_id,
            "language": language,
            "pass": False,
            "compile_ok": False,
            "compile_error": compile_error,
            "out_total": 0,
            "out_categories": {cat: 0 for cat in CATEGORIES},
            "new_msg_count": 0,
            "mrr_at_pass": None,
            "patch_count": 0,
            "lpm_p_lines_changed": 0,
            "lpm_p_fixed_count": 0,
            "lpm_p_has_fix": False,
            "added_lines": 0,
            "deleted_lines": 0,
            "line_churn": None,
            "generated_tokens": gen_tokens,
            "generated_code": revised_code,
        }

    # Run linter on revised code
    revised_messages = run_linter(revised_code, language)
    revised_cats = count_by_category(revised_messages)

    # Compute metrics
    original_total = len(original_messages)
    revised_total = len(revised_messages)

    mrr = compute_mrr(original_total, revised_total)
    new_msg_count = compute_new_messages(original_messages, revised_messages)
    patch_count = compute_patch_count(original_code, revised_code)
    line_churn = compute_line_churn(original_code, revised_code)
    category_mrr = compute_category_mrr(original_messages, revised_messages)

    # Compute added/deleted lines for LPM-P
    orig_lines = original_code.splitlines(keepends=True)
    rev_lines = revised_code.splitlines(keepends=True)
    sm = SequenceMatcher(None, orig_lines, rev_lines)
    added_lines = 0
    deleted_lines = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            deleted_lines += i2 - i1
            added_lines += j2 - j1
        elif tag == "delete":
            deleted_lines += i2 - i1
        elif tag == "insert":
            added_lines += j2 - j1

    lpm_p_data = compute_lpm_p_sample(original_messages, revised_messages, added_lines, deleted_lines)

    return {
        "index": index,
        "sample_id": sample_id,
        "language": language,
        "pass": pass_at_1,
        "compile_ok": True,
        "tests_generated": tests_generated,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "in_total": original_total,
        "out_total": revised_total,
        "out_categories": revised_cats,
        "new_msg_count": new_msg_count,
        "mrr_at_pass": mrr,
        "patch_count": patch_count,
        "lpm_p_lines_changed": lpm_p_data["lines_changed"],
        "lpm_p_fixed_count": lpm_p_data["fixed_count"],
        "lpm_p_has_fix": lpm_p_data["has_fix"],
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "line_churn": line_churn,
        "category_mrr": category_mrr,
        "generated_tokens": gen_tokens,
        "generated_code": revised_code,
    }


# ============================================================
# Model Evaluation (vLLM)
# ============================================================

def evaluate_model_vllm(
    model_name: str,
    model_path: str,
    data: List[Dict],
    baselines: List[Dict],
    tensor_parallel_size: int = 1,
    max_model_len: int = 0,
) -> List[Dict]:
    """Evaluate a local model using vLLM."""
    print(f"\n{'='*60}")
    print(f"vLLM evaluating: {model_name} (tp={tensor_parallel_size})")
    print(f"{'='*60}")

    from vllm import LLM, SamplingParams
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    llm_kwargs = dict(
        model=model_path,
        trust_remote_code=True,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=0.9,
    )
    if max_model_len > 0:
        llm_kwargs["max_model_len"] = max_model_len
    llm = LLM(**llm_kwargs)
    max_output_tokens = 4096
    sp = SamplingParams(temperature=0.0, max_tokens=max_output_tokens)

    # Build prompts via chat template and filter by context length
    effective_ctx = llm.llm_engine.model_config.max_model_len
    max_input_tokens = effective_ctx - max_output_tokens

    prompts: List[str] = []
    valid_indices: List[int] = []
    for i, entry in enumerate(data):
        code = entry.get("code", "")
        language = entry.get("language", "cpp")
        msgs = baselines[i]["messages"] if i < len(baselines) else []
        chat = build_chat_messages(code, msgs, language=language, sample_index=i)
        prompt_text = tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )
        n_tokens = len(tokenizer.encode(prompt_text))
        if n_tokens > max_input_tokens:
            print(f"  Skipping sample {i}: {n_tokens} tokens > {max_input_tokens} limit")
            continue
        prompts.append(prompt_text)
        valid_indices.append(i)

    skipped = len(data) - len(prompts)
    if skipped > 0:
        print(f"Skipped {skipped}/{len(data)} samples exceeding context limit ({max_input_tokens} tokens)")

    print(f"vLLM generating {len(prompts)} samples...")
    t0 = time.time()
    outputs = llm.generate(prompts, sp)
    print(f"vLLM done: {time.time()-t0:.1f}s")

    responses: List[str] = []
    gen_tokens_list: List[int] = []
    for o in outputs:
        responses.append(o.outputs[0].text)
        gen_tokens_list.append(len(o.outputs[0].token_ids))

    # Build full result list, filling skipped entries as failures
    results = _eval_responses(model_name, responses, gen_tokens_list,
                              [data[i] for i in valid_indices],
                              [baselines[i] for i in valid_indices])

    # Re-insert skipped samples as failed entries
    full_results: List[Dict] = []
    res_idx = 0
    for i in range(len(data)):
        if i in valid_indices:
            full_results.append(results[res_idx])
            res_idx += 1
        else:
            full_results.append({
                "index": i,
                "sample_id": f"v3_test_{i}",
                "language": data[i].get("language", "cpp"),
                "pass": False,
                "compile_ok": False,
                "compile_error": "prompt_exceeds_context",
                "out_total": 0,
                "out_categories": {},
                "new_msg_count": 0,
                "mrr_at_pass": None,
                "line_churn": None,
                "generated_tokens": 0,
                "generated_code": "",
            })
    return full_results


# ============================================================
# Model Evaluation (API - DeepSeek)
# ============================================================

def evaluate_model_api(
    config: Dict,
    data: List[Dict],
    baselines: List[Dict],
    n_workers: int = 4,
    only_indices: Optional[List[int]] = None,
    cache_path: Optional[Path] = None,
    api_timeout: int = 60,
    max_retries: int = 5,
) -> List[Dict]:
    """Evaluate model via API with parallel calls using requests library.

    If only_indices is provided, only those sample indices will be generated
    and evaluated (useful for resuming API failures).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import requests

    model_name = config["display_name"]
    print(f"\n{'='*60}")
    print(f"API evaluating: {model_name} (n_workers={n_workers})")
    print(f"{'='*60}")

    cache: Dict[str, Dict[str, Any]] = {}
    if cache_path is not None and cache_path.exists():
        try:
            cache = json.load(open(cache_path, "r", encoding="utf-8"))
        except Exception:
            cache = {}

    def _cache_key(i: int) -> str:
        return str(i)

    def _cache_put(i: int, content: str, tokens: int) -> None:
        if cache_path is None:
            return
        cache[_cache_key(i)] = {"content": content, "tokens": int(tokens)}
        _atomic_write_json(cache_path, cache)

    def call_api(i: int, entry: Dict, bl: Dict):
        code = entry.get("code", "")
        language = entry.get("language", "cpp")
        msgs = bl["messages"]
        chat = build_chat_messages(code, msgs, language=language, sample_index=i)

        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": config["model_id"],
            "messages": chat,
            "temperature": 0.0,
            "max_completion_tokens": 4096
        }

        ck = _cache_key(i)
        if ck in cache:
            item = cache.get(ck) or {}
            return i, (item.get("content") or ""), int(item.get("tokens") or 0)

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{config['base_url']}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=api_timeout
                )
                resp.raise_for_status()
                result = resp.json()
                
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"] or ""
                    tokens = result.get("usage", {}).get("completion_tokens", 0)
                    _cache_put(i, content, tokens)
                    return i, content, tokens
                else:
                    _cache_put(i, "", 0)
                    return i, "", 0
                    
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    wait_time = 10 * (attempt + 1)
                    print(f"  API rate limit sample {i} attempt {attempt+1}, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"  API error sample {i} attempt {attempt+1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(10 * (attempt + 1))
                    else:
                        _cache_put(i, "", 0)
                        return i, "", 0
            except Exception as e:
                print(f"  API error sample {i} attempt {attempt+1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(10 * (attempt + 1))
                else:
                    _cache_put(i, "", 0)
                    return i, "", 0
        
        _cache_put(i, "", 0)
        return i, "", 0

    indices = list(range(len(data))) if only_indices is None else sorted(set(int(i) for i in only_indices))
    responses = [""] * len(data)
    gen_tokens_list = [0] * len(data)
    done = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(call_api, i, entry, baselines[i]): i
            for i in indices
            for entry in [data[i]]
        }
        for future in as_completed(futures):
            idx, content, tokens = future.result()
            responses[idx] = content
            gen_tokens_list[idx] = tokens
            done += 1
            if done % 20 == 0 or done == len(indices):
                elapsed = time.time() - t0
                remaining = max(len(indices) - done, 0)
                eta = elapsed / done * remaining if done > 0 else 0
                print(f"  API {done}/{len(indices)} ({elapsed:.0f}s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    print(f"  API done: {done}/{len(indices)} samples in {elapsed:.0f}s")
    if only_indices is None:
        return _eval_responses(model_name, responses, gen_tokens_list, data, baselines)

    # Evaluate only the subset we generated.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: List[Dict] = [None] * len(data)
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=min(n_workers, max(len(indices), 1))) as pool:
        futures = {
            pool.submit(_eval_one_response, (i, responses[i], gen_tokens_list[i], data[i], baselines[i])): i
            for i in indices
        }
        eval_done = 0
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
            eval_done += 1
            if eval_done % 20 == 0 or eval_done == len(indices):
                elapsed = time.time() - t1
                remaining = max(len(indices) - eval_done, 0)
                eta = elapsed / eval_done * remaining if eval_done > 0 else 0
                print(f"  evaluated {eval_done}/{len(indices)} ({elapsed:.0f}s, ETA {eta:.0f}s)")
    return results


def _find_api_generation_failures(existing_results: List[Dict]) -> List[int]:
    """Heuristic: identify samples where the API call likely failed.

    We treat an entry as an API failure when it has no generated code and no
    generated tokens. This avoids re-running legitimate (but non-compiling)
    model outputs.
    """
    failed: List[int] = []
    for i, r in enumerate(existing_results):
        if not isinstance(r, dict):
            failed.append(i)
            continue
        gen_tokens = int(r.get("generated_tokens") or 0)
        gen_code = r.get("generated_code") or ""
        if gen_tokens == 0 and not gen_code.strip():
            failed.append(i)
    return failed


def _atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ============================================================
# Shared evaluation logic
# ============================================================

def _eval_one_response(args_tuple):
    """Worker for single response evaluation (top-level for pickling)."""
    i, response, gen_tokens, entry, bl = args_tuple
    original_code = entry.get("code", "")
    original_messages = bl["messages"]
    sample_id = entry.get("sample_id", f"unknown_{i}")
    return evaluate_single_response(
        index=i, sample_id=sample_id, response_text=response,
        gen_tokens=gen_tokens, original_code=original_code,
        original_messages=original_messages, entry=entry,
    )


def _eval_responses(
    model_name: str,
    responses: List[str],
    gen_tokens_list: List[int],
    data: List[Dict],
    baselines: List[Dict],
    n_workers: int = 8,
) -> List[Dict]:
    """Process model responses in parallel: extract code, compile, test, lint, compute metrics."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: List[Dict] = [None] * len(data)
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        args_list = [
            (i, responses[i], gen_tokens_list[i], data[i], baselines[i])
            for i in range(len(data))
        ]
        futures = {pool.submit(_eval_one_response, args): args[0] for args in args_list}
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
            done += 1
            if done % 20 == 0:
                elapsed = time.time() - t0
                eta = elapsed / done * (len(data) - done)
                print(f"  evaluated {done}/{len(data)} ({elapsed:.0f}s, ETA {eta:.0f}s)")

    return results


# ============================================================
# Aggregation
# ============================================================

def aggregate(model_name: str, results: List[Dict], baselines: List[Dict]) -> Dict:
    """Compute aggregate metrics from per-sample results."""
    n = len(results)
    if n == 0:
        return {"model": model_name}

    # Pass@1: fraction of samples where code compiled and tests passed
    passed = [r for r in results if r.get("pass")]
    pass_at_1 = round(len(passed) / n, 4)

    # MRR@Pass: only on passed samples, exclude orig_total=0
    mrr_vals: List[float] = []
    for r in passed:
        bl = baselines[r["index"]]
        orig_total = bl["total"]
        if orig_total > 0:
            mrr_vals.append((orig_total - r["out_total"]) / orig_total)
    avg_mrr = round(sum(mrr_vals) / len(mrr_vals), 4) if mrr_vals else 0

    # Per-category MRR@Pass
    cat_mrr: Dict[str, float] = {}
    for cat in CATEGORIES:
        vals: List[float] = []
        for r in passed:
            bl = baselines[r["index"]]
            orig_c = bl["categories"].get(cat, 0)
            if orig_c > 0:
                out_c = r["out_categories"].get(cat, 0)
                vals.append((orig_c - out_c) / orig_c)
        cat_mrr[cat] = round(sum(vals) / len(vals), 4) if vals else 0

    # NewMsg-P: New introduced messages ratio @ Pass (new_msg_count / orig_total * 100)
    new_msg_ratios: List[float] = []
    for r in passed:
        bl = baselines[r["index"]]
        orig_total = bl["total"]
        if orig_total > 0:
            new_msg_ratios.append(r["new_msg_count"] / orig_total * 100)
    avg_new = round(sum(new_msg_ratios) / len(new_msg_ratios), 2) if new_msg_ratios else 0

    # LPM-P: Lines Per Message (micro-average)
    # LPM-P = Σ lines_changed / Σ fixed_count (only for samples with fixes)
    lpm_p_total_lines = sum(r["lpm_p_lines_changed"] for r in passed if r.get("lpm_p_has_fix", False))
    lpm_p_total_fixed = sum(r["lpm_p_fixed_count"] for r in passed if r.get("lpm_p_has_fix", False))
    lpm_p = round(lpm_p_total_lines / lpm_p_total_fixed, 4) if lpm_p_total_fixed > 0 else 0

    churn_vals = [r["line_churn"] for r in passed if r.get("line_churn") is not None]
    avg_churn = round(sum(churn_vals) / len(churn_vals), 4) if churn_vals else 0

    return {
        "model": model_name,
        "pass@1": pass_at_1,
        "avg_mrr_at_pass": avg_mrr,
        "mrr_at_pass_by_category": cat_mrr,
        "new_msg_per_sample_at_pass": avg_new,
        "lpm_p": lpm_p,
        "line_churn_at_pass": avg_churn,
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate base/finetuned models on the C++ benchmark test split."
    )
    parser.add_argument("--model_name", type=str, default="")
    parser.add_argument("--model_path", type=str, default="")
    parser.add_argument("--all", action="store_true", help="Evaluate all base models")
    parser.add_argument("--merged", action="store_true", help="Evaluate all merged/finetuned models")
    parser.add_argument("--deepseek", action="store_true", help="Evaluate DeepSeek via API")
    parser.add_argument("--custom_api", action="store_true", help="Evaluate custom API model")
    parser.add_argument("--api_key", type=str, default="", help="API key for custom API")
    parser.add_argument("--base_url", type=str, default="", help="Base URL for custom API")
    parser.add_argument("--api_model_id", type=str, default="", help="Model ID for custom API")
    parser.add_argument("--api_display_name", type=str, default="", help="Display name for custom API model")
    parser.add_argument("--n_workers", type=int, default=4, help="Number of parallel API workers")
    parser.add_argument("--api_timeout", type=int, default=60, help="Per-request timeout (seconds) for API calls")
    parser.add_argument("--api_max_retries", type=int, default=5, help="Max retries per sample for API calls")
    parser.add_argument("--baseline_only", action="store_true", help="Only compute baseline")
    parser.add_argument("--skip_baseline", action="store_true", help="Skip baseline if already saved")
    parser.add_argument("--resume_failed", action="store_true", help="If result json exists, only rerun API-generation failures and update the file")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of test samples")
    parser.add_argument("--gpu", type=str, default="", help="CUDA_VISIBLE_DEVICES")
    parser.add_argument("--tp", type=int, default=1, help="Tensor parallel size for vLLM")
    parser.add_argument("--max_model_len", type=int, default=0, help="Max model length for vLLM (0=auto)")
    parser.add_argument("--data_path", type=str, default="", help="Override data path")
    parser.add_argument("--no_message", action="store_true", help="(deprecated) No-message ablation. Use --ablation_mode=no_message instead.")
    parser.add_argument("--ablation_mode", type=str, default="full",
                        choices=["full", "no_message", "shuffled", "rule_only", "message_only", "location_only"],
                        help="Ablation experiment mode (default: full=standard alerts)")
    args = parser.parse_args()

    if args.gpu:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu

    # Ablation mode (backward-compat with --no_message)
    global _ABLATION_MODE
    if args.no_message:
        _ABLATION_MODE = "no_message"
    else:
        _ABLATION_MODE = args.ablation_mode
    ablation_suffix = "" if _ABLATION_MODE == "full" else f"_{_ABLATION_MODE}"
    if _ABLATION_MODE != "full":
        print(f"ABLATION MODE: {_ABLATION_MODE} (suffix: {ablation_suffix})")

    if args.data_path:
        global DATA_PATH
        DATA_PATH = Path(args.data_path)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # Load test data
    data = load_test_data(DATA_PATH, args.limit)
    print(f"Loaded {len(data)} test samples")

    # ---- Baseline ----
    bl_path = RESULT_DIR / "baseline.json"
    if args.skip_baseline and bl_path.exists():
        baselines = json.load(open(bl_path))
        print(f"Loaded existing baseline ({len(baselines)} entries)")
    else:
        print("Computing clang-tidy baseline on test split...")
        baselines = compute_baseline(data)
        with open(bl_path, "w") as f:
            json.dump(baselines, f, ensure_ascii=False)
        print(f"Baseline saved: {bl_path}")

    # ---- Table 1 ----
    t1_path = RESULT_DIR / "table1_benchmark_stats.json"
    if not t1_path.exists():
        stats = compute_table1(baselines)
        with open(t1_path, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"Table 1 saved: {t1_path}")

    if args.baseline_only:
        print("Baseline-only mode, done.")
        return

    # ---- Determine models ----
    models_to_eval: Dict[str, str] = {}

    if args.all:
        for name, path in BASE_MODELS.items():
            models_to_eval[name] = path

    if args.merged:
        # Find all merged models across all format directories
        for fmt_dir in sorted(OUTPUTS_DIR.iterdir()):
            if not fmt_dir.is_dir():
                continue
            for d in sorted(fmt_dir.glob("*_merged")):
                if d.is_dir():
                    # Skip old non-v3 merged models
                    if "_v3_" not in d.name and d.name.endswith("_lora_sft_merged"):
                        continue
                    fmt_name = fmt_dir.name  # revision, codegen, clean_codegen
                    size_tag = d.name.replace("_lora_sft_v3_merged", "").replace("_lora_sft_merged", "").replace("qwen", "Qwen-")
                    model_name = f"finetuned_{size_tag}_{fmt_name}"
                    models_to_eval[model_name] = str(d)

    if args.model_name and args.model_path:
        models_to_eval[args.model_name] = args.model_path

    if args.deepseek:
        if not DEEPSEEK_CONFIG["api_key"]:
            print("WARNING: DEEPSEEK_API_KEY not set. Set it via environment variable.")
        else:
            models_to_eval[DEEPSEEK_CONFIG["display_name"]] = "api:deepseek"

    if args.custom_api:
        api_key = args.api_key or os.environ.get("CUSTOM_API_KEY", "")
        base_url = args.base_url or os.environ.get("CUSTOM_BASE_URL", "")
        model_id = args.api_model_id or os.environ.get("CUSTOM_MODEL_ID", "")
        display_name = args.api_display_name or os.environ.get("CUSTOM_DISPLAY_NAME", "") or model_id

        if not api_key or not base_url or not model_id:
            print("WARNING: Custom API requires --api_key/ENV(CUSTOM_API_KEY), --base_url/ENV(CUSTOM_BASE_URL), and --api_model_id/ENV(CUSTOM_MODEL_ID)")
        else:
            CUSTOM_API_CONFIG["api_key"] = api_key
            CUSTOM_API_CONFIG["base_url"] = base_url
            CUSTOM_API_CONFIG["model_id"] = model_id
            CUSTOM_API_CONFIG["display_name"] = display_name
            models_to_eval[CUSTOM_API_CONFIG["display_name"]] = "api:custom"

    if not models_to_eval:
        print("No models specified. Use --all / --merged / --deepseek / --custom_api / --model_name")
        return

    print(f"\nWill evaluate {len(models_to_eval)} models:")
    for n, p in models_to_eval.items():
        print(f"  {n}: {p[:80]}...")

    # Pre-build shuffled message pool for shuffled-alert ablation
    if _ABLATION_MODE == "shuffled":
        _build_shuffled_pool(baselines, data)
        print("Built shuffled message pool for cross-file alert assignment")

    # ---- Evaluate ----
    for model_name, model_path in models_to_eval.items():
        safe_name = model_name.replace(".", "_").replace(" ", "_")
        safe_name = f"{safe_name}{ablation_suffix}"
        out_path = RESULT_DIR / f"{safe_name}.json"
        api_cache_path = RESULT_DIR / f"{safe_name}.api_cache.json"
        if out_path.exists() and not args.resume_failed:
            print(f"\nSkipping {model_name} (exists: {out_path.name})")
            continue

        if out_path.exists() and args.resume_failed:
            try:
                existing = json.load(open(out_path, "r", encoding="utf-8"))
                existing_results = existing.get("results") or []
                if not isinstance(existing_results, list) or len(existing_results) != len(data):
                    print(f"\nCannot resume {model_name}: results length mismatch (file: {out_path.name})")
                    continue
            except Exception as e:
                print(f"\nCannot resume {model_name}: failed to read {out_path.name}: {e}")
                continue

            failed_indices = _find_api_generation_failures(existing_results)
            if not failed_indices:
                print(f"\nSkipping {model_name} (no API-generation failures to resume)")
                continue

            if model_path not in ("api:deepseek", "api:custom"):
                print(f"\nCannot resume non-API model {model_name} (path: {model_path})")
                continue

            print(f"\nResuming {model_name}: rerun {len(failed_indices)}/{len(data)} failed samples")
            cfg = DEEPSEEK_CONFIG if model_path == "api:deepseek" else CUSTOM_API_CONFIG
            new_results = evaluate_model_api(
                cfg, data, baselines,
                n_workers=args.n_workers,
                only_indices=failed_indices,
                cache_path=api_cache_path,
                api_timeout=args.api_timeout,
                max_retries=args.api_max_retries,
            )

            # Merge back: only update the indices we re-ran.
            for i in failed_indices:
                existing_results[i] = new_results[i]

            summary = aggregate(model_name, existing_results, baselines)
            updated = {
                "model": model_name,
                "total_entries": len(data),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "summary": summary,
                "results": existing_results,
            }
            _atomic_write_json(out_path, updated)
            print(f"Updated: {out_path}")
            print(f"Summary: {json.dumps(summary, indent=2)}")
            continue

        if model_path == "api:deepseek":
            results = evaluate_model_api(
                DEEPSEEK_CONFIG, data, baselines,
                n_workers=args.n_workers,
                cache_path=api_cache_path,
                api_timeout=args.api_timeout,
                max_retries=args.api_max_retries,
            )
        elif model_path == "api:custom":
            results = evaluate_model_api(
                CUSTOM_API_CONFIG, data, baselines,
                n_workers=args.n_workers,
                cache_path=api_cache_path,
                api_timeout=args.api_timeout,
                max_retries=args.api_max_retries,
            )
        else:
            if not os.path.exists(model_path):
                print(f"Skipping {model_name}: path not found ({model_path})")
                continue
            results = evaluate_model_vllm(model_name, model_path, data, baselines, tensor_parallel_size=args.tp, max_model_len=args.max_model_len)

        summary = aggregate(model_name, results, baselines)
        out = {
            "model": model_name,
            "total_entries": len(data),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary,
            "results": results,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"Saved: {out_path}")
        print(f"Summary: {json.dumps(summary, indent=2)}")

    print("\nAll evaluations complete.")


if __name__ == "__main__":
    main()
