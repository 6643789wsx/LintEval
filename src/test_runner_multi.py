"""Multi-language test runner for CodeContests+ problems.

Implements a testlib-based validation loop for solutions in multiple languages
(currently: C++/Python3/Java) using the same generator/checker pipeline.

This is used to make `pass_at_1` mean "passes the generated unit tests"
instead of "compile-only".
"""

from __future__ import annotations

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# Support both `from src.test_runner_cpp` and `from test_runner_cpp` import styles
try:
    from test_runner_cpp import (
        check_with_checker,
        compile_solution,
        compile_tool,
        generate_test_cases,
        run_program,
        _normalize_output,
        _short_diff,
    )
except ImportError:
    from src.test_runner_cpp import (
        check_with_checker,
        compile_solution,
        compile_tool,
        generate_test_cases,
        run_program,
        _normalize_output,
        _short_diff,
    )


@dataclass(frozen=True)
class Runner:
    command: List[str]
    work_dir: str


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _build_runner_cpp(code: str, work_dir: str, name: str, timeout_compile: int) -> Tuple[Optional[Runner], str]:
    out_path = os.path.join(work_dir, name)
    ok, err = compile_solution(code, out_path, timeout=timeout_compile)
    if not ok:
        return None, err
    return Runner(command=[out_path], work_dir=work_dir), ""


def _build_runner_py3(code: str, work_dir: str, name: str, timeout_compile: int) -> Tuple[Optional[Runner], str]:
    py_path = os.path.join(work_dir, f"{name}.py")
    _write_text(py_path, code)
    # Syntax check (best-effort).
    try:
        res = subprocess.run(
            ["python3", "-m", "py_compile", py_path],
            capture_output=True,
            text=True,
            timeout=timeout_compile,
            cwd=work_dir,
        )
    except subprocess.TimeoutExpired:
        return None, "Python syntax check timed out"
    except FileNotFoundError:
        return None, "python3 not found"
    if res.returncode != 0:
        return None, res.stderr.strip() or res.stdout.strip() or "Python syntax error"
    return Runner(command=["python3", py_path], work_dir=work_dir), ""


def _build_runner_java(code: str, work_dir: str, name: str, timeout_compile: int) -> Tuple[Optional[Runner], str]:
    # Honor the actual public class name; javac requires the file to match it.
    # Competitive submissions may declare `public class Solution`/`A`/etc.
    # Build into a per-role subdirectory so candidate and oracle never collide
    # on a shared class name / .class output within the same work_dir.
    m = re.search(r'public\s+class\s+([A-Za-z_$][A-Za-z0-9_$]*)', code)
    class_name = m.group(1) if m else "Main"
    sub_dir = os.path.join(work_dir, f"java_{name}")
    os.makedirs(sub_dir, exist_ok=True)
    _write_text(os.path.join(sub_dir, f"{class_name}.java"), code)
    try:
        res = subprocess.run(
            ["javac", f"{class_name}.java"],
            capture_output=True,
            text=True,
            timeout=timeout_compile,
            cwd=sub_dir,
        )
    except subprocess.TimeoutExpired:
        return None, "Java compilation timed out"
    except FileNotFoundError:
        return None, "javac not found"
    if res.returncode != 0:
        return None, res.stderr.strip() or res.stdout.strip() or "Java compilation failed"
    return Runner(command=["java", "-cp", sub_dir, class_name], work_dir=sub_dir), ""


def _build_runner(code: str, language: str, work_dir: str, name: str, timeout_compile: int) -> Tuple[Optional[Runner], str]:
    lang = (language or "cpp").lower()
    if lang == "cpp":
        return _build_runner_cpp(code, work_dir, name, timeout_compile)
    if lang in ("py3", "python", "python3"):
        return _build_runner_py3(code, work_dir, name, timeout_compile)
    if lang == "java":
        return _build_runner_java(code, work_dir, name, timeout_compile)
    return None, f"Unsupported language for validation: {language}"


def _run_runner(runner: Runner, input_path: str, timeout_sec: int) -> Tuple[bool, str, str]:
    if len(runner.command) == 1 and os.path.exists(runner.command[0]) and os.access(runner.command[0], os.X_OK):
        return run_program(runner.command[0], input_path, timeout_sec=timeout_sec)
    try:
        with open(input_path, "r", encoding="utf-8", errors="ignore") as f_in:
            res = subprocess.run(
                runner.command,
                stdin=f_in,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=runner.work_dir,
            )
        ok = res.returncode == 0
        stderr = res.stderr.strip() or ""
        return ok, res.stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timed out"


def _run_single_test(
    test_idx: int,
    input_path: str,
    oracle_runner: Optional[Runner],
    candidate_runner: Runner,
    checker_bin: Optional[str],
    checker_available: bool,
    timeout_run: int,
) -> Dict:
    """Run one oracle + candidate + checker test and return a detail dict."""
    input_dir = os.path.dirname(input_path)
    answer_path = os.path.join(input_dir, f"answer_{test_idx:03d}.txt")
    output_path = os.path.join(input_dir, f"output_{test_idx:03d}.txt")

    if oracle_runner is not None:
        ok, stdout, stderr = _run_runner(oracle_runner, input_path, timeout_run)
        if ok:
            _write_text(answer_path, stdout)
        else:
            status = "timeout" if (stderr or "").strip() == "Timed out" else "oracle_error"
            return {
                "test_idx": test_idx,
                "passed": False,
                "status": status,
                "error": f"Oracle failed: {(stderr or '')[:300]}",
            }

    ok, cand_stdout, cand_stderr = _run_runner(candidate_runner, input_path, timeout_run)
    if not ok:
        status = "timeout" if (cand_stderr or "").strip() == "Timed out" else "runtime_error"
        return {
            "test_idx": test_idx,
            "passed": False,
            "status": status,
            "error": f"Runtime error: {(cand_stderr or '')[:300]}",
        }
    _write_text(output_path, cand_stdout)

    if checker_bin and checker_available and os.path.exists(answer_path):
        accepted, check_msg = check_with_checker(
            checker_bin, input_path, answer_path, output_path, timeout=timeout_run
        )
        if accepted:
            return {"test_idx": test_idx, "passed": True, "status": "passed", "error": ""}
        else:
            return {"test_idx": test_idx, "passed": False, "status": "wrong_answer", "error": (check_msg or "")[:300]}
    elif os.path.exists(answer_path):
        expected_raw = open(answer_path, "r", encoding="utf-8", errors="ignore").read()
        expected_norm = _normalize_output(expected_raw)
        cand_norm = _normalize_output(cand_stdout)
        if expected_norm == cand_norm:
            return {"test_idx": test_idx, "passed": True, "status": "passed", "error": ""}
        else:
            diff_hint = _short_diff(expected_norm, cand_norm)
            return {"test_idx": test_idx, "passed": False, "status": "wrong_answer", "error": f"Output mismatch: {diff_hint}"}
    else:
        return {"test_idx": test_idx, "passed": False, "status": "oracle_error", "error": "No reference answer available"}


def validate_submission_multi(
    code: str,
    language: str,
    problem: Dict,
    work_dir: str,
    testlib_include: Optional[str] = None,
    max_tests: int = 100,
    timeout_compile: int = 30,
    timeout_run: int = 5,
    num_workers: int = 1,
) -> Dict:
    os.makedirs(work_dir, exist_ok=True)

    errors: List[str] = []
    test_details: List[Dict] = []

    candidate_runner, cand_err = _build_runner(code, language, work_dir, "candidate", timeout_compile)
    if candidate_runner is None:
        return {
            "compile_ok": False,
            "tests_generated": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "pass_at_1": False,
            "checker_available": False,
            "generator_available": False,
            "test_details": [],
            "errors": [f"Compilation failed: {cand_err}"],
        }

    oracle_code = (problem.get("solution") or "").strip()
    oracle_runner: Optional[Runner] = None
    if oracle_code:
        oracle_runner, oracle_err = _build_runner(oracle_code, language, work_dir, "oracle", timeout_compile)
        if oracle_runner is None:
            errors.append(f"Oracle compilation failed: {oracle_err}")
            oracle_runner = None

    generator_bin = (problem.get("generator_bin") or "").strip()
    generator_code = (problem.get("generator") or "").strip()
    generator_available = bool(generator_bin) or bool(generator_code)
    if generator_bin:
        if not os.path.exists(generator_bin):
            errors.append(f"Generator binary not found: {generator_bin}")
            generator_bin = None
            generator_available = False
    elif generator_code:
        generator_bin = os.path.join(work_dir, "generator")
        ok, err = compile_tool(
            generator_code, generator_bin, testlib_include, timeout=timeout_compile
        )
        if not ok:
            errors.append(f"Generator compilation failed: {err}")
            generator_available = False
            generator_bin = None

    checker_bin = (problem.get("checker_bin") or "").strip()
    checker_code = (problem.get("checker") or "").strip()
    checker_available = bool(checker_bin) or bool(checker_code)
    if checker_bin:
        if not os.path.exists(checker_bin):
            errors.append(f"Checker binary not found: {checker_bin}")
            checker_bin = None
            checker_available = False
    elif checker_code:
        checker_bin = os.path.join(work_dir, "checker")
        ok, err = compile_tool(
            checker_code, checker_bin, testlib_include, timeout=timeout_compile
        )
        if not ok:
            errors.append(f"Checker compilation failed: {err}")
            checker_available = False
            checker_bin = None

    if not generator_bin:
        return {
            "compile_ok": True,
            "tests_generated": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "pass_at_1": False,
            "checker_available": checker_available,
            "generator_available": generator_available,
            "test_details": [],
            "errors": errors + ["Generator unavailable; cannot run unit tests"],
        }

    input_files = problem.get("input_files") or []
    if not input_files:
        input_files = generate_test_cases(
            generator_path=generator_bin,
            generator_cmds=problem.get("generator_cmds", "") or "",
            work_dir=os.path.join(work_dir, "tests"),
            max_tests=max_tests,
            timeout_per_test=timeout_run,
        )

    tests_passed = 0
    tests_failed = 0

    if num_workers > 1:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(
                    _run_single_test,
                    test_idx,
                    input_path,
                    oracle_runner,
                    candidate_runner,
                    checker_bin,
                    checker_available,
                    timeout_run,
                )
                for test_idx, input_path in enumerate(input_files, 1)
            ]
            for future in futures:
                detail = future.result()
                test_details.append(detail)
                if detail["passed"]:
                    tests_passed += 1
                else:
                    tests_failed += 1
    else:
        for test_idx, input_path in enumerate(input_files, 1):
            detail = _run_single_test(
                test_idx,
                input_path,
                oracle_runner,
                candidate_runner,
                checker_bin,
                checker_available,
                timeout_run,
            )
            test_details.append(detail)
            if detail["passed"]:
                tests_passed += 1
            else:
                tests_failed += 1
            # Historical default: stop after the first failure for Pass@1.
            # Analysis scripts that need severity/test-pass-rate distributions
            # should pass num_workers > 1, which evaluates all generated tests.
            if tests_failed > 0:
                break

    pass_at_1 = (tests_passed > 0) and (tests_failed == 0) and (tests_passed + tests_failed > 0)
    return {
        "compile_ok": True,
        "tests_generated": len(input_files),
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "pass_at_1": pass_at_1,
        "checker_available": checker_available,
        "generator_available": generator_available,
        "test_details": test_details,
        "errors": errors,
    }
