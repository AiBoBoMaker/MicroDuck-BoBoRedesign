#!/bin/bash
# Restore slot-width 32 overlay, install duckmix_cap ALSA PCM, verify mic.
# Copy to board with:
#   orangepi-h616-aic3104.dts
#   asound-opi-aic3104.conf
#   opi-flash-aic3104-overlay.sh
#   opi-apply-mic-fix.sh
# Then:  sudo bash opi-apply-mic-fix.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
  echo "sudo bash $0"
  exit 1
fi

DTS=${HERE}/orangepi-h616-aic3104.dts
ASOUND=${HERE}/asound-opi-aic3104.conf
FLASH=${HERE}/opi-flash-aic3104-overlay.sh

for f in "$DTS" "$ASOUND" "$FLASH"; do
  [ -f "$f" ] || { echo "missing $f — scp the four files into one folder"; exit 1; }
done

if ! grep -q 'slot-width = <32>' "$DTS"; then
  echo "REFUSING: $DTS must have slot-width = <32> (S32 left channel path)"
  exit 1
fi

echo "== install /etc/asound.conf =="
cp "$ASOUND" /etc/asound.conf

echo "== flash aic3104-h616 overlay (slot 32) and reboot =="
echo "After reboot run:  sudo bash $HERE/opi-apply-mic-fix.sh --test-only"
bash "$FLASH" "$DTS"
# flash script reboots — unreachable
