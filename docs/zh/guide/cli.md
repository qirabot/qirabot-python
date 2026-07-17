---
title: CLI 参考
description: 在命令行运行自然语言 GUI 自动化任务——browser、android、ios、desktop 四个子命令,录屏、报告与脚本友好的退出码。
---

# CLI 参考

`qirabot` 命令不写 Python 就能端到端运行任务,随核心包安装。`android`、
`ios` 和 `desktop --window-title/--hwnd` 走内置后端——无需 extras。只有
`browser`(`qirabot[browser]`)、全屏 `desktop`(`qirabot[desktop]`)和
Appium 引擎(`qirabot[appium]`)需要对应 extra。

```bash
# 浏览器(需要 qirabot[browser] + `playwright install chromium`)
qirabot browser "搜索 SpaceX 并提取词条的第一句话" --url wikipedia.org

# 浏览器——headless/视口;持久化 profile;或经 CDP 接管已运行的 Chrome
qirabot browser "..." --headless --viewport 1920x1080
qirabot browser "..." --user-data-dir ~/.qira-profile --channel chrome
qirabot browser "..." --cdp-url http://localhost:9222

# Android——adb 直连(内置;只需 adb 二进制,无需服务器)
qirabot android "打开设置并开启飞行模式"
qirabot android "..." -d emulator-5554 --app-package com.android.settings

# iOS——直连 WebDriverAgent(内置;WDA 需运行在 :8100)
qirabot ios "在微信里给 Alice 发一句 hi" --bundle-id com.tencent.xin

# 两者也可改走 Appium 服务器(需要 qirabot[appium])
qirabot android "..." --appium-url http://localhost:4723
qirabot ios "..." --device "iPhone 15"   # 仅模拟器(选择 Appium 引擎)

# 桌面(pyautogui,需要 qirabot[desktop])
qirabot desktop "新建一条标题为 Groceries 的备忘录" --app Notes

# 绑定单个 Windows 窗口(内置)——DirectInput 扫描码输入
qirabot desktop "打开背包并列出所有物品" --window-title "Genshin"
qirabot desktop "..." --hwnd 132456

# 环境自检——装了什么、缺什么、服务器是否可达
qirabot doctor

# 只读服务器查询
qirabot task <task_id>            # 状态、指令、步骤
qirabot screenshot <task_id>      # 下载截图
qirabot models                    # 列出模型档位
```

## 命令一览

| 命令 | 用途 |
|---|---|
| `browser 指令` | 在本地浏览器运行 AI 任务([浏览器后端](/zh/backends/browser)) |
| `android 指令` | 在 Android 设备运行 AI 任务([adb 直连](/zh/backends/android),内置;`--appium-url` 走 Appium) |
| `ios 指令` | 在 iOS 设备运行 AI 任务([WDA 直连](/zh/backends/ios),内置;`--appium-url`/`--device` 走 Appium) |
| `desktop 指令` | 在[桌面](/zh/backends/desktop)运行 AI 任务(pyautogui;`--window-title`/`--hwnd` 绑定[单个 Windows 窗口](/zh/backends/windows-games),内置) |
| `login` | 浏览器授权登录并保存 API key(`--paste` 手动粘贴,`--status` 查看当前生效的 key,已脱敏) |
| `install-browser` | 一次性下载浏览器后端所需的 Chromium |
| `doctor` | 检查 Python、API key/服务器与各后端依赖 |
| `task TASK_ID` | 打印任务状态、指令与步骤 |
| `screenshot TASK_ID` | 下载任务截图 |
| `models` | 列出可用模型档位 |

## 全局选项

全局选项写在**子命令之前**(用于配置连接):

```bash
qirabot --api-key qk_... --base-url https://app.qirabot.com browser "..."
```

API key 的解析顺序:`--api-key` 参数 > `QIRA_API_KEY` 环境变量 > 项目
`.env` > `qirabot login` 配置文件。`qirabot login --status` 可查看当前生效
的是哪一层。另有 `--timeout`、`--verify-ssl` / `--no-verify-ssl`、
`--version`。

## 退出码

脚本友好:`0` 任务成功,`1` 任务失败或出错,`130` Ctrl+C 中断——因此
`qirabot browser "..." && next-step` 只在成功时继续。

## 通用运行选项

`browser` / `android` / `ios` / `desktop` 均支持:

| 选项 | 默认值 | 作用 |
|---|---|---|
| `-n, --name` | 从指令推导 | 网页控制台中显示的任务名 |
| `-m, --model` | 服务器默认 | 模型档位(见[配置](/zh/advanced/configuration)) |
| `-l, --language` | 服务器默认 | 响应语言,如 `zh`、`en` |
| `--max-steps` | `20` | AI 任务的步数预算 |
| `--report / --no-report` | 开 | 写 HTML 运行报告 |
| `--report-dir` | `./qira_runs/...` | 报告输出根目录(环境变量 `QIRA_REPORT_DIR`) |
| `--annotate / --no-annotate` | 开 | 在保存的截图上用十字线标注点击/输入坐标 |
| `--record` | 关 | 把运行录制为 `recording.mp4`(见下) |

## 各命令专属选项

**`browser`** —— 见[浏览器后端](/zh/backends/browser):

| 选项 | 默认值 | 作用 |
|---|---|---|
| `-u, --url` | — | 要打开的 URL(省略则由 AI 自行导航) |
| `--headless` | 关 | headless 模式(无显示器时自动开启) |
| `--viewport` | `1280x800` | 视口,格式 `宽x高`(`WIDTHxHEIGHT`) |
| `--channel` | 自带的 Chromium | 使用已安装的浏览器:`chrome`、`msedge` 等 |
| `--user-data-dir` | — | 持久化 profile 目录(cookie/登录态跨运行保留) |
| `--browser-arg` | — | 额外的 Chromium 启动参数,可重复 |
| `--cdp-url` | — | 经 CDP 接管已运行的 Chrome;与上面四个选项互斥 |

**`android`** —— 见 [Android 后端](/zh/backends/android):

| 选项 | 默认值 | 作用 |
|---|---|---|
| `-d, --device` | 唯一已连接的设备 | `adb devices` 里的 adb serial |
| `--app-package` | — | 要启动的应用包名(如 `com.android.settings`) |
| `--app-activity` | — | 要启动的应用 activity |
| `--appium-url` | adb 直连,无服务器 | 传入即切换到 [Appium 引擎](/zh/frameworks/appium) |
| `--record` | 关 | 录制**设备**屏幕(adb screenrecord / Appium API) |

**`ios`** —— 见 [iOS 后端](/zh/backends/ios):

| 选项 | 默认值 | 作用 |
|---|---|---|
| `--wda-url` | `http://127.0.0.1:8100` | WebDriverAgent 地址——由它选择设备(USB 真机:`iproxy 8100 8100`) |
| `--bundle-id` | — | 要启动的应用 bundle id(如 `com.tencent.xin`) |
| `--device` | — | `xcrun simctl list devicetypes` 里的模拟器设备类型——切换到 Appium 引擎,仅模拟器(无 `-d` 简写:切换引擎应显式写全) |
| `--appium-url` | WDA 直连,无服务器 | Appium 服务器地址(配合 `--device`) |
| `--record` | 关 | 录制**设备**屏幕(WDA MJPEG + ffmpeg / Appium API) |
| `--mjpeg-url` | `--wda-url` 主机的 9100 端口 | `--record` 的 MJPEG 流覆盖地址 |

**`desktop`** —— 见[桌面](/zh/backends/desktop)与
[Windows 与游戏](/zh/backends/windows-games):

| 选项 | 默认值 | 作用 |
|---|---|---|
| `--app` | — | 先启动/激活应用(macOS:名称或 bundle id;Windows:exe/注册名/UWP id;Linux:可执行文件) |
| `--app-wait` | `2.0` | `--app` 之后等窗口出现的秒数 |
| `--window-title` | — | 绑定标题匹配该正则的窗口(Windows 窗口后端) |
| `--hwnd` | — | 绑定窗口句柄,十进制(Windows 窗口后端) |

**`screenshot TASK_ID`** —— `-s/--step`(0 = 最新)、`-o/--output`、
`-f/--force`(覆盖)。

`--record` 把 `recording.mp4` 存入运行目录并嵌入 HTML 报告。录制对象因
平台而异:

- `browser` / `desktop` —— 用 ffmpeg 录制**宿主机**屏幕(ffmpeg 需在
  PATH)。绑定窗口时(`--window-title`/`--hwnd`)只录该窗口。
- `android` —— 录制**设备**屏幕:默认引擎用 `adb screenrecord`,Appium
  引擎用其录屏 API。
- `ios` —— 录制**设备**屏幕:默认引擎用 WDA 的 MJPEG 流(需要 ffmpeg;
  USB 真机还需 `iproxy 9100 9100`),Appium 引擎用其录屏 API。

录制机制、报告结构与音频采集见
[报告与录屏](/zh/advanced/reports)。运行同样遵循 SDK 的环境变量——
`QIRA_REPORT_DIR`、`QIRA_SETTLE_SECONDS`、`QIRA_RECORD*` 等;完整清单见
[配置](/zh/advanced/configuration)。
