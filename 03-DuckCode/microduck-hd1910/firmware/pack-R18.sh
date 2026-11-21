#!/usr/bin/env bash
# Cross-compile every board program, then write Microduck-R18.zip.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
exec python3 "$ROOT/pack_r18.py" "$@"
