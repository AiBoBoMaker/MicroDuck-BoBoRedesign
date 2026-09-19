# HD-1910-C001 Servo Shell — Changelog

> 飞特 HD-1910-C001 舵机外壳 3D 模型版本记录

---

## About This Folder

This folder contains the 3D model files for the MicroDuck BoBoRedesign shell components, designed around the **Feetech HD-1910-C001** servo motor.

### Acknowledgments

Special thanks to [@fanhao375](https://github.com/fanhao375) for the [microduck-replica](https://github.com/fanhao375/microduck-replica) repository. The reference models from that project significantly accelerated our initial design iteration.

### Known Issues

The current models were converted from STL files sourced from the replica project. As a result:

- **Fragmented mesh faces** — The conversion process produces a high triangle count with non-manifold geometry in some areas.
- **Surface artifacts on flat planes** — Certain flat surfaces exhibit visible facet lines and texture irregularities inherited from the STL tessellation.

### Roadmap

Each component will be **individually remodeled from scratch** using parametric CAD to resolve the mesh quality issues above. Progress will be tracked per-part in future releases.

---

## Release History

### v20260919 — 2026-09-19

**Assembly & Structural Improvements**

1. **Fixed calf support-to-foot assembly interference** — Resolved the fitment issue between the lower leg support bracket and the foot connection point, ensuring smooth assembly without binding.
2. **Reinforced dual-servo mounting plate inside the torso** — Increased the thickness and added ribbing to the internal mounting plate that holds the two side-by-side servos, improving torsional rigidity under load.
3. **Remodeled thigh fixture support bracket** — Rebuilt the thigh mounting support from the ground up with a stronger geometry, providing better load distribution and print reliability.
4. **Merged foot components into a single part** — The left and right foot halves, originally split for injection molding, are now combined into one printable unit — taking full advantage of 3D printing's design freedom.

---

### v20260919 — 2026-09-19（中文记录）

**装配与结构优化**

1. **修复小腿支撑件与脚部连接处的装配干涉** — 解决了小腿支撑件与脚连接位置的配合问题，确保装配顺畅无卡顿。
2. **加强躯干内部双舵机并排固定板强度** — 对机身内部两个并排舵机的固定板进行了加厚和加强筋设计，提升受载时的抗扭刚性。
3. **重新建模大腿固件支撑件** — 对大腿固定支撑件进行了全新建模，采用更强的结构设计，改善受力分布并提高打印成功率。
4. **合并脚部组件为单一零件** — 原本为注塑工艺拆分的左右脚两半零件，现已合并为一个整体打印件，充分发挥 3D 打印的设计自由度优势。

---

## Parts List

| # | File Name | Qty | Description |
|---|-----------|-----|-------------|
| 1 | 下巴 | x1 | Chin / Lower beak |
| 2 | 前脸 | x1 | Face plate |
| 3 | 右脚 | x1 | Right foot (merged) |
| 4 | 右脚底板 | x1 | Right foot sole |
| 5 | 右腿内测 | x1 | Right leg inner shell |
| 6 | 右躯干 | x1 | Right torso |
| 7 | 大腿固定件 | x2 | Thigh fixture |
| 8 | 大腿根 | x2 | Thigh root |
| 9 | 大腿轴承固定件 | x2 | Thigh bearing mount |
| 10 | 头内部固定件 | x1 | Head internal mount |
| 11 | 头盖骨 | x1 | Head skull / top shell |
| 12 | 头颈连接件 | x1 | Head-neck connector |
| 13 | 头骨架 | x1 | Head skeleton / frame |
| 14 | 小腿固定件 | x2 | Calf fixture |
| 15 | 左右腿内测 | x2 | Left/right leg inner shell |
| 16 | 左脚 | x1 | Left foot (merged) |
| 17 | 左脚底板 | x1 | Left foot sole |
| 18 | 左腿外侧 | x1 | Left leg outer shell |
| 19 | 左躯干 | x1 | Left torso |
| 20 | 电池支撑架 | x1 | Battery support bracket |
| 21 | 眼圈 | x1 | Eye ring |
| 22 | 舌头 | x1 | Tongue |
| 23 | 踝关节固定件 | x2 | Ankle joint mount |
| 24 | 躯干舵机底座 | x1 | Torso servo base |
| 25 | 颈部连接件 | x2 | Neck connector |
