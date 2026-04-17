#!/usr/bin/env bash

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE_ROOT="${AEGIS_WORKSPACE_ROOT:-$(pwd)}"

cd "$AEGIS_ROOT"
export AEGIS_WORKSPACE_ROOT="$WORKSPACE_ROOT"
export AEGIS_CORE_ROOT="$AEGIS_ROOT"
export PYTHONPATH="$AEGIS_ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "ctl" ]]; then
  shift
  exec python3 -m tools.control_plane "$@"
fi
exec python3 -m tools.automation_runner "$@"
