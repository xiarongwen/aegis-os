#!/bin/bash
# AEGIS Nightly Agent Evolution Script
# Runs at 02:00 daily via cron
# Philosophy: Evaluate -> Improve -> Test -> Keep or Revert

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKTREE_BASE="/tmp/aegis-evolution"
EVOLUTION_BRANCH="auto-evolve/$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$AEGIS_ROOT/.aegis/core/evolution.log"
REGISTRY="$AEGIS_ROOT/.aegis/core/registry.json"

mkdir -p "$WORKTREE_BASE"
cd "$AEGIS_ROOT"

# 1. Create isolated git worktree
git worktree add "$WORKTREE_BASE/$EVOLUTION_BRANCH" -b "$EVOLUTION_BRANCH" 2>/dev/null || {
  echo "[ERROR] Failed to create worktree"
  exit 1
}

cd "$WORKTREE_BASE/$EVOLUTION_BRANCH"

echo "=== AEGIS Nightly Evolution Started: $(date) ==="
echo "Branch: $EVOLUTION_BRANCH"

IMPROVEMENTS=0

# 2. Iterate over all agents with evolution enabled
for agent_dir in agents/*/; do
  agent_id=$(basename "$agent_dir")
  skill_file="$agent_dir/SKILL.md"
  agent_json="$agent_dir/agent.json"

  # Skip if no SKILL.md to optimize
  [ ! -f "$skill_file" ] && continue

  # Check if evolution is enabled in registry
  enabled=$(python3 -c "
import json
with open('$REGISTRY') as f:
    data = json.load(f)
for a in data['agents']:
    if a['id'] == '$agent_id' and a.get('evolution', False):
        print('true')
        break
" 2>/dev/null || echo "false")

  [ "$enabled" != "true" ] && continue

  echo ""
  echo "--- Evolving $agent_id ---"

  # Get current score from agent.json (default 5.0)
  old_score=$(python3 -c "
import json, sys
try:
    with open('$agent_json') as f:
        data = json.load(f)
    print(data.get('metrics', {}).get('last_score', 5.0))
except:
    print('5.0')
" 2>/dev/null || echo "5.0")

  # 3. Run darwin-skill optimization via Claude Code
  # In practice, this spawns a Claude Code session with darwin-skill
  echo "Running darwin-skill on $agent_id (baseline: $old_score)..."

  # For v1, we use a simplified self-evaluation approach:
  # The agent's SKILL.md is analyzed and improved in-place
  # A real implementation would call: claude code --skill agents/darwin-skill/SKILL.md

  # Simplified v1 approach: check if SKILL.md was modified by external process
  # In actual nightly run, this script is invoked BY Claude Code with darwin-skill loaded

  # Placeholder for darwin-skill invocation:
  # claude code --skill "$AEGIS_ROOT/agents/darwin-skill/SKILL.md" \
  #   --prompt "Optimize $skill_file using the 8-dimension rubric at $AEGIS_ROOT/shared-contexts/review-rubric-8dim.json"

  # v1 simplified: simulate evaluation and potential improvement
  # In production, replace this block with actual darwin-skill execution
  new_score="$old_score"
  status="skipped"
  note="v1_placeholder: replace with actual darwin-skill invocation"

  # If a .evolution-result file exists (created by darwin-skill), read it
  if [ -f "$agent_dir/.evolution-result.json" ]; then
    new_score=$(python3 -c "import json; print(json.load(open('$agent_dir/.evolution-result.json')).get('new_score', $old_score))" 2>/dev/null || echo "$old_score")
    status=$(python3 -c "import json; print(json.load(open('$agent_dir/.evolution-result.json')).get('status', 'skipped'))" 2>/dev/null || echo "skipped")
    rm -f "$agent_dir/.evolution-result.json"
  fi

  # 4. Ratchet mechanism: only keep improvements
  if python3 -c "import sys; sys.exit(0 if float('$new_score') > float('$old_score') else 1)" 2>/dev/null; then
    git add "$agent_dir/"
    git commit -m "[AEGIS-EVOLVE] $agent_id: $old_score -> $new_score" || true
    echo "KEEP: $agent_id improved from $old_score to $new_score"
    IMPROVEMENTS=$((IMPROVEMENTS + 1))

    # Update agent.json with new score
    python3 -c "
import json
with open('$agent_json', 'r') as f:
    data = json.load(f)
data.setdefault('metrics', {})
data['metrics']['last_score'] = float('$new_score')
data['metrics']['evolution_count'] = data['metrics'].get('evolution_count', 0) + 1
with open('$agent_json', 'w') as f:
    json.dump(data, f, indent=2)
"
    git add "$agent_json"
    git commit --amend -m "[AEGIS-EVOLVE] $agent_id: $old_score -> $new_score" || true

    # Log
    commit_hash=$(git rev-parse --short HEAD)
    echo "$(date -Iseconds) | $agent_id | keep | $old_score | $new_score | $commit_hash | $note" >> "$LOG_FILE"
  else
    git checkout HEAD -- "$agent_dir/" 2>/dev/null || true
    git commit --allow-empty -m "[AEGIS-EVOLVE] $agent_id: revert ($new_score <= $old_score)" || true
    echo "REVERT: $agent_id did not improve ($old_score -> $new_score)"

    commit_hash=$(git rev-parse --short HEAD)
    echo "$(date -Iseconds) | $agent_id | revert | $old_score | $new_score | $commit_hash | $note" >> "$LOG_FILE"
  fi
done

# 5. Finalize branch
echo ""
echo "=== Evolution Summary ==="
echo "Improvements: $IMPROVEMENTS"

if [ "$IMPROVEMENTS" -gt 0 ]; then
  git add "$LOG_FILE"
  git commit -m "[AEGIS-EVOLVE] Daily evolution complete: $IMPROVEMENTS agents improved" || true
  echo "Branch $EVOLUTION_BRANCH contains improvements."
  echo "To merge: git checkout main && git merge $EVOLUTION_BRANCH"
else
  echo "No improvements. Cleaning up branch."
  cd "$AEGIS_ROOT"
  git branch -D "$EVOLUTION_BRANCH" 2>/dev/null || true
fi

# 6. Cleanup worktree
cd "$AEGIS_ROOT"
git worktree remove "$WORKTREE_BASE/$EVOLUTION_BRANCH" 2>/dev/null || rm -rf "$WORKTREE_BASE/$EVOLUTION_BRANCH"

echo "=== AEGIS Nightly Evolution Finished: $(date) ==="
