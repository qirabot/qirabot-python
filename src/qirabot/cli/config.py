"""User-level CLI configuration (``qirabot login``).

One JSON file holding the API key, so ``qirabot login`` is a one-time step
instead of exporting ``QIRA_API_KEY`` in every shell:

* Linux/macOS: ``$XDG_CONFIG_HOME/qirabot/config.json`` (default
  ``~/.config/qirabot/config.json``), written with mode 0600.
* Windows: ``%APPDATA%\\qirabot\\config.json``.

Deliberately stdlib-only (json, no keyring/tomli-w) and read as the LAST
resolution layer: ``--api-key`` flag > ``QIRA_API_KEY`` env var > ``./.env`` >
this file. Existing env/.env setups keep working untouched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_path() -> Path:
    """Platform-conventional path of the user config file."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "qirabot" / "config.json"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "qirabot" / "config.json"


def load_api_key() -> str:
    """API key from the user config file, or "" (best-effort, never raises)."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        key = data.get("api_key", "")
        return key if isinstance(key, str) else ""
    except Exception:
        return ""


def save_api_key(key: str) -> Path:
    """Persist the API key; returns the file path written.

    The file is created 0600 (owner read/write only) on POSIX — it holds a
    credential. Existing unrelated fields in the file are preserved.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            data = existing
    except Exception:
        pass
    data["api_key"] = key
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return path


def mask_key(key: str) -> str:
    """``qk_abc…yz`` — enough to recognize a key, never enough to use it."""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:5]}…{key[-2:]}"
