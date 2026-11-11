#!/bin/sh
# R18 board installer. Run from the unpacked package:
#   sudo sh install-R18.sh
set -eu
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
exec sh "$here/scripts/install-local.sh" "$@"
