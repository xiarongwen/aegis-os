#!/bin/bash
# AEGIS Bootstrap Script

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "================================"
echo "AEGIS v1 Bootstrap"
echo "================================"

if ! command -v claude >/dev/null 2>&1; then
  echo "[ERROR] Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
  exit 1
fi

cd "$AEGIS_ROOT"

python3 -m tools.control_plane doctor
python3 -m tools.control_plane sync-agent-metadata
python3 -m tools.control_plane sync-agents
python3 -m tools.control_plane install-cron

echo ""
echo "================================"
echo "AEGIS Bootstrap Complete!"
echo "================================"
echo "Next steps:"
echo "  1. cd $AEGIS_ROOT"
echo "  2. Start a workflow: tell Claude '启动 AEGIS 工作流测试项目'"
echo "  3. Or run: claude code"
