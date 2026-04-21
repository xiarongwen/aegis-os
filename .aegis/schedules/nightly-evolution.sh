#!/bin/bash
# AEGIS Nightly Agent Evolution Script

set -euo pipefail

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

run_control_plane evolution-run
