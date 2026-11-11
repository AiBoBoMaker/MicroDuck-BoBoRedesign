#!/bin/sh
# Install THIS firmware tree onto the board it is copied to. Nothing is downloaded.
#
# On the board, after the tree is at /opt/microduck/firmware:
#
#   sudo sh /opt/microduck/firmware/scripts/install-local.sh
#
# It asks which board, then the servo port, the IMU and the Wi-Fi provision
# button, and writes those choices into /etc/robot/robotd.toml. Radxa ZERO 3W
# also turns on the UART and audio overlays from deploy/audio. Service units
# from this tree are installed and enabled. A binary is copied into
# /opt/robot/daemon/current/bin only when this tree already contains the
# aarch64 build of it.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行：sudo sh /opt/microduck/firmware/scripts/install-local.sh" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    echo "这台系统没有正在运行的 systemd，服务无法设成开机自启。" >&2
    exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
DEPLOY="$ROOT/deploy"
SCRIPTS="$ROOT/scripts"
CONFIG=/etc/robot/robotd.toml
BIN_DST=/opt/robot/daemon/current/bin
NEED_REBOOT=0

say() { printf '==> %s\n' "$*"; }
warn() { printf '注意: %s\n' "$*" >&2; }

prompt() {
    # $1 question, $2 default. Answer in $REPLY.
    printf '%s [%s]: ' "$1" "$2"
    IFS= read -r REPLY || REPLY=""
    if [ -z "$REPLY" ]; then
        REPLY=$2
    fi
}

yes_no() {
    # $1 question, $2 default y or n. Returns 0 for yes.
    if [ "$2" = y ]; then
        prompt "$1（y/n）" "y"
    else
        prompt "$1（y/n）" "n"
    fi
    case "$REPLY" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

list_nodes() {
    # $1 shell glob
    found=0
    for node in $1; do
        if [ -e "$node" ]; then
            echo "    $node"
            found=1
        fi
    done
    if [ "$found" = 0 ]; then
        echo "    （现在没看到设备，仍可以先填一个，插上后再重启）"
    fi
}

choose_board() {
    echo
    echo "选择这块板子。回车等于 1。"
    echo "  1) Radxa ZERO 3W + Armbian（舵机 /dev/ttyS2，会改设备树）"
    echo "  2) 通用 Ubuntu（不改设备树，串口和 IMU 由你填）"
    prompt "编号" "1"
    case "$REPLY" in
        2) BOARD=ubuntu ;;
        *) BOARD=radxa ;;
    esac
}

choose_port() {
    echo
    echo "舵机串口。当前系统里能看到的有："
    list_nodes "/dev/ttyUSB* /dev/ttyACM* /dev/ttyAMA* /dev/ttyS*"
    if [ "$BOARD" = radxa ]; then
        prompt "舵机串口" "/dev/ttyS2"
    else
        prompt "舵机串口" "/dev/ttyUSB0"
    fi
    BUS_PORT=$REPLY
}

choose_imu() {
    echo
    echo "机身 IMU："
    echo "  1) 和舵机共用上面这条串口（imu_to_dxl）"
    echo "  2) 单独的 I2C（LSM6DSV16X，常见地址 0x6a / 0x6b）"
    prompt "编号" "1"
    if [ "$REPLY" = 2 ]; then
        IMU=i2c
        echo "I2C 总线："
        list_nodes "/dev/i2c-*"
        if [ "$BOARD" = radxa ]; then
            prompt "I2C 设备" "/dev/i2c-3"
        else
            prompt "I2C 设备" "/dev/i2c-1"
        fi
        I2C_DEV=$REPLY
        prompt "I2C 地址，0 表示 0x6a 和 0x6b 都探测" "0"
        I2C_ADDR=$REPLY
    else
        IMU=dxl
        I2C_DEV=""
        I2C_ADDR=0
    fi
}

choose_button() {
    echo
    WANT_BUTTON=0
    GPIO_CHIP=""
    GPIO_LINE=""
    if yes_no "开机前 5 秒按键进入配网热点 Microduck" y; then
        WANT_BUTTON=1
        echo "按键接在哪条 GPIO。Radxa ZERO 3W 排针 7 是 gpiochip3 的第 20 线。"
        if command -v gpiodetect >/dev/null 2>&1; then
            gpiodetect || true
        fi
        if [ "$BOARD" = radxa ]; then
            prompt "GPIO 芯片（gpiodetect 第一列）" "gpiochip3"
            GPIO_CHIP=$REPLY
            prompt "线号" "20"
            GPIO_LINE=$REPLY
        else
            prompt "GPIO 芯片（gpiodetect 第一列）" "gpiochip0"
            GPIO_CHIP=$REPLY
            prompt "线号" "0"
            GPIO_LINE=$REPLY
        fi
    fi
    echo
    echo "Wi-Fi 网卡："
    if command -v nmcli >/dev/null 2>&1; then
        nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | grep ':wifi' || true
    fi
    prompt "Wi-Fi 网卡名" "wlan0"
    WLAN=$REPLY
}

write_robotd_toml() {
    if ! command -v python3 >/dev/null 2>&1; then
        warn "没有 python3，没改 $CONFIG。先安装 python3 再跑一次。"
        return 0
    fi
    if [ ! -f "$DEPLOY/robotd.toml" ]; then
        warn "本地没有 $DEPLOY/robotd.toml，不写 /etc/robot/robotd.toml"
        return 0
    fi
    mkdir -p /etc/robot
    if [ -f "$CONFIG" ]; then
        if ! yes_no "$CONFIG 已存在，用这次选择覆盖串口和 IMU" n; then
            say "保留已有的 $CONFIG"
            return 0
        fi
    fi
    say "写入 $CONFIG"
    cp "$DEPLOY/robotd.toml" "$CONFIG"
    python3 - "$CONFIG" "$BUS_PORT" "$IMU" "$I2C_DEV" "$I2C_ADDR" <<'PY'
import re, sys
path, port, imu, i2c_dev, i2c_addr = sys.argv[1:]
text = open(path, encoding="utf-8").read()
new, n = re.subn(r'(?m)^port = ".*"$', 'port = "%s"' % port, text, count=1)
if n != 1:
    sys.exit("robotd.toml 里没有 port = 这一行")
text = new
if imu == "i2c":
    pairs = [
        ('# imu = "dxl"', 'imu = "i2c"'),
        ('# i2c = "/dev/i2c-3"', 'i2c = "%s"' % i2c_dev),
        ('# i2c_addr = 0', 'i2c_addr = %s' % i2c_addr),
        ('# imu_mount = "board"', 'imu_mount = "board"'),
    ]
    for old, repl in pairs:
        if old not in text:
            sys.exit("robotd.toml 里找不到：%s" % old)
        text = text.replace(old, repl, 1)
open(path, "w", encoding="utf-8").write(text)
PY
    chmod 644 "$CONFIG"
}

free_motor_port() {
    tty=$(basename "$BUS_PORT")
    unit="serial-getty@${tty}.service"
    if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
        say "屏蔽 $unit，避免登录进程把舵机回包读走"
        systemctl disable --now "$unit" >/dev/null 2>&1 || true
        systemctl mask "$unit" >/dev/null 2>&1 || warn "没能屏蔽 $unit"
    fi
    if [ -f /boot/armbianEnv.txt ] && grep -Eq '^console=(both|serial)$' /boot/armbianEnv.txt; then
        say "内核控制台改到显示器，不再占用舵机串口"
        sed -i 's/^console=both$/console=display/' /boot/armbianEnv.txt
        sed -i 's/^console=serial$/console=display/' /boot/armbianEnv.txt
        NEED_REBOOT=1
    fi
}

armbian_word() {
    # $1 word to ensure on the overlays= line
    env=/boot/armbianEnv.txt
    if ! grep -Eq '^overlays=' "$env"; then
        echo "overlays=$1" >> "$env"
    elif ! grep -E '^overlays=' "$env" | grep -qw "$1"; then
        sed -i "s/^overlays=\(.*\)\$/overlays=\1 $1/" "$env"
    fi
    NEED_REBOOT=1
}

radxa_overlays() {
    env=/boot/armbianEnv.txt
    if [ ! -f "$env" ]; then
        warn "没有 $env，跳过设备树。通用档不需要它；Radxa 的 Armbian 镜像才有这个文件。"
        return 0
    fi
    if ! yes_no "写入 Radxa 设备树（uart2-m0，以及本地的音频 I2C overlay）" y; then
        say "跳过设备树"
        return 0
    fi
    say "修正 overlay 前缀并启用 uart2-m0"
    if grep -Eq '^overlay_prefix=rk35xx$' "$env"; then
        sed -i 's/^overlay_prefix=rk35xx$/overlay_prefix=rk3568/' "$env"
    elif ! grep -Eq '^overlay_prefix=' "$env"; then
        echo 'overlay_prefix=rk3568' >> "$env"
    fi
    armbian_word uart2-m0

    dtbo_dir=$(find /boot -maxdepth 3 -type d -path '*/rockchip/overlay' 2>/dev/null | head -1)
    if [ -z "$dtbo_dir" ]; then
        warn "没有找到 /boot 下的 rockchip/overlay，音频设备树没放上去"
        return 0
    fi
    if ! command -v dtc >/dev/null 2>&1; then
        warn "没有 dtc，音频设备树没编译。可以稍后 apt-get install device-tree-compiler 再跑一次本脚本"
        return 0
    fi
    for name in i2c3-pihat aic3104-i2c3; do
        src="$DEPLOY/audio/${name}.dts"
        if [ ! -f "$src" ]; then
            warn "本地没有 $src"
            continue
        fi
        say "编译并安装 $name"
        dtc -@ -I dts -O dtb -o "$dtbo_dir/rk3568-${name}.dtbo" "$src"
        armbian_word "$name"
    done

    cam=radxa-zero3-rpi-camera-v2
    if [ -f "$dtbo_dir/${cam}.dtbo" ] && yes_no "启用头部摄像头 overlay（$cam）" y; then
        cp "$dtbo_dir/${cam}.dtbo" "$dtbo_dir/rk3568-${cam}.dtbo"
        armbian_word "$cam"
    fi
}

install_binaries() {
    src=""
    for dir in \
        "$ROOT/target/aarch64-unknown-linux-gnu/release" \
        "$ROOT/target/release"
    do
        if [ -x "$dir/robotd" ]; then
            src=$dir
            break
        fi
    done
    mkdir -p "$BIN_DST"
    if [ -z "$src" ]; then
        warn "这份目录里没有编好的 aarch64 程序（robotd）。服务文件会装上，但开机拉不起来。"
        warn "在电脑上编好后，把程序放到 $BIN_DST ，或放到上面的 target 目录再跑一次本脚本。"
        return 0
    fi
    say "从 $src 安装程序到 $BIN_DST"
    for name in robotd configd btd mediad padd tofd updaterd robotctl sounds; do
        if [ -f "$src/$name" ]; then
            install -m 755 "$src/$name" "$BIN_DST/$name"
        fi
    done
}

install_units() {
    if ! getent group robot >/dev/null 2>&1; then
        say "建立 robot 组"
        groupadd --system robot || true
    fi
    installed=""
    for pair in \
        "robotd/systemd/robotd.service:robotd" \
        "configd/systemd/configd.service:configd" \
        "btd/systemd/btd.service:btd" \
        "mediad/systemd/mediad.service:mediad" \
        "padd/systemd/padd.service:padd" \
        "tof/systemd/tofd.service:tofd" \
        "updater/systemd/updaterd.service:updaterd"
    do
        rel=${pair%%:*}
        bin=${pair#*:}
        unit_src="$ROOT/$rel"
        unit_name=$(basename "$rel")
        if [ ! -f "$unit_src" ]; then
            continue
        fi
        say "安装 $unit_name"
        install -m 644 "$unit_src" "/etc/systemd/system/$unit_name"
        if [ -x "$BIN_DST/$bin" ]; then
            systemctl enable "$unit_name" >/dev/null 2>&1 || warn "没能 enable $unit_name"
            installed="$installed $unit_name"
        else
            warn "$unit_name 已放到 /etc/systemd/system，但没有 $BIN_DST/$bin，所以没有设成开机自启"
        fi
    done
    systemctl daemon-reload || true
    if [ -n "$installed" ]; then
        say "已设为开机自启:$installed"
    fi
}

install_button() {
    if [ "$WANT_BUTTON" != 1 ]; then
        say "不安装配网键"
        return 0
    fi
    if [ ! -f "$SCRIPTS/install-wifi-provision.sh" ]; then
        warn "没有 install-wifi-provision.sh"
        return 0
    fi
    cat > /etc/wifi-provision.env <<EOF
WIFI_PROVISION_GPIO_CHIP=$GPIO_CHIP
WIFI_PROVISION_GPIO_LINE=$GPIO_LINE
WIFI_PROVISION_WLAN=$WLAN
EOF
    chmod 644 /etc/wifi-provision.env
    sh "$SCRIPTS/install-wifi-provision.sh" || warn "配网键安装没有完成"
}

echo "本地固件目录：$ROOT"
echo "不会从网上拉任何文件。"
choose_board
choose_port
choose_imu
choose_button

echo
echo "将要写入："
echo "  舵机串口  $BUS_PORT"
echo "  IMU       $IMU"
if [ "$IMU" = i2c ]; then
    echo "  I2C       $I2C_DEV  地址 $I2C_ADDR"
fi
if [ "$WANT_BUTTON" = 1 ]; then
    echo "  配网键    $GPIO_CHIP 线 $GPIO_LINE ，网卡 $WLAN"
else
    echo "  配网键    不装"
fi
if ! yes_no "按上面这些写进系统" y; then
    echo "已取消，没有改系统。"
    exit 0
fi

write_robotd_toml
free_motor_port
if [ "$BOARD" = radxa ]; then
    radxa_overlays
else
    say "通用 Ubuntu：不改设备树"
fi
install_binaries
install_units
install_button

echo
echo "配置已经落到板上："
echo "  $CONFIG"
echo "  /etc/systemd/system/ 里的服务，能启动的已 enable"
echo "  程序目录 $BIN_DST"
if [ "$NEED_REBOOT" = 1 ]; then
    echo "设备树或内核控制台改过，需要重启后才生效： sudo reboot"
fi
