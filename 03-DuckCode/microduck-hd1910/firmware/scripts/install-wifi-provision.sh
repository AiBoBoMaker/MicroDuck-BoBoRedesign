#!/bin/sh
# Install the Microduck Wi-Fi provision button on a systemd Linux.
#
# This is the piece that opens hotspot "Microduck" when a button is held
# during the first 5 seconds of boot. It does not install robotd, the
# servos, or the console. Those stay on the Radxa board setup.
#
# From a checkout of this firmware tree, on the machine that will run it:
#
#   sudo sh install-wifi-provision.sh
#
# Debian, Ubuntu, Armbian, Fedora, Arch and Alpine are the package paths it
# knows. Anywhere else, install python3, gpioget, NetworkManager, espeak-ng
# and aplay yourself and run it again — the copy and the service still happen
# once those commands exist.
#
# Radxa ZERO 3W is the default pin: header pin 7 (GPIO3_C4) to pin 9 (GND).
# Another board edits /etc/wifi-provision.env after install. Re-running this
# script does not overwrite that file.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行：sudo sh install-wifi-provision.sh" >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    echo "这台系统没有正在运行的 systemd，装不上开机前 5 秒读按键的服务。" >&2
    exit 1
fi

here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
py="$here/wifi-provision-button.py"
unit_src="$here/systemd/wifi-provision-button.service"
[ -f "$py" ] || { echo "找不到 $py" >&2; exit 1; }
[ -f "$unit_src" ] || { echo "找不到 $unit_src" >&2; exit 1; }

say() { printf '==> %s\n' "$*"; }

install_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        say "用 apt 安装 python3、gpiod、NetworkManager、espeak-ng、alsa-utils"
        apt-get update -qq || true
        apt-get install -y python3 gpiod network-manager espeak-ng alsa-utils iptables
    elif command -v dnf >/dev/null 2>&1; then
        say "用 dnf 安装依赖"
        dnf install -y python3 libgpiod-utils NetworkManager espeak-ng alsa-utils iptables
    elif command -v pacman >/dev/null 2>&1; then
        say "用 pacman 安装依赖"
        pacman -Sy --noconfirm python gpiod espeak-ng networkmanager alsa-utils iptables
    elif command -v apk >/dev/null 2>&1; then
        say "用 apk 安装依赖"
        apk add python3 libgpiod espeak-ng networkmanager alsa-utils iptables
    else
        echo "没有识别到 apt / dnf / pacman / apk。请先自行装好 python3、gpioget、nmcli，再重跑本脚本。" >&2
        return 1
    fi
}

if ! install_packages; then
    echo "包没有装完，继续检查命令是否已经在。" >&2
fi

missing=""
for cmd in python3 gpioget nmcli; do
    command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
done
if [ -n "$missing" ]; then
    echo "还缺这些命令，服务先不启用：$missing" >&2
    exit 1
fi

say "安装 /usr/local/sbin/wifi-provision-button.py"
install -m 755 "$py" /usr/local/sbin/wifi-provision-button.py
say "安装 wifi-provision-button.service"
install -m 644 "$unit_src" /etc/systemd/system/wifi-provision-button.service

if [ ! -f /etc/wifi-provision.env ]; then
    say "写入 /etc/wifi-provision.env（换板子时改这个文件）"
    cat > /etc/wifi-provision.env <<'EOF'
# 开机前 5 秒按住按键，打开热点 Microduck（密码 12345678）。
# Radxa ZERO 3W 不用改：排针 7 是 GPIO3_C4，在标签为 gpio3 的芯片上，线号 20。
# 换板子时先看 `gpiodetect` 和 `gpioinfo`，再取消下面相应行的注释。
# WIFI_PROVISION_GPIO_CHIP=gpiochip3
# WIFI_PROVISION_GPIO_LINE=20
# 网卡不是 wlan0 时改这里（nmcli device status 里的那一列）。
# WIFI_PROVISION_WLAN=wlan0
EOF
else
    say "保留已有的 /etc/wifi-provision.env"
fi

systemctl daemon-reload
systemctl enable wifi-provision-button.service
if systemctl list-unit-files NetworkManager.service >/dev/null 2>&1; then
    systemctl enable NetworkManager.service >/dev/null 2>&1 || true
fi

echo
echo "配网键已安装。重启后，从上电起 5 秒内按住按键，手机会看到热点 Microduck，密码 12345678。"
echo "默认接线：Radxa ZERO 3W 排针 7 和排针 9（地）。别的板子改 /etc/wifi-provision.env 后重启。"
echo "现在就可以看按键读数（按下应为 pressed）："
echo "  python3 /usr/local/sbin/wifi-provision-button.py --check"
if command -v nmcli >/dev/null 2>&1; then
    wifi_state=$(nmcli -t -f DEVICE,STATE device status 2>/dev/null | sed -n 's/^wlan0://p' || true)
    if [ "$wifi_state" = "unmanaged" ]; then
        echo "wlan0 还不是 NetworkManager 在管。这块 ZERO 请先跑 firmware/scripts/migrate-network.sh，否则热点开不起来。"
    fi
fi
