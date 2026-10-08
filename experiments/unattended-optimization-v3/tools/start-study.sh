#!/bin/sh
# Fixed reviewed workflow. No arbitrary command, path, or environment overrides.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
exec python3 "$ROOT/owner/deployment.py" "$@"
