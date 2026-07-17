"""Shared Chromium launch logic.

Two callers: ``Qirabot.open()`` (the SDK path) and the CLI's ``open-browser``
command, which opens a browser for manual login without an API key or task.
Parameter semantics are documented once, on ``Qirabot.open()``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from typing import TYPE_CHECKING, Any, NamedTuple

from qirabot._optional import require

if TYPE_CHECKING:
    from playwright.sync_api import ViewportSize

logger = logging.getLogger("qirabot")


class LaunchedBrowser(NamedTuple):
    playwright: Any
    context: Any
    page: Any
    cdp: bool
    """True when attached over CDP — the browser belongs to someone else, so
    closing should detach (close the tab), not kill the browser."""


def launch_browser(
    url: str = "",
    headless: bool = False,
    *,
    viewport: tuple[int, int] = (1280, 800),
    user_data_dir: str = "",
    channel: str = "",
    args: list[str] | None = None,
    cdp_url: str = "",
) -> LaunchedBrowser:
    """Start playwright and launch (or attach to) a Chromium browser."""
    sync_playwright = require("playwright.sync_api", "browser").sync_playwright

    if cdp_url and (user_data_dir or channel or args or headless):
        raise ValueError(
            "cdp_url cannot be combined with headless/user_data_dir/channel/args "
            "(those apply only when launching a browser)"
        )

    # A headed launch cannot succeed without a display server, so on a
    # display-less Linux box (typical headless VM / CI) fall back rather
    # than fail. cdp_url is exempt: it attaches to a browser that already
    # runs elsewhere.
    if (
        not headless
        and not cdp_url
        and sys.platform.startswith("linux")
        and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    ):
        logger.warning(
            "no display detected (DISPLAY/WAYLAND_DISPLAY unset) — a headed "
            "browser cannot start here; launching headless instead"
        )
        headless = True

    pw = sync_playwright().start()
    try:
        viewport_dict: ViewportSize = {"width": viewport[0], "height": viewport[1]}

        if cdp_url:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
        elif user_data_dir:
            # Playwright resolves the path as-is (no ~ expansion), which would
            # silently create a literal "~" directory under cwd.
            user_data_dir = os.path.expanduser(user_data_dir)
            launch_kwargs: dict[str, Any] = {"headless": headless}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = list(args)
            context = pw.chromium.launch_persistent_context(
                user_data_dir,
                viewport=viewport_dict,
                **launch_kwargs,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            launch_kwargs = {"headless": headless}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = list(args)
            browser = pw.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport=viewport_dict)
            page = context.new_page()

        if url:
            if "://" not in url:
                url = "https://" + url
            page.goto(url)
    except BaseException:
        # Nobody holds a reference to pw yet, so stop it here or leak the
        # driver process.
        with contextlib.suppress(Exception):
            pw.stop()
        raise
    return LaunchedBrowser(pw, context, page, bool(cdp_url))
