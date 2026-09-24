#!/usr/bin/env bash
# macOS: prepare the local environment and open the study agent.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 scripts/run.py "$@"
