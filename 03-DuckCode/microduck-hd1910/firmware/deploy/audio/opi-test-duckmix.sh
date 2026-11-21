#!/bin/bash
# After slot-32 overlay is back: install asound + record via duckmix_cap (BoBo format).
# No reboot.  sudo bash opi-test-duckmix.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ASOUND=${1:-"$HERE/asound-opi-aic3104.conf"}

if [ "$(id -u)" -ne 0 ]; then echo "sudo bash $0"; exit 1; fi
[ -f "$ASOUND" ] || { echo "missing $ASOUND"; exit 1; }

cp "$ASOUND" /etc/asound.conf
amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0'
amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF'
amixer -c aic3104 cset name='PGA Capture Volume' 60,60 2>/dev/null || true

echo "Speak for 3s (duckmix_cap = left S32 → S16 16k mono) ..."
arecord -D duckmix_cap -f S16_LE -r 16000 -c 1 -d 3 /tmp/duckmix.wav
aplay -D plughw:aic3104 /tmp/duckmix.wav
command -v sox >/dev/null && sox /tmp/duckmix.wav -n stats
echo "If speech is clear: keep /etc/asound.conf and set capture_pcm = \"duckmix_cap\" in robotd.toml after next robotd build."
