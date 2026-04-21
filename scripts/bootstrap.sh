#!/bin/bash
# AEGIS Bootstrap Script

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

resolve_workspace_root() {
  if [[ -n "${AEGIS_WORKSPACE_ROOT:-}" ]]; then
    (cd "$AEGIS_WORKSPACE_ROOT" && pwd)
    return 0
  fi
  if git_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    printf '%s\n' "$git_root"
    return 0
  fi
  pwd
}

WORKSPACE_ROOT="$(resolve_workspace_root)"

echo "================================"
echo "AEGIS v1 Bootstrap"
echo "================================"

if ! command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
  echo "[ERROR] Neither Claude Code CLI nor Codex CLI was found."
  echo "        Install one of them first:"
  echo "        - Claude Code: npm install -g @anthropic-ai/claude-code"
  echo "        - Codex CLI: make sure \`codex\` is installed and in PATH"
  exit 1
fi

cd "$AEGIS_ROOT"

export AEGIS_WORKSPACE_ROOT="$WORKSPACE_ROOT"

python3 -m tools.control_plane doctor
python3 -m tools.control_plane workspace-doctor
python3 -m tools.control_plane sync-agent-metadata
python3 -m tools.control_plane sync-agents
python3 -m tools.control_plane install-shims
python3 -m tools.control_plane install-cron

echo ""
echo "================================"
echo "AEGIS Bootstrap Complete!"
echo "================================"
echo "Next steps:"
echo "  1. cd $WORKSPACE_ROOT"
echo "  2. In Claude Code, use: /aegis 帮我开发一个聊天页面"
echo "  3. Or in Codex, invoke the aegis skill inside the current session"
echo "  4. Team Packs also install slash commands like /aegis-video when available"
echo "  5. For CLI fallback/debug, use aegis run --runtime codex or aegis run --runtime claude"
