#!/bin/bash
# Install OPi mic path: asound + duckmix-capture (2× speed fix + MIC2R).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "sudo bash $0"; exit 1; }

command -v sox >/dev/null || apt-get install -y sox
command -v arecord >/dev/null || apt-get install -y alsa-utils

install -m 755 "$HERE/duckmix-capture.sh" /usr/local/bin/duckmix-capture.sh
install -m 644 "$HERE/duckmix-capture.service" /etc/systemd/system/duckmix-capture.service
cp "$HERE/asound-opi-aic3104.conf" /etc/asound.conf

if [ -f "$HERE/aic3104-init.sh" ]; then
  install -m 755 "$HERE/aic3104-init.sh" /usr/local/bin/aic3104-init.sh
  bash /usr/local/bin/aic3104-init.sh || true
elif [ -f /usr/local/bin/aic3104-init.sh ]; then
  bash /usr/local/bin/aic3104-init.sh || true
fi

systemctl daemon-reload
systemctl enable duckmix-capture.service
systemctl restart duckmix-capture.service
sleep 1
systemctl --no-pager --full status duckmix-capture.service | head -12 || true

echo
echo "=== Test (speak ~3s; uses FIFO, does not steal hw device) ==="
# speed 0.5 needs ~6s wall to emit 3s audio — give 12s
rm -f /tmp/duckmix-ok.raw /tmp/duckmix-ok.wav
if timeout 12 dd if=/run/duckmix/cap.raw of=/tmp/duckmix-ok.raw bs=96000 count=1 status=progress; then
  sox -t raw -r 16000 -e signed -b 16 -c 1 /tmp/duckmix-ok.raw /tmp/duckmix-ok.wav
  echo "playing..."
  aplay -D plughw:aic3104 /tmp/duckmix-ok.wav
  echo "OK — check speed. If good: [audio] capture_pcm = \"duckmix_cap\" (needs new robotd)."
else
  echo "FIFO read failed. Falling back to one-shot (stops service briefly)..."
  systemctl stop duckmix-capture.service
  # 3s wall @ 48k + speed 0.5 → ~3s correct speech
  arecord -D hw:aic3104,0 -f S32_LE -r 48000 -c 2 -d 3 -t raw | \
    sox -t raw -r 48000 -e signed -b 32 -c 2 - \
        -t wav -r 16000 -e signed -b 16 -c 1 /tmp/duckmix-ok.wav \
        remix 2 speed 0.5 highpass 80
  aplay -D plughw:aic3104 /tmp/duckmix-ok.wav
  systemctl start duckmix-capture.service
fi
