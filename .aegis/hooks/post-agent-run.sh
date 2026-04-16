#!/bin/bash
# Post-Agent Run Hook

set -euo pipefail

AEGIS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT_ID="${1:-unknown}"
WORKFLOW_ID="${2:-unknown}"

cd "$AEGIS_ROOT"
python3 -m tools.control_plane post-agent-run --agent "$AGENT_ID" --workflow "$WORKFLOW_ID"
