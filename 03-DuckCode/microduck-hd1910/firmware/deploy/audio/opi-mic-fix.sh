#!/bin/bash
# Orange Pi aic3104 mic: kill Mic Bias, set mixer, short capture probe.
# No reboot.  sudo bash opi-mic-fix.sh
set -euo pipefail

CARD=aic3104
WAV=/tmp/opi-mic-probe.wav

echo "== not UART baud rate; this is I2S / Mic Bias =="

# Prefer sysfs (instant). Never hang on i2cdetect across every bus.
find_bus() {
  local node bus
  for node in /sys/bus/i2c/devices/*-0018; do
    [ -e "$node" ] || continue
    bus=$(basename "$node")
    bus=${bus%-0018}
    # strip leading zeros: 003 -> 3, 0 -> 0
    bus=$((10#$bus))
    echo "$bus"
    return 0
  done
  # Fallback: only buses that already look like the HAT (timeout 2s each)
  local b
  for b in 1 2 3 0 4 5; do
    if timeout 2 i2cdetect -y "$b" 2>/dev/null | grep -Eq '(^| )18( |$)'; then
      echo "$b"
      return 0
    fi
  done
  return 1
}

if ! command -v i2cset >/dev/null; then
  echo "need i2c-tools: sudo apt-get install -y i2c-tools"
  exit 1
fi

echo "looking for codec @ 0x18 ..."
BUS=$(find_bus || true)
if [ -z "${BUS:-}" ]; then
  echo "FATAL: no i2c *-0018 device. Have:"
  ls /sys/bus/i2c/devices/ 2>/dev/null || true
  exit 1
fi
echo "codec on i2c-$BUS @ 0x18"

echo "clearing MICBIAS (reg 25) with i2cset -f (driver owns 0x18) ..."
# -f: kernel snd-soc-tlv320aic3x already bound; without -f → Device busy.
i2cset -y -f "$BUS" 0x18 0x00 0x00
BEFORE=$(i2cget -y -f "$BUS" 0x18 0x19)
i2cset -y -f "$BUS" 0x18 0x19 0x00
AFTER=$(i2cget -y -f "$BUS" 0x18 0x19)
echo "MICBIAS reg25: $BEFORE -> $AFTER (want 0x00)"
if [ "$AFTER" != "0x00" ]; then
  echo "WARN: could not clear MICBIAS"
fi

echo "mixer ..."
amixer -c "$CARD" sset 'Right PGA Mixer Mic3R' on >/dev/null
amixer -c "$CARD" sset 'Left PGA Mixer Mic3R' on >/dev/null
amixer -c "$CARD" sset 'Left PGA Mixer Mic3L' off >/dev/null 2>&1 || true
amixer -c "$CARD" sset 'Right PGA Mixer Mic3L' off >/dev/null 2>&1 || true
amixer -c "$CARD" cset name='PGA Capture Switch' on,on >/dev/null 2>&1 || true
amixer -c "$CARD" cset name='PGA Capture Volume' 60,60 >/dev/null 2>&1 \
  || amixer -c "$CARD" sset 'PGA' 50% >/dev/null 2>&1 || true
amixer -c "$CARD" sset 'AGC' off >/dev/null 2>&1 || true
amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0' >/dev/null 2>&1 || true
amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF' >/dev/null 2>&1 || true
amixer -c ahubdam sget 'APBIF0 Src Select' || true
amixer -c ahubdam sget 'I2S0 Src Select' || true

echo
# duckmix-capture holds hw:aic3104 — stop it or arecord blocks forever.
if systemctl is-active --quiet duckmix-capture.service 2>/dev/null; then
  echo "stopping duckmix-capture (it holds the sound card) ..."
  systemctl stop duckmix-capture.service
  RESTART_DUCKMIX=1
fi
echo "Speak into the onboard MEMS for 3 seconds ..."
arecord -D hw:${CARD},0 -f S32_LE -r 48000 -c 2 -d 3 -t raw | \
  sox -t raw -r 48000 -e signed -b 32 -c 2 - \
      -t wav -r 16000 -e signed -b 16 -c 1 "$WAV" \
      remix 2 speed 0.5 highpass 80
echo "playing $WAV"
aplay -D plughw:${CARD} "$WAV" || true
if [ "${RESTART_DUCKMIX:-0}" = 1 ]; then
  systemctl start duckmix-capture.service || true
fi
echo "done."
