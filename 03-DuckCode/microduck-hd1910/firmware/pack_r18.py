#!/usr/bin/env python3
"""Cross-compile the board programs and pack them into Microduck-R18.zip.

The zip is the tree scripts/install-local.sh installs. Every name in BINS is
required: a package that only contains robotd is how a board ended up with one
file in /opt/robot/daemon/current/bin.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "Microduck-R18.zip"
BIN_DIR = ROOT / "target" / "aarch64-unknown-linux-gnu" / "release"
TARGET = "aarch64-unknown-linux-gnu.2.31"
ZIG_VERSION = "0.15.1"
ZIGBUILD_VERSION = "0.23.4"
# The board build already in this tree was made with this pair. A newer Zig
# speaks a different C ABI to cargo-zigbuild and fails halfway through mediad.
# Package names. tof and updater publish different binary names; pet-detect
# publishes both of its bins.
PACKAGES = (
    "robotd",
    "configd",
    "btd",
    "mediad",
    "padd",
    "tof",
    "updater",
    "robotctl",
    "sounds",
    "pet-detect",
)
# What install-local.sh copies into /opt/robot/daemon/current/bin.
# Keep the two lists the same.
BINS = (
    "robotd",
    "configd",
    "btd",
    "mediad",
    "padd",
    "tofd",
    "updaterd",
    "robotctl",
    "sounds",
    "pet-detect",
    "pet-features",
)
PATHS = (
    "install-R18.sh",
    "R18-使用方法.md",
    "R18-TF卡安装.md",
    "scripts/install-local.sh",
    "scripts/make-orangepi-clone-image.sh",
    "scripts/install-wifi-provision.sh",
    "scripts/wifi-provision-button.py",
    "scripts/systemd/wifi-provision-button.service",
    "scripts/cross-sysroot.sh",
    "deploy/robotd.toml",
    "deploy/updater.toml",
    "deploy/audio/aic3104-i2c3.dts",
    "deploy/audio/aic3104-init.sh",
    "deploy/audio/i2c3-pihat.dts",
    "deploy/audio/orangepi-h616-aic3104.dts",
    "deploy/overlays/orangepi-h616-apb2-300m.dts",
    "deploy/overlays/rk3568-npu-enable.dts",
    "config/robotd-selftrained.toml",
    "robotd/systemd/robotd.service",
    "configd/systemd/configd.service",
    "btd/systemd/btd.service",
    "btd/systemd/sysusers.d/btd.conf",
    "mediad/systemd/mediad.service",
    "mediad/systemd/sysusers.d/mediad.conf",
    "padd/systemd/padd.service",
    "padd/systemd/sysusers.d/padd.conf",
    "tof/systemd/tofd.service",
    "tof/systemd/sysusers.d/tofd.conf",
    "updater/systemd/updaterd.service",
    "updater/systemd/sysusers.d/robot.conf",
    # GameSir → virtual Xbox bridge (padd ignores the raw GameSir node).
    "gamepad-r7/gamesir-xboxd",
    "gamepad-r7/gamesir-xboxd.service",
    "gamepad-r7/70-gamesir-xbox-bridge.rules",
    "gamepad-r7/gamesir-xbox-status",
)


def _shell():
    for name in ("bash", "sh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def apply_sysroot():
    """mediad and padd link the board's GStreamer and libudev, not the host's."""
    shell = _shell()
    if shell is None:
        print("完整编译需要 sh 或 bash 来准备 aarch64 sysroot。", file=sys.stderr)
        print("Git Bash 里执行：bash pack-R18.sh", file=sys.stderr)
        return False
    script = ROOT / "scripts" / "cross-sysroot.sh"
    proc = subprocess.run([shell, str(script)], cwd=ROOT, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        sys.stdout.write(proc.stdout)
        print("aarch64 sysroot 没准备好，已停止打包。", file=sys.stderr)
        return False
    # The script prints the exports for a human to read; only those lines are applied.
    for line in proc.stdout.splitlines():
        if not line.startswith("export "):
            if line.strip():
                print(line)
            continue
        key, _, raw = line[len("export "):].partition("=")
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            raw = raw[1:-1]
        match = re.fullmatch(r"\$\{RUSTFLAGS:\+\$RUSTFLAGS \}(.*)", raw)
        if match:
            previous = os.environ.get("RUSTFLAGS", "")
            raw = (previous + " " + match.group(1)).strip() if previous else match.group(1)
        os.environ[key] = raw
        print(f"export {key}={raw}")
    return True


def _prepend_path(directory):
    directory = str(directory)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if directory not in parts:
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")


def _run(command, **kwargs):
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, **kwargs).returncode == 0


def install_packages():
    if shutil.which("pkg-config") and shutil.which("gcc") and shutil.which("xz"):
        return True
    print("WSL 里安装 pkg-config、gcc、xz…", flush=True)
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    if not _run(["apt-get", "update"], env=env):
        return False
    return _run(
        ["apt-get", "install", "-y", "pkg-config", "build-essential", "curl", "xz-utils", "ca-certificates"],
        env=env,
    )


def use_mirrors():
    """crates.io 和 Debian sysroot 走清华源。Rust 1.99.0 清华源还没有，工具链走腾讯云。"""
    os.environ["RUSTUP_DIST_SERVER"] = "https://mirrors.cloud.tencent.com/rustup"
    os.environ["RUSTUP_UPDATE_ROOT"] = "https://mirrors.cloud.tencent.com/rustup/rustup"
    os.environ["DUCK_DEBIAN_MIRROR"] = "https://mirrors.tuna.tsinghua.edu.cn/debian"
    cargo_dir = Path.home() / ".cargo"
    cargo_dir.mkdir(parents=True, exist_ok=True)
    config = cargo_dir / "config.toml"
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    if "crates.io-index" not in text and "rsproxy" not in text:
        config.write_text(
            "[source.crates-io]\n"
            'replace-with = "tuna"\n'
            "\n"
            "[source.tuna]\n"
            'registry = "sparse+https://mirrors.tuna.tsinghua.edu.cn/crates.io-index/"\n',
            encoding="utf-8",
        )
    print("rustup 使用腾讯云镜像，crates.io 和 Debian sysroot 使用清华源。", flush=True)


def install_rustup():
    cargo_bin = Path.home() / ".cargo" / "bin"
    _prepend_path(cargo_bin)
    if shutil.which("rustup") and shutil.which("cargo"):
        return True
    print("WSL 里安装 rustup…", flush=True)
    installer = subprocess.run(
        ["curl", "--proto", "=https", "--tlsv1.2", "-fsSL", "https://sh.rustup.rs"],
        capture_output=True,
    )
    if installer.returncode != 0:
        sys.stderr.buffer.write(installer.stderr)
        print("下载 rustup 失败。", file=sys.stderr)
        return False
    proc = subprocess.run(["sh", "-s", "--", "-y", "--default-toolchain", "none"], input=installer.stdout)
    _prepend_path(cargo_bin)
    return proc.returncode == 0 and shutil.which("cargo") is not None


def install_zig():
    _prepend_path("/usr/local/bin")
    if shutil.which("zig"):
        return True
    name = f"zig-x86_64-linux-{ZIG_VERSION}"
    archive = Path("/tmp") / f"{name}.tar.xz"
    # 清华、中科大、腾讯、阿里、华为都没有这份文件。实测 zig.linus.dev 约 6 MB/s。
    urls = [
        f"https://zig.linus.dev/zig/{name}.tar.xz",
        f"https://fs.liujiacai.net/zigbuilds/{name}.tar.xz",
        f"https://ziglang.org/download/{ZIG_VERSION}/{name}.tar.xz",
    ]
    print(f"WSL 里下载 Zig {ZIG_VERSION}…", flush=True)
    downloaded = False
    for url in urls:
        print(f"尝试 {url}", flush=True)
        if _run(["curl", "-fL", "--retry", "2", "-o", str(archive), url]):
            downloaded = True
            break
        archive.unlink(missing_ok=True)
    if not downloaded:
        return False
    if not _run(["tar", "-xJf", str(archive), "-C", "/usr/local"]):
        return False
    link = Path("/usr/local/bin/zig")
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(Path("/usr/local") / name / "zig")
    return shutil.which("zig") is not None


def install_zigbuild():
    if shutil.which("cargo-zigbuild"):
        return True
    # rust-toolchain.toml selects 1.99.0 once cargo runs inside this tree.
    print(f"安装 Rust 工具链并编译 cargo-zigbuild {ZIGBUILD_VERSION}…", flush=True)
    if not _run(["rustup", "show"], cwd=ROOT):
        return False
    return _run(
        ["cargo", "install", "cargo-zigbuild", "--locked", "--version", ZIGBUILD_VERSION],
        cwd=ROOT,
    )


def ensure_toolchain():
    use_mirrors()
    if not install_packages() or not install_rustup() or not install_zig() or not install_zigbuild():
        print("WSL 交叉编译工具没装齐，已停止打包。", file=sys.stderr)
        return False
    print(f"工具链：cargo-zigbuild {ZIGBUILD_VERSION}，Zig {ZIG_VERSION}", flush=True)
    return True


def publish_bins():
    """cargo on /mnt is too slow, so the build lives on the Linux disk."""
    built = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")) / "aarch64-unknown-linux-gnu" / "release"
    if built.resolve() == BIN_DIR.resolve():
        return
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for name in BINS:
        source = built / name
        if not source.is_file():
            continue
        dest = BIN_DIR / name
        shutil.copy2(source, dest)
        dest.chmod(0o755)


def build_bins():
    print("在 WSL 里交叉编译。", flush=True)
    if not ensure_toolchain():
        return False
    if str(ROOT).startswith("/mnt/"):
        os.environ["CARGO_TARGET_DIR"] = "/var/tmp/microduck-r18-target"
        print("编译目录：/var/tmp/microduck-r18-target", flush=True)
    if not apply_sysroot():
        return False
    command = [
        "cargo", "zigbuild", "--locked", "--release",
        "--config", "profile.release.package.robotd.codegen-units=1",
        "--target", TARGET,
    ]
    for name in PACKAGES:
        command.extend(["-p", name])
    print("编译：" + "、".join(PACKAGES), flush=True)
    if not _run(command, cwd=ROOT):
        return False
    publish_bins()
    return True


def _zipinfo(path, arcname, mode):
    info = zipfile.ZipInfo.from_file(path, arcname)
    # create_system 3 is Unix, so the board's unzip reads the mode. Windows
    # writers otherwise store 0666 and the unpacked file is not executable.
    info.create_system = 3
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def pack():
    missing_paths = [name for name in PATHS if not (ROOT / name).is_file()]
    if missing_paths:
        print("缺少打包文件：\n  " + "\n  ".join(missing_paths), file=sys.stderr)
        return 1
    missing_bins = [name for name in BINS if not (BIN_DIR / name).is_file()]
    if missing_bins:
        print("程序不齐，没有写出 " + OUTPUT.name + "。缺少：", file=sys.stderr)
        print("  " + "、".join(missing_bins), file=sys.stderr)
        print("需要的全部程序：" + "、".join(BINS), file=sys.stderr)
        return 1
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in PATHS:
            path = ROOT / name
            raw = path.read_bytes()
            # ELF must not be CRLF-normalized; shell helpers still need LF-only.
            is_elf = raw.startswith(b"\x7fELF")
            if is_elf or name.endswith((".sh", ".py")) or name.endswith("/gamesir-xbox-status"):
                mode = 0o755
            else:
                mode = 0o644
            if is_elf:
                payload = raw
            else:
                # The tree is edited on Windows, so these files are CRLF. dash on
                # the board treats the carriage return as part of `set -eu`.
                payload = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            archive.writestr(_zipinfo(path, name, mode), payload)
        for name in BINS:
            binary = BIN_DIR / name
            archive.writestr(
                _zipinfo(binary, f"target/aarch64-unknown-linux-gnu/release/{name}", 0o755),
                binary.read_bytes(),
            )
    print(f"已写出 {OUTPUT} （{OUTPUT.stat().st_size} 字节）")
    print("包含程序：" + "、".join(BINS))
    print("另含 GameSir 桥：gamepad-r7/gamesir-xboxd")
    return 0


def relaunch_in_wsl():
    """Windows has no zig. The board build runs in the distro `wsl` starts."""
    if sys.platform != "win32":
        return None
    import shlex
    located = subprocess.run(["wsl", "wslpath", "-a", str(ROOT)], capture_output=True, text=True)
    if located.returncode != 0 or not located.stdout.strip():
        print("没有可用的 WSL。", file=sys.stderr)
        sys.stderr.write(located.stderr)
        return 1
    wsl_root = shlex.quote(located.stdout.strip())
    args = " ".join(shlex.quote(arg) for arg in sys.argv[1:])
    inner = (
        "source /root/.cargo/env 2>/dev/null || true; "
        f"cd {wsl_root} && export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 && "
        f"python3 pack_r18.py {args}"
    )
    return subprocess.run(["wsl", "-e", "bash", "-lc", inner]).returncode


def main():
    forwarded = relaunch_in_wsl()
    if forwarded is not None:
        return forwarded
    if "--no-build" not in sys.argv:
        if not build_bins():
            return 1
    return pack()


if __name__ == "__main__":
    raise SystemExit(main())
