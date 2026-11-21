# R18：拷到 TF 卡并安装（Orange Pi Zero 2W）

本文说明如何把电脑上打好的 `Microduck-R18.zip` 放到鸭子的 TF 卡上，并完成安装。适用于香橙派 Zero 2W + Robot HAT。

## 1. 电脑上先有 zip

在 `firmware` 目录打包（Windows）：

```bat
pack-R18.bat
```

成功后，同目录出现：

```text
k:\MicroDuck-BoBoRedesign\03-DuckCode\microduck-hd1910\firmware\Microduck-R18.zip
```

包内含：全部板端程序、`install-R18.sh`、Orange Pi 的 UART/音频 overlay、ONNX 安装逻辑等。  
**不含** HD1910 的 `policy.onnx`（模型另拷，见文末）。

## 2. 拷到 TF 卡哪里

鸭子开机后，系统根分区就是 TF 卡上的 Linux 根文件系统。推荐放到用户主目录，不要解压到 `/`。

| 方式 | 推荐路径 |
| --- | --- |
| 鸭子已能 SSH（Type-C / Wi-Fi） | `/home/orangepi/Microduck-R18.zip` |
| 把 TF 卡拔到电脑上读 | 打开系统分区，拷到 `home/orangepi/Microduck-R18.zip`（与上面同一位置） |

**不要**解压到 `/` 根目录，也不要覆盖 `/boot` 以外的系统目录。

### 用 scp（推荐）

电脑 PowerShell：

```powershell
scp "k:\MicroDuck-BoBoRedesign\03-DuckCode\microduck-hd1910\firmware\Microduck-R18.zip" orangepi@192.168.1.146:~/
```

把 IP 换成你鸭子的地址。

### 用 TF 读卡器

1. 关机，拔出 TF 卡，插入电脑。
2. 打开 **Linux 根分区**（不是仅 boot 小分区）。
3. 进入 `home/orangepi/`，放入 `Microduck-R18.zip`。
4. 安全弹出，插回鸭子，开机。

## 3. 在鸭子上解压并安装

SSH 登录（用户一般是 `orangepi`）：

```sh
cd ~
ls -lh Microduck-R18.zip

# 解到单独目录
sudo mkdir -p /opt/microduck-r18
sudo python3 -c "import zipfile; zipfile.ZipFile('/home/orangepi/Microduck-R18.zip').extractall('/opt/microduck-r18')"
# 若已装 unzip，也可用：
# sudo unzip -o ~/Microduck-R18.zip -d /opt/microduck-r18

cd /opt/microduck-r18
ls install-R18.sh scripts/install-local.sh

sudo sh install-R18.sh
```

### 安装时怎么选

| 提示 | Orange Pi Zero 2W 建议 |
| --- | --- |
| 板子编号 | **2** |
| 舵机串口 | 回车（默认 `/dev/ttyS0`） |
| IMU | 回车（默认 I2C，`/dev/i2c-3`） |
| 配网键 | 按需；没有按键选 `n` |
| 写设备树 / ONNX | 默认 **y** |

脚本会：腾出 UART0、装 `apb2-300m`（1 Mbps）、装 `aic3104-h616` 音频、装 ONNX Runtime 1.28.0。

若提示改过设备树，执行：

```sh
sudo reboot
```

再用 Type-C / Wi-Fi 重新 SSH（排针串口不再当系统控制台）。

## 4. 重启后自检

```sh
# 内核参数里不应再有 ttyS0
cat /proc/cmdline | tr ' ' '\n' | grep console

# 舵机口波特率底座约 18.75M
sudo apt-get install -y setserial >/dev/null
sudo setserial -ag /dev/ttyS0

# 声卡
aplay -l | grep aic3104

# ONNX
ls -l /usr/local/lib/libonnxruntime.so*
systemctl cat robotd | grep ORT_DYLIB || true

# 服务
systemctl is-enabled robotd
systemctl status robotd --no-pager | head -20
```

## 5. 模型（走路用，不在 R18 zip 里）

把 R17 包或旧机里的模型拷到：

```text
/opt/robot/feetech-ft5-r5/models/<模型ID>/policy.onnx
```

例如 walk：`1cbf8730eadd75a5704332c9f3c10f60`。  
对照 `config/robotd-selftrained.toml` 写好 `/etc/robot/robotd.toml` 的 `[policy]`，或重跑安装并在「已有模型」提示时选 y。

国内若装 ONNX 时 GitHub 下不动，先在电脑下载：

```text
https://github.com/microsoft/onnxruntime/releases/download/v1.28.0/onnxruntime-linux-aarch64-1.28.0.tgz
```

拷到鸭子 `/tmp/onnxruntime-linux-aarch64-1.28.0.tgz` 后再执行 `sudo sh install-R18.sh`。

## 6. 常见路径小结

| 物品 | 位置 |
| --- | --- |
| 安装包 | `/home/orangepi/Microduck-R18.zip` |
| 解压目录 | `/opt/microduck-r18/` |
| 安装入口 | `sudo sh /opt/microduck-r18/install-R18.sh` |
| 程序 | `/opt/robot/daemon/current/bin/` |
| 命令 | `/usr/local/bin/robotctl` |
| 配置 | `/etc/robot/robotd.toml` |
| 舵机口 | `/dev/ttyS0` |
| 音频 | `plughw:aic3104` |
| 手柄桥 | `gamesir-xboxd.service` · `/usr/local/sbin/gamesir-xboxd` |
| 配对标记 | `/var/lib/robot/weird-ble` |
| ONNX | `/usr/local/lib/libonnxruntime.so*` |
| 模型 | `/opt/robot/feetech-ft5-r5/models/` |

## 7. 从已装好的卡做「清洁」克隆镜像（Ubuntu 电脑）

鸭子装通、测过后，若要批量刷卡：关机拔卡 → 插到 **Ubuntu 电脑** 读卡器 → 用仓库脚本清 Wi‑Fi / 标定再打镜像。

脚本：`scripts/make-orangepi-clone-image.sh`（也可从 R18 zip 里拷出）。

```bash
# 可选：压缩更小
sudo apt-get install -y xz-utils zerofree

lsblk   # 确认 TF 是 /dev/sdb 之类，切勿选错系统盘

# 把脚本拷到 Ubuntu 后：
chmod +x make-orangepi-clone-image.sh
sudo bash make-orangepi-clone-image.sh /dev/sdb
```

会生成：`~/Microduck-OPi-R18-clean-YYYYMMDD.img.xz`

**注意：脚本在源卡 rootfs 上就地清理，再 dd。源卡上的 Wi‑Fi / 标定也会被清掉。**

清除内容：NetworkManager Wi‑Fi、舵机标定、`bobo-client-id`、shell 历史、日志、SSH host keys、`machine-id`、ALSA 状态。  
并写入：OPi 配网环境（`/etc/wifi-provision.env`）、自动配网脚本、SSH host key 首启重生单元。  
保留：R18 程序、overlay、ONNX、模型、板级 `robotd.toml` 等。

刷到新卡：

```bash
lsblk
sudo xz -dc ~/Microduck-OPi-R18-clean-*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```

新卡开机后重新配 Wi‑Fi，并重新做舵机标定 / IMU 确认；标定完成后在中控把服务切到 **motion**（会写入 `motion_enabled=true`）。

### 第二次「清卡再上网」踩过的坑（本包已对症）

| 现象 | 原因 | 本包/脚本侧 |
| --- | --- | --- |
| 清掉 Wi‑Fi 后不出热点 | 旧逻辑只认开机 5 秒按键；OPi GPIO 默认还不对；且服务在 NM 起来前就退出 | `wifi-provision-button.py`：无家庭 Wi‑Fi 时自动开热点；先等 `wlan0`；克隆写入 `gpiochip1`/`269` |
| NM `hotspot` 报 802.1X / 超时 | `uwe5622` + NetworkManager SoftAP 不稳 | 优先串口 `nmcli connect` 连 **2.4G**（如 `CU_xxx`，不要 `_5G`）；或 `hostapd` |
| 扫不到周围 Wi‑Fi | 热点失败后驱动卡住 | `sudo reboot` 后再 `nmcli device wifi list`，勿再 `modprobe -r sprdwl_ng` |
| SSH 起不来 | 清了 host keys 未重生，`sshd -t` 失败 | 克隆装 `microduck-regen-ssh-hostkeys.service`；或手动 `sudo ssh-keygen -A && sudo systemctl enable --now ssh` |
| 电脑报 host key 变了 | 密钥已重生 | 电脑上 `ssh-keygen -R <鸭子IP>` |
| 启动卡在 `ttyACM0` | Radxa 默认口 | OPi 安装选板型 2，`port=/dev/ttyS0` |
| 启动卡在「只允许 ttyACM0/ttyS2」 | 旧 `robotd` 白名单 | 本包 `robotd` 已允许 `/dev/ttyS0` |
| 标定完仍 `motion_enabled is false` | R18 切 motion 未写标志（R17 `enable` 会写） | 中控 `service_control.py` 切到 motion 时校验标定并写 `motion_enabled=true` |
| 喇叭变小 | 清了 `asound.state` | 开机 `aic3104-init`；可再 `amixer` + `alsactl store` |

配网命令备忘（串口、2.4G）：

```sh
sudo nmcli radio wifi on
sudo nmcli device wifi rescan
sudo nmcli -f SSID,CHAN,SIGNAL device wifi list
sudo nmcli --wait 60 device wifi connect '你家2.4G-SSID' password '密码' ifname wlan0
```
