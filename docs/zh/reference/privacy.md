---
title: 数据与隐私
description: Qirabot 具体上传什么(截图、指令、步骤元数据)、什么永不离开你的机器(代码、cookie、凭据)、服务端存什么,以及只存本地的报告文件。
---

# 数据与隐私

Qirabot 是视觉服务:模型需要看到屏幕,除此之外什么都不需要。本页明确
说明哪些数据会经过网络。

## 会上传什么

每个 AI 步骤发送到 Qirabot 服务端的内容:

- 绑定目标的**截图**(默认 JPEG、质量 80——`screenshot_format` /
  `screenshot_quality` 见[配置](/zh/advanced/configuration)),
- 你的**指令文本**(自然语言描述或任务),
- **步骤元数据**(动作类型、参数、耗时)。

## 什么永不离开你的机器

- **你的代码。** 服务端只返回坐标和决策;动作通过你的框架或 adapter 在
  本地执行。
- **Cookie、凭据、会话状态。** Qirabot 驱动你的浏览器或设备,不读取也
  不传输它们的存储。
- **自定义工具。** 通过 `custom_tools` 传入的函数在本地运行——你的接口
  地址、token、数据库服务端一概看不到,只有工具的字符串返回值会反馈给
  模型。见 [AI 任务与自定义工具](/zh/advanced/ai-tasks)。

## 服务端存什么

每次运行对应一个服务端任务:名称、状态、步骤和步骤截图——这就是
[控制台](https://app.qirabot.com)展示、`qirabot task <id>` /
`qirabot screenshot <id>` 能取到的内容。未经 AI 的本地步骤也会补传到同
一时间线以保持完整;用 `Qirabot(sync_local_steps=False)` 可关闭。

## 什么只存本地

[HTML 报告](/zh/advanced/reports)(`report.html`、全分辨率
`screenshots/`、`recording.mp4`)写入你机器上的 `./qira_runs/`,完全自
包含、不发起任何网络请求。`report=False` 可整体关闭。

## 传输

所有流量走 HTTPS 到 `app.qirabot.com`(或你自己的 `base_url`)。证书校
验默认开启;`verify_ssl=False` 仅用于自建 / 自签名场景。
