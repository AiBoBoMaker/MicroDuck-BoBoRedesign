#!/bin/bash
# Install orangepi-h616-aic3104.dts (no Mic Bias) and reboot once.
# Usage on the board (put both files in the same directory first):
#   sudo bash opi-flash-aic3104-overlay.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:-"$HERE/orangepi-h616-aic3104.dts"}
NAME=aic3104-h616
DTBO=/boot/overlay-user/${NAME}.dtbo
ENV=/boot/orangepiEnv.txt

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo bash $0"
  exit 1
fi
if [ ! -f "$SRC" ]; then
  echo "missing $SRC"
  echo "scp both opi-flash-aic3104-overlay.sh and orangepi-h616-aic3104.dts to the same folder"
  exit 1
fi
if grep -q 'ai3x-micbias' "$SRC"; then
  echo "REFUSING: $SRC still contains ai3x-micbias — use the repo copy without it"
  exit 1
fi
command -v dtc >/dev/null || apt-get install -y device-tree-compiler

mkdir -p /boot/overlay-user
echo "compiling $SRC -> $DTBO"
dtc -@ -I dts -O dtb -o "$DTBO" "$SRC"
cp "$SRC" "/boot/overlay-user/${NAME}.dts"

if [ ! -f "$ENV" ]; then
  echo "missing $ENV"
  exit 1
fi
if ! grep -Eq '^user_overlays=' "$ENV"; then
  echo "user_overlays=$NAME" >> "$ENV"
elif ! grep -E '^user_overlays=' "$ENV" | grep -qw "$NAME"; then
  sed -i "s/^user_overlays=\(.*\)\$/user_overlays=\1 $NAME/" "$ENV"
fi

echo "installed. user_overlays:"
grep '^user_overlays=' "$ENV"
echo "rebooting in 2s ..."
sleep 2
reboot
