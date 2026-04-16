#!/bin/bash
# AEGIS Bootstrap Script
# Run this on a new machine to set up the entire AEGIS system

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"

echo "================================"
echo "AEGIS v1 Bootstrap"
echo "================================"

# 1. Verify Claude Code CLI
if ! command -v claude &> /dev/null; then
  echo "[ERROR] Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
  exit 1
fi
echo "[OK] Claude Code CLI found"

# 2. Sync AEGIS agents as skills
mkdir -p "$SKILLS_DIR"

echo "[INFO] Installing AEGIS agent skills..."
for agent_dir in "$AEGIS_ROOT"/agents/*/; do
  agent_id=$(basename "$agent_dir")
  skill_file="$agent_dir/SKILL.md"

  if [ ! -f "$skill_file" ]; then
    echo "[SKIP] $agent_id: no SKILL.md"
    continue
  fi

  target_dir="$SKILLS_DIR/$agent_id"

  # Remove old symlink or directory
  if [ -L "$target_dir" ] || [ -d "$target_dir" ]; then
    rm -rf "$target_dir"
  fi

  # Create symlink so changes in aegis-os are immediately reflected in Claude Code
  ln -s "$agent_dir" "$target_dir"
  echo "[OK] Linked $agent_id -> $agent_dir"
done

# 3. Sync external skills referenced by agents
EXTERNAL_SKILLS=(
  "agent-browser"
  "darwin-skill"
  "1password"
)

for skill in "${EXTERNAL_SKILLS[@]}"; do
  if [ ! -d "$SKILLS_DIR/$skill" ] && [ ! -L "$SKILLS_DIR/$skill" ]; then
    echo "[WARN] External skill missing: $skill"
    echo "       Install with: npx skills add <source> --skill $skill"
  else
    echo "[OK] External skill present: $skill"
  fi
done

# 4. Validate registry
if ! python3 -c "import json; json.load(open('$AEGIS_ROOT/.aegis/core/registry.json'))" 2>/dev/null; then
  echo "[ERROR] registry.json is invalid JSON"
  exit 1
fi
echo "[OK] Registry valid"

# 5. Validate orchestrator YAML
if ! python3 -c "import yaml; yaml.safe_load(open('$AEGIS_ROOT/.aegis/core/orchestrator.yml'))" 2>/dev/null; then
  # Fallback: if PyYAML not installed, just check file exists
  if [ ! -f "$AEGIS_ROOT/.aegis/core/orchestrator.yml" ]; then
    echo "[ERROR] orchestrator.yml missing"
    exit 1
  fi
fi
echo "[OK] Orchestrator config present"

# 6. Schedule nightly evolution if not already scheduled
if ! crontab -l 2>/dev/null | grep -q "nightly-evolution.sh"; then
  echo "[INFO] Setting up nightly evolution cron job..."
  (crontab -l 2>/dev/null || true; echo "0 2 * * * $AEGIS_ROOT/.aegis/schedules/nightly-evolution.sh >> /tmp/aegis-evolution.log 2>&1") | crontab -
  echo "[OK] Cron job installed: 0 2 * * *"
else
  echo "[OK] Nightly evolution cron job already exists"
fi

# 7. Initialize git if not already
if [ ! -d "$AEGIS_ROOT/.git" ]; then
  cd "$AEGIS_ROOT"
  git init
  git add .
  git commit -m "[AEGIS] v1.0.0 initial bootstrap"
  echo "[OK] Git repository initialized"
else
  echo "[OK] Git repository already initialized"
fi

echo ""
echo "================================"
echo "AEGIS Bootstrap Complete!"
echo "================================"
echo "Next steps:"
echo "  1. cd $AEGIS_ROOT"
echo "  2. Start a workflow: tell Claude '启动 AEGIS 工作流测试项目'"
echo "  3. Or run: claude code"
echo ""
