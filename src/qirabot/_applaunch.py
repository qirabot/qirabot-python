"""Cross-platform desktop application launcher.

pyautogui can drive the mouse and keyboard but has no ability to launch an
application, so desktop automation has to shell out to the OS. This module
isolates that platform-specific logic behind a single ``launch_app`` call,
reused by the CLI's ``desktop --app`` option, ``Qirabot.launch_app``, and
available to SDK users directly.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time


def _looks_like_bundle_id(app: str) -> bool:
    """macOS heuristic: ``com.tencent.xinWeChat`` vs an app name or path.

    A bundle id is dotted with no path separator and is not a ``.app`` bundle
    path (e.g. ``/Applications/WeChat.app``).
    """
    return "/" not in app and not app.endswith(".app") and app.count(".") >= 2


def launch_app(app: str, *, wait: float = 2.0) -> None:
    """Launch (or activate) a desktop application by name, path, or id.

    Platform behaviour:

    - **macOS**: ``open -b <app>`` when ``app`` looks like a bundle id
      (``com.tencent.xinWeChat``), otherwise ``open -a <app>`` for an app name
      (``"WeChat"``) or a ``.app`` path. ``open`` activates an already-running
      instance instead of starting a duplicate.
    - **Windows**: ``os.startfile`` for an existing path; ``explorer.exe
      shell:AppsFolder\\<AUMID>`` for Store/UWP apps (``app`` contains ``!``);
      otherwise the ``start`` shell builtin to resolve a registered name.
    - **Linux/other**: run the executable directly (path or name on ``PATH``).

    Args:
        app: application name, executable path, macOS bundle id, or Windows
            AppUserModelID.
        wait: seconds to sleep after launching so the window can render before
            the first screenshot. Pass ``0`` to return immediately.

    Raises:
        RuntimeError: if the launch command fails (e.g. app not found).
    """
    system = platform.system()

    if system == "Darwin":
        flag = "-b" if _looks_like_bundle_id(app) else "-a"
        _run(["open", flag, app], app)
    elif system == "Windows":
        if "!" in app:  # UWP AppUserModelID, e.g. Microsoft.WindowsCalculator_..!App
            _run(["explorer.exe", f"shell:AppsFolder\\{app}"], app, check=False)
        elif os.path.exists(app):
            os.startfile(app)  # type: ignore[attr-defined]  # Windows-only
        else:
            # 'start' is a cmd builtin; the first quoted arg is the window title.
            _run(["cmd", "/c", "start", "", app], app)
    else:  # Linux and other POSIX
        exe = shutil.which(app) or app
        try:
            subprocess.Popen([exe])
        except OSError as e:
            raise RuntimeError(f"failed to launch app {app!r}: {e}") from e

    if wait > 0:
        time.sleep(wait)


def _run(cmd: list[str], app: str, *, check: bool = True) -> None:
    try:
        subprocess.run(cmd, check=check, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"failed to launch app {app!r}: {e}") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip() or str(e)
        raise RuntimeError(f"failed to launch app {app!r}: {detail}") from e
