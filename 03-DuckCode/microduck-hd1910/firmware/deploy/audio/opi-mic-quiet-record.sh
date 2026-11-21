#!/bin/bash
# Mute speaker path, keep AHUB capture route, record 3s. No reboot.
set -euo pipefail
CARD=aic3104

echo "stop robotd (releases codec speaker use) ..."
systemctl stop robotd 2>/dev/null || true
sleep 1

echo "AHUB routes ..."
amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0'
amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF'

echo "mute playback / keep mic ..."
# Radxa-style names
amixer -c "$CARD" cset name='Line Playback Switch' off,off 2>/dev/null || true
amixer -c "$CARD" cset name='PCM Playback Volume' 0,0 2>/dev/null || true
amixer -c "$CARD" cset name='Line Playback Volume' 0,0 2>/dev/null || true
# OPi mainline short names
amixer -c "$CARD" sset 'PCM' 0% 2>/dev/null || true
amixer -c "$CARD" sset 'Line' 0% mute 2>/dev/null || true
amixer -c "$CARD" sset 'Line DAC' 0% 2>/dev/null || true

amixer -c "$CARD" sset 'Right PGA Mixer Mic3R' on
amixer -c "$CARD" sset 'Left PGA Mixer Mic3R' on
amixer -c "$CARD" cset name='PGA Capture Volume' 70,70 2>/dev/null \
  || amixer -c "$CARD" sset 'PGA' 60% 2>/dev/null || true
amixer -c "$CARD" sset 'AGC' off 2>/dev/null || true
# DC / rumble filter if present
amixer -c "$CARD" sset 'ADC HPF Cut-off' '0.0045xFs' 2>/dev/null \
  || amixer -c "$CARD" sset 'ADC HPF Cut-off' '0.00025xFs' 2>/dev/null || true

echo
echo "PGA mixers present:"
amixer -c "$CARD" scontrols | grep -i PGA || true
echo
echo "Speak close to onboard MEMS for 3s (speaker is muted) ..."
arecord -D plughw:${CARD},0 -f S16_LE -r 48000 -c 2 -d 3 /tmp/mic-quiet.wav

echo "restore modest playback volume for listening ..."
amixer -c "$CARD" sset 'PCM' 70% 2>/dev/null || true
amixer -c "$CARD" sset 'Line' 70% unmute 2>/dev/null || true
amixer -c "$CARD" cset name='Line Playback Switch' on,on 2>/dev/null || true
amixer -c "$CARD" cset name='PCM Playback Volume' 100,100 2>/dev/null || true
amixer -c "$CARD" cset name='Line Playback Volume' 6,6 2>/dev/null || true

aplay -D plughw:${CARD} /tmp/mic-quiet.wav

if command -v sox >/dev/null; then
  echo "--- sox stats ---"
  sox /tmp/mic-quiet.wav -n stats 2>&1 | head -20
fi

echo
echo "Also try native 32-bit (slot-width 32) ..."
if arecord -D hw:${CARD},0 -f S32_LE -r 48000 -c 2 -d 3 /tmp/mic-s32.wav 2>/tmp/mic-s32.err; then
  if command -v sox >/dev/null; then
    sox /tmp/mic-s32.wav -b 16 /tmp/mic-s32-16.wav
    aplay -D plughw:${CARD} /tmp/mic-s32-16.wav
    sox /tmp/mic-s32.wav -n stats 2>&1 | head -12
  else
    echo "recorded /tmp/mic-s32.wav (apt-get install -y sox to convert/play)"
  fi
else
  echo "S32 failed: $(cat /tmp/mic-s32.err)"
fi

echo "restart robotd?  sudo systemctl start robotd"
