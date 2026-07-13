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
    # 构造函数本身就可能抛异常:它会校验 API key 并向服务器注册任务。
    # `with` 保证 close() 在——且仅在——构造成功时执行。
    with Qirabot() as bot:
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
```

完整体系——所有异常都派生自 `QirabotError`,所以单独一个
`except QirabotError` 永远是安全的兜底:

| 异常 | 时机 |
|---|---|
| `AuthenticationError` | API key 缺失或无效(401)。不重试。 |
| `InsufficientBalanceError` | 积分余额耗尽(402)。不重试。 |
| `RateLimitError` | 请求过多(429)。SDK 内部会退避并重试;捕获它可加自己的退避策略。 |
| `QirabotTimeoutError` | 客户端等待超时(`wait_for`、自动等待)。 |
| `QirabotConnectionError` | 服务器不可达(DNS 解析失败、连接被拒)——请求根本没有完成,而不是慢。 |
| `TaskTerminatedError` | 脚本还在运行时任务被服务端终止(控制台停止、孤儿清理器、最长时长上限)。`.task_status` 携带终态。不重试。 |
| `ActionError` | AI 动作在服务端执行失败。 |
| `MissingDependencyError` | 某个可选后端依赖(playwright、pyautogui 等)未安装——消息里给出要执行的确切 `pip install "qirabot[<extra>]"`。同时也是 `ImportError`。 |

`verify()` 是"失败即抛异常"语义的刻意例外:**断言不成立**不抛异常——
返回 falsy 结果(`VerifyResult`,其 `.reason` 说明原因),可直接用于
`assert` 或 `if`。传输和服务器错误(连接丢失、鉴权、终止)仍像其他调用
一样抛出。

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
