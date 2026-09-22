# MicroDuck BoBo IMU Module

> 六轴 IMU 模块 — 模拟为 Dynamixel 2.0 设备

## 概述

本目录包含 MicroDuck BoBoRedesign 项目的 **IMU（惯性测量单元）模块** PCB 设计文件。该模块将六轴 IMU 传感器模拟为一个 **Dynamixel 2.0 协议设备**，可直接接入 MicroDuck 的舵机总线，无需额外的通信接口。

## 设计文件

| 文件 | 说明 |
|------|------|
| `MicroDuck-BoBo-IMU-2026-09-22.epro2` | 嘉立创 EDA 专业版工程文件 |

## 打开方式

本项目使用 **嘉立创 EDA 专业版（LCEDA Pro）** 进行设计。

1. 下载安装 [嘉立创 EDA 专业版](https://lceda.cn/page/download)
2. 打开软件，选择 **文件 → 打开工程**
3. 选择 `MicroDuck-BoBo-IMU-2026-09-22.epro2` 文件即可打开

> **注意：** 该文件为 `.epro2` 格式，需要使用嘉立创 EDA **专业版**（Pro）打开，标准版（Std）无法兼容。

## 功能说明

- **六轴 IMU 传感器** — 集成加速度计 + 陀螺仪，提供姿态感知能力
- **Dynamixel 2.0 协议兼容** — 模块在总线上表现为一个标准的 Dynamixel 2.0 设备，可直接使用现有的 Dynamixel 通信库进行读写
- **即插即用** — 无需修改主控固件的通信层，IMU 数据通过 Dynamixel 协议帧传输

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v20260922 | 2026-09-22 | 初始版本，实现六轴 IMU 模拟为 Dynamixel 2.0 设备 |
