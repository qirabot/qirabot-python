---
title: Automate Windows Apps & Games with AI — DirectInput Scancodes
description: Bind one Windows window by title or HWND and drive it with AI vision. Input is DirectInput scancodes that Unity, Unreal, and native games actually read — where virtual-key automation fails.
---

# Windows Windows & Games

`qirabot.Window` binds to a **single window** (by title regex or HWND):
screenshots are its client area, clicks are window-relative, and keys are
**DirectInput scancodes** — the level games poll, which virtual-key
automation (pyautogui, AutoHotkey's default send mode) can't reach. Stdlib
ctypes only; built into the core package, no extras.

Combined with AI vision for element location, this drives what no
DOM/accessibility-based framework can: Unity and Unreal games, custom
launchers, legacy native apps.

```python
from qirabot import Qirabot, Window

window = Window(title_re="Genshin")   # or Window(hwnd=0x132456)
bot = Qirabot().bind(window)

result = bot.ai("Open the inventory and list all items")
bot.close()
```

From the CLI:

```bash
qirabot desktop "Open the inventory and list all items" --window-title "Genshin"
qirabot desktop "..." --hwnd 132456
```

## Game-grade input

- **Keys are scancodes** — real hardware-level input, including
  `ctrl`/`alt`/`win` combos. Characters outside the scancode table are
  injected as unicode key events.
- **Hold a key for a duration** — quantified in-game movement:

  ```python
  bot.press_key(window, "w", duration_seconds=2)      # walk forward 2s
  bot.press_key(window, "shift+w", duration_seconds=1.5)  # sprint
  ```

- **Modifier-click** — atomic alt+click for games, ctrl+click multi-select:

  ```python
  bot.click(window, "enemy unit", modifier="alt")
  ```

- **Split press/release primitives** — `mouse_down` / `mouse_up` /
  `key_down` / `key_up` hold an input across other actions (keep moving while
  clicking, press-and-hold drags). Any input still held is auto-released at
  the end of an `ai()` run and on `close()`.

## Mixing deterministic steps with AI

Game UI audits work well as deterministic navigation plus AI verification:

```python
bot.click(window, "the Bag icon")
bot.wait_for(window, "the inventory panel is open")
ok = bot.verify(window, "every item slot shows an icon and a count")
items = bot.extract(window, "list the item names visible in the inventory")
```

See the full walkthrough in
[examples/game/](https://github.com/qirabot/qirabot-python/tree/main/examples/game),
including a custom-tool example where the AI calls your GM backend mid-task
(add energy on an out-of-energy popup, then continue the quest loop).

## Recording the window

On Windows you can record just the window under test, with system audio:

```python
bot = Qirabot(record=True, record_window=True, record_audio=True)
```

Keep the window visible — `gdigrab` produces black frames for minimized or
GPU-composited (fullscreen-exclusive game) windows; for those, record the
full screen instead.

## Notes

- Whole-desktop automation (any OS) is the separate
  [pyautogui backend](/backends/desktop); the Window backend is
  Windows-specific and single-window by design.
- Coming from Airtest 1.x? `connect_device("Windows:///132456")` becomes
  `Window(hwnd=132456)`.
