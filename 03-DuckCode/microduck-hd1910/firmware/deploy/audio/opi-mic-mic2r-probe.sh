#!/bin/bash
# Probe capture with schematic routing: pin16 MIC2R → Right PGA only.
# No DT flash required for the mixer part.  sudo bash opi-mic-mic2r-probe.sh
set -euo pipefail
CARD=aic3104

echo "HAT: MEMS --R--> AIC3104 pin16 MIC2R --> Right PGA / Right I2S slot"

amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0'
amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF'

for side in Left Right; do
  for inp in Mic3L Mic3R Mic2L Mic2R Line1L Line1R Line2L Line2R; do
    amixer -c "$CARD" sset "$side PGA Mixer $inp" off >/dev/null 2>&1 || true
  done
done
# Prefer Mic2R (3104 driver); fall back to Mic3R (generic aic3x names, same reg).
if amixer -c "$CARD" sset 'Right PGA Mixer Mic2R' on 2>/dev/null; then
  echo "using Right PGA Mixer Mic2R"
else
  amixer -c "$CARD" sset 'Right PGA Mixer Mic3R' on
  echo "using Right PGA Mixer Mic3R (generic name)"
fi
amixer -c "$CARD" cset name='PGA Capture Volume' 40,70 2>/dev/null || true
amixer -c "$CARD" sset 'AGC' off 2>/dev/null || true

echo "Speak 3s ..."
arecord -D hw:${CARD},0 -f S32_LE -r 48000 -c 2 -d 3 /tmp/mic2r.wav
echo "--- stats ---"
sox /tmp/mic2r.wav -n stats 2>&1 | head -20
sox /tmp/mic2r.wav -b 16 /tmp/mic2r-L.wav remix 1 gain -n -3
sox /tmp/mic2r.wav -b 16 /tmp/mic2r-R.wav remix 2 gain -n -3
amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0'
amixer -c "$CARD" sset 'PCM' 90% 2>/dev/null || true
amixer -c "$CARD" sset 'Line' 80% unmute 2>/dev/null || true
echo "play LEFT:"
aplay -D plughw:${CARD} /tmp/mic2r-L.wav
echo "play RIGHT (schematic channel):"
aplay -D plughw:${CARD} /tmp/mic2r-R.wav
echo "Say which side had speech: L / R / neither / both"
