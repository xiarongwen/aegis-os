#!/bin/bash
# Post-Agent Run Hook

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT_ID="${1:-unknown}"
WORKFLOW_ID="${2:-unknown}"

resolve_workspace_root() {
  if [[ -n "${AEGIS_WORKSPACE_ROOT:-}" ]]; then
    printf '%s\n' "$AEGIS_WORKSPACE_ROOT"
    return 0
  fi
  local resolved
  if ! resolved="$(python3 -m tools.control_plane workflow-workspace --workflow "$WORKFLOW_ID" 2>/dev/null)"; then
    echo "failed to resolve workspace for workflow $WORKFLOW_ID; attach the workspace first or set AEGIS_WORKSPACE_ROOT" >&2
    return 1
  fi
  if [[ -z "$resolved" ]]; then
    echo "empty workspace resolution for workflow $WORKFLOW_ID" >&2
    return 1
  fi
  printf '%s\n' "$resolved"
}

cd "$AEGIS_ROOT"
WORKSPACE_ROOT="$(resolve_workspace_root)"
export AEGIS_WORKSPACE_ROOT="$WORKSPACE_ROOT"
python3 -m tools.control_plane post-agent-run --agent "$AGENT_ID" --workflow "$WORKFLOW_ID"
