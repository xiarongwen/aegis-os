#!/bin/bash
# Post-Agent Run Hook

set -euo pipefail

AGENT_ID="${1:-unknown}"
WORKFLOW_ID="${2:-unknown}"

run_control_plane() {
  if command -v aegis >/dev/null 2>&1; then
    aegis ctl "$@"
    return 0
  fi
  if command -v aegisctl >/dev/null 2>&1; then
    aegisctl "$@"
    return 0
  fi
  if [[ -n "${AEGIS_CORE_ROOT:-}" ]]; then
    export PYTHONPATH="${AEGIS_CORE_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
    python3 -m tools.control_plane "$@"
    return 0
  fi
  echo "AEGIS control plane is unavailable; install the aegis shim or set AEGIS_CORE_ROOT" >&2
  return 1
}

resolve_workspace_root() {
  if [[ -n "${AEGIS_WORKSPACE_ROOT:-}" ]]; then
    printf '%s\n' "$AEGIS_WORKSPACE_ROOT"
    return 0
  fi
  local resolved
  if ! resolved="$(AEGIS_SKIP_WORKSPACE_AUTO_DETECT=1 run_control_plane workflow-workspace --workflow "$WORKFLOW_ID" 2>/dev/null)"; then
    echo "failed to resolve workspace for workflow $WORKFLOW_ID; attach the workspace first or set AEGIS_WORKSPACE_ROOT" >&2
    return 1
  fi
  if [[ -z "$resolved" ]]; then
    echo "failed to resolve workspace for workflow $WORKFLOW_ID; attach the workspace first or set AEGIS_WORKSPACE_ROOT" >&2
    return 1
  fi
  printf '%s\n' "$resolved"
}

WORKSPACE_ROOT="$(resolve_workspace_root)"
export AEGIS_WORKSPACE_ROOT="$WORKSPACE_ROOT"
run_control_plane post-agent-run --agent "$AGENT_ID" --workflow "$WORKFLOW_ID"
