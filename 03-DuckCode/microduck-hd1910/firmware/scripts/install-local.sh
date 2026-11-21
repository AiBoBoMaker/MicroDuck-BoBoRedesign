#!/bin/sh
# Install THIS firmware tree onto the board it is copied to. Nothing is downloaded.
#
# On the board, after the tree is at /opt/microduck/firmware:
#
#   sudo sh /opt/microduck/firmware/scripts/install-local.sh
#
# It asks which board, then the servo port, the IMU and the Wi-Fi provision
# button, and writes those choices into /etc/robot/robotd.toml.
#
# Radxa ZERO 3W: uart2-m0 + deploy/audio aic3104 I2C overlays.
# Orange Pi Zero 2W: free UART0 (pins 8/10) from serial console, apb2-300m
# for Feetech 1 Mbps, aic3104-h616 audio + mixer. Do not load
# sun50i-h616-disable-uart0.
#
# Also installs ONNX Runtime 1.28.0 so policies can load (vendor tarball or
# GitHub download). Service units are installed and enabled.

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
BINS_INSTALLED=0
ONNX_VERSION="${ONNX_VERSION:-1.28.0}"
ONNX_LIB_DIR=/usr/local/lib
ORT_INSTALLED=0

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
    echo "  2) Orange Pi Zero 2W（舵机 /dev/ttyS0＝排针 8/10，会改 UART/音频设备树）"
    echo "  3) 通用 Ubuntu（不改设备树，串口和 IMU 由你填）"
    prompt "编号" "1"
    case "$REPLY" in
        2) BOARD=orangepi ;;
        3) BOARD=ubuntu ;;
        *) BOARD=radxa ;;
    esac
}

choose_port() {
    echo
    echo "舵机串口。当前系统里能看到的有："
    list_nodes "/dev/ttyUSB* /dev/ttyACM* /dev/ttyAMA* /dev/ttyS*"
    if [ "$BOARD" = radxa ]; then
        prompt "舵机串口" "/dev/ttyS2"
    elif [ "$BOARD" = orangepi ]; then
        echo "Orange Pi Zero 2W：排针 8（TX）/10（RX）是 UART0 → /dev/ttyS0。"
        echo "不要选 ttyS5；也不要加载 sun50i-h616-disable-uart0。"
        prompt "舵机串口" "/dev/ttyS0"
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
    if [ "$BOARD" = orangepi ] || [ "$BOARD" = radxa ]; then
        prompt "编号" "2"
    else
        prompt "编号" "1"
    fi
    if [ "$REPLY" = 2 ]; then
        IMU=i2c
        echo "I2C 总线："
        list_nodes "/dev/i2c-*"
        if [ "$BOARD" = radxa ] || [ "$BOARD" = orangepi ]; then
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
            # Orange Pi Zero 2W 排针 7 = PI13 = gpiochip1 line 269
            prompt "GPIO 芯片（gpiodetect 第一列）" "gpiochip1"
            GPIO_CHIP=$REPLY
            prompt "线号" "269"
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
    if [ -f /boot/orangepiEnv.txt ]; then
        if grep -Eq '^console=(both|serial)$' /boot/orangepiEnv.txt; then
            say "orangepiEnv：console=display，不再把 UART0 当调试口"
            sed -i 's/^console=both$/console=display/' /boot/orangepiEnv.txt
            sed -i 's/^console=serial$/console=display/' /boot/orangepiEnv.txt
            NEED_REBOOT=1
        elif ! grep -Eq '^console=' /boot/orangepiEnv.txt; then
            echo 'console=display' >> /boot/orangepiEnv.txt
            NEED_REBOOT=1
        fi
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
    install_aic3104_mixer
}

install_aic3104_mixer() {
    src="$DEPLOY/audio/aic3104-init.sh"
    if [ ! -f "$src" ]; then
        warn "没有 $src，跳过 mixer 开机脚本"
        return 0
    fi
    say "安装 aic3104-init（开机打开喇叭通路）"
    install -m 755 "$src" /usr/local/bin/aic3104-init.sh
    cat > /etc/systemd/system/aic3104-init.service <<'UNIT'
[Unit]
Description=TLV320AIC3104 mixer init
After=systemd-modules-load.service sound.target
Before=robotd.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/aic3104-init.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload || true
    systemctl enable aic3104-init.service >/dev/null 2>&1 || true
}

orangepi_user_overlay_word() {
    env=/boot/orangepiEnv.txt
    if [ ! -f "$env" ]; then
        warn "没有 $env，跳过 user_overlays=$1"
        return 0
    fi
    if ! grep -Eq '^user_overlays=' "$env"; then
        echo "user_overlays=$1" >> "$env"
    elif ! grep -E '^user_overlays=' "$env" | grep -qw "$1"; then
        sed -i "s/^user_overlays=\(.*\)\$/user_overlays=\1 $1/" "$env"
    fi
    NEED_REBOOT=1
}

orangepi_strip_uart0_console() {
    if [ ! -f /boot/boot.cmd ]; then
        warn "没有 /boot/boot.cmd，无法从内核参数里去掉 ttyS0"
        return 0
    fi
    if grep -q 'console=ttyS0,115200 console=tty1' /boot/boot.cmd; then
        say "从 boot.cmd 的 display 分支去掉 console=ttyS0（保留 tty1 / ttyGS0）"
        [ -f /boot/boot.cmd.bak-r18 ] || cp /boot/boot.cmd /boot/boot.cmd.bak-r18
        if [ -f /boot/boot.scr ] && [ ! -f /boot/boot.scr.bak-r18 ]; then
            cp /boot/boot.scr /boot/boot.scr.bak-r18
        fi
        sed -i 's/setenv consoleargs "console=ttyS0,115200 console=tty1"/setenv consoleargs "console=tty1"/' /boot/boot.cmd
        if ! command -v mkimage >/dev/null 2>&1; then
            say "安装 u-boot-tools（mkimage）以重写 boot.scr"
            apt-get update -qq || true
            apt-get install -y -qq u-boot-tools || warn "没能安装 u-boot-tools"
        fi
        if command -v mkimage >/dev/null 2>&1; then
            mkimage -C none -A arm64 -T script -d /boot/boot.cmd /boot/boot.scr >/dev/null \
                || warn "mkimage 写 boot.scr 失败"
            NEED_REBOOT=1
        else
            warn "没有 mkimage，boot.cmd 已改但 boot.scr 未更新"
        fi
    fi
    if [ -f /boot/orangepiEnv.txt ]; then
        if grep -Eq '^extraargs=.*console=ttyS0' /boot/orangepiEnv.txt; then
            say "从 orangepiEnv extraargs 去掉 console=ttyS0"
            sed -i 's/ *console=ttyS0[^ ]*//g' /boot/orangepiEnv.txt
            NEED_REBOOT=1
        fi
        if ! grep -Eq '^extraargs=.*console=ttyGS0' /boot/orangepiEnv.txt; then
            if grep -Eq '^extraargs=' /boot/orangepiEnv.txt; then
                sed -i 's/^extraargs=\(.*\)$/extraargs=\1 console=ttyGS0,115200/' /boot/orangepiEnv.txt
            else
                echo 'extraargs=console=ttyGS0,115200' >> /boot/orangepiEnv.txt
            fi
            NEED_REBOOT=1
        fi
    fi
}

orangepi_compile_user_overlay() {
    src=$1
    name=$2
    if [ ! -f "$src" ]; then
        warn "本地没有 $src"
        return 0
    fi
    if ! command -v dtc >/dev/null 2>&1; then
        say "安装 device-tree-compiler"
        apt-get update -qq || true
        apt-get install -y -qq device-tree-compiler || {
            warn "没有 dtc，跳过 $name"
            return 0
        }
    fi
    mkdir -p /boot/overlay-user
    say "编译并安装 user overlay $name"
    if ! dtc -@ -I dts -O dtb -o "/boot/overlay-user/${name}.dtbo" "$src"; then
        warn "dtc 编译 $name 失败"
        return 0
    fi
    cp "$src" "/boot/overlay-user/${name}.dts"
    orangepi_user_overlay_word "$name"
}

orangepi_overlays() {
    env=/boot/orangepiEnv.txt
    if [ ! -f "$env" ]; then
        warn "没有 $env，这不像 Orange Pi 官方镜像；跳过 UART/音频设备树"
        return 0
    fi
    if ! yes_no "写入 Orange Pi 设备树（UART0 去控制台、apb2-300m、aic3104 音频）" y; then
        say "跳过设备树"
        return 0
    fi
    orangepi_strip_uart0_console
    if grep -E '^(overlays|user_overlays)=' "$env" | grep -qw 'sun50i-h616-disable-uart0'; then
        say "从 overlays 去掉 sun50i-h616-disable-uart0（舵机口需要 UART0）"
        sed -i 's/ *sun50i-h616-disable-uart0//g' "$env"
        NEED_REBOOT=1
    fi
    orangepi_compile_user_overlay \
        "$DEPLOY/overlays/orangepi-h616-apb2-300m.dts" apb2-300m
    orangepi_compile_user_overlay \
        "$DEPLOY/audio/orangepi-h616-aic3104.dts" aic3104-h616
    if ! command -v aplay >/dev/null 2>&1; then
        say "安装 alsa-utils（aplay/amixer）"
        apt-get update -qq || true
        apt-get install -y -qq alsa-utils || warn "alsa-utils 没装上"
    fi
    install_aic3104_mixer
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
    for name in robotd configd btd mediad padd tofd updaterd robotctl sounds pet-detect pet-features; do
        if [ -f "$src/$name" ]; then
            install -m 755 "$src/$name" "$BIN_DST/$name"
            BINS_INSTALLED=1
        fi
    done
}

install_cli_path() {
    # robotctl lives under /opt/.../bin; operators type `robotctl` after pairing docs.
    mkdir -p /usr/local/bin
    for name in robotctl robotd; do
        if [ -x "$BIN_DST/$name" ]; then
            ln -sfn "$BIN_DST/$name" "/usr/local/bin/$name"
            say "命令链接 /usr/local/bin/$name → $BIN_DST/$name"
        fi
    done
}

install_sysusers() {
    if ! getent group robot >/dev/null 2>&1; then
        say "建立 robot 组"
        groupadd --system robot || true
    fi
    for conf in \
        "updater/systemd/sysusers.d/robot.conf" \
        "btd/systemd/sysusers.d/btd.conf" \
        "mediad/systemd/sysusers.d/mediad.conf" \
        "padd/systemd/sysusers.d/padd.conf" \
        "tof/systemd/sysusers.d/tofd.conf"
    do
        src="$ROOT/$conf"
        if [ ! -f "$src" ]; then
            continue
        fi
        dest="/usr/lib/sysusers.d/$(basename "$conf")"
        say "安装 sysusers $(basename "$conf")"
        install -m 644 "$src" "$dest"
    done
    if command -v systemd-sysusers >/dev/null 2>&1; then
        systemd-sysusers || warn "systemd-sysusers 未完全成功"
    else
        warn "没有 systemd-sysusers；padd/btd 等用户可能缺失"
    fi
}

install_gamesir_bridge() {
    # padd ignores the raw GameSir-Nova 2 Lite node; it drives the uinput Xbox clone.
    bridge_bin=""
    for candidate in \
        "$ROOT/gamepad-r7/gamesir-xboxd" \
        "$ROOT/packaging/gamepad-r7/gamesir-xboxd"
    do
        if [ -f "$candidate" ]; then
            bridge_bin=$candidate
            break
        fi
    done
    unit_src=""
    for candidate in \
        "$ROOT/gamepad-r7/gamesir-xboxd.service" \
        "$ROOT/packaging/gamepad-r7/gamesir-xboxd.service"
    do
        if [ -f "$candidate" ]; then
            unit_src=$candidate
            break
        fi
    done
    rules_src=""
    for candidate in \
        "$ROOT/gamepad-r7/70-gamesir-xbox-bridge.rules" \
        "$ROOT/packaging/gamepad-r7/70-gamesir-xbox-bridge.rules"
    do
        if [ -f "$candidate" ]; then
            rules_src=$candidate
            break
        fi
    done
    if [ -z "$bridge_bin" ] || [ -z "$unit_src" ]; then
        warn "包内没有 gamesir-xboxd，跳过 GameSir→Xbox 输入桥（盖世小鸡实体键将无法被 padd 识别）"
        return 0
    fi
    say "安装 GameSir Xbox 输入桥"
    if ! modprobe uinput 2>/dev/null; then
        warn "modprobe uinput 失败；桥接需要 uinput"
    fi
    mkdir -p /etc/modules-load.d
    echo uinput > /etc/modules-load.d/gamesir-xbox.conf
    chmod 644 /etc/modules-load.d/gamesir-xbox.conf
    install -m 755 "$bridge_bin" /usr/local/sbin/gamesir-xboxd
    if [ -f "$ROOT/gamepad-r7/gamesir-xbox-status" ]; then
        install -m 755 "$ROOT/gamepad-r7/gamesir-xbox-status" /usr/local/sbin/gamesir-xbox-status
    elif [ -f "$ROOT/packaging/gamepad-r7/gamesir-xbox-status" ]; then
        install -m 755 "$ROOT/packaging/gamepad-r7/gamesir-xbox-status" /usr/local/sbin/gamesir-xbox-status
    fi
    install -m 644 "$unit_src" /etc/systemd/system/gamesir-xboxd.service
    # R18 does not use the R17 startup_gate ExecStart wrapper.
    rm -f /etc/systemd/system/gamesir-xboxd.service.d/zzzz-r17-ready.conf
    if [ -n "$rules_src" ]; then
        install -m 644 "$rules_src" /etc/udev/rules.d/70-gamesir-xbox-bridge.rules
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true
    fi
    systemctl daemon-reload || true
    systemctl enable gamesir-xboxd.service >/dev/null 2>&1 || warn "没能 enable gamesir-xboxd"
    systemctl restart gamesir-xboxd.service 2>/dev/null || systemctl start gamesir-xboxd.service 2>/dev/null || \
        warn "gamesir-xboxd 未能立即启动（可在手柄连上后再 systemctl start）"
}

install_pad_pairing_support() {
    # aic8800 (Radxa / Orange Pi Wi-Fi): a new bond fails while btd advertises.
    # Marker makes `robotctl pad pair` stop btd for the pairing window. Do not
    # force Privacy=device here — that breaks reconnect on boards that only need the pause.
    case "$BOARD" in
        orangepi|radxa) ;;
        *)
            say "通用板：不写 btd 配对暂停标记（需要时可 sudo touch /var/lib/robot/weird-ble）"
            return 0
            ;;
    esac
    marker=/var/lib/robot/weird-ble
    mkdir -p /var/lib/robot
    if [ -f "$marker" ]; then
        say "已有 $marker（pad pair 会暂停 btd）"
    else
        cat > "$marker" <<'EOF'
# R18: pause btd while a gamepad bonds (aic8800).
# robotctl pad pair stops btd, power-cycles the adapter, then starts btd again.
EOF
        chmod 644 "$marker"
        say "写入 $marker，使 robotctl pad pair 配对时暂停 btd"
    fi
    # Classic pads through kernel HID, not bluetoothd userspace HID.
    bt_input=/etc/bluetooth/input.conf
    if [ -f "$bt_input" ] || mkdir -p /etc/bluetooth 2>/dev/null; then
        if [ ! -f "$bt_input" ]; then
            printf '[General]\nUserspaceHID=false\n' > "$bt_input"
            say "写入 $bt_input UserspaceHID=false"
            NEED_REBOOT=1
        elif grep -Eq '^[[:space:]]*UserspaceHID[[:space:]]*=[[:space:]]*false' "$bt_input"; then
            say "UserspaceHID 已是 false"
        else
            if grep -Eq '^[[:space:]]*#?[[:space:]]*UserspaceHID[[:space:]]*=' "$bt_input"; then
                sed -i -E 's|^[[:space:]]*#?[[:space:]]*UserspaceHID[[:space:]]*=.*|UserspaceHID=false|' "$bt_input"
            elif grep -q '^\[General\]' "$bt_input"; then
                sed -i '/^\[General\]/a UserspaceHID=false' "$bt_input"
            else
                printf '\n[General]\nUserspaceHID=false\n' >> "$bt_input"
            fi
            say "设置 UserspaceHID=false（经典手柄走内核 HID）"
            NEED_REBOOT=1
        fi
    fi
}

install_units() {
    install_sysusers
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

ort_ldconfig() {
    if command -v ldconfig >/dev/null 2>&1; then
        ldconfig
    elif [ -x /usr/sbin/ldconfig ]; then
        /usr/sbin/ldconfig
    else
        warn "没有 ldconfig；已写 ORT_DYLIB_PATH 给 robotd"
    fi
}

ort_robotd_dropin() {
    so="${ONNX_LIB_DIR}/libonnxruntime.so.${ONNX_VERSION}"
    if [ ! -e "$so" ]; then
        so="${ONNX_LIB_DIR}/libonnxruntime.so"
    fi
    if [ ! -e "$so" ]; then
        return 0
    fi
    mkdir -p /etc/systemd/system/robotd.service.d
    cat > /etc/systemd/system/robotd.service.d/10-onnxruntime.conf <<EOF
[Service]
Environment=ORT_DYLIB_PATH=$so
EOF
    systemctl daemon-reload || true
}

install_onnxruntime_from_dir() {
    src=$1
    found=$(find "$src" -name 'libonnxruntime.so*' -type f | head -1)
    if [ -z "$found" ]; then
        return 1
    fi
    mkdir -p "$ONNX_LIB_DIR"
    install -m 0644 "$found" "${ONNX_LIB_DIR}/$(basename "$found")"
    ln -sfn "$(basename "$found")" "${ONNX_LIB_DIR}/libonnxruntime.so"
    shared=$(find "$src" -name 'libonnxruntime_providers_shared.so*' -type f | head -1)
    if [ -n "$shared" ]; then
        install -m 0644 "$shared" "${ONNX_LIB_DIR}/$(basename "$shared")"
        case "$(basename "$shared")" in
            libonnxruntime_providers_shared.so) ;;
            *) ln -sfn "$(basename "$shared")" "${ONNX_LIB_DIR}/libonnxruntime_providers_shared.so" ;;
        esac
    fi
    ort_ldconfig
    ort_robotd_dropin
    ORT_INSTALLED=1
    say "已安装 ONNX Runtime → ${ONNX_LIB_DIR}/$(basename "$found")"
    return 0
}

install_onnxruntime() {
    # robotd loads policies via ort. Without libonnxruntime, custom_only boards
    # silently disable policy after walk validation fails.
    existing=""
    if [ -e "${ONNX_LIB_DIR}/libonnxruntime.so" ]; then
        resolved=$(readlink -f "${ONNX_LIB_DIR}/libonnxruntime.so" 2>/dev/null || true)
        case "$resolved" in
            */libonnxruntime.so.*) existing=${resolved##*/libonnxruntime.so.} ;;
            *) existing=unknown ;;
        esac
    fi
    if [ "$existing" = "$ONNX_VERSION" ]; then
        say "ONNX Runtime ${ONNX_VERSION} 已在 ${ONNX_LIB_DIR}"
        ort_robotd_dropin
        ORT_INSTALLED=1
        return 0
    fi
    if [ -n "$existing" ]; then
        say "替换 ONNX Runtime ${existing} → ${ONNX_VERSION}"
    else
        say "安装 ONNX Runtime ${ONNX_VERSION}（策略推理需要）"
    fi

    for dir in \
        "$ROOT/packaging/onnxruntime" \
        "$ROOT/onnxruntime" \
        "$ROOT/vendor/onnxruntime-linux-aarch64-${ONNX_VERSION}"
    do
        if [ -d "$dir" ] && install_onnxruntime_from_dir "$dir"; then
            return 0
        fi
    done

    for tgz in \
        "$ROOT/vendor/onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz" \
        "$ROOT/onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz" \
        "/tmp/onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz"
    do
        if [ -f "$tgz" ]; then
            tmp=$(mktemp -d)
            if tar -xzf "$tgz" -C "$tmp" && install_onnxruntime_from_dir "$tmp"; then
                rm -rf "$tmp"
                return 0
            fi
            rm -rf "$tmp"
        fi
    done

    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        warn "没有 curl/wget，无法下载 ONNX Runtime。把 aarch64 ${ONNX_VERSION} 的 .tgz 放到 $ROOT/vendor/ 后再跑一次。"
        return 0
    fi
    url="https://github.com/microsoft/onnxruntime/releases/download/v${ONNX_VERSION}/onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz"
    tmp=$(mktemp -d)
    say "下载 $url"
    dl_ok=0
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "${tmp}/ort.tgz" "$url" && dl_ok=1
    else
        wget -q -O "${tmp}/ort.tgz" "$url" && dl_ok=1
    fi
    if [ "$dl_ok" != 1 ]; then
        rm -rf "$tmp"
        warn "下载 ONNX Runtime 失败（常见于访问不了 GitHub）。"
        warn "在电脑上下载后 scp 到 /tmp/onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz，再执行本安装。"
        return 0
    fi
    if tar -xzf "${tmp}/ort.tgz" -C "$tmp" && install_onnxruntime_from_dir "$tmp"; then
        rm -rf "$tmp"
        return 0
    fi
    rm -rf "$tmp"
    warn "ONNX Runtime 解压/安装失败"
}

apply_policy_paths_if_models_present() {
    walk=/opt/robot/feetech-ft5-r5/models/1cbf8730eadd75a5704332c9f3c10f60/policy.onnx
    if [ ! -f "$walk" ]; then
        say "未发现 $walk — 策略路径不改。装好模型后可对照 config/robotd-selftrained.toml"
        return 0
    fi
    if [ ! -f "$CONFIG" ]; then
        return 0
    fi
    if ! yes_no "已有 HD1910 模型目录，把 /etc/robot/robotd.toml 的 [policy] 指过去并 enabled=true" y; then
        return 0
    fi
    say "按自训练合同写入 [policy] 路径"
    python3 - "$CONFIG" <<'PY' || warn "改 [policy] 失败，请手工对照 config/robotd-selftrained.toml"
from pathlib import Path
import re, sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
pairs = {
    "custom_only": "true",
    "enabled": "true",
    "mode": '"walk"',
    "walk": '"/opt/robot/feetech-ft5-r5/models/1cbf8730eadd75a5704332c9f3c10f60/policy.onnx"',
    "sitstand": '"/opt/robot/feetech-ft5-r5/models/1c94934c6421ec72ed48079cea749668/policy.onnx"',
    "stand": '"none"',
    "ground_pick": '"/opt/robot/feetech-ft5-r5/models/b14e3a8b56ddbb8d2d831e727774a168/policy.onnx"',
    "kick_left": '"/opt/robot/feetech-ft5-r5/models/ee0376c927044cdece056ba1d3e6eac7/policy.onnx"',
    "kick_right": '"/opt/robot/feetech-ft5-r5/models/67ad09d82f4865d222a7ae06f250cf9f/policy.onnx"',
    "roulade": '"/opt/robot/feetech-ft5-r5/models/59e15d7b04d0c40e9b11b8a70bdecae6/policy.onnx"',
}
for key, value in pairs.items():
    pat = re.compile(r"(?m)^(\s*)" + re.escape(key) + r"\s*=\s*.*$")
    if pat.search(text):
        text = pat.sub(r"\1%s = %s" % (key, value), text, count=1)
    elif re.search(r"(?m)^\[policy\]", text):
        text = re.sub(r"(?m)^\[policy\]\s*$", "[policy]\n%s = %s" % (key, value), text, count=1)
path.write_text(text, encoding="utf-8")
print("policy paths updated")
PY
}

echo "本地固件目录：$ROOT"
echo "除 ONNX Runtime（策略推理库）外，不从网上拉程序本体。"
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
echo "  ONNX      ${ONNX_VERSION} → ${ONNX_LIB_DIR}"
if ! yes_no "按上面这些写进系统" y; then
    echo "已取消，没有改系统。"
    exit 0
fi

write_robotd_toml
free_motor_port
case "$BOARD" in
    radxa)
        radxa_overlays
        ;;
    orangepi)
        orangepi_overlays
        ;;
    *)
        say "通用 Ubuntu：不改设备树"
        ;;
esac
install_binaries
install_cli_path
install_units
install_gamesir_bridge
install_pad_pairing_support
install_onnxruntime
apply_policy_paths_if_models_present
install_button

echo
echo "配置已经落到板上："
echo "  $CONFIG"
echo "  /etc/systemd/system/ 里的服务，能启动的已 enable"
echo "  程序目录 $BIN_DST"
echo "  命令      /usr/local/bin/robotctl （以及 robotd 链接）"
if [ -x /usr/local/sbin/gamesir-xboxd ]; then
    echo "  手柄桥    gamesir-xboxd.service（盖世小鸡 → 虚拟 Xbox）"
fi
if [ -f /var/lib/robot/weird-ble ]; then
    echo "  配对      /var/lib/robot/weird-ble（pad pair 时暂停 btd）"
fi
if [ "$ORT_INSTALLED" = 1 ]; then
    echo "  ONNX Runtime ${ONNX_VERSION} → ${ONNX_LIB_DIR}（robotd drop-in ORT_DYLIB_PATH）"
else
    echo "  ONNX Runtime 未装上 — 走路策略无法推理。见上方警告。"
fi
if [ "$BOARD" = orangepi ]; then
    echo "  Orange Pi：UART0=/dev/ttyS0，user_overlays 含 apb2-300m aic3104-h616"
fi
echo
echo "手柄配对（盖世小鸡 Nova 2 Lite：Home+X 后 Home+截图快闪）："
echo "  sudo robotctl pad pair"
echo "  sudo robotctl pad status"
if [ "$NEED_REBOOT" = 1 ]; then
    echo "设备树、内核控制台或蓝牙 input.conf 改过，需要重启后才生效： sudo reboot"
fi

