#!/bin/bash
# ascend-ci-insight: One-command CI failure analysis
#
# Usage:
#   ./scripts/run.sh              # Analyze last 7 days (Chinese output)
#   ./scripts/run.sh --days 14    # Analyze last 14 days
#   ./scripts/run.sh --pr 9495    # Analyze specific PR
#   ./scripts/run.sh --lang en    # English output

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Ensure gh CLI is authenticated
if ! gh auth status &>/dev/null; then
    echo "ERROR: gh CLI not authenticated. Run 'gh auth login' first."
    exit 1
fi

# Ensure claude CLI is available
if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found. Install Claude Code first."
    exit 1
fi

exec python3 -m src "$@"
