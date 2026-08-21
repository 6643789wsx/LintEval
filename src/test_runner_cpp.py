"""C++ test runner for CodeContests+ problems.

Handles compilation, test generation, execution, and checker-based validation
for competitive programming submissions.
"""

import subprocess
import os
import shutil
import tempfile
import time
import shlex
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# testlib.h location (override with TESTLIB_INCLUDE env var)
DEFAULT_TESTLIB_INCLUDE = os.environ.get("TESTLIB_INCLUDE", "tools")

GPP_BIN = os.environ.get("GPP_BIN") or shutil.which("g++") or "g++"


def compile_tool(
    code: str,
    output_path: str,
    testlib_include: Optional[str] = None,
    timeout: int = 30,
) -> Tuple[bool, str]:
    """Compile a tool (generator/checker) that uses testlib.h.

    Uses: g++ -std=c++17 -I{testlib_include} code.cpp -o output

    Args:
        code:             C++ source code string.
        output_path:      Path for the compiled binary.
        testlib_include:  Directory containing testlib.h. Uses default if None.
        timeout:          Max compilation seconds.

    Returns:
        (success, error_message)
    """
    if testlib_include is None:
        testlib_include = DEFAULT_TESTLIB_INCLUDE

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cpp", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        cmd = [
            GPP_BIN,
            "-std=c++17",
            f"-I{testlib_include}",
            "-O2",
            "-pipe",
            tmp_path,
            "-o",
            output_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )

        if result.returncode == 0:
            return (True, "")
        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return (False, error_msg)

    except subprocess.TimeoutExpired:
        return (False, "Compilation timed out")
    except FileNotFoundError:
        return (False, f"g++ not found at {GPP_BIN}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def compile_solution(
    code: str,
    output_path: str,
    timeout: int = 30,
) -> Tuple[bool, str]:
    """Compile a solution.

    Uses: g++ -std=c++17 -O2 -pipe code.cpp -o output
    Tries -static first, falls back to dynamic linking.

    Args:
        code:        C++ source code string.
        output_path: Path for the compiled binary.
        timeout:     Max compilation seconds.

    Returns:
        (success, error_message)
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cpp", delete=False
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        # First attempt: static linking
        cmd_static = [
            GPP_BIN,
            "-std=c++17",
            "-O2",
            "-pipe",
            "-static",
            tmp_path,
            "-o",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd_static, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return (True, "")
        except subprocess.TimeoutExpired:
            return (False, "Compilation timed out (static)")
        except FileNotFoundError:
            return (False, f"g++ not found at {GPP_BIN}")

        # Fallback: dynamic linking
        cmd_dynamic = [
            GPP_BIN,
            "-std=c++17",
            "-O2",
            "-pipe",
            tmp_path,
            "-o",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd_dynamic, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return (True, "")
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                return (False, error_msg)
        except subprocess.TimeoutExpired:
            return (False, "Compilation timed out (dynamic)")
        except FileNotFoundError:
            return (False, f"g++ not found at {GPP_BIN}")

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def generate_test_cases(
    generator_path: str,
    generator_cmds: str,
    work_dir: str,
    max_tests: int = 100,
    timeout_per_test: int = 5,
) -> List[str]:
    """Generate test case input files using the generator.

    Args:
        generator_path:   Path to the compiled generator binary.
        generator_cmds:   Multiline string; each line is a command like:
                          ./gen -n 5 -m 10 -type random
                          The first token is the generator binary name (replaced
                          by generator_path). Remaining tokens are arguments.
        work_dir:         Directory where input files are written.
    max_tests:        Maximum number of test cases to generate. Values <= 0
                      mean all generator commands.
        timeout_per_test: Timeout in seconds per generator invocation.

    Returns:
        List of input file paths (e.g. work_dir/input_001.txt).
    """
    os.makedirs(work_dir, exist_ok=True)
    input_files: List[str] = []

    lines = [line.strip() for line in generator_cmds.strip().splitlines() if line.strip()]
    if not lines:
        return input_files

    test_idx = 0
    for cmd_line in lines:
        if max_tests > 0 and test_idx >= max_tests:
            break

        try:
            tokens = shlex.split(cmd_line)
        except ValueError:
            # Be robust to malformed quoting in generator_cmds.
            tokens = cmd_line.split()
        if not tokens:
            continue

        # Replace the first token (binary name) with the actual generator path
        args = tokens[1:]  # everything after the binary name

        input_path = os.path.join(work_dir, f"input_{test_idx + 1:03d}.txt")

        try:
            with open(input_path, "w") as f:
                result = subprocess.run(
                    [generator_path] + args,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout_per_test,
                    cwd=work_dir,
                )

            if result.returncode == 0:
                input_files.append(input_path)
                test_idx += 1
            else:
                # Generator failed; skip this command
                try:
                    os.unlink(input_path)
                except OSError:
                    pass

        except subprocess.TimeoutExpired:
            try:
                os.unlink(input_path)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(input_path)
            except OSError:
                pass

    return input_files


def run_program(
    program_path: str,
    input_path: str,
    timeout_sec: int = 5,
) -> Tuple[bool, str, str]:
    """Run a program with input from a file.

    Args:
        program_path: Path to the compiled binary.
        input_path:   Path to the input file.
        timeout_sec:  Maximum runtime in seconds.

    Returns:
        (success, stdout, stderr)
        success is False if the program times out, crashes, or returns non-zero.
    """
    try:
        with open(input_path, "r") as fin:
            result = subprocess.run(
                [program_path],
                stdin=fin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
            )

        stdout = result.stdout
        stderr = result.stderr

        if result.returncode != 0:
            return (False, stdout, stderr)

        return (True, stdout, stderr)

    except subprocess.TimeoutExpired:
        return (False, "", "Time limit exceeded")
    except FileNotFoundError:
        return (False, "", f"Program not found: {program_path}")
    except Exception as e:
        return (False, "", str(e))


def check_with_checker(
    checker_path: str,
    input_path: str,
    answer_path: str,
    output_path: str,
    timeout: int = 5,
) -> Tuple[bool, str]:
    """Run a checker to validate output against the expected answer.

    Invokes: checker input.txt answer.txt output.txt

    Checker exit codes (testlib convention):
        0 = Accepted (AC)
        1 = Wrong Answer (WA)
        2 = Presentation Error (PE)
        3 = Checker Fail

    Args:
        checker_path: Path to the compiled checker binary.
        input_path:   Path to the test input file.
        answer_path:  Path to the expected answer file.
        output_path:  Path to the candidate's output file.
        timeout:      Maximum runtime in seconds.

    Returns:
        (accepted, message)
    """
    try:
        result = subprocess.run(
            [checker_path, input_path, answer_path, output_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Checker writes human-readable message to stdout or stderr
        message = (result.stdout + result.stderr).strip()

        if result.returncode == 0:
            return (True, message or "Accepted")
        else:
            return (False, message or f"Rejected (exit code {result.returncode})")

    except subprocess.TimeoutExpired:
        return (False, "Checker timed out")
    except FileNotFoundError:
        return (False, f"Checker not found: {checker_path}")
    except Exception as e:
        return (False, str(e))


def _write_temp_file(content: str, suffix: str, directory: str) -> str:
    """Write content to a named temp file in the given directory."""
    fd, path = tempfile.mkstemp(suffix=suffix, dir=directory)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def validate_submission(
    code: str,
    problem: Dict,
    work_dir: str,
    testlib_include: Optional[str] = None,
    max_tests: int = 100,
    timeout_compile: int = 30,
    timeout_run: int = 5,
) -> Dict:
    """Full validation pipeline for a competitive programming submission.

    Steps:
        1. Compile the candidate solution.
        2. Compile generator (if available in problem dict).
        3. Compile checker (if available in problem dict).
        4. Generate test inputs using the generator.
        5. For each test: run oracle (original solution) to get the reference
           answer, run the candidate solution, then compare outputs.
        6. If a checker is available, use it; otherwise do exact string match.
        7. If no generator, try to use example test cases from the problem
           description as a fallback.

    Args:
        code:             Candidate's C++ source code.
        problem:          Problem dict with keys such as:
                          - "solution" (str): oracle/reference solution code
                          - "generator" (str, optional): generator code
                          - "checker" (str, optional): checker code
                          - "generator_cmds" (str, optional): generator commands
                          - "examples" (list, optional): list of dicts with
                            "input" and "output" keys for fallback testing
        work_dir:         Working directory for temp files and binaries.
        testlib_include:  Directory containing testlib.h.
        max_tests:        Maximum number of generated tests.
        timeout_compile:  Compilation timeout in seconds.
        timeout_run:      Runtime timeout per test in seconds.

    Returns:
        Dict with validation results (see docstring in the spec).
    """
    os.makedirs(work_dir, exist_ok=True)

    errors: List[str] = []
    test_details: List[Dict] = []

    # ------------------------------------------------------------------
    # 1. Compile the candidate solution
    # ------------------------------------------------------------------
    candidate_bin = os.path.join(work_dir, "candidate")
    compile_ok, compile_err = compile_solution(code, candidate_bin, timeout=timeout_compile)
    if not compile_ok:
        return {
            "compile_ok": False,
            "tests_generated": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "pass_at_1": False,
            "checker_available": False,
            "generator_available": False,
            "test_details": [],
            "errors": [f"Compilation failed: {compile_err}"],
        }

    # ------------------------------------------------------------------
    # 2. Compile oracle (original solution)
    # ------------------------------------------------------------------
    oracle_code = problem.get("solution", "")
    oracle_bin = os.path.join(work_dir, "oracle")
    if oracle_code:
        oracle_ok, oracle_err = compile_solution(
            oracle_code, oracle_bin, timeout=timeout_compile
        )
        if not oracle_ok:
            errors.append(f"Oracle compilation failed: {oracle_err}")
            oracle_bin = None
    else:
        oracle_bin = None

    # ------------------------------------------------------------------
    # 3. Compile generator (if available)
    # ------------------------------------------------------------------
    generator_code = problem.get("generator", "")
    generator_available = bool(generator_code)
    generator_bin = None
    if generator_code:
        generator_bin = os.path.join(work_dir, "generator")
        gen_ok, gen_err = compile_tool(
            generator_code, generator_bin, testlib_include, timeout=timeout_compile
        )
        if not gen_ok:
            errors.append(f"Generator compilation failed: {gen_err}")
            generator_bin = None
            generator_available = False

    # ------------------------------------------------------------------
    # 4. Compile checker (if available)
    # ------------------------------------------------------------------
    checker_code = problem.get("checker", "")
    checker_available = bool(checker_code)
    checker_bin = None
    if checker_code:
        checker_bin = os.path.join(work_dir, "checker")
        chk_ok, chk_err = compile_tool(
            checker_code, checker_bin, testlib_include, timeout=timeout_compile
        )
        if not chk_ok:
            errors.append(f"Checker compilation failed: {chk_err}")
            checker_bin = None
            checker_available = False

    # ------------------------------------------------------------------
    # 5. Generate test inputs
    # ------------------------------------------------------------------
    input_files: List[str] = []
    generator_cmds = problem.get("generator_cmds", "")

    if generator_bin and generator_cmds:
        test_gen_dir = os.path.join(work_dir, "tests")
        input_files = generate_test_cases(
            generator_bin,
            generator_cmds,
            test_gen_dir,
            max_tests=max_tests,
            timeout_per_test=timeout_run,
        )

    # ------------------------------------------------------------------
    # 6. Fallback: use examples from problem description
    # ------------------------------------------------------------------
    if not input_files:
        examples = problem.get("examples", [])
        if examples:
            examples_dir = os.path.join(work_dir, "examples")
            os.makedirs(examples_dir, exist_ok=True)

            for idx, ex in enumerate(examples):
                inp = ex.get("input", "")
                out = ex.get("output", "")
                if not inp:
                    continue

                inp_path = os.path.join(examples_dir, f"input_{idx + 1:03d}.txt")
                out_path = os.path.join(examples_dir, f"answer_{idx + 1:03d}.txt")

                with open(inp_path, "w") as f:
                    f.write(inp)
                with open(out_path, "w") as f:
                    f.write(out)

                input_files.append(inp_path)
                # Store the expected answer path alongside for later use
                # We use a convention: for examples, the answer file is at
                # examples_dir/answer_NNN.txt

    # ------------------------------------------------------------------
    # 7. Run tests
    # ------------------------------------------------------------------
    tests_passed = 0
    tests_failed = 0

    for test_idx, input_path in enumerate(input_files):
        input_path_obj = Path(input_path)
        input_dir = input_path_obj.parent
        stem = input_path_obj.stem  # e.g. "input_001"

        # Determine the answer file path
        # For generated tests: produce answer via oracle
        # For example tests: answer file should already exist
        answer_path = os.path.join(input_dir, stem.replace("input_", "answer_") + ".txt")

        if not os.path.exists(answer_path) and oracle_bin:
            # Generate answer using oracle
            oracle_ok_run, oracle_stdout, oracle_stderr = run_program(
                oracle_bin, input_path, timeout_sec=timeout_run
            )
            if oracle_ok_run:
                with open(answer_path, "w") as f:
                    f.write(oracle_stdout)
            else:
                # Oracle failed on this test; skip it
                test_details.append(
                    {
                        "test_idx": test_idx,
                        "passed": False,
                        "error": f"Oracle failed: {oracle_stderr[:200]}",
                    }
                )
                tests_failed += 1
                continue

        # Run candidate
        output_path = os.path.join(
            input_dir, stem.replace("input_", "output_") + ".txt"
        )
        cand_ok, cand_stdout, cand_stderr = run_program(
            candidate_bin, input_path, timeout_sec=timeout_run
        )

        if not cand_ok:
            test_details.append(
                {
                    "test_idx": test_idx,
                    "passed": False,
                    "error": f"Runtime error or TLE: {cand_stderr[:200]}",
                }
            )
            tests_failed += 1
            continue

        # Write candidate output
        with open(output_path, "w") as f:
            f.write(cand_stdout)

        # Check output
        if checker_bin and os.path.exists(answer_path):
            accepted, check_msg = check_with_checker(
                checker_bin, input_path, answer_path, output_path, timeout=timeout_run
            )
            if accepted:
                tests_passed += 1
                test_details.append(
                    {"test_idx": test_idx, "passed": True, "error": ""}
                )
            else:
                tests_failed += 1
                test_details.append(
                    {"test_idx": test_idx, "passed": False, "error": check_msg[:300]}
                )
        elif os.path.exists(answer_path):
            # Exact string match (strip trailing whitespace per line)
            with open(answer_path, "r") as f:
                expected_raw = f.read()
            expected_normalized = _normalize_output(expected_raw)
            candidate_normalized = _normalize_output(cand_stdout)

            if expected_normalized == candidate_normalized:
                tests_passed += 1
                test_details.append(
                    {"test_idx": test_idx, "passed": True, "error": ""}
                )
            else:
                tests_failed += 1
                # Show a useful diff snippet
                diff_hint = _short_diff(expected_normalized, candidate_normalized)
                test_details.append(
                    {
                        "test_idx": test_idx,
                        "passed": False,
                        "error": f"Output mismatch: {diff_hint}",
                    }
                )
        else:
            # No answer file and no oracle -- cannot verify
            test_details.append(
                {
                    "test_idx": test_idx,
                    "passed": False,
                    "error": "No reference answer available",
                }
            )
            tests_failed += 1

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


def _normalize_output(text: str) -> str:
    """Normalize output for comparison: strip trailing whitespace per line,
    then strip trailing newlines."""
    lines = text.splitlines()
    lines = [line.rstrip() for line in lines]
    # Remove trailing empty lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _short_diff(expected: str, actual: str, max_len: int = 150) -> str:
    """Produce a short diff hint string."""
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()

    for i in range(max(len(exp_lines), len(act_lines))):
        e = exp_lines[i] if i < len(exp_lines) else "<missing>"
        a = act_lines[i] if i < len(act_lines) else "<extra>"
        if e != a:
            hint = f"line {i + 1}: expected '{e[:60]}' got '{a[:60]}'"
            return hint[:max_len]

    if len(exp_lines) != len(act_lines):
        return f"different line counts: {len(exp_lines)} vs {len(act_lines)}"

    return "outputs differ"
