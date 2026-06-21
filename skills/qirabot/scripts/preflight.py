#!/usr/bin/env python3
"""Qirabot skill preflight — verify the environment BEFORE writing an automation.

Uses only the standard library, so it runs on a stock Python *before* qirabot
is installed.

    python preflight.py [browser|android|ios|desktop]

Exit code 0 = ready to go; non-zero = fix the printed items first.
"""

import importlib
import os
import platform
import shutil
import subprocess
import sys

OK = "OK  "
NO = "FAIL"
WARN = "warn"


def line(status: str, label: str, hint: str = "") -> None:
    print(f"[{status}] {label}")
    if hint:
        print(f"       -> {hint}")


def check_import(module: str, extra: str, label: str = "") -> bool:
    """Hard-check that an optional extra imports on THIS interpreter.

    Core `qirabot` does not pull in the backend extras (they're lazy), so a
    missing or broken one only surfaces mid-run. Importing here catches it —
    broadly, since a numpy/opencv ABI mismatch on an unsupported Python raises
    things other than ImportError. Prints an OK/FAIL line; returns True on success.
    """
    try:
        importlib.import_module(module)
        line(OK, label or f"{module} importable")
        return True
    except Exception as exc:  # noqa: BLE001
        line(NO, label or f"{module} importable",
             f'{type(exc).__name__}: {exc}  ->  pip install "qirabot[{extra}]"')
        return False


def main() -> int:
    target = (sys.argv[1] if len(sys.argv) > 1 else "browser").lower()
    if target not in {"browser", "android", "ios", "desktop"}:
        print(f"unknown target {target!r}; use browser | android | ios | desktop")
        return 2

    print(f"Qirabot preflight (target: {target})")
    # The whole point: this run validates ONE interpreter — echo which, so the
    # automation can be run with the exact same one (see the success message).
    print(f"interpreter: {sys.executable}\n")
    hard_ok = True
    # Use platform.system() (not sys.platform) so type-checkers don't statically
    # narrow the Windows-only branches to "unreachable" on a non-Windows host.
    is_windows = platform.system() == "Windows"

    # 1. Python version
    v = sys.version_info
    py_ok = (v.major, v.minor) >= (3, 10)
    line(OK if py_ok else NO, f"Python {v.major}.{v.minor} (need >= 3.10)",
         "" if py_ok else "Install Python 3.10-3.12.")
    hard_ok = hard_ok and py_ok
    if target == "android" and not ((3, 10) <= (v.major, v.minor) <= (3, 12)):
        line(WARN, "airtest extra wants Python 3.10-3.12",
             "numpy<2 / opencv 4.4-4.6 have prebuilt wheels only up to 3.12.")
    if (target == "desktop" and is_windows
            and not ((3, 10) <= (v.major, v.minor) <= (3, 12))):
        line(WARN, "airtest (window-scoped) desktop backend wants Python 3.10-3.12",
             "pyautogui (whole-screen) is fine on any 3.10+; only the airtest path pins numpy<2.")

    # 2. API key
    has_key = bool(os.environ.get("QIRA_API_KEY"))
    line(OK if has_key else NO, "QIRA_API_KEY is set",
         "" if has_key else "Get a key at https://app.qirabot.com, then: export QIRA_API_KEY=qk_...")
    hard_ok = hard_ok and has_key

    # 3. qirabot importable
    try:
        import qirabot  # noqa: F401
        line(OK, f"qirabot importable (v{getattr(qirabot, '__version__', '?')})")
    except ImportError:
        extra = {"browser": "browser", "android": "airtest",
                 "ios": "appium", "desktop": "desktop"}[target]
        line(NO, "qirabot importable",
             f"pip install 'qirabot[{extra}]'  (prefer a venv: "
             "python -m venv .qira-venv && source .qira-venv/bin/activate)")
        hard_ok = False

    # 4. target-specific
    if target == "browser":
        # Core `qirabot` does NOT pull in Playwright, and a missing Chromium
        # binary only surfaces at bot.open() — verify both so "Ready" is real.
        if check_import("playwright", "browser", "playwright importable"):
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    exe = p.chromium.executable_path
                if os.path.exists(exe):
                    line(OK, "Chromium installed")
                else:
                    line(NO, "Chromium installed", "playwright install chromium")
                    hard_ok = False
            except Exception as exc:  # noqa: BLE001
                line(NO, "Chromium check failed", f"{exc}; try: playwright install chromium")
                hard_ok = False
        else:
            hard_ok = False
    elif target == "android":
        # Import the API module (it pulls cv2/numpy) so a missing or ABI-broken
        # airtest — e.g. numpy<2 / opencv wheels absent on Python >3.12 — fails
        # here instead of mid-run.
        if not check_import("airtest.core.api", "airtest", "airtest importable"):
            hard_ok = False
        adb = shutil.which("adb")
        line(OK if adb else NO, "adb on PATH",
             "" if adb else "Install Android platform-tools and connect a device/emulator.")
        hard_ok = hard_ok and bool(adb)
        if adb:
            try:
                out = subprocess.run([adb, "devices"], capture_output=True,
                                     text=True, timeout=10).stdout
                devs = [ln for ln in out.splitlines()[1:] if ln.strip() and "\tdevice" in ln]
                line(OK if devs else NO, f"Android device connected ({len(devs)})",
                     "" if devs else "Start an emulator or plug in a device (USB debugging on).")
                hard_ok = hard_ok and bool(devs)
            except Exception as exc:  # noqa: BLE001
                line(WARN, "adb devices", str(exc))
    elif target == "ios":
        # No bot.open() for iOS — you build an Appium or Airtest driver and
        # bind() it. Verify at least one iOS-capable client imports; the Appium
        # server / WebDriverAgent / device chain is external and can't be checked.
        backends = []
        for mod, name in (("appium", "appium"), ("airtest.core.api", "airtest")):
            try:
                importlib.import_module(mod)
                backends.append(name)
            except Exception:  # noqa: BLE001
                pass
        if backends:
            line(OK, f"iOS client importable ({'/'.join(backends)})")
        else:
            line(NO, "iOS client importable",
                 'install one: pip install "qirabot[appium]"  (or "qirabot[airtest]")')
            hard_ok = False
        if shutil.which("appium"):
            line(OK, "appium server on PATH")
        else:
            line(WARN, "appium server not on PATH (Appium path)",
                 "npm i -g appium && appium driver install xcuitest  (skip if using a remote grid)")
        line(WARN, "iOS device + WebDriverAgent",
             "Needs macOS + Xcode, a built/signed WebDriverAgent, and a trusted device or simulator.")
    elif target == "desktop":
        # Desktop backends — "ready" if EITHER imports on this interpreter:
        #   * pyautogui — any OS (Win/macOS/Linux), drives the whole primary screen
        #   * airtest's pywinauto backend — Windows-only, scopes to one window.
        # airtest itself also drives Android/iOS, but has NO macOS desktop backend,
        # so on macOS pyautogui is the only path. Core qirabot pulls in neither
        # (lazy adapters); import here so a missing one — or a headless-Linux
        # "no display" — fails now, not mid-run.
        backends = []
        try:
            importlib.import_module("pyautogui")
            backends.append("pyautogui (whole screen, any OS)")
        except Exception:  # noqa: BLE001
            pass
        if is_windows:
            # airtest ships pywinauto only on win32; offer it as the window-scoped
            # alternative when present.
            try:
                importlib.import_module("pywinauto")
                backends.append("airtest/pywinauto (Windows, window-scoped)")
            except Exception:  # noqa: BLE001
                pass
        if backends:
            line(OK, f"desktop backend importable ({'; '.join(backends)})")
        else:
            hint = 'pip install "qirabot[desktop]"  (whole screen)'
            if is_windows:
                hint += '  — or "qirabot[airtest]" for window-scoped'
            line(NO, "desktop backend importable", hint)
            hard_ok = False
        line(WARN, "desktop runtime",
             "Ensure the target app is installed; on macOS grant Screen Recording + Accessibility.")

    # 5. ffmpeg (optional)
    if not shutil.which("ffmpeg"):
        line(WARN, "ffmpeg not found", "Optional — only needed for record=True screen recording.")

    print()
    if hard_ok:
        print("Ready. Copy a template from templates/, then run it with THIS exact")
        print("interpreter (NOT a bare `python`) so the run matches what was validated:")
        print(f"    {sys.executable} your_script.py")
        return 0
    print("Not ready — fix the FAIL items above, then re-run preflight.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
