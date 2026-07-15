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

先保存一次 API key（在[控制台](https://app.qirabot.com)获取）：

```bash
qirabot login
```

然后把任务交给 AI。下面是一次真实运行的完整输出——AI 自己导航、滚动、记录数据，最后按要求整理成表格：

```text
$ qirabot browser "百度热搜中10条热点新闻，以表格形式返回" -l zh
Task: d2631017-2612-4585-bca7-58409b67b9a5
[1/20] navigate
        └ 打开百度热搜页面
[2/20] save_note
        └ 保存当前屏幕可见的百度热搜前几名数据
[3/20] scroll  down 600
        └ 向下滚动以查看更多热搜新闻
[4/20] save_note
        └ 保存第5到第10名的热搜数据
Done: 以下是百度热搜中的热点新闻：

| 排名 | 热搜话题 | 热搜指数 |
| --- | --- | --- |
| 1 | 《功夫女足》换片源 | 7809330 |
| 2 | 富士康打工妹逆袭成中国女首富 | 7714556 |
| 3 | 二季度GDP增长4.3% 怎么看 | 7618975 |
| 4 | 国科大本科录取通知书001号签收 | 7523307 |
| 5 | 克罗地亚正式致函FIFA抗议 | 7427059 |
| 6 | 演员许鹏自曝已返乡卖菜 | 7328813 |
| 7 | 家长月薪3500元请大学生暑假带娃 | 7236804 |
| 8 | 有200台小米设备的“米粉”心凉了 | 7140192 |
| 9 | 安理会通过决议 中俄投了弃权票 | 7040362 |
| 10 | 世界杯：英格兰vs阿根廷 | 6952280 |
```

每次运行都会生成带逐步截图的 HTML 报告，加 `--record` 还能录下整个过程的视频。

## 实战场景：社交媒体运营

以 B 站为例，把日常互动交给一句自然语言指令。`--user-data-dir` 指定一个持久化浏览器 profile：第一次运行中途需要登录时，AI 会自己停下来等你扫码，登录后接着执行。以下是真实运行输出，仅省略了部分中间步骤：

```text
$ qirabot browser --user-data-dir ~/.automation "给B站影视飓风最新发布的视频点赞和评论，如果需要登录，等待我登录后继续，不要结束任务" -l zh
Task: 5947caf9-46fa-4648-83d5-d9c096b525f4
[1/20] navigate
        └ 打开B站官网
[2/20] type_text  ← "影视飓风"
        └ 在搜索框中输入“影视飓风”并回车搜索
        ⋯（略 3 步：进入主页、打开最新视频、尝试点赞）
[6/20] click
        └ 点击右上角的“登录”按钮，因为当前未登录，无法进行点赞和评论。根据用户要求，如果需要登录，
          等待用户登录后继续，不要结束任务。我先点击登录按钮弹出登录框。
[7/20] wait
        └ 已弹出登录二维码和登录框，等待用户扫码或输入账号密码登录。根据指令“如果需要登录，等待我
          登录后继续，不要结束任务”，我将等待10秒，然后检查登录状态。
        ⋯（略 2 步：继续等待登录）
[10/20] click
        └ 用户已成功登录，现在点击点赞按钮给视频点赞。
        ⋯（略 3 步：滚动到评论区并等待加载）
[14/20] type_text  ← "太酷了！支持影视飓风！"
        └ 在评论输入框（“这里是评论区，不是无人区;-)”）中输入评论内容。
[15/20] click
        └ 点击“发布”按钮发表评论。
Done: 已成功给B站影视飓风最新发布的视频点赞，并发表了评论“太酷了！支持影视飓风！”。
```

换个任务再跑一次——同一个 profile，登录态还在，这次全程无人值守：

```text
$ qirabot browser --user-data-dir ~/.automation "给B站影视飓风最新发布的第二个视频点赞和评论" -l zh
Task: f123a9a8-3882-4e61-b354-9c34e8492657
[1/20] navigate
        └ 打开B站官网
        ⋯（略 4 步：搜索、进入主页、打开投稿列表）
[6/20] click
        └ 点击最新发布的第二个视频“去了一趟得克萨斯州。”
[7/20] click
        └ 点击点赞按钮给视频点赞
        ⋯（略 1 步：滚动到评论区）
[9/20] type_text  ← "视频拍得太棒了！支持影视飓风！"
        └ 在评论输入框中输入评论内容并发送
[10/20] click
        └ 点击“发布”按钮发送评论
Done: 已成功给B站影视飓风最新发布的第二个视频点赞并发表评论。
```

凡是"打开网页、看着屏幕操作"的运营流程——发布内容、回复评论、巡检数据——都可以这样写成一句话，配合 crontab 或 CI 定时跑。

## Python SDK

CLI 背后是同一个引擎。用 Python 调用 `bot.ai()`，AI 同样观察屏幕、决策下一步动作、循环执行直到任务完成——区别是结果直接回到你的代码里：

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://top.baidu.com/board?tab=realtime")

result = bot.ai(page, "提取百度热搜中的 10 条热点新闻，以表格形式返回")
print(f"Success: {result.success}")
print(f"Result: {result.output}")

bot.close()
```

想自己控制每一步？同样的自然语言定位也能按单步调用——`bot.click(page, "登录按钮")`、`bot.extract(...)`、`bot.verify(...)`——流程由你的代码掌控。

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
