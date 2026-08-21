#!/usr/bin/env python3
"""
Test the LintEval environment.

Verifies that all required Python packages and system tools are available,
and that the repository layout is complete. All checks are relative to this
script's location, so it can be run from any working directory.

Usage:
    python scripts/test_environment.py
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


def check_python_package(package_name: str) -> tuple:
    try:
        __import__(package_name)
        return True, f"OK   {package_name} is installed"
    except ImportError:
        return False, f"MISS {package_name} is NOT installed"


def check_command(command: str) -> tuple:
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = (result.stdout or result.stderr).strip().splitlines()
            return True, f"OK   {command}: {version[0][:50] if version else 'available'}"
        return False, f"MISS {command}: error code {result.returncode}"
    except FileNotFoundError:
        return False, f"MISS {command}: not found in PATH"
    except Exception as e:
        return False, f"MISS {command}: {e}"


def main() -> int:
    print("=" * 60)
    print("LintEval Environment Test")
    print("=" * 60)
    print()

    all_passed = True

    # Python version
    py_version = sys.version.split()[0]
    if sys.version_info >= (3, 8):
        print(f"OK   Python {py_version} (>= 3.8 required)")
    else:
        print(f"MISS Python {py_version} (>= 3.8 required)")
        all_passed = False
    print()

    # Python packages
    print("Python Packages:")
    for pkg in ["openai", "openpyxl", "yaml", "tqdm", "numpy", "transformers"]:
        ok, msg = check_python_package(pkg)
        print(f"  {msg}")
        all_passed = all_passed and ok
    print()

    # External tools
    print("External Tools:")
    for tool in ["clang-tidy", "pylint", "pmd", "g++", "javac", "java"]:
        ok, msg = check_command(tool)
        print(f"  {msg}")
        all_passed = all_passed and ok
    print()

    # Repository layout
    print("Repository Layout:")
    for rel in ["src", "scripts", "scripts/gen_tab", "configs", "tools", "eval_results", "docs/table"]:
        p = PROJECT_ROOT / rel
        ok = p.exists() and p.is_dir()
        print(f"  {'OK   ' if ok else 'MISS '}{rel}/")
        all_passed = all_passed and ok
    print()

    # Data files
    print("Data Files:")
    for rel in ["data/demo_100.jsonl", "data/linteval_lite_test.jsonl", "tools/testlib.h"]:
        p = PROJECT_ROOT / rel
        ok = p.exists()
        print(f"  {'OK   ' if ok else 'MISS '}{rel}")
        all_passed = all_passed and ok
    print()

    # Summary
    print("=" * 60)
    if all_passed:
        print("All critical checks passed! You can run the LintEval pipeline.")
    else:
        print("Some checks failed. See messages above and install missing pieces.")
        print("Python packages: pip install -r requirements.txt")
        print("System tools:    see README.md -> Environment Setup")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
