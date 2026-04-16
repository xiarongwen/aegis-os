#!/bin/bash
# Pre-Agent Run Hook
# Validates environment before spawning any agent

set -euo pipefail

AGENT_ID="${1:-unknown}"
WORKFLOW_ID="${2:-unknown}"
AEGIS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "[AEGIS] Pre-run check for agent=$AGENT_ID workflow=$WORKFLOW_ID"

# 1. Verify agent exists in registry
if ! python3 -c "
import json, sys
with open('$AEGIS_ROOT/.aegis/core/registry.json') as f:
    data = json.load(f)
if not any(a['id'] == '$AGENT_ID' for a in data['agents']):
    sys.exit(1)
" 2>/dev/null; then
  echo "[ERROR] Agent $AGENT_ID not found in registry"
  exit 1
fi

# 2. Verify workflow directory exists
WORKFLOW_DIR="$AEGIS_ROOT/workflows/$WORKFLOW_ID"
if [ ! -d "$WORKFLOW_DIR" ]; then
  mkdir -p "$WORKFLOW_DIR"/{l1-intelligence,l2-planning,l3-dev/{frontend,backend},l4-validation,l5-release}
  echo "[INFO] Created workflow directory: $WORKFLOW_DIR"
fi

# 3. Check required skills are installed
# (v1: basic check, can be expanded)
SKILLS_DIR="${HOME}/.claude/skills"
for skill in agent-browser darwin-skill; do
  if [ ! -d "$SKILLS_DIR/$skill" ] && [ ! -L "$SKILLS_DIR/$skill" ]; then
    echo "[WARN] Skill not installed: $skill"
  fi
done

# 4. Verify git status is clean enough
cd "$AEGIS_ROOT"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "[WARN] AEGIS repo has uncommitted changes"
fi

echo "[AEGIS] Pre-run checks passed"
