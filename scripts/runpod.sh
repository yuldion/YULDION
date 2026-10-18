#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo 'Usage: bash scripts/runpod.sh /workspace/config.local.json [seconds<=3600]' >&2
  exit 2
fi
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_dir="$(CDPATH= cd -- "$script_dir/.." && pwd)"
python_bin="${YULDION_PYTHON:-python3}"
limit="${2:-300}"
case "$limit" in ''|*[!0-9]*) echo 'seconds must be an integer' >&2; exit 2;; esac
if [[ "$limit" -lt 1 || "$limit" -gt 3600 ]]; then echo 'seconds must be 1..3600' >&2; exit 2; fi
if ! command -v timeout >/dev/null 2>&1; then echo 'Linux timeout command is required' >&2; exit 2; fi
# This starts only the foreground engine. No pod/API operations, installs, downloads or training.
# Local virtualenvs and model adapter dependencies are prepared by the operator.
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec timeout --signal=INT --kill-after=10 "${limit}s" "$python_bin" -m yuldion run \
  --config "$1" --max-seconds "$limit" --json-events
