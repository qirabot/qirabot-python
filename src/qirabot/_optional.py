"""Lazy loading of optional backend dependencies.

Each device backend (browser/desktop/appium) ships as an ``[project.optional-
dependencies]`` extra. Rather than importing those modules eagerly — or letting a
missing one surface as a raw ``ModuleNotFoundError`` traceback — call :func:`require`
at the point of use. It returns the imported module on success, or raises a
:class:`~qirabot.exceptions.MissingDependencyError` whose message tells the user the
exact ``python -m pip install "qirabot[<extra>]"`` command to run.
"""

from __future__ import annotations

import importlib
import warnings
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

# Packages that are deliberately NOT qirabot extras (bring-your-own-driver): the
# hint must be a plain `python -m pip install <package>`, not a nonexistent
# qirabot[<extra>].
_NOT_AN_EXTRA = frozenset({"selenium"})


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
        # airtest and facebook-wda still contain pre-3.12 escape sequences
        # ('\d' in docstrings etc.); on Python >=3.12 their first bytecode
        # compile emits SyntaxWarnings that read like qirabot errors. They are
        # third-party code we can't fix, so silence them for the import only.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return importlib.import_module(module)
    except ImportError as e:
        package = module.split(".")[0]
        if package in _NOT_AN_EXTRA:
            hint = f"python -m pip install {package}"
        else:
            which = extra or _EXTRA_FOR_PACKAGE.get(package, package)
            hint = f'python -m pip install "qirabot[{which}]"'
        raise MissingDependencyError(
            f"'{package}' is required for this feature but is not installed. "
            f"Install it with:  {hint}"
        ) from e
