#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK_PYTHON="$TASK_ROOT/.venv/bin/python"
if [[ ! -x "$TASK_PYTHON" ]]; then TASK_PYTHON=python3; fi
PYTHONPATH="$TASK_ROOT/src" "$TASK_PYTHON" -m unittest discover -s "$TASK_ROOT/tests" -p 'test_*.py' -v
for TASK_TOOL in roots hse lms telegram mail calendar smartpro tracks doctor; do
  bash "$TASK_ROOT/scripts/$TASK_TOOL/$TASK_TOOL.sh" --help >/dev/null
done
if [[ "${1:-}" == "--browser" ]]; then
  node --test "$TASK_ROOT/tests/test_browser.mjs"
  node --check "$TASK_ROOT/scripts/browser/login.mjs"
  node --check "$TASK_ROOT/scripts/browser/probe.mjs"
elif [[ "${1:-}" != "" ]]; then echo 'Usage: check.sh [--browser]' >&2; exit 2; fi
