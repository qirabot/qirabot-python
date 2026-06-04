"""Qirabot CLI entry point."""

from __future__ import annotations

import sys
from typing import Any

import click

from qirabot._transport import Transport


def _transport(ctx: click.Context) -> Transport:
    """Get or create a shared Transport from the CLI context."""
    if "transport" not in ctx.obj:
        api_key = ctx.obj["api_key"]
        base_url = ctx.obj["base_url"]
        if not api_key:
            click.echo("Error: --api-key or QIRA_API_KEY is required", err=True)
            sys.exit(1)
        ctx.obj["transport"] = Transport(base_url=base_url, api_key=api_key)
    transport: Transport = ctx.obj["transport"]
    return transport


def _make_bot(
    ctx: click.Context,
    model: str = "",
    language: str = "",
    screenshot_dir: str = "",
    screenshot_debug: bool = False,
    task_name: str = "cli",
) -> Any:
    from qirabot import Qirabot

    api_key = ctx.obj["api_key"]
    base_url = ctx.obj["base_url"]
    if not api_key:
        click.echo("Error: API key is required. Set QIRA_API_KEY or use --api-key.", err=True)
        sys.exit(1)
    try:
        return Qirabot(
            api_key=api_key,
            base_url=base_url,
            model_alias=model,
            language=language,
            task_name=task_name,
            source="cli",
            screenshot_dir=screenshot_dir,
            screenshot_annotate=screenshot_debug,
        )
    except Exception as e:
        msg = str(e)
        if "ConnectError" in type(e).__name__ or "nodename" in msg or "Connection refused" in msg:
            click.echo(f"Error: Cannot connect to server at {base_url}. Check QIRA_BASE_URL.", err=True)
        else:
            click.echo(f"Error: {msg}", err=True)
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
        msg = str(e)
        if "<html" in msg.lower():
            msg = msg.split("<")[0].strip().rstrip(":")
        # Report the client-side abort so the task is recorded as failed; without
        # this the bot.close() in the caller's finally would complete the
        # still-running task as succeeded.
        bot.fail(msg)
        console.print(f"[bold red]Error:[/bold red] {msg}")
        sys.exit(1)
    if result.success:
        console.print(f"[bold green]Done:[/bold green] {result.output}")
    else:
        # The server already set a terminal status for known failures (e.g. max
        # steps); fail() is idempotent there and ensures other failure paths are
        # not left to close()'s success default.
        bot.fail(result.output)
        console.print(f"[bold red]Failed:[/bold red] {result.output}")


@click.group()
@click.option("--api-key", envvar="QIRA_API_KEY", help="API key")
@click.option("--base-url", envvar="QIRA_BASE_URL", default="https://app.qirabot.com", help="Server URL")
@click.pass_context
def cli(ctx: click.Context, api_key: str, base_url: str) -> None:
    """Qirabot CLI — AI automation tool."""
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url


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
@click.option("--output", "-o", default="", help="Save to file path")
@click.pass_context
def screenshot(ctx: click.Context, task_id: str, step: int, output: str) -> None:
    """Download a task screenshot."""
    t = _transport(ctx)

    path = f"/screenshots?taskId={task_id}"
    if step > 0:
        path += f"&step={step}"

    data = t.get_bytes(path)
    if output:
        with open(output, "wb") as f:
            f.write(data)
        click.echo(f"Saved to {output} ({len(data)} bytes)")
    else:
        click.echo(f"Screenshot: {len(data)} bytes (use -o to save)")


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
# Task
@click.option("--name", "-n", default="cli", help="Task name (shown in web UI / task list)")
@click.option("--model", "-m", default="", help="Model alias")
@click.option("--language", "-l", default="", help="Language (e.g. zh, en)")
@click.option("--max-steps", default=20, help="Max steps for AI")
# Browser — basic
@click.option("--url", "-u", default="", help="URL to open (optional, AI navigates if omitted)")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
@click.option("--viewport", default="1280x800", help="Viewport size as WIDTHxHEIGHT")
# Browser — advanced
@click.option("--channel", default="", help="Browser channel: chrome, msedge, etc. (uses installed browser instead of bundled Chromium)")
@click.option("--user-data-dir", default="", help="Persistent browser profile directory (keeps cookies/history across runs)")
@click.option("--browser-arg", multiple=True, help="Extra Chromium launch arg, repeatable (e.g. --browser-arg=--disable-blink-features=AutomationControlled)")
@click.option("--cdp", default="", help="Connect to existing Chrome via CDP (e.g. http://localhost:9222 or wss://chrome.browserless.io?token=xxx). Mutually exclusive with --headless/--user-data-dir/--channel/--browser-arg.")
# Debug
@click.option("--screenshot-dir", default="", help="Save screenshots to directory")
@click.option("--screenshot-debug", is_flag=True, help="Annotate saved screenshots with click coordinates (requires --screenshot-dir)")
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
    cdp: str,
    screenshot_dir: str,
    screenshot_debug: bool,
) -> None:
    """Run an AI task in a local browser."""
    if cdp and (headless or user_data_dir or channel or browser_arg):
        raise click.UsageError(
            "--cdp cannot be combined with --headless/--user-data-dir/--channel/--browser-arg"
        )
    try:
        w_str, h_str = viewport.lower().split("x")
        vp = (int(w_str), int(h_str))
    except ValueError:
        raise click.BadParameter(f"viewport must be WIDTHxHEIGHT, got '{viewport}'")

    bot = _make_bot(ctx, model=model, language=language, screenshot_dir=screenshot_dir, screenshot_debug=screenshot_debug, task_name=name)
    try:
        page = bot.open(
            url=url,
            headless=headless,
            viewport=vp,
            user_data_dir=user_data_dir,
            channel=channel,
            args=list(browser_arg) if browser_arg else None,
            cdp_url=cdp,
        )
        _run_local(bot, page, instruction, max_steps, base_url=ctx.obj["base_url"])
    finally:
        bot.close()


@cli.command()
@click.argument("instruction")
# Task
@click.option("--name", "-n", default="cli", help="Task name (shown in web UI / task list)")
@click.option("--model", "-m", default="", help="Model alias")
@click.option("--language", "-l", default="", help="Language (e.g. zh, en)")
@click.option("--max-steps", default=20, help="Max steps for AI")
# Mobile — basic
@click.option("--platform", "-p", default="android", type=click.Choice(["android", "ios"]), help="Mobile platform")
@click.option("--device", "-d", default="", help="Device name or serial")
@click.option("--appium-url", default="http://localhost:4723", help="Appium server URL")
# Mobile — Android app launch
@click.option("--app-package", default="", help="Android app package")
@click.option("--app-activity", default="", help="Android app activity")
# Mobile — iOS app launch
@click.option("--bundle-id", default="", help="iOS app bundle id to launch (e.g. com.tencent.xin)")
# Debug
@click.option("--screenshot-dir", default="", help="Save screenshots to directory")
@click.option("--screenshot-debug", is_flag=True, help="Annotate saved screenshots with click coordinates (requires --screenshot-dir)")
@click.pass_context
def mobile(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, platform: str, device: str, appium_url: str, app_package: str, app_activity: str, bundle_id: str, screenshot_dir: str, screenshot_debug: bool) -> None:
    """Run an AI task on a mobile device via Appium."""
    from appium import webdriver as appium_webdriver

    if platform == "android":
        from appium.options.android import UiAutomator2Options
        options = UiAutomator2Options()
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

    driver = appium_webdriver.Remote(appium_url, options=options)
    bot = _make_bot(ctx, model=model, language=language, screenshot_dir=screenshot_dir, screenshot_debug=screenshot_debug, task_name=name)
    try:
        _run_local(bot, driver, instruction, max_steps, base_url=ctx.obj["base_url"])
    finally:
        bot.close()
        driver.quit()


@cli.command()
@click.argument("instruction")
# Task
@click.option("--name", "-n", default="cli", help="Task name (shown in web UI / task list)")
@click.option("--model", "-m", default="", help="Model alias")
@click.option("--language", "-l", default="", help="Language (e.g. zh, en)")
@click.option("--max-steps", default=20, help="Max steps for AI")
# Desktop — app launch
@click.option("--app", default="", help="Launch/activate an app before the task. macOS: app name (\"WeChat\") or bundle id; Windows: exe path, registered name, or UWP AppUserModelID; Linux: executable.")
@click.option("--app-wait", default=2.0, type=float, help="Seconds to wait after --app launch for the window to appear")
# Debug
@click.option("--screenshot-dir", default="", help="Save screenshots to directory")
@click.option("--screenshot-debug", is_flag=True, help="Annotate saved screenshots with click coordinates (requires --screenshot-dir)")
@click.pass_context
def desktop(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, app: str, app_wait: float, screenshot_dir: str, screenshot_debug: bool) -> None:
    """Run an AI task on the desktop screen via pyautogui."""
    import pyautogui

    if app:
        from qirabot import launch_app

        try:
            launch_app(app, wait=app_wait)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    bot = _make_bot(ctx, model=model, language=language, screenshot_dir=screenshot_dir, screenshot_debug=screenshot_debug, task_name=name)
    try:
        _run_local(bot, pyautogui, instruction, max_steps, base_url=ctx.obj["base_url"])
    finally:
        bot.close()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
