"""Lazy loading of optional backend dependencies.

Each device backend (browser/desktop/appium) ships as an ``[project.optional-
dependencies]`` extra. Rather than importing those modules eagerly — or letting a
missing one surface as a raw ``ModuleNotFoundError`` traceback — call :func:`require`
at the point of use. It returns the imported module on success, or raises a
:class:`~qirabot.exceptions.MissingDependencyError` whose message tells the user the
exact ``pip install "qirabot[<extra>]"`` command to run.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from qirabot.exceptions import MissingDependencyError

# Top-level package -> the extra that provides it, so we can infer the install hint
# from a dotted import path (e.g. "playwright.sync_api" -> "browser") without the
# caller having to repeat it.
_EXTRA_FOR_PACKAGE = {
    "playwright": "browser",
    "pyautogui": "desktop",
    "pyperclip": "desktop",
    "appium": "appium",
}


def require(module: str, extra: str | None = None) -> ModuleType:
    """Import an optional dependency or raise an actionable install hint.

    Args:
        module: import path, dotted paths allowed (e.g. ``"playwright.sync_api"``).
        extra: the ``qirabot[<extra>]`` that provides it. Inferred from the
            top-level package when omitted.

    Returns:
        The imported module.

    Raises:
        MissingDependencyError: if the module is not installed.
    """
    try:
        return importlib.import_module(module)
    except ImportError as e:
        package = module.split(".")[0]
        which = extra or _EXTRA_FOR_PACKAGE.get(package, package)
        raise MissingDependencyError(
            f"'{package}' is required for this feature but is not installed. "
            f'Install it with:  pip install "qirabot[{which}]"'
        ) from e
