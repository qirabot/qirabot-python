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
| `model_alias` | — | `""` | 所有操作的模型档位;留空 = 由服务器选默认 |
| `language` | — | 服务器默认 | 响应语言,如 `"zh"` / `"en"` |
| `task_name` | — | `""` | 任务名(控制台可见) |
| `task_id` | — | `""` | 附加到已有的服务端任务,而不是新建 |
| `source` | — | `"sdk"` | 控制台显示的任务来源标签 |
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
| `retry` | — | `1` | 瞬时失败的每动作重试次数(也可按调用传:`bot.click(..., retry=3)`) |
| `retry_delay` | — | `1.0` | 重试间隔(秒) |
| `settle_seconds` | `QIRA_SETTLE_SECONDS` | 按平台 | 每个动作后等 UI 重绘的暂停 |
| `heartbeat` | `QIRA_HEARTBEAT` | `True` | 后台存活心跳,长时间休眠的脚本不会被当作孤儿回收;`QIRA_HEARTBEAT=0` 可一键关闭 |
| `sync_local_steps` | — | `True` | 把本地执行的步骤上传到服务端任务时间线 |

`record*` 各开关实际产出什么(格式、各平台机制、文件落在哪)见
[报告与录屏](/zh/advanced/reports)。

少数只有环境变量、没有构造参数对应的覆盖项:`QIRA_ADB_PATH`(Android
后端显式指定 adb 可执行文件)、`QIRA_SCREEN_INDEX`(多显示器机器上录哪块
屏)、`QIRA_AUDIO_DEVICE`(录音的音频设备)、`QIRA_DOTENV`
(`load_dotenv()` 读取的路径,替代 `./.env`)。

## 模型与语言

`model_alias` 决定所有操作背后的模型:

| 档位 | 取舍 |
|---|---|
| `fast` | 最便宜、延迟最低 |
| `balanced` | 质量与成本均衡 |
| `balanced_pro` | 强于 `balanced` |
| `high_quality` | 最高质量、成本最高 |

```python
bot = Qirabot(model_alias="high_quality")        # 全局生效
bot.click(page, "登录", model_alias="fast")      # 或按调用覆盖
```

模型托管在服务端——没有 API key 或 endpoint 需要配置,各档位背后的具体
模型由平台管理(并持续升级)。`qirabot models` 列出你的账号可用的档位;
档位留空则使用服务器默认。

**什么时候选哪个档位?**经验法则:

- **先不设置**,除非有明确理由——服务器默认档位已为通用场景调优。
- **`fast`**——干净、高对比度、目标明确的界面:表单填写、标准 web
  流程、大按钮。最便宜、延迟最低。
- **`high_quality`**——密集或低对比度的画面:小字号、拥挤的仪表盘、
  游戏 UI、细微的视觉断言(“图标是置灰的”)。
- **按调用混用**——既压低成本又不牺牲准确率的模式:bot 默认用便宜
  档位,只给难的调用升档:

```python
bot = Qirabot(model_alias="fast")
bot.click(page, "搜索按钮")                                 # 简单 → fast
data = bot.extract(page, "结果表格里的所有价格",
                   model_alias="high_quality")              # 难 → 升档
```

**关注成本:**`extract()` / `verify()` 的结果和 `ai()` 的每个
`StepResult` 都带有 `input_tokens` / `output_tokens` 字段——一次调用的
花费就是两者之和。见[方法参考](/zh/reference/methods#结果对象)。

`language` 设定 AI 响应(提取文本、推理)的语言——短语言标签如 `"zh"` /
`"en"`:

```python
bot = Qirabot(language="zh")
text = bot.extract(page, "提取主标题", language="zh")
```

## Settle 延迟

每个改变屏幕的动作后,adapter 会短暂停顿,等 UI 重绘后再截下一张图——
否则模型可能截到动画中间帧,误判动作没有生效。默认值按平台调好
(桌面/Android `1.0` 秒,Selenium/Appium/WDA `0.6` 秒;Playwright 依赖自身的
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
标记完成。忘了 `close()` 有 `atexit` 兜底;进程运行期间后台心跳会保持
任务在线,悄然死掉的进程由服务端孤儿清理器约 5 分钟后回收。要以失败或
取消而非完成结束任务,见
[API 参考](/zh/reference/api#任务生命周期)中的 `fail()` / `cancel()`。
