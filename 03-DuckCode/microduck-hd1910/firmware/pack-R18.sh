#!/usr/bin/env bash
# Cross-compile robotd when the toolchain is present, then write Microduck-R18.zip.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
BIN="$ROOT/target/aarch64-unknown-linux-gnu/release/robotd"
if [[ "${1:-}" != "--no-build" ]]; then
    if command -v cargo-zigbuild >/dev/null 2>&1 && command -v zig >/dev/null 2>&1; then
        cargo zigbuild --locked --release \
            --config profile.release.package.robotd.codegen-units=1 \
            -p robotd --target aarch64-unknown-linux-gnu.2.31
    elif [[ ! -x "$BIN" ]]; then
        echo "未找到 cargo-zigbuild / zig，也没有已编好的 $BIN" >&2
        echo "继续只打包安装文件。鸭子上可以执行安装，但没有 robotd 时服务不会开机自启。" >&2
    fi
fi
python3 "$ROOT/pack_r18.py"
