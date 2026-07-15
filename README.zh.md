# Qirabot Python SDK

[English](README.md) | 简体中文

跨平台 GUI 自动化，由多模态 AI 视觉驱动。像人一样识别屏幕画面并直接操作浏览器、手机 App、整个桌面与游戏——无需 DOM、无需选择器——覆盖 Playwright / Selenium / Appium 这类框架无法触及的场景。

既可独立运行（`bot.open()` 自动启动浏览器；Android / iOS / Windows 窗口后端内置，零额外依赖），也可接入你现有的 Playwright / Selenium / Appium / pyautogui 会话、嵌入 pytest 测试套件，或按 HWND 绑定窗口驱动 Unity / Unreal / 原生桌面游戏。所有平台共用同一套 API。

**📖 完整文档：[qirabot.com/docs/zh](https://qirabot.com/docs/zh/)**

## 效果演示

真实、未剪辑的运行记录——AI 全程只看屏幕画面。点击封面观看（[全部 demo →](https://qirabot.com/?lang=zh#demos)）：

[![《梦幻西游》手游：从创号自动玩到 15 级](https://assets.qirabot.com/demos/mhxy_zero_to_15.poster.webp)](https://qirabot.com/?lang=zh#demos)

**《梦幻西游》手游：从创号自动玩到 15 级** — iOS 真机 ·
[脚本](examples/game/ios_appium_mmorpg.py)

<table>
  <tr>
    <td align="center" width="33%">
      <a href="https://qirabot.com/?lang=zh#demos"><img src="https://assets.qirabot.com/demos/afk_journey_tutorial.poster.webp" alt="《剑与远征：启程》创号通关新手教程，进入大世界"></a>
      <br><b>《剑与远征：启程》创号通关新手教程，进入大世界</b> — iOS 真机
    </td>
    <td align="center" width="33%">
      <a href="https://qirabot.com/?lang=zh#demos"><img src="https://assets.qirabot.com/demos/lichess_play_chess.poster.webp" alt="在 lichess.org 上对弈国际象棋"></a>
      <br><b>在 lichess.org 上对弈国际象棋</b> — Android 真机
    </td>
    <td align="center" width="33%">
      <a href="https://qirabot.com/?lang=zh#demos"><img src="https://assets.qirabot.com/demos/tile_match_game.poster.webp" alt="自主通关水果连连消手游"></a>
      <br><b>自主通关水果连连消手游</b> — Android 真机
    </td>
  </tr>
</table>

## 安装

一行命令——自动安装 [uv](https://docs.astral.sh/uv/)、qirabot（隔离环境，不改动系统 Python）和 Chromium，无需预装 Python：

```bash
# macOS / Linux
curl -LsSf https://qirabot.com/install | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://qirabot.com/install.ps1 | iex"
```

需要驱动设备而不是浏览器？Android（adb）、iOS（WDA）、Windows 单窗口后端均内置于核心包：

```bash
uv tool install qirabot        # Android + iOS + Windows 窗口；零额外依赖
```

pip、虚拟环境、各框架 extras 与故障排查见[安装指南](https://qirabot.com/docs/zh/guide/installation.html)。安装完成后运行 `qirabot doctor`，它会报告已安装与缺失的组件（并给出对应的修复命令），以及 API key 能否连通服务器。

## 快速上手

先保存一次 API key（在[控制台](https://app.qirabot.com)获取），然后把任务交给 AI：

```bash
qirabot login
qirabot browser "搜索 SpaceX，返回词条的第一句话" --url wikipedia.org
```

同一个任务用 Python SDK 实现——`bot.ai()` 是同一个引擎：AI 观察屏幕、决策下一步动作、循环执行直到任务完成：

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://www.wikipedia.org")

result = bot.ai(page, "搜索 SpaceX，返回词条的第一句话")
print(f"Success: {result.success}")
print(f"Result: {result.output}")

bot.close()
```

想自己控制每一步？同样的自然语言定位也能按单步调用——`bot.click(page, "登录按钮")`、`bot.extract(...)`、`bot.verify(...)`——流程由你的代码掌控。每次运行都会生成带逐步截图的 HTML 报告；`--record` 可录制视频。

也无需重写任何代码：将现有的 `page` / `driver` / 设备对象直接传入，即可在原有选择器脚本中混用 AI 步骤（视觉断言、动态控件、逐步脚本化过于繁琐的流程）——Playwright / Selenium / Appium / pyautogui 及内置设备后端均适用，详见[框架集成文档](https://qirabot.com/docs/zh/frameworks/playwright.html)。

## 自定义工具：让 AI 调用你的代码

任务执行中，AI 不只会点击和输入。`custom_tools` 可以把普通 Python 函数注册为模型可调用的工具——调内部 API、查数据库、从邮箱取验证码、造测试数据，或在遇到 CAPTCHA 时暂停等人工处理。工具的名称、描述和参数会自动从函数本身提取：

```python
def gm_command(command: str) -> str:
    """向游戏 GM 后台发送命令并返回结果。
    可用命令：add_energy <数量>、add_gold <数量>"""
    return requests.post(GM_URL, json={"cmd": command}, timeout=10).text

result = bot.ai(
    device,
    "完成所有日常任务。如果弹出体力不足的提示，"
    "就用 gm_command 加 100 体力后继续",
    custom_tools=[gm_command],
)
```

工具**在你的本地机器上执行**——服务端接触不到你的接口和凭据——返回值会作为模型下一步的观察结果。过去需要一整页胶水代码串联的跨系统流程（UI 操作、后端调用、人工介入），现在一句指令就能覆盖。更多细节（schema、错误处理、裁剪内置工具）见[AI 任务与自定义工具](https://qirabot.com/docs/zh/advanced/ai-tasks.html)；可运行示例：[custom_tool_gm.py](examples/game/custom_tool_gm.py) · [06_human_in_the_loop.py](examples/automation/06_human_in_the_loop.py)。

## 文档

| 主题 | |
|---|---|
| 入门 | [安装](https://qirabot.com/docs/zh/guide/installation.html) · [快速上手](https://qirabot.com/docs/zh/guide/quickstart.html) · [CLI 参考](https://qirabot.com/docs/zh/guide/cli.html) |
| 支持平台 | [浏览器](https://qirabot.com/docs/zh/backends/browser.html) · [Android（adb，免 Appium）](https://qirabot.com/docs/zh/backends/android.html) · [iOS（WDA，免 Appium）](https://qirabot.com/docs/zh/backends/ios.html) · [Windows 与游戏（DirectInput）](https://qirabot.com/docs/zh/backends/windows-games.html) · [桌面](https://qirabot.com/docs/zh/backends/desktop.html) · [自定义 Adapter](https://qirabot.com/docs/zh/backends/custom-adapters.html) |
| 框架集成 | [Playwright](https://qirabot.com/docs/zh/frameworks/playwright.html) · [Selenium](https://qirabot.com/docs/zh/frameworks/selenium.html) · [Appium](https://qirabot.com/docs/zh/frameworks/appium.html) · [pytest](https://qirabot.com/docs/zh/frameworks/pytest.html) |
| 进阶 | [AI 任务与自定义工具](https://qirabot.com/docs/zh/advanced/ai-tasks.html) · [报告与录屏](https://qirabot.com/docs/zh/advanced/reports.html) · [配置](https://qirabot.com/docs/zh/advanced/configuration.html) · [错误处理](https://qirabot.com/docs/zh/advanced/error-handling.html) |
| 参考 | [API——动作与平台矩阵](https://qirabot.com/docs/zh/reference/api.html) |

## 示例

可直接运行的示例在 [examples/](examples/)：pytest 集成（Playwright / Selenium / Appium / 桌面）、独立自动化脚本（爬取 / RPA / agent），以及游戏驱动（Windows 桌面游戏 + demo 视频背后的 iOS 手游脚本）。选择指南见 [examples/README.md](examples/README.md)。

## Agent Skill

`plugins/qirabot/skills/qirabot/` 是预置的 agent skill：AI agent（Claude Code、Cursor 等）加载后，可以从一句自然语言的自动化目标出发，自主完成环境搭建、脚本编写和验证。在 Claude Code 中安装：

```text
/plugin marketplace add qirabot/claude-plugins
/plugin install qirabot@qirabot
```

详见 [plugins/qirabot/README.md](plugins/qirabot/README.md)。

## 从 1.x（airtest）迁移

2.0 移除了 airtest 集成；内置后端（`AdbDevice` / `WdaClient` / `Window`）可直接替换，同时提供一份可复制的 adapter，让现有 airtest 脚本无需改动即可继续运行。指南：[自定义 Adapter——从 Airtest 迁移](https://qirabot.com/docs/zh/backends/custom-adapters.html#从-airtest-迁移-qirabot-1-x)。1.x 系列在 [`1.x` 分支](https://github.com/qirabot/qirabot-python/tree/1.x)进入维护模式，`pip install "qirabot<2"` 始终解析到最新的 1.9.x 补丁版本。

## 许可证

MIT
