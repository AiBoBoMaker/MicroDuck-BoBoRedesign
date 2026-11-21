#!/bin/bash
# Realtime mic path for OPi H616 + AIC3104:
#   AHUB capture is ~2× fast → sox speed 0.5
#   MEMS → pin16 MIC2R → right channel → remix 2
#   Out: raw S16_LE / 16 kHz / mono on FIFO /run/duckmix/cap.raw
set -euo pipefail

CARD=aic3104
FIFO=/run/duckmix/cap.raw
mkdir -p /run/duckmix
# Reuse the FIFO inode when possible. Deleting it while robotd is blocked in
# open()/read() leaves the capture thread stuck on a dead pipe (no peak logs).
if [ ! -p "$FIFO" ]; then
  mkfifo "$FIFO"
fi

amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0' >/dev/null 2>&1 || true
amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF' >/dev/null 2>&1 || true

# MIC2R only (Mic2R on 3104 driver, Mic3R on generic aic3x names)
for side in Left Right; do
  for inp in Mic3L Mic3R Mic2L Mic2R Line1L Line1R Line2L Line2R; do
    amixer -c "$CARD" sset "$side PGA Mixer $inp" off >/dev/null 2>&1 || true
  done
done
amixer -c "$CARD" sset 'Right PGA Mixer Mic2R' on >/dev/null 2>&1 \
  || amixer -c "$CARD" sset 'Right PGA Mixer Mic3R' on >/dev/null
# Match aic3104-init: right PGA higher — mic is MIC2R only.
amixer -c "$CARD" cset name='PGA Capture Volume' 40,70 >/dev/null 2>&1 || true
amixer -c "$CARD" sset 'AGC' off >/dev/null 2>&1 || true
amixer -c "$CARD" sset 'ADC HPF Cut-off' '0.0045xFs' >/dev/null 2>&1 || true

echo "duckmix-capture: writing $FIFO (MIC2R, speed 0.5, 16 kHz mono)"

# No compand/gate: the previous soft-gate crushed speech to digital silence
# (FIFO peak≈0) while raw hw capture was fine. Keep only rate/channel fix.
exec arecord -D hw:${CARD},0 -f S32_LE -r 48000 -c 2 -t raw -q | \
  sox -t raw -r 48000 -e signed -b 32 -c 2 - \
      -t raw -r 16000 -e signed -b 16 -c 1 "$FIFO" \
      remix 2 speed 0.5
