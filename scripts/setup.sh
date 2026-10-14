#!/usr/bin/env bash
# One-command environment setup for LintEval.
#
#   bash scripts/setup.sh              # venv + python deps + tool check
#   bash scripts/setup.sh --no-venv    # install into the current interpreter
#
# The script never needs root: it uses a local virtualenv and prints ready-to-paste
# commands for whichever system tools are still missing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USE_VENV=1
[[ "${1:-}" == "--no-venv" ]] && USE_VENV=0

echo "======================================================"
echo "LintEval setup  ($REPO_ROOT)"
echo "======================================================"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ "$USE_VENV" == "1" ]]; then
    if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
        echo "[1/3] creating virtualenv .venv"
        "$PYTHON_BIN" -m venv "$REPO_ROOT/.venv"
    else
        echo "[1/3] reusing existing .venv"
    fi
    PY="$REPO_ROOT/.venv/bin/python"
else
    echo "[1/3] using current interpreter"
    PY="$PYTHON_BIN"
fi

echo "[2/3] installing Python dependencies"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r "$REPO_ROOT/requirements.txt"

echo "[3/3] checking external tools"
missing=()
check () { # name, version-flag
    if command -v "$1" >/dev/null 2>&1; then
        printf '  OK   %-12s %s\n' "$1" "$("$1" "$2" 2>&1 | head -1 | cut -c1-52)"
    else
        printf '  MISS %-12s\n' "$1"
        missing+=("$1")
    fi
}
check g++        --version
check python3    --version
check pylint     --version
check clang-tidy --version
check pmd        --version
check javac      --version
check java       --version

if (( ${#missing[@]} )); then
    cat <<EOF

Missing tools: ${missing[*]}
Install hints (no root needed for the pip/conda variants):

  clang-tidy   : apt-get install clang-tidy            # or: mamba install -c conda-forge clang-tools
  pmd          : download PMD 7.x from https://pmd.github.io and put \`pmd\` on PATH,
                 or export PMD_BIN=/path/to/pmd/bin/pmd
  javac / java : apt-get install openjdk-21-jdk        # or: mamba install -c conda-forge openjdk
  g++          : apt-get install g++                   # or: mamba install -c conda-forge gxx

Every binary can also be pointed at explicitly through the environment variables
documented in setup_env.sh (CLANG_TIDY_BIN, PMD_BIN, JAVAC_BIN, GPP_BIN, PYLINT_BIN).
Only the languages you actually evaluate need their tool: the Python smoke test
requires just pylint.
EOF
else
    echo "  all external tools found"
fi

echo
echo "Verifying the installation ..."
"$PY" "$REPO_ROOT/scripts/test_environment.py" || true

cat <<EOF

Next steps
----------
  source setup_env.sh                 # exports tool paths + PYTHONPATH
  $PY scripts/sanity_check.py         # 1-minute pipeline check, no API needed
  export pku_maas_base_url=https://chat.pku.edu.cn/v1
  export pku_maas_api_key=sk-...
  $PY scripts/smoke_test.py           # one-sample end-to-end smoke (gpt-6-luna)
  $PY scripts/verify_paper_metrics.py --check-tables

(\$PY = the interpreter that has the dependencies installed; \`source .venv/bin/activate\`
works too.)
EOF
