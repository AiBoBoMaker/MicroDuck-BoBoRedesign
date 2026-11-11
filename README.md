<p align="center">
  <img src="assets/logo.jpg" alt="BoBoMaker Logo" width="600"/>
</p>

<h1 align="center">MicroDuck BoBoRedesign</h1>

<p align="center">
  <a href="README_EN.md">English</a> |
  <a href="http://opc.bobomaker.com">BoBoMaker 官网</a> |
  <a href="https://github.com/pollen-robotics/microduck">原始项目</a> |
  <a href="https://github.com/kissqy/Microduck-kissqy">参考项目</a>
</p>

<p align="center">
  <strong>面向 3D 打印的 MicroDuck 双足机器人复刻与再设计项目</strong>
</p>

---

## 项目概述

**MicroDuck BoBoRedesign** 是 [MicroDuck](https://github.com/pollen-robotics/microduck) 的社区二次开发项目。MicroDuck 是 Pollen Robotics 开发的小型双足机器人，由强化学习策略驱动行走；官方外壳为注塑件，不适合直接 3D 打印复刻。本项目对结构件、电路板和固件进行再设计或适配，使其可以用 FDM/SLA 打印件和常见采购件完成复刻。

本项目的外壳模型、HAT 驱动板、IMU 模块与固件版本来自 [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)（以下简称 kissqy 项目），并在其基础上继续修改。当前仓库的结构：

- 提供 **XL330-M288-T**（原版 Dynamixel 舵机）和 **HD-1910-C001**（飞特舵机）两套外壳方案；
- 提供 Radxa ZERO 3W 的 HAT 驱动板与 IMU 模块（IMU 挂在舵机总线上，含 imu_to_dxl 与 imu_to_feetech 适配）；
- 提供基于官方 0.15.1 与 kissqy 飞特方案的机器人固件、机器人中控和训练中控；
- 提供采购清单（BOM）、舵机调试工具与主板资料。

> **当前状态：** HD-1910-C001 外壳已实际打印装配验证；HAT 驱动板 Rev.A、IMU 板（imu_to_dxl）已更新；固件与中控为 R17 V167（console 1.0.167）+ control.43。训练中控已独立到 `04-TrainCode/training-console/`。

## 项目目标

- **可打印复刻** —— 将注塑外壳改为适合 FDM/SLA 的分件模型，并按打印工艺调整公差与受力结构
- **硬件可采购** —— 控制板、IMU、舵机、电池等均给出可下单的型号与链接
- **两种舵机路线** —— 保留 XL330 原版方案，同时提供价格更低的 HD-1910-C001 方案
- **固件可用** —— 保留调试、标定、行走与训练流程，可通过电脑或手机浏览器操作
- **社区共建** —— 模型、PCB、固件、文档均开放修改与提交

## 仓库结构

```
MicroDuck-BoBoRedesign/
├── 01-3DPrint/       # 3D 打印外壳：XL330 与 HD-1910 两套舵机方案
├── 02-PCB/           # 电路板：IMU 模块、HAT 驱动板（嘉立创 EDA 专业版工程）
├── 03-DuckCode/      # 鸭子固件与机器人中控（microduck-hd1910）
├── 04-TrainCode/     # 训练中控（training-console）
├── 05-BOM/           # 采购清单、Radxa ZERO 3W 主板资料、飞特舵机资料
├── 06-tools/         # 舵机调试工具、CH340 串口驱动等
├── assets/           # Logo 与图片素材
├── .gitignore
├── README.md         # 中文主文档（本文件）
└── README_EN.md      # 英文文档
```

### 目录一览

| 目录 | 放什么 | 建议先看 |
|------|--------|----------|
| `01-3DPrint` | 两套外壳 STL：`01-XL330-M288-T/`（原版舵机）、`02-HD-1910-C001/`（飞特舵机）；另有 `0位支架.stp` | `01-3DPrint/02-HD-1910-C001/README.md` |
| `02-PCB` | `01-IMU/`（IMU 板工程与固件）、`02-HAT/`（HAT 驱动板工程） | `02-PCB/01-IMU/README.md`、`02-PCB/02-HAT/README.md` |
| `03-DuckCode` | `microduck-hd1910/`：Rust 机器人固件、Python 机器人中控及许可证 | `03-DuckCode/microduck-hd1910/README.md` |
| `04-TrainCode` | `training-console/`：Python 训练中控（R1.5.27） | `04-TrainCode/training-console/README.md` |
| `05-BOM` | `MicroDuck购买清单.md`、`01-主板资料整理/`、`02-飞特舵机/` | `05-BOM/MicroDuck购买清单.md` |
| `06-tools` | `02-feite/`：飞特调试工具、CH340 驱动、HD-1910 手册；`01-XL330-M288-T/` 为空 | `06-tools/02-feite/` |
| `assets` | `logo.jpg`（文档抬头图）、`wechat.jpg` | — |

## 目录说明

### 01-3DPrint —— 3D 打印外壳

按舵机型号分为两套，**两套模型不能混用**：选择哪套取决于你买的是 XL330 还是 HD-1910。

- **`01-XL330-M288-T/`** —— 适配原版 Dynamixel XL330-M288-T 的 STL。文件名带数量后缀（如 `左脚x1.stl`、`大腿固定件x2.stl`、`舵盘x4.stl`），共 28 个 STL 文件；目录内 `CHANGELOG.md` 记录了 2026-09-19 的装配与结构改进。
- **`02-HD-1910-C001/`** —— 适配飞特 HD-1910-C001 的 STL，是当前主推且已验证打印装配的方案。
  - `stl模型/`：最新模型，按颜色/材料分盘——`TPU部分/`（脚底、滑轮）、`支撑部分/`、`橙色部分/`、`躯体部分/`、`黑色部分/`；
  - `老版/`：早期模型，仅供参考，含 `摆盘文件.3mf`。
  - 打印建议：外壳件 PLA/PETG、层高 0.2 mm、填充 ≥20%；TPU 件 85A–95A、填充 15%–20%；支撑建议树状支撑。详见该目录 README。
- **`0位支架.stp`** —— 独立 STEP 格式支架件。

### 02-PCB —— 电路板

两个子目录均使用**嘉立创 EDA 专业版（LCEDA Pro）** 的 `.epro2` 工程格式，标准版无法打开。

- **`01-IMU/`** —— 六轴 IMU 模块。板上把加速度计 + 陀螺仪模拟为 Dynamixel 2.0 设备，直接挂在舵机总线上，主控无需额外通信接口。
  - `MicroDuck-BoBo-IMU-2026-09-22.epro2`：初始版本；
  - `MicroDuck-kissqy-imu_to_dxl-2026-10-15.epro2`：IMU 转 Dynamixel 接口版本（最新）；
  - `firmware/imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin`：可直接烧录的 IMU 固件；
  - `firmware/Microduck-Robotd-FT6-R17.tar.gz`：完整固件包。
- **`02-HAT/`** —— Radxa ZERO 3W 的 HAT 扩展板（Rev.A 原理图 `Microduck-kissqy-HAT_REVA_SCH_2026-10-15.epro2`）。功能为舵机总线驱动（最多 15 路）、电源分配、IMU 接口，直接对接 ZERO 3W 的 40pin 排针。

> 注意：两个子目录的 README 中列出的工程文件名与实际文件名略有出入，请以目录中的实际文件为准。

### 03-DuckCode —— 固件与中控

目前只有 **`microduck-hd1910/`** 一个子项目：基于 Microduck 官方 0.15.1 的飞特 HD1910 适配，参考硬件为 Radxa ZERO 3W + 15 个 HD1910 舵机。

| 组成 | 内容 | 入口 |
|------|------|------|
| `firmware/` | Rust workspace，含 `robotd`（控制循环）、`robotctl`、`padd`、`console`、`configd`、`btd`、`policies`、`kinematics`、`odometry`、`tof` 等 crate，以及 `Cargo.toml`、`rust-toolchain.toml` | `firmware/console/start.cmd` / `start.command`（中控） |
| `tools/` | 本地编译脚本 | `tools/build-firmware.sh` |
| `LICENSES/` | `Apache-2.0.txt`、`Personal-NonCommercial.txt` | — |

关键文件：

- 版本与构建：`firmware/BUILD.json`、`firmware/BUILDING-V167.md`（R17 V167 / control.43 构建说明）；
- 打包脚本：`firmware/prepare-V167.py`、`firmware/build-V167.sh`、`firmware/package-V167.py`；
- 预置策略：`firmware/policies/`（`stand`、`walk`、`sitstand`、`kick_left`、`roulade`、`ground_pick`）；
- 更新包：`firmware/console/updates/`（与 `02-PCB/01-IMU/firmware/` 中的 IMU 固件为同名同大小文件）。

编译固件需要 Linux/WSL2、Rust 1.99、cargo-zigbuild 0.23.4、Zig 0.15.1、Python 3 与 libudev 开发库。**日常使用不需要自己编译**，可直接使用仓库中的固件包与中控。

> 版本说明：R17 V167（中控 `1.0.167`）是当前中控与配套固件的版本。`firmware/` 下的 `install-R18.sh`、`pack-R18.sh`、`R18-使用方法.md` 是**干净板安装包**（`Microduck-R18.zip`）的安装/打包文件及说明，不代表中控已升级到 R18；中控版本以 `firmware/console/release_identity.py` 的 `CONSOLE_VERSION = '1.0.167'` 为准。

> 说明：该子项目的 README 引用了 `release-assets/`、`hardware/` 与 `docs/BUILD.md`，这些路径当前未随仓库提供；系统镜像与中控 ZIP 需按该 README 中的下载链接获取。

### 04-TrainCode —— 训练中控

存放独立的 Python 训练中控 `training-console/`（Microduck Training Studio R1.5.27），用于组织训练任务、查看奖励曲线与日志、评估仿真并导出 ONNX 与模型包。

| 组成 | 内容 | 入口 |
|------|------|------|
| `training-console/` | `studio.py`、`training_console.py`、`training/`（训练调度、模型导入、部署、SSH 等） | `training-console/start-training.cmd` / `start-training.command` |

- 配套固件为 0.15.1，骨架为官方骨架 + HD1910；当前提供 14 类动作、35 种任务配方。
- 运行中控页面的电脑需要 Python 3.10 或以上；训练本身需要 NVIDIA GPU + Linux/WSL2（或通过 SSH 连接训练服务器）。
- 训练中控不是机器人固件，不刷写 ZERO、不直接控制舵机；导出策略后部署到机器人的 `policies/` 由 `robotd` 加载。
- 详细规则见 `training-console/README.zh-CN.md`。

```
04-TrainCode/
└── training-console/
    ├── start-training.cmd / start-training.command
    ├── training_console.py
    ├── studio.py
    ├── training/
    └── tests/
```

### 05-BOM —— 采购清单与硬件资料

- **`MicroDuck购买清单.md`** —— 逐项列出主板、舵机、TF 卡、驱动板、IMU、轴承、螺丝、摄像头、ToF、扬声器、手柄、电池、舵机线的型号、记录价格与购买链接；舵机分 XL330 与 HD1910 二选一。价格为文档内记录价（最近更新 2026-09-23），下单前请以商品页为准。
- **`01-主板资料整理/`** —— Radxa ZERO 3W 原理图（`radxa_zero_3w_v1.12_schematic.pdf`）、40pin 引脚说明（`40pin引脚说明.png`）、`radxa_zero_3w_v1110_smb.zip`；`1.12j版本硬件的固件安装步骤/` 目前为空。
- **`02-飞特舵机/`** —— HD-1910 舵机手册 `HD-1910..07.pdf`。

### 06-tools —— 调试工具

- **`02-feite/`** —— `飞特舵机调试工具1.9.8.5(250729).7z`（飞特舵机上位机）、`CH340_URT.rar`（USB 转串口驱动）、`HD-1910..07.pdf`（舵机手册）。压缩包需自行解压后使用。
- **`01-XL330-M288-T/`** —— 目前为空目录。

### assets —— 素材

`logo.jpg` 用于文档抬头；`wechat.jpg` 为微信交流相关图片。

## 模块之间的关系

```
                ┌─────────────────────────────┐
                │ 05-BOM  采购：主板/舵机/... │
                └──────────────┬──────────────┘
                               │ 按清单买料
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                       ▼
 01-3DPrint 外壳         02-PCB 电路板            舵机 + Radxa ZERO 3W
 （按舵机二选一）       （IMU + HAT）                    │
        │                      │                        │
        └──────────装配────────┴────────────────────────┘
                               ▼
                 03-DuckCode 固件（跑在 ZERO 3W 上）
                 robotd 控制 15 个舵机 + 读取 IMU
                               │
                     ┌─────────┴─────────┐
                     ▼                   ▼
              机器人中控 console     04-TrainCode 训练中控
              （电脑/手机 SSH）      （训练并部署新策略）
```

- 外壳与舵机型号强绑定：`01-XL330-M288-T` 配 XL330，`02-HD-1910-C001` 配 HD-1910-C001。
- HAT 是 Radxa ZERO 3W 的扩展板，负责舵机总线与供电；IMU 板挂在同一条总线上，按总线设备被固件读取（工程含 imu_to_dxl 与 imu_to_feetech 两种适配）。
- 固件运行在 ZERO 3W 上；中控是运行在电脑/手机上的操作界面，通过 SSH 连接机器人，本身不控制舵机。
- 训练中控产出策略模型，部署到机器人的 `policies/` 后由 `robotd` 加载。
- `06-tools` 用于舵机 ID/零点/限位调试和串口驱动安装，属于装配与标定阶段的辅助工具。

## 根目录文件说明

| 文件 | 作用 |
|------|------|
| `README.md` | 中文主文档（本文件），仓库入口 |
| `README_EN.md` | 英文文档，内容与本文对应 |
| `.gitignore` | 忽略 OS 文件（`.DS_Store`、`Thumbs.db`）、IDE 配置、构建产物（`build/`、`dist/`、`__pycache__/`）、切片文件（`*.gcode`、`*.3mf`）、训练输出（`runs/`、`*.pt`、`*.onnx`）、虚拟环境与临时文件等 |
| `LICENSE` | 根目录**没有**独立 LICENSE 文件；许可条款见下文及各子目录（如 `03-DuckCode/microduck-hd1910/LICENSE`） |

## 快速开始

### 前置条件

- 一台 3D 打印机（FDM 或 SLA），能打印 PLA/PETG，最好能打印 TPU
- 基本电子装配与焊接能力
- 会使用舵机调试上位机完成 ID、零点与限位设置
- （可选）训练自定义策略需要 NVIDIA GPU 与 Linux/WSL2 环境

### 制作顺序

1. **买料** —— 按 `05-BOM/MicroDuck购买清单.md` 采购；先确定舵机路线（XL330 或 HD-1910）。
2. **打印外壳** —— HD-1910 方案用 `01-3DPrint/02-HD-1910-C001/stl模型/`；XL330 方案用 `01-3DPrint/01-XL330-M288-T/`。
3. **打板与贴片** —— 用嘉立创 EDA 专业版打开 `02-PCB/01-IMU/`、`02-PCB/02-HAT/` 下的 `.epro2` 工程下单。
4. **烧录 IMU** —— 使用 `02-PCB/01-IMU/firmware/imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin` 烧录 IMU 固件。
5. **装配** —— 装舵机、HAT、IMU、电池与外壳；用 `06-tools/02-feite/` 中的调试工具设置舵机 ID 与零点。
6. **准备系统与固件** —— 按 `03-DuckCode/microduck-hd1910/README.md` 下载系统镜像并刷入 TF 卡；已有系统可在中控中安装随包固件。
7. **调试运行** —— 启动 `03-DuckCode/microduck-hd1910/firmware/console/start.cmd`（macOS/Linux 用 `start.command`），填写 `用户名@机器人IP` 与 SSH 信息，按 **HOME → 保持 → 行走** 操作。
8. **训练（可选）** —— 启动 `04-TrainCode/training-console/start-training.cmd`（或 `start-training.command`），训练完成后部署策略。

> 每台机器人都需要核对自己的关节零位、方向、限位与 IMU，不能直接套用他人的标定结果。

## 版本与硬件对应

| 项目 | 当前版本 / 型号 | 位置 |
|------|------------------|------|
| 机器人固件 | 官方 0.15.1 · control.43 · API40 | `03-DuckCode/microduck-hd1910/firmware/` |
| 机器人中控 | R17 V167（1.0.167） | `03-DuckCode/microduck-hd1910/firmware/console/` |
| 训练中控 | R1.5.27 | `04-TrainCode/training-console/` |
| HAT 驱动板 | Rev.A（2026-10-15） | `02-PCB/02-HAT/` |
| IMU 模块 | imu_to_dxl（2026-10-15） | `02-PCB/01-IMU/` |
| 外壳 | XL330 版 / HD-1910 版 | `01-3DPrint/` |
| 主控 | Radxa ZERO 3W（2G，无 eMMC） | 见 `05-BOM/MicroDuck购买清单.md` |

## 致谢

本项目基于 [Pollen Robotics](https://pollen-robotics.com/) 的 [MicroDuck](https://github.com/pollen-robotics/microduck) 进行二次开发，感谢其在开源机器人领域的开创性工作。

同时感谢 [@kissqy](https://github.com/kissqy) 的 [Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy) 项目：本仓库的外壳模型、HAT、IMU 与固件适配均以其为基础上继续改进；也感谢 [@fanhao375](https://github.com/fanhao375) 的 [microduck-replica](https://github.com/fanhao375/microduck-replica) 提供的早期模型参考。

- **原始项目：** [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck)
- **参考项目：** [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)
- **RL 训练仓库：** [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl)

## 开源协议

根目录未放置独立 LICENSE 文件，各部分遵循其来源项目的许可：

- **代码与固件：** Apache License 2.0（`03-DuckCode/microduck-hd1910/LICENSE`、`LICENSES/Apache-2.0.txt`）
- **本项目作者原创部分：** 个人非商业许可（`03-DuckCode/microduck-hd1910/LICENSES/Personal-NonCommercial.txt`）
- **3D 模型与设计：** 遵循原始 MicroDuck 项目的 CC BY-SA-NC 条款

完整条款请参阅原始项目的 [LICENSE](https://github.com/pollen-robotics/microduck/blob/main/LICENSE) 及上述子目录中的许可文件。

## 声明

本项目是基于官方 MicroDuck 0.15.1 的个人学习与开发项目，并非 Pollen Robotics 官方发布。除明确标注的官方及第三方代码、模型、素材外，本项目新增的固件适配、控制板、工具与文档为作者原创（部分使用 AI 工具辅助）。

作者原创部分仅供个人学习、研究与非商业使用；商业使用需事先取得作者书面授权。官方 Apache-2.0、第三方 MIT 及官方几何模型等仍遵循各自原许可证，不被本项目条款覆盖。

## 参与贡献

1. Fork 本仓库
2. 创建分支（`git checkout -b feature/YourFeature`）
3. 提交修改（`git commit -m 'Add YourFeature'`）
4. 推送分支（`git push origin feature/YourFeature`）
5. 发起 Pull Request

问题反馈与制作交流：

- **Issues：** [AiBoBoMaker/MicroDuck-BoBoRedesign Issues](https://github.com/AiBoBoMaker/MicroDuck-BoBoRedesign/issues)
- **Discussions：** [AiBoBoMaker/MicroDuck-BoBoRedesign Discussions](https://github.com/AiBoBoMaker/MicroDuck-BoBoRedesign/discussions)

---

<p align="center">
  由 <a href="http://opc.bobomaker.com">BoBoMaker</a> 社区维护
</p>

## 作者与交流

BoBoMaker，AI 硬件开发者

- 小红书：BoBoMaker
- 视频号：BoBoMaker
- 抖音：BoBoMaker

选型、装配、调试上遇到问题都欢迎来聊；加微信扫码即可，备注一下具体问题会更快对上。

![BoBoMaker 微信二维码](assets/wechat.jpg)

