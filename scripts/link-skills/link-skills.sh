#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$TASK_ROOT/.claude/skills"
for TASK_SKILL in "$TASK_ROOT"/.agents/skills/*; do
  TASK_NAME="$(basename "$TASK_SKILL")"
  TASK_LINK="$TASK_ROOT/.claude/skills/$TASK_NAME"
  if [[ -e "$TASK_LINK" || -L "$TASK_LINK" ]]; then
    if [[ -L "$TASK_LINK" && "$(readlink "$TASK_LINK")" == "../../.agents/skills/$TASK_NAME" ]]; then continue; fi
    echo "Refusing to overwrite $TASK_LINK" >&2; exit 1
  fi
  ln -s "../../.agents/skills/$TASK_NAME" "$TASK_LINK"
done
