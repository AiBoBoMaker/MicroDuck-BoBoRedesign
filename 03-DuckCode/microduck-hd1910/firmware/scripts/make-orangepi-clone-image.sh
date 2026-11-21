#!/usr/bin/env bash
# 在 Ubuntu 电脑上：从已装好 R18 的鸭子 TF 卡制作可刷写镜像，
# 并清除本机 Wi-Fi 与舵机标定等「单机私货」，方便刷到下一张卡。
#
# 用法：
#   1. 鸭子正常关机，拔出 TF 卡，插入读卡器接到 Ubuntu
#   2. lsblk 确认卡设备（例如 /dev/sdb，切勿选错系统盘）
#   3. sudo bash make-orangepi-clone-image.sh /dev/sdb
#   4. 得到 ~/Microduck-OPi-R18-clean-YYYYMMDD.img.xz
#
# 刷到新卡：
#   sudo xz -dc Microduck-OPi-R18-clean-*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
#
# 环境变量（可选）：
#   OUT=/path/to/out.img.xz   输出路径
#   KEEP_SSH_HOST_KEYS=1      保留 SSH 主机密钥（默认删除，首启会重生）
#   KEEP_MACHINE_ID=1         保留 machine-id（默认清空，首启会重生）
#   SKIP_ZEROFREE=1           跳过 zerofree（默认有则做，利于压缩）

set -euo pipefail

die() { printf '错误: %s\n' "$*" >&2; exit 1; }
say() { printf '==> %s\n' "$*"; }
warn() { printf '注意: %s\n' "$*" >&2; }

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "请用 root：sudo bash $0 /dev/sdX"
  fi
}

usage() {
  cat <<'EOF'
用法: sudo bash make-orangepi-clone-image.sh <TF卡设备>

示例:
  lsblk
  sudo bash make-orangepi-clone-image.sh /dev/sdb

会挂载卡上的分区，删除 Wi-Fi 连接与标定等，再整盘 dd 并 xz 压缩。
EOF
}

DEV="${1:-}"
if [ -z "$DEV" ] || [ "$DEV" = "-h" ] || [ "$DEV" = "--help" ]; then
  usage
  exit 0
fi

need_root

case "$DEV" in
  /dev/sd?[0-9]*|/dev/mmcblk*[pP][0-9]*|/dev/nvme*p[0-9]*)
    die "请给整盘设备（如 /dev/sdb），不要带分区号（不要 /dev/sdb1）"
    ;;
esac

[ -b "$DEV" ] || die "不是块设备: $DEV"

# 拒绝系统盘
root_src=$(findmnt -no SOURCE / 2>/dev/null || true)
root_disk=""
if [ -n "$root_src" ]; then
  root_disk=$(lsblk -no PKNAME "$root_src" 2>/dev/null || true)
  if [ -n "$root_disk" ]; then
    root_disk="/dev/$root_disk"
  else
    root_disk=$root_src
  fi
fi
if [ "$DEV" = "$root_disk" ] || [ "$DEV" = "$(findmnt -no SOURCE / | sed 's/[0-9]*$//;s/p$//')" ]; then
  die "拒绝：看起来像当前系统盘 ($DEV)。请确认 TF 卡设备名。"
fi

# 仍有挂载则先提醒（脚本后面会 umount）
if findmnt -S "$DEV" >/dev/null 2>&1 || lsblk -ln "$DEV" | awk '{print $7}' | grep -q .; then
  warn "设备上有挂载点，稍后会尝试卸载"
fi

SIZE_B=$(blockdev --getsize64 "$DEV")
SIZE_G=$(awk -v b="$SIZE_B" 'BEGIN{printf "%.1f", b/1024/1024/1024}')
MODEL=$(lsblk -dno MODEL "$DEV" 2>/dev/null | tr -s ' ' || true)
NAME=$(lsblk -dno NAME,SIZE,MODEL,TRAN "$DEV" 2>/dev/null || true)

echo
echo "即将制作镜像的设备："
echo "  $NAME"
echo "  容量约 ${SIZE_G} GiB"
echo
echo "将清除（在卡内 rootfs 上）："
echo "  - NetworkManager / wpa_supplicant Wi-Fi 配置与租约"
echo "  - /etc/robot 下舵机标定（feetech / hd1910-calibration 等）"
echo "  - /var/lib/robot/bobo-client-id（若有）"
echo "  - 用户与 root 的 shell 历史"
echo "  - 日志与临时文件"
echo
echo "清完 Wi-Fi 后：下次开机若无已保存家庭 Wi-Fi，会自动开 Microduck 热点"
echo "（密码 12345678，页面 http://10.42.0.1:8088）。"
if [ "${KEEP_SSH_HOST_KEYS:-0}" != 1 ]; then
  echo "  - SSH host keys（新卡首次开机重生）"
fi
if [ "${KEEP_MACHINE_ID:-0}" != 1 ]; then
  echo "  - machine-id（新卡首次开机重生）"
fi
echo
echo "会保留：R18 程序、overlay、ONNX、模型、robotd.toml 里的板级默认等。"
echo
read -r -p "确认无误，输入 YES 继续: " ans
[ "$ans" = "YES" ] || die "已取消"

STAMP=$(date +%Y%m%d)
OUT="${OUT:-$HOME/Microduck-OPi-R18-clean-${STAMP}.img}"
case "$OUT" in
  *.xz) RAW="${OUT%.xz}" ;;
  *.img) RAW="$OUT"; OUT="${OUT}.xz" ;;
  *) RAW="${OUT}.img"; OUT="${OUT}.img.xz" ;;
esac

WORK=$(mktemp -d /tmp/microduck-clone-XXXXXX)
BOOT_MNT="$WORK/boot"
ROOT_MNT="$WORK/root"
mkdir -p "$BOOT_MNT" "$ROOT_MNT"
cleanup() {
  set +e
  sync
  umount -R "$BOOT_MNT" 2>/dev/null
  umount -R "$ROOT_MNT" 2>/dev/null
  # 分区挂载点
  for m in "$WORK"/p*; do
    [ -d "$m" ] || continue
    umount -R "$m" 2>/dev/null
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

say "卸载 ${DEV} 上已有挂载"
for mp in $(lsblk -lnpo MOUNTPOINT "$DEV" | awk 'NF'); do
  umount -R "$mp" || umount -l "$mp" || true
done
sleep 1

# 发现分区
mapfile -t PARTS < <(lsblk -lnpo NAME,FSTYPE,TYPE "$DEV" | awk '$3=="part"{print $1"\t"$2}')
[ "${#PARTS[@]}" -ge 1 ] || die "没有发现分区，请检查读卡器与卡"

ROOT_PART=""
BOOT_PART=""
for line in "${PARTS[@]}"; do
  p=${line%%$'\t'*}
  fs=${line#*$'\t'}
  m="$WORK/$(basename "$p")"
  mkdir -p "$m"
  case "$fs" in
    ext4|ext3|ext2|btrfs|xfs)
      if mount -o rw "$p" "$m" 2>/dev/null; then
        if [ -d "$m/etc" ] && { [ -f "$m/etc/robot/robotd.toml" ] || [ -d "$m/opt/robot" ] || [ -f "$m/boot/orangepiEnv.txt" ] || [ -f "$m/etc/orangepi-release" ]; }; then
          ROOT_PART=$p
          ROOT_MNT=$m
        fi
      fi
      ;;
    vfat|fat|fat32|exfat)
      if mount -o rw "$p" "$m" 2>/dev/null; then
        if [ -f "$m/orangepiEnv.txt" ] || [ -f "$m/boot.cmd" ] || [ -d "$m/overlay-user" ]; then
          BOOT_PART=$p
          BOOT_MNT=$m
        fi
      fi
      ;;
  esac
done

[ -n "$ROOT_PART" ] || die "未找到含 /etc 或 /opt/robot 的 root 分区。PARTS=${PARTS[*]}"

say "root 分区: $ROOT_PART → $ROOT_MNT"
[ -n "$BOOT_PART" ] && say "boot 分区: $BOOT_PART → $BOOT_MNT"

sanitize_root() {
  local root=$1
  local here
  here=$(cd "$(dirname "$0")" && pwd)

  say "清除 Wi-Fi / NetworkManager"
  rm -f "$root"/etc/NetworkManager/system-connections/* 2>/dev/null || true
  rm -f "$root"/etc/wpa_supplicant/wpa_supplicant.conf 2>/dev/null || true
  rm -f "$root"/etc/wpa_supplicant/*.conf 2>/dev/null || true
  # 只清租约与内部状态文件，保留目录结构，避免 NM 起不来
  rm -f "$root"/var/lib/NetworkManager/* 2>/dev/null || true
  mkdir -p "$root"/var/lib/NetworkManager
  # netplan 里若写了个人 Wi-Fi，删掉自定义 yaml（保留 example）
  if [ -d "$root/etc/netplan" ]; then
    find "$root/etc/netplan" -maxdepth 1 -type f -name '*.yaml' ! -name '*example*' -delete 2>/dev/null || true
  fi

  say "确保无 Wi-Fi 时能自动开配网热点（Orange Pi Zero 2W）"
  if [ -f "$here/wifi-provision-button.py" ]; then
    install -m 755 "$here/wifi-provision-button.py" \
      "$root/usr/local/sbin/wifi-provision-button.py"
  fi
  if [ -f "$here/systemd/wifi-provision-button.service" ]; then
    install -m 644 "$here/systemd/wifi-provision-button.service" \
      "$root/etc/systemd/system/wifi-provision-button.service"
  fi
  mkdir -p "$root/etc/systemd/system/sysinit.target.wants"
  ln -sfn /etc/systemd/system/wifi-provision-button.service \
    "$root/etc/systemd/system/sysinit.target.wants/wifi-provision-button.service"
  # 排针 7 = PI13 = gpiochip1 line 269；无家庭 Wi-Fi 时自动开热点
  cat > "$root/etc/wifi-provision.env" <<'EOF'
WIFI_PROVISION_GPIO_CHIP=gpiochip1
WIFI_PROVISION_GPIO_LINE=269
WIFI_PROVISION_WLAN=wlan0
WIFI_PROVISION_AUTO=1
EOF
  chmod 644 "$root/etc/wifi-provision.env"

  say "清除舵机标定与单机 ID"
  rm -f "$root"/etc/robot/feetech-ft5/*.toml 2>/dev/null || true
  rm -f "$root"/etc/robot/feetech-ft5/*calibration* 2>/dev/null || true
  rm -rf "$root"/etc/robot/feetech-ft5/hd1910-calibration.toml 2>/dev/null || true
  # 常见标定路径变体
  find "$root/etc/robot" -type f \( -name '*calibration*' -o -name 'hd1910*.toml' \) -delete 2>/dev/null || true
  rm -f "$root"/var/lib/robot/bobo-client-id 2>/dev/null || true
  # ALSA 本机音量状态可清，开机由 aic3104-init 再设
  rm -f "$root"/var/lib/alsa/asound.state 2>/dev/null || true

  say "清除历史与日志"
  rm -f "$root"/root/.bash_history "$root"/root/.zsh_history 2>/dev/null || true
  find "$root/home" -maxdepth 2 -type f \( -name '.bash_history' -o -name '.zsh_history' -o -name '.lesshst' \) -delete 2>/dev/null || true
  rm -rf "$root"/var/log/journal/* 2>/dev/null || true
  find "$root/var/log" -type f -name '*.log' -delete 2>/dev/null || true
  find "$root/var/log" -type f -name '*.gz' -delete 2>/dev/null || true
  truncate -s 0 "$root"/var/log/wtmp 2>/dev/null || true
  truncate -s 0 "$root"/var/log/btmp 2>/dev/null || true
  truncate -s 0 "$root"/var/log/lastlog 2>/dev/null || true
  rm -rf "$root"/tmp/* "$root"/var/tmp/* 2>/dev/null || true
  rm -f "$root"/var/lib/dhcp/*.leases "$root"/var/lib/dhcpcd5/*.lease 2>/dev/null || true

  if [ "${KEEP_SSH_HOST_KEYS:-0}" != 1 ]; then
    say "删除 SSH host keys，并装首启重生单元（否则 sshd -t 会失败）"
    rm -f "$root"/etc/ssh/ssh_host_* 2>/dev/null || true
    cat > "$root/etc/systemd/system/microduck-regen-ssh-hostkeys.service" <<'EOF'
[Unit]
Description=Regenerate SSH host keys once after clone sanitize
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key
After=local-fs.target
Before=ssh.service ssh.socket

[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A
# Clone images sometimes left ssh.service disabled after a failed start loop.
ExecStartPost=/bin/systemctl enable ssh.service
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    mkdir -p "$root/etc/systemd/system/multi-user.target.wants"
    ln -sfn /etc/systemd/system/microduck-regen-ssh-hostkeys.service \
      "$root/etc/systemd/system/multi-user.target.wants/microduck-regen-ssh-hostkeys.service"
  fi

  if [ "${KEEP_MACHINE_ID:-0}" != 1 ]; then
    say "清空 machine-id（新卡首启重生）"
    : > "$root/etc/machine-id" 2>/dev/null || true
    rm -f "$root/var/lib/dbus/machine-id" 2>/dev/null || true
  fi

  # 写一个提示，方便认出这是清洁克隆
  mkdir -p "$root/etc/robot"
  cat > "$root/etc/robot/CLONE-IMAGE.txt" <<EOF
This image was sanitized by make-orangepi-clone-image.sh on $(date -Iseconds).
Wi-Fi and Feetech calibration were cleared. Re-pair Wi-Fi and re-run commissioning.
EOF

  say "清理完成"
}

sanitize_root "$ROOT_MNT"

# 若 /boot 在 root 内且存在 orangepiEnv，不动 overlay（那是板级配置）
# 独立 boot 分区一般无需清 Wi-Fi

if [ "${SKIP_ZEROFREE:-0}" != 1 ] && command -v zerofree >/dev/null 2>&1; then
  say "zerofree 以改善压缩率（只读重挂）"
  sync
  umount "$ROOT_MNT"
  if mount -o ro "$ROOT_PART" "$ROOT_MNT"; then
    zerofree -v "$ROOT_PART" || warn "zerofree 失败，继续"
    umount "$ROOT_MNT"
  fi
  mount -o rw "$ROOT_PART" "$ROOT_MNT" || true
elif [ "${SKIP_ZEROFREE:-0}" != 1 ]; then
  warn "未安装 zerofree（sudo apt-get install -y zerofree）。跳过，镜像可能更大。"
fi

say "同步并卸载"
sync
umount -R "$ROOT_MNT" 2>/dev/null || umount "$ROOT_MNT" || true
[ -n "$BOOT_PART" ] && umount -R "$BOOT_MNT" 2>/dev/null || true
# 卸掉探测时挂上的其它分区
for m in "$WORK"/p* "$WORK"/mmcblk* "$WORK"/sd*; do
  [ -d "$m" ] || continue
  umount -R "$m" 2>/dev/null || true
done
sleep 1

say "整盘写入 $RAW （约 ${SIZE_G} GiB，需足够磁盘空间）"
dd if="$DEV" of="$RAW" bs=4M status=progress conv=fsync

say "压缩为 $OUT"
if command -v xz >/dev/null 2>&1; then
  xz -T0 -9 -f -c "$RAW" > "$OUT"
  rm -f "$RAW"
elif command -v gzip >/dev/null 2>&1; then
  OUT="${OUT%.xz}.gz"
  gzip -1 -c "$RAW" > "$OUT"
  rm -f "$RAW"
else
  warn "没有 xz/gzip，保留未压缩镜像: $RAW"
  OUT=$RAW
fi

sync
say "完成: $OUT"
ls -lh "$OUT"
cat <<EOF

刷到新 TF 卡（把 /dev/sdX 换成新卡，再次确认 lsblk）：
  sudo xz -dc "$OUT" | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync

新卡开机后请：
  1) 重新配 Wi-Fi（或配网键热点）
  2) 中控做舵机标定 / IMU 方向确认
  3) 若 SSH 主机密钥已清，第一次连接会提示密钥变更，属正常

EOF
