---
title: Python AI 浏览器自动化(Playwright)——不写选择器
description: 用 AI 视觉代替 CSS 选择器驱动 Chrome——Qirabot 可自动启动 Chromium,也能挂载到你现有的 Playwright 或 Selenium 会话。支持 headless、持久化 profile、CDP 接管。
---

# 浏览器自动化

Qirabot 通过**像素而非 DOM** 驱动浏览器。AI 像人一样阅读渲染后的页面,
所以选择器方案会挂的地方它都能工作:canvas 应用、跨域 iframe、shadow
DOM、频繁 A/B 测试的布局,以及改版速度快过测试套件的页面。

可以让 Qirabot 托管浏览器,也可以挂载到你已有的 Playwright / Selenium
会话上。

## 托管浏览器

`bot.open()` 自动启动 Chromium(底层为 Playwright)——你不需要写任何框架
代码:

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://news.ycombinator.com")

result = bot.ai(page, "打开热度最高的帖子并总结讨论内容")
print(result.output)

bot.close()
```

需要 `browser` extra:`pip install "qirabot[browser]"`,然后
`qirabot install-browser`。

CLI 一条命令等价运行:

```bash
qirabot browser "打开热度最高的帖子并总结讨论内容" --url news.ycombinator.com
qirabot browser "..." --headless --viewport 1920x1080
qirabot browser "..." --user-data-dir ~/.qira-profile --channel chrome   # 登录态跨运行保留
qirabot browser "..." --cdp-url http://localhost:9222                    # 接管已运行的 Chrome
```

`--cdp-url` 也适用于 browserless 之类的远程浏览器池。

## 挂载 Playwright

传入你已有的 `page`——你的选择器和 AI 步骤自由混用:

```python
from playwright.sync_api import sync_playwright
from qirabot import Qirabot

bot = Qirabot()

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://github.com/trending")

    repos = bot.extract(page, "提取前 5 个热门仓库的名字")
    print(repos)

    browser.close()
bot.close()
```

Playwright 建议保持显式写法 `page = bot.click(page, ...)`——点击可能打开
新标签页,返回值就是后续原生 `page.fill(...)` 应该使用的那个 page。
`bot.go_back()` 对此有智能处理:如果点击在新标签页打开了链接(新标签页
没有历史),它会关闭该标签页回到上一个,所以常见的"打开条目、返回列表"
循环可以直接写:

```python
for i in range(4):
    page = bot.click(page, locate=f"打开第 {i + 1} 个视频")  # 可能打开新标签页
    bot.screenshot(page)
    page = bot.go_back(page)                                  # 关闭它,回到列表
```

## 挂载 Selenium

```python
from selenium import webdriver
from qirabot import Qirabot

driver = webdriver.Chrome()
driver.get("https://www.wikipedia.org")
bot = Qirabot().bind(driver)   # bind 一次;driver 在整个会话中稳定

summary = bot.extract("提取词条的第一段")
print(summary)

driver.quit()
bot.close()
```

Selenium 不是 extra——自带 driver 即可(`pip install qirabot selenium`)。

## 在 pytest 套件中

保留现有选择器和驱动代码,只在容易失效的地方换上 AI 断言和 AI 步骤:

```python
from qirabot import Qirabot

bot = Qirabot(task_name="test-checkout")

def test_checkout(page):          # 你现有的 pytest-playwright fixture
    page.goto("https://shop.example.com")

    page.fill("#username", "test_user")     # 你的选择器,原样保留
    page.fill("#password", "secret")
    page.click("#login-btn")

    # AI 断言——不需要知道具体文案或选择器
    assert bot.verify(page, "商品列表页已显示")

    result = bot.ai(page, "完成结算,姓名 John Doe,邮编 10001", max_steps=8)
    assert result.success
```

## 说明

- headless 检测:无显示器环境(无 `DISPLAY`)下,`bot.open()` 和 CLI 自动
  切换 headless 并给出警告。
- `close_tab` 仅 Playwright 支持;`navigate`、`go_back`、`press_key`(含
  `ctrl+t`/`ctrl+w` 切换标签页——记得重新赋值返回的 page)和 `scroll` 均可
  用。完整的平台动作矩阵见 [API 参考](/zh/reference/api#平台支持矩阵)。
