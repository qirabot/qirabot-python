---
title: 配合 AI Agent 使用——Claude Code 插件与 Agent 友好的 CLI
description: 让 AI agent 通过 Qirabot 驱动 GUI——Claude Code 插件(qirabot skill、preflight 环境检查、起步模板),以及供任意 agent 使用的 llms.txt 与退出码友好的 CLI。
---

# 配合 AI Agent 使用

Qirabot 不只是一个供你编码调用的库——它也是 AI agent 可以直接拾起的能力。
对你的 agent 说"自动化这个注册流程,并验证确认邮件页面",让它自己写脚本、
自己运行。两条路:

## Claude Code 插件

[qirabot 插件](https://github.com/qirabot/claude-plugins)打包了一个 Agent
Skill,教会 Claude Code 端到端地操作 Qirabot。安装一次:

```text
/plugin marketplace add qirabot/claude-plugins
/plugin install qirabot@qirabot
```

之后凡是涉及自动化、测试或抓取 UI 的任务,Claude 会自动调用该 skill(也
可以显式调用 `/qirabot:qirabot`)。skill 自带:

- **preflight 脚本** —— 在写任何代码*之前*检查 Python 环境、后端依赖和
  API key,缺什么直接给出修复命令。不再出现跑到第三步才失败的脚本。
- **精简版 SDK + CLI 参考** —— agent 照着准确的 API 写代码,而不是靠猜。
- **起步模板** —— 浏览器、Android(adb)、iOS(WDA 与 Appium)、自带
  driver 挂载各一份,agent 改一个能跑的骨架,而不是从零开始。

插件只包含指令和辅助脚本;`qirabot` 包本身由 preflight 在运行时引导安装。

## 任意其他 agent(Cursor、Copilot 等)

两个特性让任意 agent 都容易驱动 Qirabot:

**CLI 天然就是 agent 工具。** 一条 shell 命令跑完整个自然语言任务,一次性
工作根本不需要生成代码:

```bash
qirabot browser "以 Jane Doe 填写注册表单,遇到验证码停下" --url example.com
```

退出码可机读(`0` 成功、`1` 失败、`130` 中断),每次运行都写出带逐步截图
的 [HTML 报告](/zh/advanced/reports),出错时 agent(或你)可以直接翻看。
全部命令见 [CLI 参考](/zh/guide/cli)。

**文档对 agent 可读。** 把这些地址喂给你的 agent:

- `https://qirabot.com/docs/llms.txt` —— 索引 + 每页摘要
- `https://qirabot.com/docs/llms-full.txt` —— 全部文档合成一个文件
- 任何页面把 `.html` 换成 `.md` 即得纯 Markdown,例如
  `https://qirabot.com/docs/reference/methods.md`

Cursor 里用 `@Docs` 功能添加;其他工具在 rules 文件里引用这些 URL,或直接
贴进上下文。

## 为什么 agent 和视觉自动化是天作之合

agent 写 Playwright 仍然要猜它看不见的选择器,而且下次改版就断。用
Qirabot,agent 以它本来的推理方式——语言——描述元素;同一个 skill 还覆盖
代码优先方案够不到的地方:原生移动 App、桌面软件、游戏。见
[Qirabot 是什么](/zh/)和[平台支持矩阵](/zh/reference/api#平台支持矩阵)。
