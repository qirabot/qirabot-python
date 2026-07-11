"""Bundled binary assets (accessed via importlib.resources).

``ADBKeyboard.apk`` (GPL-2.0, vendored unmodified from
github.com/senzhk/ADBKeyBoard — see ADBKEYBOARD_LICENSE.txt alongside it) is
installed on demand by the adb adapter for non-ASCII text input. The package
works without it; the IME path then raises an actionable error instead.
"""
