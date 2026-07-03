"""Qirabot CLI entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any, NoReturn, TypeVar

import click

from qirabot._dotenv import load_dotenv
from qirabot._optional import require
from qirabot._transport import Transport
from qirabot.exceptions import QirabotError


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

    Setup — bot.open() for browse, Appium Remote() for mobile — runs after the
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
    """Task options shared by browse/mobile/desktop. Applied in reverse so
    --help lists them in reading order (name, model, language, max-steps)."""
    f = click.option("--max-steps", default=20, help="Max steps for AI")(f)
    f = click.option("--language", "-l", default="", help="Language (e.g. zh, en)")(f)
    f = click.option("--model", "-m", default="", help="Model alias")(f)
    f = click.option("--name", "-n", default="", help="Task name shown in the web UI (default: derived from the instruction)")(f)
    return f


def _debug_options(record: bool = True) -> Callable[[_FC], _FC]:
    """Debug options shared by browse/mobile/desktop; mobile has no screen
    recording, so --record is opt-out there."""

    def wrap(f: _FC) -> _FC:
        if record:
            f = click.option("--record", is_flag=True, help="Record the screen to report-dir/recording.mp4 (requires ffmpeg)")(f)
        f = click.option("--annotate/--no-annotate", default=True, help="Annotate saved screenshots with click coordinates")(f)
        f = click.option("--report-dir", default="", help="Report output root (env QIRA_REPORT_DIR; default ./qira_runs/<date>/<run>/)")(f)
        f = click.option("--report/--no-report", default=True, help="Write an HTML run report to --report-dir")(f)
        return f

    return wrap


class _AliasGroup(click.Group):
    """Accept noun aliases so every backend can be addressed by its surface
    name (`qirabot browser ...` == `qirabot browse ...`); --help lists only
    the canonical names."""

    _aliases = {"browser": "browse"}

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        return super().get_command(ctx, self._aliases.get(cmd_name, cmd_name))


@click.group(cls=_AliasGroup, context_settings=_CONTEXT_SETTINGS)
@click.version_option(package_name="qirabot", prog_name="qirabot")
@click.option("--api-key", envvar="QIRA_API_KEY", help="API key")
@click.option("--base-url", envvar="QIRA_BASE_URL", default="https://app.qirabot.com", help="Server URL")
@click.option("--timeout", type=float, default=120.0, help="HTTP request timeout (seconds)")
@click.option("--verify-ssl/--no-verify-ssl", default=True, help="Verify the server's TLS certificate")
@click.pass_context
def cli(ctx: click.Context, api_key: str, base_url: str, timeout: float, verify_ssl: bool) -> None:
    """Qirabot CLI — AI automation tool.

    Global options (--api-key/--base-url/--timeout/--verify-ssl) go before the
    subcommand, e.g. `qirabot --base-url ... browse "..."`.
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
def browse(
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


@cli.command()
@click.argument("instruction")
@_task_options
# Mobile — basic
@click.option("--platform", "-p", default="android", type=click.Choice(["android", "ios"]), help="Mobile platform")
@click.option("--device", "-d", default="", help="Device name or serial")
@click.option("--appium-url", default="http://localhost:4723", help="Appium server URL")
# Mobile — Android app launch
@click.option("--app-package", default="", help="Android app package")
@click.option("--app-activity", default="", help="Android app activity")
# Mobile — iOS app launch
@click.option("--bundle-id", default="", help="iOS app bundle id to launch (e.g. com.tencent.xin)")
@_debug_options(record=False)
@click.pass_context
def mobile(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, platform: str, device: str, appium_url: str, app_package: str, app_activity: str, bundle_id: str, report: bool, report_dir: str, annotate: bool) -> None:
    """Run an AI task on a mobile device via Appium."""
    appium_webdriver = require("appium.webdriver", "appium")

    # Reject cross-platform flag combos early — silently ignoring e.g.
    # --app-package under iOS would hide a user mistake.
    if platform == "ios" and (app_package or app_activity):
        raise click.UsageError("--app-package/--app-activity are Android-only; use --bundle-id with --platform ios")
    if platform == "android" and bundle_id:
        raise click.UsageError("--bundle-id is iOS-only; use --app-package/--app-activity with --platform android")

    if platform == "android":
        from appium.options.android import UiAutomator2Options

        # Union of the two option types via Any: the branches build different
        # concrete classes and mypy would otherwise flag the reassignment below.
        options: Any = UiAutomator2Options()
        if device:
            options.device_name = device
        if app_package:
            options.app_package = app_package
        if app_activity:
            options.app_activity = app_activity
    else:
        from appium.options.ios import XCUITestOptions
        options = XCUITestOptions()
        if device:
            options.device_name = device
        if bundle_id:
            options.bundle_id = bundle_id

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
