"""Qirabot CLI entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any, NoReturn, TypeVar

import click
from click.core import ParameterSource

from qirabot._dotenv import load_dotenv
from qirabot._optional import require
from qirabot._transport import Transport
from qirabot.exceptions import MissingDependencyError, QirabotError


def _require_api_key(ctx: click.Context) -> str:
    """Single place for the missing-key error so every command says the same thing."""
    api_key: str = ctx.obj["api_key"]
    if not api_key:
        click.echo("Error: API key is required. Set QIRA_API_KEY or pass --api-key.", err=True)
        sys.exit(1)
    return api_key


def _transport(ctx: click.Context) -> Transport:
    """Get or create a shared Transport from the CLI context."""
    if "transport" not in ctx.obj:
        ctx.obj["transport"] = Transport(
            base_url=ctx.obj["base_url"],
            api_key=_require_api_key(ctx),
            timeout=ctx.obj["timeout"],
            verify_ssl=ctx.obj["verify_ssl"],
        )
    transport: Transport = ctx.obj["transport"]
    return transport


def _make_bot(
    ctx: click.Context,
    model: str = "",
    language: str = "",
    report: bool = True,
    report_dir: str = "",
    annotate: bool = True,
    record: bool = False,
    task_name: str = "",
) -> Any:
    from qirabot import Qirabot

    api_key = _require_api_key(ctx)
    try:
        return Qirabot(
            api_key=api_key,
            base_url=ctx.obj["base_url"],
            timeout=ctx.obj["timeout"],
            verify_ssl=ctx.obj["verify_ssl"],
            model_alias=model,
            language=language,
            task_name=task_name,
            source="cli",
            report=report,
            report_dir=report_dir,
            screenshot_annotate=annotate,
            record=record,
        )
    except Exception as e:
        # No special-casing needed: Transport already maps connection failures to
        # QirabotConnectionError with an actionable message (server URL +
        # QIRA_BASE_URL hint), so str(e) is user-friendly as-is.
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _run_local(
    bot: Any,
    target: Any,
    instruction: str,
    max_steps: int,
    base_url: str = "",
) -> None:
    from rich.console import Console
    from rich.markup import escape

    console = Console()
    indent = " " * (len(f"[{max_steps}/{max_steps}]") + 1)

    if bot.task_id:
        if base_url:
            task_url = f"{base_url.rstrip('/')}/tasks/{bot.task_id}"
            console.print(f"[dim]Task:[/dim] [link={task_url}]{bot.task_id}[/link]")
        else:
            console.print(f"[dim]Task:[/dim] {bot.task_id}")

    def on_step(step: Any) -> None:
        if step.action_type == "done":
            return
        params = step.params or {}
        detail_parts = []
        if "locate" in params:
            detail_parts.append(f'"{params["locate"]}"')
        if "text" in params:
            detail_parts.append(f'← "{params["text"]}"')
        if "direction" in params:
            detail_parts.append(f'{params["direction"]} {params.get("amount", "")}'.rstrip())
        label = escape(f"[{step.step}/{max_steps}]")
        head = f"[bold cyan]{label}[/bold cyan] [yellow]{step.action_type}[/yellow]"
        if detail_parts:
            head += "  " + escape("  ".join(detail_parts))
        console.print(head)
        if step.decision:
            console.print(f"{indent}[dim]└ {escape(step.decision)}[/dim]")

    try:
        result = bot.ai(target, instruction, max_steps=max_steps, on_step=on_step)
    except KeyboardInterrupt:
        # Ctrl+C raises KeyboardInterrupt, which is a BaseException — NOT caught
        # by `except Exception` below. Without this branch the interrupt would
        # skip reporting and the caller's finally:bot.close() would complete the
        # still-running task as succeeded. Report it as a deliberate cancel so
        # the run lands in the 'cancelled' bucket, not 'failed' or 'succeeded'.
        # (130 = 128 + SIGINT, the conventional Ctrl+C exit code.)
        bot.cancel("aborted by user")
        console.print("\n[bold yellow]Cancelled[/bold yellow]")
        sys.exit(130)
    except Exception as e:
        # Report the client-side abort so the task is recorded as failed; without
        # this the bot.close() in the caller's finally would complete the
        # still-running task as succeeded. (Transport already collapses HTML
        # error bodies to one-line summaries, so str(e) prints cleanly.)
        bot.fail(str(e))
        console.print(f"[bold red]Error:[/bold red] {escape(str(e))}")
        sys.exit(1)
    if result.success:
        console.print(f"[bold green]Done:[/bold green] {result.output}")
    else:
        # The server already set a terminal status for known failures (e.g. max
        # steps); fail() is idempotent there and ensures other failure paths are
        # not left to close()'s success default.
        bot.fail(result.output)
        console.print(f"[bold red]Failed:[/bold red] {result.output}")
        # Non-zero exit so scripts/CI can detect an unfinished task; SystemExit
        # bypasses the caller's `except Exception` and still runs its finally.
        sys.exit(1)


def _fail_setup(bot: Any, e: Exception) -> NoReturn:
    """Report a setup-phase failure (before _run_local takes over) and exit.

    Setup — bot.open() for browser, Appium Remote() / airtest connect for
    android/ios — runs after the
    server task is created but before _run_local starts reporting outcomes. An
    error there leaves the task un-terminalized, so the command's
    finally:bot.close() would otherwise complete it as *succeeded*. Record it as
    failed instead, print the error, and exit 1.
    """
    bot.fail(str(e))
    click.echo(f"Error: {e}", err=True)
    sys.exit(1)


def _default_task_name(instruction: str) -> str:
    """Derive a task name from the instruction when --name is not given, so CLI
    runs are distinguishable in the web UI instead of all sharing one name."""
    first_line = next((ln.strip() for ln in instruction.splitlines() if ln.strip()), "")
    return first_line[:60] or "cli"


def _img_ext(data: bytes) -> str:
    """Infer a screenshot file extension from magic bytes (server sends jpeg or png)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "bin"


# Accept -h alongside --help, and print each option's default in --help. The
# show_default context setting is inherited by every subcommand (click >= 8.1).
_CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "show_default": True,
}

_FC = TypeVar("_FC", bound=Callable[..., Any])


def _task_options(f: _FC) -> _FC:
    """Task options shared by browser/android/ios/desktop. Applied in reverse so
    --help lists them in reading order (name, model, language, max-steps)."""
    f = click.option("--max-steps", default=20, help="Max steps for AI")(f)
    f = click.option("--language", "-l", default="", help="Language (e.g. zh, en)")(f)
    f = click.option("--model", "-m", default="", help="Model alias")(f)
    f = click.option("--name", "-n", default="", help="Task name shown in the web UI (default: derived from the instruction)")(f)
    return f


def _debug_options(record: bool = True) -> Callable[[_FC], _FC]:
    """Debug options shared by browser/android/ios/desktop; android/ios have no
    screen recording, so --record is opt-out there."""

    def wrap(f: _FC) -> _FC:
        if record:
            f = click.option("--record", is_flag=True, help="Record the screen to report-dir/recording.mp4 (requires ffmpeg)")(f)
        f = click.option("--annotate/--no-annotate", default=True, help="Annotate saved screenshots with click coordinates")(f)
        f = click.option("--report-dir", default="", help="Report output root (env QIRA_REPORT_DIR; default ./qira_runs/<date>/<run>/)")(f)
        f = click.option("--report/--no-report", default=True, help="Write an HTML run report to --report-dir")(f)
        return f

    return wrap


@click.group(context_settings=_CONTEXT_SETTINGS)
@click.version_option(package_name="qirabot", prog_name="qirabot")
@click.option("--api-key", envvar="QIRA_API_KEY", help="API key")
@click.option("--base-url", envvar="QIRA_BASE_URL", default="https://app.qirabot.com", help="Server URL")
@click.option("--timeout", type=float, default=120.0, help="HTTP request timeout (seconds)")
@click.option("--verify-ssl/--no-verify-ssl", default=True, help="Verify the server's TLS certificate")
@click.pass_context
def cli(ctx: click.Context, api_key: str, base_url: str, timeout: float, verify_ssl: bool) -> None:
    """Qirabot CLI — AI automation tool.

    Global options (--api-key/--base-url/--timeout/--verify-ssl) go before the
    subcommand, e.g. `qirabot --base-url ... browser "..."`.
    """
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url
    ctx.obj["timeout"] = timeout
    ctx.obj["verify_ssl"] = verify_ssl


@cli.command()
@click.argument("task_id")
@click.pass_context
def task(ctx: click.Context, task_id: str) -> None:
    """Get task status and steps."""
    from rich.console import Console
    from rich.table import Table

    t = _transport(ctx)
    console = Console()

    resp = t.request("GET", f"/tasks/{task_id}")
    console.print(f"Task: [cyan]{task_id}[/cyan]")
    console.print(f"  Status: {resp.get('status', '')}")
    console.print(f"  Step: {resp.get('currentStep', 0)}")

    commands = t.request("GET", f"/tasks/{task_id}/commands")
    if isinstance(commands, list) and commands:
        cmd_table = Table(title="Commands")
        cmd_table.add_column("#")
        cmd_table.add_column("Type")
        cmd_table.add_column("Instruction")
        cmd_table.add_column("Status")
        for c in commands:
            cmd_table.add_row(
                str(c.get("seq", "")),
                c.get("commandType", ""),
                c.get("instruction", ""),
                c.get("status", ""),
            )
        console.print(cmd_table)

        steps = [s for c in commands for s in (c.get("steps") or [])]
        if steps:
            table = Table(title="Steps")
            table.add_column("#")
            table.add_column("Action")
            table.add_column("Status")
            table.add_column("Duration")
            for s in steps:
                table.add_row(
                    str(s.get("stepNumber", "")),
                    s.get("actionType", ""),
                    s.get("status", ""),
                    f"{s.get('stepDurationMs', 0)}ms",
                )
            console.print(table)


@cli.command()
@click.argument("task_id")
@click.option("--step", "-s", type=int, default=0, help="Step number (0 = latest)")
@click.option("--output", "-o", default="", help="Output path (default: ./screenshot-<task_id>[-step<N>].<ext>)")
@click.option("--force", "-f", is_flag=True, help="Overwrite the output file if it already exists")
@click.pass_context
def screenshot(ctx: click.Context, task_id: str, step: int, output: str, force: bool) -> None:
    """Download a task screenshot."""
    t = _transport(ctx)

    path = f"/screenshots?taskId={task_id}"
    if step > 0:
        path += f"&step={step}"

    data = t.get_bytes(path)
    if not output:
        suffix = f"-step{step}" if step > 0 else ""
        output = f"screenshot-{task_id}{suffix}.{_img_ext(data)}"
    if os.path.exists(output) and not force:
        click.echo(f"Error: {output} already exists. Pass --force to overwrite.", err=True)
        sys.exit(1)
    with open(output, "wb") as f:
        f.write(data)
    click.echo(f"Saved to {output} ({len(data)} bytes)")


@cli.command()
@click.pass_context
def models(ctx: click.Context) -> None:
    """List available model aliases."""
    from rich.console import Console
    from rich.table import Table

    t = _transport(ctx)
    resp = t.request("GET", "/model-aliases")
    aliases = resp.get("aliases", []) if isinstance(resp, dict) else []

    table = Table(title="Model Aliases")
    table.add_column("Name", style="cyan")
    table.add_column("Display")
    table.add_column("Description")

    for m in aliases:
        table.add_row(
            m.get("name", ""),
            m.get("displayName", ""),
            m.get("description", ""),
        )

    Console().print(table)


def _has_module(module: str) -> bool:
    """Probe an optional dependency without require()'s raise (doctor only)."""
    import importlib

    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def _display_available() -> bool:
    """False only on Linux with no display server — headed launches would fail
    there, and Qirabot.open() falls back to headless with a warning."""
    if not sys.platform.startswith("linux"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _chromium_status() -> str | None:
    """None = playwright not installed; else "ready", "no-browser", or "no-libs".

    Asking playwright for ``chromium.executable_path`` needs the driver process
    (~1s startup) — acceptable for a diagnostic command, and the only reliable
    answer: the download location moves with PLAYWRIGHT_BROWSERS_PATH and the
    bundled browser revision.

    "no-libs" (Linux only): the download exists but ``ldd`` reports unresolved
    shared libraries (e.g. libnspr4.so on a bare server), so launch would fail —
    the fix is ``playwright install-deps``, not a re-download.
    """
    if not _has_module("playwright.sync_api"):
        return None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
        if not os.path.exists(exe):
            return "no-browser"
    except Exception:
        return "no-browser"
    if sys.platform.startswith("linux"):
        import subprocess

        try:
            ldd = subprocess.run(
                ["ldd", exe], capture_output=True, text=True, timeout=10
            )
            if "not found" in ldd.stdout:
                return "no-libs"
        except Exception:
            pass  # no ldd / probe failure: don't fail a browser that may work
    return "ready"


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check the environment: Python, API key + server, and each backend's deps.

    Exits 0 when at least one backend can run end-to-end (key accepted, backend
    installed), 1 otherwise — so setup scripts and CI can gate on it.
    """
    import shutil

    from rich.console import Console
    from rich.markup import escape

    console = Console()
    ok, bad, warn = "[green]✓[/green]", "[red]✗[/red]", "[yellow]![/yellow]"
    problems = 0

    py = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        console.print(f"{ok} Python {py}")
    else:
        console.print(f"{bad} Python {py} — qirabot requires 3.10+")
        problems += 1

    if not ctx.obj["api_key"]:
        console.print(
            f"{bad} API key not set — export QIRA_API_KEY=qk_... (or put it in ./.env)"
        )
        problems += 1
    else:
        # A diagnostic must fail fast: unless --timeout was passed explicitly,
        # drop the 120s default (sized for AI task steps) to 10s so an
        # unreachable server reports in seconds instead of looking like a hang.
        # Must happen before _transport(), which caches a Transport built from
        # ctx.obj["timeout"]. The status spinner is transient (and silent when
        # output is not a terminal) — it names the server so a wrong base_url
        # is visible while doctor waits, not only after the timeout.
        if ctx.find_root().get_parameter_source("timeout") != ParameterSource.COMMANDLINE:
            ctx.obj["timeout"] = 10.0
        try:
            with console.status(f"checking server ({ctx.obj['base_url']})..."):
                _transport(ctx).request("GET", "/model-aliases")
            console.print(f"{ok} API key set, server reachable ({ctx.obj['base_url']})")
        except Exception as e:
            console.print(
                f"{bad} API key set but {ctx.obj['base_url']} rejected it or is "
                f"unreachable: {escape(str(e))}"
            )
            problems += 1

    # (label, ready, fix-hint). A missing Chromium download or missing system
    # libraries both count as not-ready: bot.open() would fail at launch even
    # though the import succeeds.
    chromium = _chromium_status()
    chromium_hints = {
        "no-browser": "playwright install chromium",
        "no-libs": "sudo playwright install-deps chromium  "
        "(Chromium is downloaded but system libraries are missing)",
    }
    backends = [
        (
            "browser (Playwright — default path, powers bot.open())",
            chromium == "ready",
            chromium_hints.get(
                chromium or "",
                'python -m pip install "qirabot[browser]" && playwright install chromium',
            ),
        ),
        (
            "desktop (pyautogui)",
            _has_module("pyautogui"),
            'python -m pip install "qirabot[desktop]"',
        ),
        (
            "android/ios direct (Airtest)",
            _has_module("airtest"),
            'python -m pip install "qirabot[airtest]"  (Python 3.10–3.12 recommended)',
        ),
        (
            "android/ios via server (Appium)",
            _has_module("appium"),
            'python -m pip install "qirabot[appium]"',
        ),
        (
            "selenium (bring-your-own driver)",
            _has_module("selenium"),
            "python -m pip install selenium",
        ),
    ]

    console.print("\n[bold]Backends[/bold] — you only need the one you plan to drive:")
    for label, ready, hint in backends:
        if ready:
            console.print(f"  {ok} {escape(label)}")
        else:
            console.print(f"  {bad} {escape(label)} — {escape(hint)}")
        if label.startswith("browser") and ready and not _display_available():
            console.print(
                f"    {warn} no display (DISPLAY unset) — headed windows can't open "
                "here; bot.open() and the CLI fall back to headless automatically"
            )

    if not any(ready for _, ready, _ in backends):
        console.print(
            f"\n{bad} No backend installed. Quickest start: "
            + escape('python -m pip install "qirabot[browser]" && playwright install chromium')
        )
        problems += 1

    console.print("\n[bold]Optional[/bold]:")
    if shutil.which("ffmpeg"):
        console.print(f"  {ok} ffmpeg — screen recording (record=True) available")
    else:
        console.print(
            f"  {warn} ffmpeg not on PATH — record=True will warn and skip recording"
        )

    console.print()
    if problems:
        console.print("[bold red]Not ready[/bold red] — fix the ✗ items above.")
        sys.exit(1)
    ready_labels = ", ".join(label.split(" (")[0] for label, ready, _ in backends if ready)
    console.print(f"[bold green]Ready[/bold green] — usable backends: {escape(ready_labels)}.")


@cli.command()
@click.argument("instruction")
@_task_options
# Browser — basic
@click.option("--url", "-u", default="", help="URL to open (optional, AI navigates if omitted)")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
@click.option("--viewport", default="1280x800", help="Viewport size as WIDTHxHEIGHT")
# Browser — advanced
@click.option("--channel", default="", help="Browser channel: chrome, msedge, etc. (uses installed browser instead of bundled Chromium)")
@click.option("--user-data-dir", default="", help="Persistent browser profile directory (keeps cookies/history across runs)")
@click.option("--browser-arg", multiple=True, help="Extra Chromium launch arg, repeatable (e.g. --browser-arg=--disable-blink-features=AutomationControlled)")
@click.option("--cdp-url", default="", help="Connect to existing Chrome via CDP (e.g. http://localhost:9222 or wss://chrome.browserless.io?token=xxx). Mutually exclusive with --headless/--user-data-dir/--channel/--browser-arg.")
@_debug_options()
@click.pass_context
def browser(
    ctx: click.Context,
    instruction: str,
    name: str,
    model: str,
    language: str,
    max_steps: int,
    url: str,
    headless: bool,
    viewport: str,
    channel: str,
    user_data_dir: str,
    browser_arg: tuple[str, ...],
    cdp_url: str,
    report: bool,
    report_dir: str,
    annotate: bool,
    record: bool,
) -> None:
    """Run an AI task in a local browser."""
    if cdp_url and (headless or user_data_dir or channel or browser_arg):
        raise click.UsageError(
            "--cdp-url cannot be combined with --headless/--user-data-dir/--channel/--browser-arg"
        )
    try:
        w_str, h_str = viewport.lower().split("x")
        vp = (int(w_str), int(h_str))
    except ValueError:
        raise click.BadParameter(f"viewport must be WIDTHxHEIGHT, got '{viewport}'")

    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, record=record, task_name=name or _default_task_name(instruction),
    )
    try:
        page = bot.open(
            url=url,
            headless=headless,
            viewport=vp,
            user_data_dir=user_data_dir,
            channel=channel,
            args=list(browser_arg) if browser_arg else None,
            cdp_url=cdp_url,
        )
        _run_local(bot, page, instruction, max_steps, base_url=ctx.obj["base_url"])
    except Exception as e:
        # Only setup (bot.open) reaches here: _run_local reports its own errors
        # and exits via SystemExit, which this `except Exception` deliberately
        # skips. Record the setup failure so close() below doesn't complete the
        # task as succeeded.
        _fail_setup(bot, e)
    finally:
        bot.close()


def _flag_given(ctx: click.Context, param: str) -> bool:
    """True when the user explicitly passed the option (vs its default), so
    engine-specific flags can be rejected under the other engine without
    tripping on their own default values."""
    return ctx.get_parameter_source(param) == ParameterSource.COMMANDLINE


def _require_airtest() -> None:
    """require() with the CLI escape hatch appended: airtest is the default
    engine, so a missing install must also point at --engine appium."""
    try:
        require("airtest.core.api", "airtest")
    except MissingDependencyError as e:
        raise MissingDependencyError(
            f"{e} Or pass --engine appium to go through an Appium server instead."
        ) from e


def _run_appium(
    ctx: click.Context,
    instruction: str,
    name: str,
    model: str,
    language: str,
    max_steps: int,
    appium_url: str,
    options: Any,
    report: bool,
    report_dir: str,
    annotate: bool,
) -> None:
    """Shared android/ios body: build the bot, open an Appium session, run."""
    appium_webdriver = require("appium.webdriver", "appium")

    # Build the bot first: it validates the API key and reaches the server, and
    # may sys.exit() on failure. Creating the Appium driver before that would
    # leak the remote session (driver.quit() lives in the finally below, which
    # never runs if _make_bot exits before the try is entered).
    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, task_name=name or _default_task_name(instruction),
    )
    try:
        try:
            driver = appium_webdriver.Remote(appium_url, options=options)
        except Exception as e:
            # Appium setup failed before _run_local took over reporting; record
            # the failure so the outer finally:bot.close() doesn't complete the
            # task as succeeded. Scoped to Remote() only — a driver.quit() error
            # after a successful run must not be misreported as a task failure.
            _fail_setup(bot, e)
        try:
            _run_local(bot, driver, instruction, max_steps, base_url=ctx.obj["base_url"])
        finally:
            driver.quit()
    finally:
        bot.close()


def _run_airtest(
    ctx: click.Context,
    instruction: str,
    name: str,
    model: str,
    language: str,
    max_steps: int,
    connect: Callable[[], Any],
    report: bool,
    report_dir: str,
    annotate: bool,
) -> None:
    """Shared android/ios airtest body: build the bot, connect the device, run.

    ``connect`` performs the airtest connect + optional app launch and returns
    the bind target. Like _run_appium, the bot is built first (it validates the
    API key and may sys.exit()); unlike Appium there is no remote session to
    quit, so the only teardown is bot.close().
    """
    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, task_name=name or _default_task_name(instruction),
    )
    try:
        try:
            target = connect()
        except Exception as e:
            # Same contract as _run_appium: a setup failure before _run_local
            # takes over reporting must be recorded, or the finally:bot.close()
            # would complete the task as succeeded.
            _fail_setup(bot, e)
        _run_local(bot, target, instruction, max_steps, base_url=ctx.obj["base_url"])
    finally:
        bot.close()


@cli.command()
@click.argument("instruction")
@_task_options
@click.option("--engine", default="airtest", type=click.Choice(["airtest", "appium"]), help="Automation backend: airtest drives the device directly over adb (no server); appium goes through an Appium server at --appium-url")
@click.option("--device", "-d", default="", help="Which device: an adb serial from `adb devices` (e.g. emulator-5554 or 192.168.1.8:5555). Optional when exactly one device is connected. Appium engine: passed as deviceName.")
@click.option("--appium-url", default="http://localhost:4723", help="Appium server URL (appium engine)")
# Android — app launch
@click.option("--app-package", default="", help="App package to launch (e.g. com.android.settings)")
@click.option("--app-activity", default="", help="App activity to launch")
@_debug_options(record=False)
@click.pass_context
def android(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, engine: str, device: str, appium_url: str, app_package: str, app_activity: str, report: bool, report_dir: str, annotate: bool) -> None:
    """Run an AI task on an Android device (direct over adb; --engine appium for Appium).

    \b
    Default engine — drives the device straight over adb, no server needed:
      qirabot android "Open settings"                    # the only adb device
      qirabot android "..." -d emulator-5554             # pick one of several
      qirabot android "..." -d 192.168.1.8:5555          # network device (adb connect)
      qirabot android "..." --app-package com.android.settings --app-activity .Settings
    \b
    Appium engine — needs a running server (npm i -g appium && appium driver
    install uiautomator2 && appium), reached via --appium-url:
      qirabot android "..." --engine appium -d emulator-5554 --app-package com.android.settings
    """
    if engine == "appium":
        require("appium.webdriver", "appium")
        from appium.options.android import UiAutomator2Options

        options = UiAutomator2Options()
        if device:
            options.device_name = device
        if app_package:
            options.app_package = app_package
        if app_activity:
            options.app_activity = app_activity

        _run_appium(
            ctx, instruction, name, model, language, max_steps, appium_url, options,
            report, report_dir, annotate,
        )
        return

    if _flag_given(ctx, "appium_url"):
        raise click.UsageError("--appium-url only applies to --engine appium")
    _require_airtest()
    from airtest.core.api import connect_device, start_app

    def connect() -> Any:
        try:
            target = connect_device(f"Android:///{device}")
        except Exception as e:
            raise RuntimeError(
                f"could not connect to an adb device ({e}); check `adb devices`, "
                "or use --engine appium"
            ) from e
        if app_package:
            start_app(app_package, app_activity or None)
        return target

    _run_airtest(
        ctx, instruction, name, model, language, max_steps, connect,
        report, report_dir, annotate,
    )


@cli.command()
@click.argument("instruction")
@_task_options
@click.option("--engine", default="airtest", type=click.Choice(["airtest", "appium"]), help="Automation backend: airtest drives WebDriverAgent directly at --wda-url (no Appium server); appium goes through an Appium server (simulators, auto WDA build)")
@click.option("--wda-url", default="http://127.0.0.1:8100", help="WebDriverAgent URL — this is how the default engine picks the device (USB real device: run `iproxy 8100 8100` and keep the default; another device = its WDA address)")
@click.option("--device", "-d", default="", help="Device name for the appium engine (e.g. \"iPhone 15\" simulator). The default engine selects the device via --wda-url instead.")
@click.option("--appium-url", default="http://localhost:4723", help="Appium server URL (appium engine)")
# iOS — app launch
@click.option("--bundle-id", default="", help="App bundle id to launch (e.g. com.tencent.xin)")
@_debug_options(record=False)
@click.pass_context
def ios(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, engine: str, wda_url: str, device: str, appium_url: str, bundle_id: str, report: bool, report_dir: str, annotate: bool) -> None:
    """Run an AI task on an iOS device (direct via WDA; --engine appium for Appium).

    \b
    Default engine — talks to WebDriverAgent directly, no Appium server. WDA
    must be running on the device (USB real device: `iproxy 8100 8100` first):
      qirabot ios "..." --bundle-id com.tencent.xin          # WDA on 127.0.0.1:8100
      qirabot ios "..." --wda-url http://192.168.1.20:8100   # another device's WDA
    \b
    Appium engine — needs a running server (npm i -g appium && appium driver
    install xcuitest && appium); use for simulators or to auto build/sign WDA:
      qirabot ios "..." --engine appium -d "iPhone 15" --bundle-id com.apple.Preferences
    """
    if engine == "appium":
        if _flag_given(ctx, "wda_url"):
            raise click.UsageError("--wda-url only applies to --engine airtest")
        require("appium.webdriver", "appium")
        from appium.options.ios import XCUITestOptions

        options = XCUITestOptions()
        if device:
            options.device_name = device
        if bundle_id:
            options.bundle_id = bundle_id

        _run_appium(
            ctx, instruction, name, model, language, max_steps, appium_url, options,
            report, report_dir, annotate,
        )
        return

    if _flag_given(ctx, "appium_url"):
        raise click.UsageError("--appium-url only applies to --engine appium")
    if _flag_given(ctx, "device"):
        raise click.UsageError("--device only applies to --engine appium; the airtest engine connects via --wda-url")
    _require_airtest()
    from airtest.core.api import connect_device

    def connect() -> Any:
        try:
            target = connect_device(f"iOS:///{wda_url}")
        except Exception as e:
            raise RuntimeError(
                f"could not reach WDA at {wda_url} ({e}); start WDA (real device: "
                "`iproxy 8100 8100`), or use --engine appium"
            ) from e
        if bundle_id:
            # Launch via WDA's app_launch, NOT airtest's start_app: start_app
            # routes through the bundled go-ios CLI, which fails on iOS 17+
            # without a RemoteXPC tunnel daemon.
            target.driver.app_launch(bundle_id)
        return target

    _run_airtest(
        ctx, instruction, name, model, language, max_steps, connect,
        report, report_dir, annotate,
    )


@cli.command()
@click.argument("instruction")
@_task_options
# Desktop — app launch
@click.option("--app", default="", help="Launch/activate an app before the task. macOS: app name (\"WeChat\") or bundle id; Windows: exe path, registered name, or UWP AppUserModelID; Linux: executable.")
@click.option("--app-wait", default=2.0, type=float, help="Seconds to wait after --app launch for the window to appear")
@_debug_options()
@click.pass_context
def desktop(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, app: str, app_wait: float, report: bool, report_dir: str, annotate: bool, record: bool) -> None:
    """Run an AI task on the desktop screen via pyautogui."""
    pyautogui = require("pyautogui", "desktop")

    # Validate the key before the --app side effect: without this, a missing
    # key would launch the app first and only then error out.
    _require_api_key(ctx)

    if app:
        from qirabot import launch_app

        try:
            launch_app(app, wait=app_wait)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, record=record, task_name=name or _default_task_name(instruction),
    )
    try:
        _run_local(bot, pyautogui, instruction, max_steps, base_url=ctx.obj["base_url"])
    finally:
        bot.close()


def main() -> None:
    # The SDK never reads .env implicitly; the CLI is the "calling script" in
    # that contract, so it opts in here — before click parses options, so the
    # envvar fallbacks (QIRA_API_KEY etc.) see the values. Best-effort, and
    # exported variables always win over .env entries.
    load_dotenv()
    # Catch SDK errors that escape command bodies and print them as one line,
    # no traceback: MissingDependencyError (install hint, may surface deep
    # inside a command via lazy imports) and transport errors from the
    # read-only commands (task/screenshot/models), which call the server
    # directly without _make_bot/_run_local's handling.
    try:
        cli()
    except QirabotError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
