#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${1:-}" != "" && "${1:-}" != "--browser" ]]; then echo 'Usage: setup.sh [--browser]' >&2; exit 2; fi
python3 -m venv "$TASK_ROOT/.venv"
"$TASK_ROOT/.venv/bin/python" -m pip install -r "$TASK_ROOT/requirements.txt"
bash "$TASK_ROOT/scripts/hse/hse.sh" init
echo "Next: fill config.json in HSE_DATA_DIR (default: data/): module.start, module.end, module.timezone. See README."
bash "$TASK_ROOT/scripts/link-skills/link-skills.sh"
if [[ "${1:-}" == "--browser" ]]; then
  npm --prefix "$TASK_ROOT/scripts/browser" ci
  "$TASK_ROOT/scripts/browser/node_modules/.bin/playwright" install chromium
fi
