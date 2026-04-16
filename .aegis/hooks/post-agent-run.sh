#!/bin/bash
# Post-Agent Run Hook
# Commits agent outputs and validates gate artifacts

set -euo pipefail

AGENT_ID="${1:-unknown}"
WORKFLOW_ID="${2:-unknown}"
AEGIS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKFLOW_DIR="$AEGIS_ROOT/workflows/$WORKFLOW_ID"

echo "[AEGIS] Post-run commit for agent=$AGENT_ID workflow=$WORKFLOW_ID"

cd "$AEGIS_ROOT"

# 1. Stage workflow changes
git add "$WORKFLOW_DIR/"

# 2. Check if there's anything to commit
if git diff --cached --quiet; then
  echo "[INFO] No changes to commit"
  exit 0
fi

# 3. Commit with structured message
git commit -m "[AEGIS-RUN] agent=$AGENT_ID workflow=$WORKFLOW_ID $(date +%Y%m%d-%H%M%S)"

# 4. Tag state if gate artifact exists
LEVEL=$(python3 -c "
import json
with open('$AEGIS_ROOT/.aegis/core/registry.json') as f:
    data = json.load(f)
for a in data['agents']:
    if a['id'] == '$AGENT_ID':
        # crude level mapping
        if 'research' in a['id']: print('L1')
        elif 'architect' in a['id'] or 'prd' in a['id']: print('L2')
        elif 'squad' in a['id'] or 'dev' in a['id']: print('L3')
        elif 'review' in a['id'] or 'security' in a['id'] or 'audit' in a['id']: print('L3-GATE')
        elif 'qa' in a['id']: print('L4')
        elif 'deploy' in a['id'] or 'sre' in a['id']: print('L5')
        else: print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

if [ "$LEVEL" != "UNKNOWN" ]; then
  TAG_NAME="workflow/$WORKFLOW_ID/$LEVEL-$(date +%Y%m%d-%H%M%S)"
  git tag "$TAG_NAME"
  echo "[INFO] Tagged: $TAG_NAME"
fi

echo "[AEGIS] Post-run commit complete"
