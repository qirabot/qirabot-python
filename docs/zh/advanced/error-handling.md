---
title: 错误处理与运行结果
description: Qirabot 的异常体系、ai() 运行的四种 result.status 结果、max_steps 重试模式、动作自动重试,以及失败在 HTML 报告中的呈现。
---

# 错误处理

## 异常

```python
from qirabot import (
    Qirabot,
    QirabotError,              # 基类
    AuthenticationError,       # API key 无效
    InsufficientBalanceError,  # 积分不足
    QirabotTimeoutError,       # wait_for / 自动等待超时
)

try:
    bot = Qirabot()
    page = bot.open("https://example.com")
    bot.click(page, "登录按钮")
except AuthenticationError:
    print("API key 无效。")
except InsufficientBalanceError:
    print("积分不足。")
except QirabotTimeoutError:
    print("操作超时。")
except QirabotError as e:
    print(f"错误: {e}")
finally:
    bot.close()
```

`verify()` 是"失败即抛异常"的刻意例外:它返回 `True`/`False`、从不抛异常
——最适合 `assert`。

瞬时的动作失败会自动重试(默认 `retry=1`、`retry_delay=1.0`——见
[配置](/zh/advanced/configuration))。

## ai() 运行如何结束:result.status

`result.success` 是二值判定,但失败的运行可能意味着很不一样的事情:

| status | 含义 | `success` |
|---|---|---|
| `"completed"` | 模型判定目标已达成 | `True` |
| `"goal_failed"` | 模型判定目标不可达(登录墙、验证码) | `False` |
| `"max_steps"` | 步数预算用尽——是截断,不是能力判定 | `False` |
| `"error"` | 服务器报告终止性错误 | `False` |

`max_steps` 值得专门处理——它是预算问题,不是能力问题:

```python
result = bot.ai(page, "找到最便宜的航班并锁定")
if result.status == "max_steps":
    # 不是真的失败——预算太小;加大步数重试
    result = bot.ai(page, "找到最便宜的航班并锁定", max_steps=50)
```

`goal_failed` 通常意味着环境需要帮助——登录墙或验证码。可以考虑
[人工介入的自定义工具](/zh/advanced/ai-tasks#人工介入-human-in-the-loop),
让模型求助而不是放弃。

## 失败在报告中的呈现

以抛异常结束的运行不会产生 `RunResult`;在 [HTML 报告](/zh/advanced/reports)
里对应区块的徽章是 `ERROR`。报告在**异常和 Ctrl+C 之后也会写出**,包含
直到失败为止的逐步截图——通常是看清屏幕上到底发生了什么的最快方式。

报告头部的汇总:全部通过为绿色,只有 `MAX STEPS` 截断为琥珀色,存在真正
失败为红色。

## 自定义工具的错误

自定义工具抛异常不会杀死运行:异常以 `ERROR: ...` 回报给模型,模型可以
应对——重试、换路径,或以 `goal_failed` 结束。见
[AI 任务与自定义工具](/zh/advanced/ai-tasks)。
