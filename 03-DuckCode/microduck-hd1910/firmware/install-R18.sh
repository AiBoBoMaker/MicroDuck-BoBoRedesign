#!/bin/sh
# R18 board installer. Run from the unpacked package:
#   sudo sh install-R18.sh
#
# Delegates to scripts/install-local.sh, which:
#   - installs binaries under /opt/robot/daemon/current/bin
#   - links robotctl into /usr/local/bin
#   - installs systemd sysusers (padd/btd/mediad/tofd/robot)
#   - installs GameSir→Xbox bridge (gamesir-xboxd) + uinput
#   - on Radxa/OPi writes /var/lib/robot/weird-ble so pad pair pauses btd
#   - writes /etc/robot/robotd.toml (port / IMU)
#   - Radxa ZERO 3W: uart2-m0 + aic3104 I2C overlays
#   - Orange Pi Zero 2W: free UART0 for Feetech (no serial console),
#     apb2-300m for exact-enough 1 Mbps, aic3104-h616 audio overlay + mixer
#   - ONNX Runtime 1.28.0 (libonnxruntime) so policies can load
set -eu
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
exec sh "$here/scripts/install-local.sh" "$@"
