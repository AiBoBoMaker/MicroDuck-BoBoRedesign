#!/bin/bash
# Find record/play speed ratio.  sudo bash opi-mic-speed-check.sh
set -euo pipefail
CARD=aic3104
amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0' >/dev/null
amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF' >/dev/null

echo "Speak a steady 一二三四五 for ~3s ..."
echo "== record 48k S32 =="
/usr/bin/time -f 'wall_sec=%e' arecord -D hw:${CARD},0 -f S32_LE -r 48000 -c 2 -d 3 /tmp/spd48.wav
echo "WAV info:"
soxi /tmp/spd48.wav 2>/dev/null || file /tmp/spd48.wav
sox /tmp/spd48.wav -b 16 /tmp/spd48-R.wav remix 2

echo
echo "play native (as labeled):"
aplay -D plughw:${CARD} -v /tmp/spd48-R.wav 2>&1 | head -5

echo
echo "If that was ~3x fast, try speed 0.333:"
sox /tmp/spd48-R.wav /tmp/spd48-slow3.wav speed 0.333
aplay -D plughw:${CARD} /tmp/spd48-slow3.wav

echo
echo "If that was ~1.5x fast, try speed 0.667:"
sox /tmp/spd48-R.wav /tmp/spd48-slow15.wav speed 0.667
aplay -D plughw:${CARD} /tmp/spd48-slow15.wav

echo
echo "Tell me: native / 0.333 / 0.667 which sounded normal?"
echo "And paste wall_sec= and soxi Duration."
