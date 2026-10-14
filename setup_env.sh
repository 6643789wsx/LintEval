#!/bin/bash
# Environment setup for LintEval.
#
# Auto-detects the repository root, so it works from any checkout location.
# Usage:
#   source setup_env.sh
#
# API credentials are read from the environment when you evaluate a hosted model:
#   pku_maas_base_url / PKU_MAAS_BASE_URL     e.g. https://chat.pku.edu.cn/v1
#   pku_maas_api_key  / PKU_MAAS_API_KEY
#   pku_maas_model_name / PKU_MAAS_MODEL_NAME e.g. gpt-6-luna
#   DEEPSEEK_API_KEY / CUSTOM_API_KEY / CUSTOM_BASE_URL also supported (see README)

# Resolve the directory of this script (repo root) regardless of CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LINTEVAL_ROOT="${SCRIPT_DIR}"

# Linter / compiler binaries (each falls back to PATH lookup in src/)
export CLANG_TIDY_BIN="${CLANG_TIDY_BIN:-clang-tidy}"
export GPP_BIN="${GPP_BIN:-g++}"
export PMD_BIN="${PMD_BIN:-pmd}"
export PYLINT_BIN="${PYLINT_BIN:-pylint}"
export JAVAC_BIN="${JAVAC_BIN:-javac}"

# testlib.h include path for C++ generator/checker compilation
export TESTLIB_INCLUDE="${TESTLIB_INCLUDE:-${LINTEVAL_ROOT}/tools}"

# Add project src to PYTHONPATH
export PYTHONPATH="${LINTEVAL_ROOT}/src:${PYTHONPATH}"

echo "========================================"
echo "LintEval Environment"
echo "========================================"
echo "LINTEVAL_ROOT: ${LINTEVAL_ROOT}"
echo "  clang-tidy:  ${CLANG_TIDY_BIN}"
echo "  g++:         ${GPP_BIN}"
echo "  PMD:         ${PMD_BIN}"
echo "  pylint:      ${PYLINT_BIN}"
echo "  javac:       ${JAVAC_BIN}"
echo "  TESTLIB:     ${TESTLIB_INCLUDE}"
echo "  PKU MaaS key:    $([ -n "${PKU_MAAS_API_KEY}${pku_maas_api_key}" ] && echo 'set' || echo 'not set (needed only for API models)')"
echo "  DEEPSEEK_API_KEY: $([ -n "${DEEPSEEK_API_KEY}" ] && echo 'set' || echo 'not set (needed only for API models)')"
echo "========================================"
