#!/bin/bash
set -euo pipefail
export PATH="/home/wangjingchu/microduck-main/.build/firmware-tools/lib/python3.12/site-packages/ziglang:/home/wangjingchu/microduck-main/.build/firmware-tools/bin:/root/.cargo/bin:${PATH}"
cd /mnt/f/Microduck-kissqy-261023/Microduck-kissqy-main/microduck-hd1910/firmware
cargo zigbuild --locked --release --config profile.release.package.robotd.codegen-units=1 -p robotd --target aarch64-unknown-linux-gnu.2.31
file target/aarch64-unknown-linux-gnu/release/robotd
