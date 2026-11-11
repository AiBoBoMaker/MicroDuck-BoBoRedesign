<p align="center">
  <img src="assets/logo.jpg" alt="BoBoMaker Logo" width="600"/>
</p>

<h1 align="center">MicroDuck BoBoRedesign</h1>

<p align="center">
  <a href="README.md">简体中文</a> |
  <a href="http://opc.bobomaker.com">BoBoMaker Official</a> |
  <a href="https://github.com/pollen-robotics/microduck">Original Project</a> |
  <a href="https://github.com/kissqy/Microduck-kissqy">Reference Project</a>
</p>

<p align="center">
  <strong>A 3D-printable replica and redesign of the MicroDuck bipedal robot</strong>
</p>

---

## Overview

**MicroDuck BoBoRedesign** is a community fork of [MicroDuck](https://github.com/pollen-robotics/microduck), a small bipedal robot from Pollen Robotics driven by reinforcement-learning policies. The official shell is injection-molded and does not reproduce well with 3D printing, so this project redesigns or adapts the mechanical parts, PCBs, and firmware for FDM/SLA printing and commonly available purchased parts.

The shell models, HAT driver board, IMU module, and firmware versions come from [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy) and are modified further here. The repository currently provides:

- Two shell variants: **XL330-M288-T** (original Dynamixel servo) and **HD-1910-C001** (Feetech servo);
- A Radxa ZERO 3W HAT driver board and an IMU module that sits on the servo bus (both imu_to_dxl and imu_to_feetech adaptations are included);
- Robot firmware based on official 0.15.1 plus the kissqy Feetech adaptation, a robot console, and a training console;
- A bill of materials, servo debugging tools, and Radxa ZERO 3W documentation.

> **Status:** The HD-1910-C001 shell has been printed and assembled successfully. HAT Rev.A and the IMU board (imu_to_dxl) are up to date. Firmware and console are R17 V167 (console 1.0.167) with control.43. The training console now lives in `04-TrainCode/training-console/`.

## Goals

- **Printable replica** — split the injection-molded shell into printable parts with adjusted tolerances and reinforced load paths
- **Purchasable hardware** — provide concrete part numbers and links for the controller, IMU, servos, and battery
- **Two servo routes** — keep the original XL330 option and add the cheaper HD-1910-C001 option
- **Usable firmware** — retain debugging, calibration, walking, and training flows, operable from a computer or phone browser
- **Community driven** — models, PCBs, firmware, and docs are open to contribution

## Repository Layout

```
MicroDuck-BoBoRedesign/
├── 01-3DPrint/       # Shell STLs: XL330 and HD-1910 variants
├── 02-PCB/           # IMU module and HAT driver board (LCEDA Pro projects)
├── 03-DuckCode/      # Firmware and robot console (microduck-hd1910)
├── 04-TrainCode/     # Training console (training-console)
├── 05-BOM/           # Purchase list, Radxa ZERO 3W docs, Feetech servo docs
├── 06-tools/         # Servo debug tool, CH340 serial driver, etc.
├── assets/           # Logo and images
├── .gitignore
├── README.md         # Chinese main document
└── README_EN.md      # English document (this file)
```

### Directory Overview

| Directory | Contents | Start here |
|-----------|----------|------------|
| `01-3DPrint` | Two shell sets: `01-XL330-M288-T/` (original servo) and `02-HD-1910-C001/` (Feetech servo); plus `0位支架.stp` | `01-3DPrint/02-HD-1910-C001/README.md` |
| `02-PCB` | `01-IMU/` (IMU board project and firmware), `02-HAT/` (HAT driver board project) | `02-PCB/01-IMU/README.md`, `02-PCB/02-HAT/README.md` |
| `03-DuckCode` | `microduck-hd1910/`: Rust robot firmware, Python robot console, licenses | `03-DuckCode/microduck-hd1910/README.en.md` |
| `04-TrainCode` | `training-console/`: Python training console (R1.5.27) | `04-TrainCode/training-console/README.en.md` |
| `05-BOM` | `MicroDuck购买清单.md`, `01-主板资料整理/`, `02-飞特舵机/` | `05-BOM/MicroDuck购买清单.md` |
| `06-tools` | `02-feite/`: Feetech tool, CH340 driver, HD-1910 manual; `01-XL330-M288-T/` is empty | `06-tools/02-feite/` |
| `assets` | `logo.jpg` (header image), `wechat.jpg` | — |

## Directory Details

### 01-3DPrint — Printed Shell

The models are split by servo type, and **the two sets are not interchangeable**.

- **`01-XL330-M288-T/`** — STLs for the original Dynamixel XL330-M288-T. Filenames carry quantities (e.g. `左脚x1.stl`, `大腿固定件x2.stl`, `舵盘x4.stl`); 28 STL files in total. `CHANGELOG.md` records the assembly and structural changes dated 2026-09-19.
- **`02-HD-1910-C001/`** — STLs for the Feetech HD-1910-C001, the current validated variant.
  - `stl模型/`: latest models grouped by color/material — `TPU部分/` (feet soles, pulleys), `支撑部分/`, `橙色部分/`, `躯体部分/`, `黑色部分/`;
  - `老版/`: earlier models kept for reference, including `摆盘文件.3mf`.
  - Printing: shell parts in PLA/PETG, 0.2 mm layers, ≥20% infill; TPU parts 85A–95A, 15%–20% infill; tree supports recommended. See that directory's README for details.
- **`0位支架.stp`** — standalone STEP bracket.

### 02-PCB — Circuit Boards

Both subdirectories are **LCEDA Pro (嘉立创 EDA 专业版)** `.epro2` projects; the standard edition cannot open them.

- **`01-IMU/`** — 6-axis IMU module that emulates a Dynamixel 2.0 device on the servo bus, so the main controller needs no extra communication interface.
  - `MicroDuck-BoBo-IMU-2026-09-22.epro2`: initial version;
  - `MicroDuck-kissqy-imu_to_dxl-2026-10-15.epro2`: IMU-to-Dynamixel version (latest);
  - `firmware/imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin`: flashable IMU firmware;
  - `firmware/Microduck-Robotd-FT6-R17.tar.gz`: full firmware package.
- **`02-HAT/`** — Radxa ZERO 3W HAT (Rev.A schematic: `Microduck-kissqy-HAT_REVA_SCH_2026-10-15.epro2`). Provides servo bus driving (up to 15 servos), power distribution, and an IMU interface; plugs directly onto the ZERO 3W 40-pin header.

> Note: the project filenames listed in the two subdirectory READMEs differ slightly from the actual files; use the files present in the directory.

### 03-DuckCode — Firmware and Consoles

Currently contains a single subproject, **`microduck-hd1910/`**: a Feetech HD1910 adaptation based on official MicroDuck 0.15.1. Reference hardware is a Radxa ZERO 3W with 15 HD1910 servos.

| Part | Contents | Entry point |
|------|----------|-------------|
| `firmware/` | Rust workspace with `robotd` (control loop), `robotctl`, `padd`, `console`, `configd`, `btd`, `policies`, `kinematics`, `odometry`, `tof`, plus `Cargo.toml` and `rust-toolchain.toml` | `firmware/console/start.cmd` / `start.command` |
| `tools/` | Local build script | `tools/build-firmware.sh` |
| `LICENSES/` | `Apache-2.0.txt`, `Personal-NonCommercial.txt` | — |

Key files:

- Version and build: `firmware/BUILD.json`, `firmware/BUILDING-V167.md` (R17 V167 / control.43 build notes);
- Packaging: `firmware/prepare-V167.py`, `firmware/build-V167.sh`, `firmware/package-V167.py`;
- Bundled policies: `firmware/policies/` (`stand`, `walk`, `sitstand`, `kick_left`, `roulade`, `ground_pick`);
- Update payloads: `firmware/console/updates/` (same IMU firmware name and size as in `02-PCB/01-IMU/firmware/`).

Building the firmware requires Linux/WSL2, Rust 1.99, cargo-zigbuild 0.23.4, Zig 0.15.1, Python 3, and libudev development files. **Daily use does not require building** — use the bundled firmware and console packages.

> Version note: R17 V167 (console `1.0.167`) is the current console and matching firmware. `install-R18.sh`, `pack-R18.sh`, and `R18-使用方法.md` under `firmware/` are install/packaging files and notes for the **clean-board installer** (`Microduck-R18.zip`); they do not mean the console has moved to R18. The console version is defined by `CONSOLE_VERSION = '1.0.167'` in `firmware/console/release_identity.py`.

> The subproject README references `release-assets/`, `hardware/`, and `docs/BUILD.md`, which are not included in this repository. System images and console ZIPs are downloaded from the links in that README.

### 04-TrainCode — Training Console

Holds the standalone Python training console `training-console/` (Microduck Training Studio R1.5.27) used to organize training jobs, inspect reward curves and logs, evaluate in simulation, and export ONNX and model packages.

| Part | Contents | Entry point |
|------|----------|-------------|
| `training-console/` | `studio.py`, `training_console.py`, `training/` (scheduling, model import, deployment, SSH) | `training-console/start-training.cmd` / `start-training.command` |

- Targets firmware 0.15.1 with the official frame and HD1910; currently 14 action categories and 35 task recipes.
- The computer showing the console needs Python 3.10+; training itself needs an NVIDIA GPU with Linux/WSL2 (or an SSH training server).
- The training console is not robot firmware: it does not flash the ZERO or drive servos. Exported policies are deployed into the robot's `policies/` and loaded by `robotd`.
- See `training-console/README.zh-CN.md` for detailed rules.

```
04-TrainCode/
└── training-console/
    ├── start-training.cmd / start-training.command
    ├── training_console.py
    ├── studio.py
    ├── training/
    └── tests/
```

### 05-BOM — Purchase List and Hardware Docs

- **`MicroDuck购买清单.md`** — itemized list of mainboard, servos, TF card, driver boards, IMU, bearings, screws, camera, ToF, speaker, gamepad, battery, and servo cables, with prices and purchase links. Servos are either XL330 or HD1910. Prices reflect the document's last update (2026-09-23); check the product pages before ordering.
- **`01-主板资料整理/`** — Radxa ZERO 3W schematic (`radxa_zero_3w_v1.12_schematic.pdf`), 40-pin header diagram (`40pin引脚说明.png`), and `radxa_zero_3w_v1110_smb.zip`; `1.12j版本硬件的固件安装步骤/` is currently empty.
- **`02-飞特舵机/`** — HD-1910 servo manual `HD-1910..07.pdf`.

### 06-tools — Debugging Tools

- **`02-feite/`** — `飞特舵机调试工具1.9.8.5(250729).7z` (Feetech servo GUI), `CH340_URT.rar` (USB-to-serial driver), `HD-1910..07.pdf` (servo manual). Archives must be extracted before use.
- **`01-XL330-M288-T/`** — currently empty.

### assets

`logo.jpg` is used in the README header; `wechat.jpg` is a WeChat community image.

## How the Modules Fit Together

```
                ┌──────────────────────────────────┐
                │ 05-BOM  purchase mainboard/servos │
                └───────────────┬──────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
 01-3DPrint shell         02-PCB boards             servos + Radxa ZERO 3W
 (pick one servo type)    (IMU + HAT)                       │
        │                       │                           │
        └────────── assemble ───┴───────────────────────────┘
                                ▼
                 03-DuckCode firmware (runs on ZERO 3W)
                 robotd controls 15 servos and reads IMU
                                │
                     ┌──────────┴──────────┐
                     ▼                     ▼
            robot console          04-TrainCode training console
             (SSH from PC/phone)    (train and deploy policies)
```

- The shell is tied to the servo type: `01-XL330-M288-T` with XL330, `02-HD-1910-C001` with HD-1910-C001.
- The HAT is a Radxa ZERO 3W expansion board handling the servo bus and power; the IMU sits on the same bus and is read as a bus device (both imu_to_dxl and imu_to_feetech adaptations are included).
- Firmware runs on the ZERO 3W. The consoles are operator interfaces running on a computer or phone and connect over SSH; they do not drive servos directly.
- The training console produces policy models; after deployment into `policies/`, `robotd` loads them.
- `06-tools` supports assembly and calibration (servo ID, zero position, limits) and serial driver installation.

## Root Files

| File | Purpose |
|------|---------|
| `README.md` | Chinese main document, the repository entry point |
| `README_EN.md` | English document (this file) |
| `.gitignore` | Ignores OS files (`.DS_Store`, `Thumbs.db`), IDE config, build outputs (`build/`, `dist/`, `__pycache__/`), slicer files (`*.gcode`, `*.3mf`), training outputs (`runs/`, `*.pt`, `*.onnx`), virtual environments, and temporary files |
| `LICENSE` | There is **no** root-level LICENSE; terms are described below and in subdirectories (e.g. `03-DuckCode/microduck-hd1910/LICENSE`) |

## Getting Started

### Prerequisites

- A 3D printer (FDM or SLA) able to print PLA/PETG, ideally TPU as well
- Basic electronics assembly and soldering skills
- Ability to use a servo debugging tool to set IDs, zero positions, and limits
- (Optional) An NVIDIA GPU with Linux/WSL2 for training custom policies

### Build Order

1. **Buy parts** — follow `05-BOM/MicroDuck购买清单.md`; decide between XL330 and HD-1910 first.
2. **Print the shell** — HD-1910: `01-3DPrint/02-HD-1910-C001/stl模型/`; XL330: `01-3DPrint/01-XL330-M288-T/`.
3. **Fabricate PCBs** — open the `.epro2` projects under `02-PCB/01-IMU/` and `02-PCB/02-HAT/` with LCEDA Pro and order.
4. **Flash the IMU** — flash the IMU firmware from `02-PCB/01-IMU/firmware/imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin`.
5. **Assemble** — mount servos, HAT, IMU, battery, and shell; set servo IDs and zero positions with the tool in `06-tools/02-feite/`.
6. **Prepare the system and firmware** — download the system image and flash the TF card as described in `03-DuckCode/microduck-hd1910/README.en.md`; existing systems can install the bundled firmware from the console.
7. **Run** — start `03-DuckCode/microduck-hd1910/firmware/console/start.cmd` (`start.command` on macOS/Linux), enter `user@robot-ip` and SSH credentials, then use **HOME → hold → walk**.
8. **Train (optional)** — start `04-TrainCode/training-console/start-training.cmd` (or `start-training.command`) and deploy the resulting policy.

> Every robot needs its own joint zero positions, directions, limits, and IMU calibration. Do not reuse another robot's calibration.

## Versions and Hardware

| Item | Current version / model | Location |
|------|-------------------------|----------|
| Robot firmware | Official 0.15.1 · control.43 · API40 | `03-DuckCode/microduck-hd1910/firmware/` |
| Robot console | R17 V167 (1.0.167) | `03-DuckCode/microduck-hd1910/firmware/console/` |
| Training console | R1.5.27 | `04-TrainCode/training-console/` |
| HAT driver board | Rev.A (2026-10-15) | `02-PCB/02-HAT/` |
| IMU module | imu_to_dxl (2026-10-15) | `02-PCB/01-IMU/` |
| Shell | XL330 / HD-1910 variants | `01-3DPrint/` |
| Mainboard | Radxa ZERO 3W (2 GB, no eMMC) | see `05-BOM/MicroDuck购买清单.md` |

## Acknowledgments

This project is a secondary development based on [MicroDuck](https://github.com/pollen-robotics/microduck) by [Pollen Robotics](https://pollen-robotics.com/). We appreciate their pioneering open-source robotics work.

Thanks to [@kissqy](https://github.com/kissqy) for [Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy): the shell models, HAT, IMU, and firmware adaptation here build on that work. Thanks also to [@fanhao375](https://github.com/fanhao375) for the early model reference in [microduck-replica](https://github.com/fanhao375/microduck-replica).

- **Original project:** [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck)
- **Reference project:** [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)
- **RL training repo:** [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl)

## License

There is no standalone root LICENSE file. Each part follows the license of its origin:

- **Code and firmware:** Apache License 2.0 (`03-DuckCode/microduck-hd1910/LICENSE`, `LICENSES/Apache-2.0.txt`)
- **Original work by this project's author:** personal non-commercial license (`03-DuckCode/microduck-hd1910/LICENSES/Personal-NonCommercial.txt`)
- **3D models and designs:** CC BY-SA-NC per the original MicroDuck project

See the original project's [LICENSE](https://github.com/pollen-robotics/microduck/blob/main/LICENSE) and the license files in the subdirectories for full terms.

## Disclaimer

This is a personal learning and development project based on official MicroDuck 0.15.1; it is not an official Pollen Robotics release. Except for clearly attributed official and third-party code, models, and assets, the firmware adaptation, controller boards, tools, and documentation added here are the author's original work (partly AI-assisted).

The author's original portions are for personal learning, research, and non-commercial use only. Commercial use requires prior written authorization. Official Apache-2.0, third-party MIT, and official geometric models remain under their respective licenses and are not superseded by these terms.

## Contributing

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/YourFeature`)
3. Commit your changes (`git commit -m 'Add YourFeature'`)
4. Push the branch (`git push origin feature/YourFeature`)
5. Open a Pull Request

Feedback and build discussions:

- **Issues:** [AiBoBoMaker/MicroDuck-BoBoRedesign Issues](https://github.com/AiBoBoMaker/MicroDuck-BoBoRedesign/issues)
- **Discussions:** [AiBoBoMaker/MicroDuck-BoBoRedesign Discussions](https://github.com/AiBoBoMaker/MicroDuck-BoBoRedesign/discussions)

---

<p align="center">
  Maintained by the <a href="http://opc.bobomaker.com">BoBoMaker</a> community
</p>
