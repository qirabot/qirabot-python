# Drive a desktop game with Qirabot

Most DOM-based automation (Playwright / Selenium / Appium) can't reach a
desktop game's UI — there's no accessibility tree, the renderer is on the GPU,
and the window may sit above other apps. Qirabot drives the game window
directly: bind by HWND, locate elements purely by what's on screen, mix
deterministic steps (for known splash / launcher UI) with `bot.ai()` (for
open-ended audits).

| Example | Engine | What it does |
|---|---|---|
| [windows_unity_game.py](windows_unity_game.py) | Unity (default) / Unreal / native | Launch the game, wait for splash → in-game, then audit the character & inventory menus with `bot.ai()`. |

## Install

```bash
python -m pip install qirabot   # the Windows window backend is built in
```

`pywin32` provides the `win32gui` calls used to find the game's renderer
window by class name (Unity → `UnityWndClass`, Unreal → `UnrealWindow`, etc.).

## Run

```cmd
copy .env.example .env       :: then edit QIRA_API_KEY + QIRA_GAME_EXE
.venv\Scripts\python.exe windows_unity_game.py
```

Run elevated if your game window is admin-protected (anti-cheat, launcher
elevation) — otherwise mouse / keyboard events won't reach it.

## Why this pattern

- **Class-based HWND lookup** — matching by `UnityWndClass`, not title, rules
  out File Explorer windows that happen to show the game folder.
- **`ShellExecuteW`, not `subprocess`** — matches a real double-click, so UAC
  and shell hooks fire; many launchers refuse to start without them.
- **`record_window=True`** — crops capture to the game window's visible rect.
  Fullscreen capture often goes black on GPU-composited game windows.
- **Deterministic for the splash, AI for the audit** — the launch / splash
  flow is well-defined, so cheap `wait_for` + `click` is steadier than asking
  an LLM. The inventory walkthrough is open-ended, so `bot.ai()` earns its
  cost there.

See [windows_unity_game.py](windows_unity_game.py) for the full annotated
script and configurable environment variables.
