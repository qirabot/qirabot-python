"""Drive a Windows desktop game with Qirabot — splash launch + AI UI audit.

Pattern:
  1. Launch the game executable via ShellExecuteW (matches a real double-click —
     follows UAC and shell hooks that subprocess.Popen would skip, which most
     launchers require).
  2. Poll for the game's actual renderer window by *class name* (Unity games
     expose ``UnityWndClass``; Unreal uses ``UnrealWindow``; configure for your
     engine via ``QIRA_GAME_WND_CLASS``). Matching by class — not title —
     rules out File Explorer windows whose title happens to share the game name.
  3. Bind to that HWND via ``qirabot.Window(hwnd=...)`` — the built-in
     Windows backend (zero extra installs) — so input and screenshots target
     *this* window even when other apps overlay it; keys go out as DirectInput
     scancodes that game engines can read.
  4. Drive splash → in-game with deterministic ``wait_for`` / ``click`` /
     ``press_key`` steps (cheaper and steadier than AI for known UI), then
     hand the open-ended UI audit to ``bot.ai``.

Recording is built-in: ``record_window=True`` crops to the game window's
visible rect (GPU-composited windows safe — fullscreen capture would otherwise
go black on most games), and ``record_audio=True`` auto-detects a loopback
device.

Configure via a ``.env`` next to this script (or real env vars):

    QIRA_API_KEY=qk_...                                # required
    QIRA_GAME_EXE=C:\\Path\\To\\YourGame.exe           # required
    QIRA_GAME_WND_CLASS=UnityWndClass                  # optional; per engine
    QIRA_GAME_LAUNCH_PROMPT="The Play / Enter Game button on the splash"
    QIRA_GAME_IN_GAME_PROMPT="In-game HUD visible (minimap, character, status)"
    QIRA_GAME_AI_TASK="Open the character and inventory menus, verify each
                       tab loads, then return to the main view."

Run elevated so input reaches admin-protected game windows:

    .venv\\Scripts\\python.exe windows_unity_game.py
"""

import ctypes
import os
import time

from qirabot import Qirabot, StepResult, Window, load_dotenv

DEFAULT_WND_CLASS = "UnityWndClass"


def find_game_hwnd(wnd_class: str) -> int | None:
    """Return the HWND of the visible window matching ``wnd_class``, or None."""
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd: object, _lparam: object) -> int:
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == wnd_class:
                found.append(int(hwnd))  # type: ignore[arg-type]
        return 1

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def wait_for_game_hwnd(wnd_class: str, timeout: float = 180.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if hwnd := find_game_hwnd(wnd_class):
            return hwnd
        time.sleep(2)
    raise RuntimeError(f"game window (class {wnd_class}) not found within {timeout}s")


def on_step(step: StepResult) -> None:
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params} — {step.decision}")


def main() -> None:
    game_exe = os.environ.get("QIRA_GAME_EXE")
    if not game_exe:
        raise RuntimeError("set QIRA_GAME_EXE to your game's executable path")
    wnd_class = os.environ.get("QIRA_GAME_WND_CLASS", DEFAULT_WND_CLASS)
    launch_prompt = os.environ.get(
        "QIRA_GAME_LAUNCH_PROMPT",
        "The Play / Enter Game button on the splash screen",
    )
    in_game_prompt = os.environ.get(
        "QIRA_GAME_IN_GAME_PROMPT",
        "In-game HUD visible (e.g. minimap, character, status bars)",
    )
    ai_task = os.environ.get(
        "QIRA_GAME_AI_TASK",
        "Open the character and inventory menus, verify each tab loads "
        "correctly, then return to the main view.",
    )

    hwnd = find_game_hwnd(wnd_class)
    if not hwnd:
        print(f"launching: {game_exe}")
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "open", game_exe, None, os.path.dirname(game_exe), 1
        )
        if rc <= 32:
            raise RuntimeError(f"ShellExecuteW failed (code {rc})")
        hwnd = wait_for_game_hwnd(wnd_class)

    print(f"binding to hwnd={hwnd}")
    device = Window(hwnd=hwnd)

    with Qirabot(
        task_name="windows-game-ui-check",
        record=True,
        record_window=True,
        record_audio=True,
        record_fps=30,
    ).bind(device) as bot:
        # Splash UI is often not responsive for the first few seconds after
        # the launcher hands off to the game process.
        print("waiting for splash to settle...")
        time.sleep(15)

        # Deterministic: locate the splash launch button, click it.
        print(f"waiting for launch button: {launch_prompt!r}")
        bot.wait_for(launch_prompt, timeout=180, interval=5)
        bot.click(launch_prompt)

        # Wait for actual in-game state before doing anything else.
        print(f"waiting for in-game state: {in_game_prompt!r}")
        time.sleep(10)
        bot.wait_for(in_game_prompt, timeout=180, interval=5)

        # Most games open their main menu on Escape.
        print("pressing ESC to open the menu")
        bot.press_key("esc")

        # Open-ended audit — let the AI drive.
        result = bot.ai(ai_task, max_steps=50, on_step=on_step)
        print("success:", result.success)
        print("output:", result.output)
        print("report:", bot.report_dir)


if __name__ == "__main__":
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    main()
