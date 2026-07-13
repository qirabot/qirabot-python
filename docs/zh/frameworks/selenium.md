---
title: 给 Selenium 测试加上 AI——WebDriver 的自然语言定位
description: 把 AI 视觉挂载到现有 Selenium WebDriver 会话——用自然语言代替易碎的 XPath,视觉化提取数据,运行自主多步任务。
---

# Selenium + Qirabot

Selenium 套件会不断堆积 XPath。Qirabot 让新增的步骤不再需要它:传入你
已有的 `driver`,用自然语言描述元素,AI 视觉在渲染后的页面上定位。老
测试原样继续跑。

```python
from selenium import webdriver
from qirabot import Qirabot

driver = webdriver.Chrome()
driver.get("https://www.wikipedia.org")
bot = Qirabot().bind(driver)   # bind 一次;driver 在整个会话中稳定

summary = bot.extract("提取词条的第一段")
print(summary)

bot.close()      # 先关 bot(收尾录屏/报告),再退出 driver
driver.quit()
```

Selenium 不是 extra——自带 driver 即可:

```bash
pip install qirabot selenium
```

## bind() 是天然搭配

与 Playwright 不同(点击可能返回新标签页),Selenium 的 `driver` 对象在
整个会话中稳定,`bind()` 可以省去重复的第一个参数:

```python
bot = Qirabot().bind(driver)
bot.click("接受 Cookie 按钮")
bot.type_text("搜索框", "playwright vs selenium", press_enter=True)
ok = bot.verify("搜索结果已显示")
rows = bot.extract("前 5 条结果标题,返回 JSON 数组")
```

也可作为上下文管理器:

```python
with Qirabot().bind(driver) as bot:
    result = bot.ai("用 demo@example.com / hunter2 登录并打开设置页")
    assert result.success
```

## 与现有代码混用

```python
# 旧写法,原样保留
driver.find_element(By.ID, "username").send_keys("test_user")

# 新步骤:不再维护定位器
bot.click("提交按钮")
assert bot.verify("绿色的成功横幅可见")
```

`go_back` 映射为浏览器历史后退;`navigate(driver, "example.com")` 会自动
补 `https://`。标签页管理(`close_tab`)仅 Playwright 支持——Selenium 下
请用原生方式管理窗口。

## Selenium 套件里 Qirabot 最有用的场景

- 对渲染状态的断言(`verify`)——DOM 检查会说谎的地方:元素存在但不可见、
  被遮挡、在屏幕外。
- 不受你控制的页面(支付 iframe、SSO 页面、验证码前后的流程)——选择器
  随时可能变。
- 一次性数据提取(`extract`)——否则每个页面都要写一个解析函数。

相关:[浏览器后端](/zh/backends/browser) ·
[pytest 集成](/zh/frameworks/pytest)
