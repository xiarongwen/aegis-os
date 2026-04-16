#!/bin/bash
# AEGIS Nightly Agent Evolution Script

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

cd "$AEGIS_ROOT"
python3 -m tools.control_plane evolution-run
