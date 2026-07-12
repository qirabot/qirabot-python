---
title: 配置
description: Qirabot 的全部配置项——API key 解析顺序、构造函数参数、环境变量、模型档位与按调用覆盖、响应语言、settle 延迟调优。
---

# 配置

跑过 `qirabot login` 就已经配置完成——SDK 读取同一份保存的 key:

```python
from qirabot import Qirabot

bot = Qirabot()  # api_key 参数 > QIRA_API_KEY 环境变量 > `qirabot login` 配置
```

环境变量始终优先于 login 配置(CI 和临时覆盖因此符合直觉)。配置也可以放
项目 `.env`:脚本需显式启用——`from qirabot import load_dotenv;
load_dotenv()`——读取 `$QIRA_DOTENV` 或 `./.env`,且从不覆盖已导出的环境
变量。CLI 自动加载 `.env`;SDK 自身从不读它。

## 构造函数参数

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `api_key` | `QIRA_API_KEY` | `qirabot login` 配置 | API key |
| `base_url` | `QIRA_BASE_URL` | `https://app.qirabot.com` | API 服务器地址 |
| `timeout` | — | `120.0` | HTTP 请求超时(秒) |
| `verify_ssl` | — | `True` | TLS 校验(自托管/自签证书设 `False`) |
| `model_alias` | — | `balanced_pro` | 所有操作的模型档位;`""` = 服务器默认 |
| `language` | — | 服务器默认 | 响应语言,如 `"zh"` / `"en"` |
| `task_name` | — | `""` | 任务名(控制台可见) |
| `report` | — | `True` | 关闭时写 HTML 运行报告 |
| `report_dir` | `QIRA_REPORT_DIR` | `./qira_runs/...` | 报告输出根目录 |
| `record` | `QIRA_RECORD` | `False` | 录屏(ffmpeg) |
| `record_fps` | — | `12` | 录制帧率 |
| `record_window` | `QIRA_RECORD_WINDOW` | `False` | Windows:只录被测窗口 |
| `record_audio` | `QIRA_RECORD_AUDIO` | `False` | Windows:采集系统声音 |
| `record_audio_offset` | `QIRA_AUDIO_OFFSET` | `None` | 音画同步偏移(秒) |
| `record_device` | `QIRA_RECORD_DEVICE` | `False` | 录设备屏幕(adb / Appium) |
| `record_mjpeg_url` | `QIRA_RECORD_MJPEG_URL` | `None` | 录 MJPEG 流(iOS WDA) |
| `screenshot_annotate` | — | `True` | 在点击/输入坐标画红十字线 |
| `screenshot_format` | — | `"jpeg"` | `"jpeg"` 或 `"png"` |
| `screenshot_quality` | — | `80` | JPEG 质量,1–100 |
| `retry` | — | `1` | 瞬时失败的每动作重试次数 |
| `retry_delay` | — | `1.0` | 重试间隔(秒) |
| `settle_seconds` | `QIRA_SETTLE_SECONDS` | 按平台 | 每个动作后等 UI 重绘的暂停 |

## 模型与语言

`model_alias` 决定所有操作背后的模型:

| 档位 | 取舍 |
|---|---|
| `fast` | 最便宜、延迟最低 |
| `balanced` | 质量与成本均衡 |
| `balanced_pro` | 默认——强于 `balanced` |
| `high_quality` | 最高质量、成本最高 |

```python
bot = Qirabot(model_alias="high_quality")        # 全局生效
bot.click(page, "登录", model_alias="fast")      # 或按调用覆盖
```

账号实际可用的档位列表见[控制台](https://app.qirabot.com);留空使用服务
器默认。

`language` 设定 AI 响应(提取文本、推理)的语言——短语言标签如 `"zh"` /
`"en"`:

```python
bot = Qirabot(language="zh")
text = bot.extract(page, "提取主标题", language="zh")
```

## Settle 延迟

每个改变屏幕的动作后,adapter 会短暂停顿,等 UI 重绘后再截下一张图——
否则模型可能截到动画中间帧,误判动作没有生效。默认值按平台调好
(桌面/Android `1.0` 秒,Appium/WDA `0.6` 秒;Playwright 依赖自身的
auto-waiting,不加延迟)。

```python
bot = Qirabot(settle_seconds=1.5)   # 卡顿的远程设备:等久一点
bot = Qirabot(settle_seconds=0.3)   # 流畅的本地应用:快一点
bot = Qirabot(settle_seconds=0)     # 关闭;改用 wait_for()
```

这是一刀切的固定延迟。"等 X 出现"请优先用自动等待的 `timeout=` /
`wait_for()` 轮询——条件一成立立即返回。

## 任务生命周期

每个 `Qirabot` 实例管理一个服务端任务:构造时创建(传已有 `task_id` 可
附加到既有任务),每次调用记录为一个步骤,`close()` / 上下文管理器退出时
标记完成。忘了 `close()` 有 `atexit` 兜底,服务端也会在 30 分钟后清理
孤儿任务。
