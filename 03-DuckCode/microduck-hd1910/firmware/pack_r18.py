#!/usr/bin/env python3
"""Pack the R18 board tree into Microduck-R18.zip."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "Microduck-R18.zip"
BIN_DIR = ROOT / "target" / "aarch64-unknown-linux-gnu" / "release"
BINS = ("robotd", "configd", "btd", "mediad", "padd", "tofd", "updaterd", "robotctl", "sounds")
PATHS = (
    "install-R18.sh",
    "R18-使用方法.md",
    "scripts/install-local.sh",
    "scripts/install-wifi-provision.sh",
    "scripts/wifi-provision-button.py",
    "scripts/systemd/wifi-provision-button.service",
    "deploy/robotd.toml",
    "deploy/updater.toml",
    "deploy/audio/aic3104-i2c3.dts",
    "deploy/audio/i2c3-pihat.dts",
    "deploy/overlays/rk3568-npu-enable.dts",
    "robotd/systemd/robotd.service",
    "configd/systemd/configd.service",
    "btd/systemd/btd.service",
    "mediad/systemd/mediad.service",
    "padd/systemd/padd.service",
    "tof/systemd/tofd.service",
    "updater/systemd/updaterd.service",
)


def main():
    missing = [name for name in PATHS if not (ROOT / name).is_file()]
    if missing:
        print("缺少打包文件：\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    packed_bins = []
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in PATHS:
            archive.write(ROOT / name, name)
        if BIN_DIR.is_dir():
            for name in BINS:
                binary = BIN_DIR / name
                if binary.is_file():
                    archive.write(binary, f"target/aarch64-unknown-linux-gnu/release/{name}")
                    packed_bins.append(name)
    print(f"已写出 {OUTPUT} （{OUTPUT.stat().st_size} 字节）")
    if "robotd" in packed_bins:
        print("包含程序：" + "、".join(packed_bins))
    else:
        print("包内没有 aarch64 robotd。安装脚本可以运行，服务不会开机自启。")
        print("在 Linux 上执行 bash pack-R18.sh 交叉编译后再打包。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
