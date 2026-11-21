# MicroDuck 手机中控 · console-apk

把桌面中控 [`firmware/console`](../firmware/console) 打进 Android APK：本机跑 Python 中控（8090），WebView 打开管理页；另提供蓝牙 HID 手柄页，伪装成 GameSir-Nova 2 Lite 给鸭子配对。

## 与桌面中控的关系

| 部分 | 来源 |
| --- | --- |
| 管理页（标定、BoBo 关键词/幅度、固件、网页手柄等） | 构建时打包 `firmware/console` → `console-runtime.zip` |
| 蓝牙实体手柄页 | `lib/pad_page.dart` + HID 报告 |
| 局域网扫 SSH | `lib/lan_scan.dart`（与 `firmware/console/lan_scan.py` 同策略） |

**更新桌面中控后重新构建 APK**，就会带上最新 console（含 BoBo R3/菜单键、关键词表、头部幅度、R18 模式切换等）。

## 构建

```bash
cd 03-DuckCode/microduck-hd1910/console-apk
flutter pub get
flutter build apk
```

Gradle 的 `packConsole` 会在合并 assets 前把 `../firmware/console` 打成 zip。路径相对 `console-apk/android`。

## 使用要点

1. 打开 App →「管理」等本机中控起来（`http://127.0.0.1:8090`）。
2. 可扫局域网填入 `radxa@IP`，连鸭子 SSH。
3. 「手柄」页开启蓝牙，保持前台；中控「手柄修复」勾选首次配对。手机名应为 **GameSir-Nova 2 Lite**。
4. **对话**按钮发 R3（右摇杆按下），与桌面中控网页手柄一致，接通/挂断 BoBo（需鸭子已配 `[bobo]`）。

专家模式开关与设置齿轮点的是 WebView 里的 `#bobo-expert` / `#settings-button`。
