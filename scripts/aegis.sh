#!/usr/bin/env bash

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

cd "$AEGIS_ROOT"
if [[ "${AEGIS_SKIP_WORKSPACE_AUTO_DETECT:-0}" != "1" ]]; then
  export AEGIS_WORKSPACE_ROOT="$WORKSPACE_ROOT"
fi
export AEGIS_CORE_ROOT="$AEGIS_ROOT"
export PYTHONPATH="$AEGIS_ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "ctl" ]]; then
  shift
  exec python3 -m tools.control_plane "$@"
fi
exec python3 -m tools.automation_runner "$@"
