# MicroDuck BoBo HAT 驱动板

> Radxa ZERO 3W 扩展板 — 舵机驱动与电源管理

## 概述

本目录包含 MicroDuck BoBoRedesign 项目的 **HAT 驱动板** PCB 设计文件。该板作为 Radxa ZERO 3W 的扩展板，提供舵机总线驱动、电源管理及 IMU 接口等功能，是 MicroDuck 控制系统的核心硬件之一。

> **版本说明：** 当前最新版本（Rev.A）参考自 [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy) 项目，感谢 kissqy 的硬件设计支持。

## 设计文件

| 文件 | 说明 |
|------|------|
| `ProPrj_HAT_REVA_SCH_2026-10-15.epro2` | HAT 驱动板 Rev.A 原理图，嘉立创 EDA 专业版工程文件（最新） |

## 打开方式

本项目使用 **嘉立创 EDA 专业版（LCEDA Pro）** 进行设计。

1. 下载安装 [嘉立创 EDA 专业版](https://lceda.cn/page/download)
2. 打开软件，选择 **文件 → 打开工程**
3. 选择 `ProPrj_HAT_REVA_SCH_2026-10-15.epro2` 文件即可打开

> **注意：** 该文件为 `.epro2` 格式，需要使用嘉立创 EDA **专业版**（Pro）打开，标准版（Std）无法兼容。

## 功能说明

- **舵机总线驱动** — 支持 Dynamixel 2.0 协议总线通信，可驱动最多 15 个舵机
- **电源管理** — 为 Radxa ZERO 3W 和舵机提供稳定的电源分配
- **IMU 接口** — 预留 I2C IMU 模块接口，可直接连接 BoBo IMU 板
- **即插即用** — 与 Radxa ZERO 3W 40pin 接口直接对接，无需额外接线

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| Rev.A | 2026-10-15 | 初始版本，集成舵机驱动、电源管理及 IMU 接口 |
