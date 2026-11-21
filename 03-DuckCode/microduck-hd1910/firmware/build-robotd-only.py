#!/usr/bin/env python3
"""Cross-compile only robotd (bobo is linked in). For ducks that already have R18."""
import os
import shutil
import sys
from pathlib import Path

import pack_r18


def main() -> int:
    root = Path(__file__).resolve().parent
    os.chdir(root)
    if str(root).startswith("/mnt/"):
        os.environ["CARGO_TARGET_DIR"] = "/var/tmp/microduck-r18-target"
        print("编译目录：/var/tmp/microduck-r18-target", flush=True)
    if not pack_r18.ensure_toolchain():
        return 1
    if not pack_r18.apply_sysroot():
        return 1
    command = [
        "cargo",
        "zigbuild",
        "--locked",
        "--release",
        "--config",
        "profile.release.package.robotd.codegen-units=1",
        "--target",
        pack_r18.TARGET,
        "-p",
        "robotd",
    ]
    print("编译：robotd（含 bobo 关键词）", flush=True)
    if not pack_r18._run(command, cwd=root):
        return 1
    built = (
        Path(os.environ.get("CARGO_TARGET_DIR", root / "target"))
        / "aarch64-unknown-linux-gnu"
        / "release"
        / "robotd"
    )
    if not built.is_file():
        print(f"没有找到编译产物：{built}", file=sys.stderr)
        return 1
    dest_dir = pack_r18.BIN_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "robotd"
    shutil.copy2(built, dest)
    dest.chmod(0o755)
    print(f"已产出 {dest} （{dest.stat().st_size} 字节）")
    print("装到已有鸭子上：")
    print("  scp robotd user@duck:/tmp/robotd")
    print("  ssh user@duck 'sudo install -m 755 /tmp/robotd /opt/robot/daemon/current/bin/robotd && sudo systemctl restart robotd'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
