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
echo "  2. In Claude Code, use: /aegis 帮我开发一个聊天页面"
echo "  3. Or in Codex, invoke the aegis skill inside the current session"
echo "  4. Use ./aegis or python3 -m tools.automation_runner only for fallback/debug"
