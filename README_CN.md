<p align="center">
  <img src="assets/logo.jpg" alt="BoBoMaker Logo" width="600"/>
</p>

<h1 align="center">MicroDuck BoBoRedesign</h1>

<p align="center">
  <a href="README.md">English</a> |
  <a href="http://opc.bobomaker.com">BoBoMaker 官网</a> |
  <a href="https://github.com/pollen-robotics/microduck">原始项目</a>
</p>

<p align="center">
  <strong>面向 3D 打印社区的 MicroDuck 双足机器人开源重设计项目</strong>
</p>

---

## 项目概述

**MicroDuck BoBoRedesign** 是一个开源社区项目，旨在将 [MicroDuck](https://github.com/pollen-robotics/microduck) —— 一款基于强化学习驱动的小型双足机器人 —— 重新设计为**完全适配 3D 打印**的版本。

原始 MicroDuck 由 [Pollen Robotics](https://pollen-robotics.com/microduck) 开发，其外壳采用注塑工艺制造，对于 3D 打印复刻来说效果并不理想。本项目致力于**对所有零部件进行二次创作**，在保持原有外观基本一致的前提下，针对 FDM/SLA 3D 打印工艺进行美学优化与结构增强，使 3D 打印复刻版本具备更高的可用性和观赏性。

> **我们的使命：** 让每一位拥有 3D 打印机的创客、爱好者和研究者都能亲手打造属于自己的 MicroDuck —— 无需注塑模具。

## 项目目标

- **高度还原** —— 尽可能还原官方版本的外壳、电路板、固件及强化学习策略
- **3D 打印优化** —— 对所有外壳部件进行打印友好型几何重构，优化公差配合，提升增材制造的美学表现
- **结构增强** —— 对关键受力部件进行加固设计，提高 3D 打印版本的耐用性与可靠性
- **国产舵机适配** —— 逐步扩展对国产舵机的支持，提供更具性价比的替代方案
- **社区共建** —— 面向全球创客社区开放，欢迎各类贡献

## 项目结构

```
MicroDuck-BoBoRedesign/
├── 01-3DPrint/    # 3D 打印外壳模型（STL/STEP 文件、打印配置）
├── 02-PCB/        # 自定义 PCB 设计与原理图
├── 03-Code/       # 固件与控制代码
├── 04-RL/         # 强化学习训练与策略文件
├── assets/        # 项目资源（Logo、图片等）
└── README_CN.md
```

### 目录说明

| 目录 | 内容 |
|------|------|
| `01-3DPrint` | 针对 FDM/SLA 打印优化的重设计 3D 模型，含装配指南与推荐打印参数 |
| `02-PCB` | 自定义控制板的 PCB 布局、原理图及 BOM（物料清单） |
| `03-Code` | 固件源码、配置文件及部署脚本 |
| `04-RL` | 强化学习训练环境、策略配置及 ONNX 模型导出文件 |

## 快速开始

> **注意：** 本项目目前处于积极开发阶段。详细的组装说明、BOM 清单及打印配置将在各模块成熟后陆续补充。

### 前置条件

- 一台 3D 打印机（FDM 或 SLA）
- 基本的电子装配能力
- 熟悉舵机校准流程
- （可选）具备强化学习经验以进行自定义策略训练

### 制作顺序

1. **3D 打印** `01-3DPrint/` 中的外壳组件
2. **焊接组装** `02-PCB/` 中的控制板
3. **烧录固件** `03-Code/` 中的控制程序
4. **训练与部署** `04-RL/` 中的强化学习策略（或使用预训练模型）

## 致谢

本项目是基于 [Pollen Robotics](https://pollen-robotics.com/) 的 [MicroDuck](https://github.com/pollen-robotics/microduck) 项目进行的**二次开发**。我们深深感谢他们在开源机器人领域的开创性工作。

- **原始项目：** [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck)
- **RL 训练仓库：** [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl)

## 开源协议

本项目遵循原始 MicroDuck 项目的开源协议：

- **代码与固件：** Apache License 2.0
- **3D 模型与设计：** Creative Commons Attribution-ShareAlike-NonCommercial (CC BY-SA-NC)

完整条款请参阅原始项目的 [LICENSE](https://github.com/pollen-robotics/microduck/blob/main/LICENSE) 文件。本仓库中的所有衍生作品均受相同条件约束。

## 参与贡献

欢迎任何形式的贡献！无论是优化打印配置、改进 PCB 布局、编写固件，还是训练新的强化学习策略 —— 每一份贡献都意义非凡。

1. Fork 本仓库
2. 创建你的特性分支（`git checkout -b feature/YourFeature`）
3. 提交你的修改（`git commit -m 'Add YourFeature'`）
4. 推送到分支（`git push origin feature/YourFeature`）
5. 发起 Pull Request

## 社区交流

加入讨论，分享你的制作成果，与全球创客连接：

- **Issues：** 通过 [GitHub Issues](https://github.com/your-username/MicroDuck-BoBoRedesign/issues) 报告 Bug 或提出功能建议
- **Discussions：** 在 [GitHub Discussions](https://github.com/your-username/MicroDuck-BoBoRedesign/discussions) 分享你的制作进度与创意想法

---

<p align="center">
  由 <a href="http://opc.bobomaker.com">BoBoMaker</a> 社区倾情打造
</p>
