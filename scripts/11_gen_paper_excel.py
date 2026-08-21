"""
11_gen_paper_excel.py - Generate LaTeX tables for linter-guided file refactoring benchmark.

This is the unified entry point. All table generation logic lives in gen_tab/ modules.

Usage:
  python scripts/11_gen_paper_excel.py

Output:
  docs/table/*.tex
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from gen_tab.generate_all_tables import main


if __name__ == "__main__":
    main()
