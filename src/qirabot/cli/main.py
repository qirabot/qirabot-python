"""Qirabot CLI entry point."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, TypeVar

import click
from click.core import ParameterSource

from qirabot._browser import launch_browser
from qirabot._dotenv import load_dotenv
from qirabot._optional import extra_install_hint, package_install_hint, require
from qirabot._transport import Transport
from qirabot.exceptions import QirabotError


# Whether QIRA_API_KEY entered os.environ via ./.env (set by main() around
# load_dotenv), so `login --status` can name the real source layer.
_KEY_FROM_DOTENV = False


def _require_api_key(ctx: click.Context) -> str:
    """Single place for the missing-key error so every command says the same thing."""
    api_key: str = ctx.obj["api_key"]
    if not api_key:
        click.echo(
            "Error: API key is required. Run `qirabot login` to save one "
            "(or set QIRA_API_KEY / pass --api-key).",
            err=True,
        )
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
    record_mjpeg_url: str = "",
    record_device: bool = False,
    record_window: bool = False,
    task_name: str = "",
    overlay: bool = False,
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
            record_mjpeg_url=record_mjpeg_url or None,
            record_device=record_device,
            record_window=record_window,
            overlay=overlay,
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
    knowledge: str = "",
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
        result = bot.ai(
            target, instruction, max_steps=max_steps, on_step=on_step,
            knowledge=knowledge or None,
        )
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
    except QirabotError as e:
        if getattr(e, "code", "") == "user_abort":
            # ESC-hold kill switch: the same deliberate cancel as Ctrl+C
            # above, so it gets the same face — yellow, exit 130, never a
            # red Error. ai() already routed it through cancel(), so the
            # terminal state is recorded; no fail() here.
            console.print("\n[bold yellow]Cancelled[/bold yellow] (ESC held)")
            sys.exit(130)
        bot.fail(str(e))
        console.print(f"[bold red]Error:[/bold red] {escape(str(e))}")
        sys.exit(1)
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

    Setup — bot.open() for browser, Appium Remote() / device resolution for
    android/ios/desktop — runs after the
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

# --help group headings for the task commands. The two shared groups say
# "(all platforms)" so users can see at a glance which flags carry over
# between browser/android/ios/desktop.
_TASK_GROUP = "Task options (all platforms)"
_DEBUG_GROUP = "Report & debug options (all platforms)"


def _option(*decls: str, group: str, **attrs: Any) -> Callable[[_FC], _FC]:
    """click.option that tags the option with a --help group heading, rendered
    by _GroupedCommand. Groups appear in declaration (reading) order."""

    def deco(f: _FC) -> _FC:
        f = click.option(*decls, **attrs)(f)
        f.__click_params__[-1].help_group = group  # type: ignore[attr-defined]
        return f

    return deco


class _GroupedCommand(click.Command):
    """Command whose --help lists options under group headings instead of one
    flat list. Untagged params (just the trailing --help in practice) land
    under "Other options"."""

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        groups: dict[str, list[tuple[str, str]]] = {}
        for param in self.get_params(ctx):
            record = param.get_help_record(ctx)
            if record is None:
                continue
            title = getattr(param, "help_group", "") or "Other options"
            groups.setdefault(title, []).append(record)
        for title, records in groups.items():
            with formatter.section(title):
                formatter.write_dl(records)


def _resolve_knowledge_cb(
    ctx: click.Context, param: click.Parameter, value: tuple[Path, ...]
) -> str:
    """Resolve --knowledge files into the final text at parse time, so UTF-8 and
    size errors surface before any task is created or browser/device opened.
    click.Path already guarantees each file exists."""
    if not value:
        return ""
    from qirabot._knowledge import resolve_knowledge

    try:
        return resolve_knowledge(list(value))
    except ValueError as e:
        raise click.BadParameter(str(e)) from None


def _task_options(f: _FC) -> _FC:
    """Task options shared by browser/android/ios/desktop. Applied in reverse so
    --help lists them in reading order (name, model, language, max-steps,
    knowledge)."""
    # File paths only, never inline text: argv has no str/Path type split to
    # declare intent with, and sniffing is off the table (see _knowledge.py).
    # Inline snippets work through the shell: -k <(printf '...').
    f = _option(
        "--knowledge", "-k", group=_TASK_GROUP, multiple=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        callback=_resolve_knowledge_cb,
        help="Knowledge file the AI consults during the task (UTF-8 text; repeatable, 32KB total)",
    )(f)
    f = _option("--max-steps", group=_TASK_GROUP, default=20, help="Max steps for AI")(f)
    f = _option("--language", "-l", group=_TASK_GROUP, default="", help="Language (e.g. zh, en)")(f)
    f = _option("--model", "-m", group=_TASK_GROUP, default="", help="Model alias")(f)
    f = _option("--name", "-n", group=_TASK_GROUP, default="", help="Task name shown in the web UI (default: derived from the instruction)")(f)
    return f


def _debug_options(record: bool = True) -> Callable[[_FC], _FC]:
    """Debug options shared by browser/android/ios/desktop. This --record is
    the host-screen (ffmpeg) recorder, so it's opted out for android/ios —
    they define their own device-screen --record instead (grouped under the
    platform heading, since its semantics are platform-specific)."""

    def wrap(f: _FC) -> _FC:
        if record:
            f = _option("--record", group=_DEBUG_GROUP, is_flag=True, help="Record the screen to report-dir/recording.mp4 (requires ffmpeg)")(f)
        f = _option("--overlay/--no-overlay", group=_DEBUG_GROUP, default=True, help="Show task progress in a small bottom-right on-screen window — excluded from screenshots, click-through (macOS/Windows; no-op elsewhere)")(f)
        f = _option("--annotate/--no-annotate", group=_DEBUG_GROUP, default=True, help="Annotate saved screenshots with click coordinates")(f)
        f = _option("--report-dir", group=_DEBUG_GROUP, default="", help="Report output root (env QIRA_REPORT_DIR; default ./qira_runs/<date>/<run>/)")(f)
        f = _option("--report/--no-report", group=_DEBUG_GROUP, default=True, help="Write an HTML run report to --report-dir")(f)
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
    # Key resolution order: --api-key flag > QIRA_API_KEY env var > ./.env
    # (loaded into the environment by main()) > the `qirabot login` config
    # file. The source tag feeds `qirabot login --status`.
    source = ""
    if api_key:
        if ctx.get_parameter_source("api_key") == ParameterSource.COMMANDLINE:
            source = "flag"
        else:
            source = ".env" if _KEY_FROM_DOTENV else "env"
    else:
        from qirabot._userconfig import load_api_key

        stored = load_api_key()
        if stored:
            api_key, source = stored, "config"
    ctx.obj["api_key"] = api_key
    ctx.obj["api_key_source"] = source
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
@click.option("--status", is_flag=True, help="Show the configured key (masked) and which layer it comes from")
@click.option("--paste", is_flag=True, help="Paste an API key manually instead of the browser flow")
@click.pass_context
def login(ctx: click.Context, status: bool, paste: bool) -> None:
    """Log in via the browser — every later command picks the key up automatically.

    Prints a short confirmation code and a URL (opening the browser when one
    is available), waits for you to click Authorize on the web page, then
    verifies the resulting API key against the server and writes it to the
    user config file (chmod 600). The page can be opened on any device — the
    browser doesn't have to run on this machine. Environment variables and
    ./.env keep working and always take precedence. Use --paste to enter a
    key from the dashboard manually instead.
    """
    from qirabot import _userconfig as user_config

    if status:
        key: str = ctx.obj["api_key"]
        if not key:
            click.echo(
                "No API key configured. Run `qirabot login`, or set QIRA_API_KEY."
            )
            sys.exit(1)
        origin = {
            "flag": "--api-key flag",
            "env": "QIRA_API_KEY environment variable",
            ".env": "./.env file",
            "config": f"login config ({user_config.config_path()})",
        }.get(ctx.obj["api_key_source"], "unknown")
        click.echo(f"API key: {user_config.mask_key(key)}  (from: {origin})")
        return

    if paste:
        _login_paste(ctx)
        return

    import platform as platform_mod

    transport = Transport(
        base_url=ctx.obj["base_url"],
        api_key="",
        timeout=min(ctx.obj["timeout"], 10.0),
        verify_ssl=ctx.obj["verify_ssl"],
    )
    try:
        start = transport.request(
            "POST", "/auth/cli/start", json_data={"clientName": platform_mod.node()}
        )
    except QirabotError as e:
        # Only a missing route means "older server without browser login".
        # Connection failures must NOT fall back to paste — the user would
        # save a key for a server they can't reach and be confused later.
        if getattr(e, "status_code", None) in (404, 405):
            click.echo(
                "This server doesn't support browser login; falling back to manual entry."
            )
            _login_paste(ctx)
            return
        click.echo(f"Error: could not start browser login ({e})", err=True)
        sys.exit(1)

    user_code = start.get("userCode", "")
    uri_complete = start.get("verificationUriComplete") or start.get("verificationUri", "")
    interval = max(1, int(start.get("interval", 3)))
    expires_in = int(start.get("expiresIn", 600))

    click.echo()
    click.echo(f"  Confirmation code: {user_code}")
    click.echo(f"  Open this page and check the code matches: {uri_complete}")
    click.echo()

    import webbrowser

    try:
        webbrowser.open(uri_complete)
    except Exception:
        pass  # headless is fine — the URL above works from any device

    from rich.console import Console

    key = ""
    deadline = time.monotonic() + expires_in
    with Console().status("Waiting for approval in the browser (Ctrl-C to cancel)..."):
        while time.monotonic() < deadline:
            time.sleep(interval)
            try:
                res = transport.request(
                    "POST",
                    "/auth/cli/poll",
                    json_data={"deviceCode": start.get("deviceCode", "")},
                )
            except QirabotError as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)
            poll_status = res.get("status")
            if poll_status == "pending":
                continue
            if poll_status == "approved":
                key = res.get("apiKey") or ""
                break
            if poll_status == "denied":
                click.echo(
                    "Error: the request was denied in the browser; nothing saved.",
                    err=True,
                )
                sys.exit(1)
            click.echo(
                "Error: the code expired before approval; run `qirabot login` again.",
                err=True,
            )
            sys.exit(1)

    if not key:
        click.echo(
            "Error: timed out waiting for approval; run `qirabot login` again.",
            err=True,
        )
        sys.exit(1)

    _verify_and_save(ctx, key)


def _login_paste(ctx: click.Context) -> None:
    """The pre-2.2 manual flow: prompt for a key pasted from the dashboard."""
    key = click.prompt(
        "API key (qk_..., from https://app.qirabot.com)", hide_input=True
    ).strip()
    if not key:
        raise click.ClickException("empty API key; nothing saved")
    _verify_and_save(ctx, key)


def _verify_and_save(ctx: click.Context, key: str) -> None:
    from qirabot import _userconfig as user_config

    # Verify BEFORE writing — an unverified key must not silently poison every
    # later command. Short timeout: this is a diagnostic-grade request.
    try:
        with_transport = Transport(
            base_url=ctx.obj["base_url"],
            api_key=key,
            timeout=min(ctx.obj["timeout"], 10.0),
            verify_ssl=ctx.obj["verify_ssl"],
        )
        with_transport.request("GET", "/model-aliases")
    except Exception as e:
        click.echo(
            f"Error: {ctx.obj['base_url']} rejected this key or is unreachable "
            f"({e}); nothing saved.",
            err=True,
        )
        sys.exit(1)
    path = user_config.save_api_key(key)
    click.echo(f"Key verified and saved to {path}.")
    click.echo('You\'re set — try: qirabot browser "Search for SpaceX on Wikipedia"')


@cli.command("install-browser")
def install_browser() -> None:
    """Download the Chromium that browser automation drives (one-time).

    Exists because isolated installs (`uv tool install`, the install script)
    don't put Playwright's own `playwright` command on PATH — this wraps the
    same Chromium download so the second setup step is identical everywhere.
    """
    require("playwright", "browser")
    import subprocess

    rc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"]
    ).returncode
    if rc != 0:
        raise click.ClickException(f"Chromium download failed (exit {rc})")
    click.echo('Chromium installed — you\'re ready: qirabot browser "..."')


def _parse_viewport(viewport: str) -> tuple[int, int]:
    try:
        w_str, h_str = viewport.lower().split("x")
        return (int(w_str), int(h_str))
    except ValueError:
        raise click.BadParameter(f"viewport must be WIDTHxHEIGHT, got '{viewport}'")


@cli.command("open-browser", cls=_GroupedCommand)
@_option("--url", "-u", group="Browser options", default="", help="URL to open, e.g. the site's login page")
@_option("--user-data-dir", group="Browser options", required=True, help="Profile directory to save the session into — pass the same directory to `qirabot browser` or bot.open() later")
@_option("--viewport", group="Browser options", default="1280x800", help="Viewport size as WIDTHxHEIGHT")
@_option("--channel", group="Browser options", default="", help="Browser channel: chrome, msedge, etc. (uses installed browser instead of bundled Chromium)")
@_option("--browser-arg", group="Browser options", multiple=True, help="Extra Chromium launch arg, repeatable")
def open_browser(
    url: str,
    user_data_dir: str,
    viewport: str,
    channel: str,
    browser_arg: tuple[str, ...],
) -> None:
    """Open a browser to log in to websites by hand — no AI task, no API key.

    Cookies and local storage persist in --user-data-dir, so AI runs that
    reuse the same directory (`qirabot browser ... --user-data-dir <dir>` or
    `bot.open(url, user_data_dir=<dir>)`) start already signed in. Close the
    browser window (or press Ctrl-C) when you're done; a profile directory
    can't be shared by two browsers at once, so close it before running tasks.
    """
    # Qirabot.open() would fall back to headless here, which is right for AI
    # tasks but useless for a browser that exists only to be clicked in.
    if not _display_available():
        raise click.ClickException(
            "no display detected (DISPLAY/WAYLAND_DISPLAY unset) — this command "
            "opens a visible browser for you to log in with, which cannot work "
            "here. Run it on a machine with a display, then copy the profile "
            "directory over."
        )
    vp = _parse_viewport(viewport)
    launched = launch_browser(
        url=url,
        headless=False,
        viewport=vp,
        user_data_dir=user_data_dir,
        channel=channel,
        args=list(browser_arg) if browser_arg else None,
    )
    click.echo("Browser is open — log in to the sites your automation needs.")
    click.echo("When you're done, close the browser window (or press Ctrl-C here).")
    try:
        launched.context.wait_for_event("close", timeout=0)
    except KeyboardInterrupt:
        pass
    finally:
        for close in (launched.context.close, launched.playwright.stop):
            try:
                close()
            except Exception:
                pass
    click.echo(f"Session saved to {user_data_dir}")
    click.echo(f'Next: qirabot browser "<your task>" --user-data-dir {user_data_dir}')


def _has_module(module: str) -> bool:
    """Probe an optional dependency without require()'s raise (doctor only).

    Catches every exception, not just ImportError: pyautogui raises KeyError
    at import time on a display-less Linux box (no $DISPLAY), and a probe
    must report "not usable here", never crash doctor.
    """
    import importlib

    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


def _adb_binary_found() -> bool:
    """Probe the adb binary (doctor only) — the android backend is pure stdlib,
    so the binary, not a Python module, is the thing that can be missing."""
    from qirabot.adb import _which_adb

    return _which_adb() is not None


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
            f"{bad} API key not set — run `qirabot login` "
            "(or export QIRA_API_KEY=qk_... / put it in ./.env)"
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
        # Not `playwright install chromium`: isolated installs (uv tool) don't
        # put Playwright's own command on PATH, and the wrapper works everywhere.
        "no-browser": "qirabot install-browser",
        "no-libs": "sudo playwright install-deps chromium  "
        "(Chromium is downloaded but system libraries are missing)",
    }
    browser_hint = extra_install_hint("browser") + " && qirabot install-browser"
    backends = [
        (
            "browser (Playwright — default path, powers bot.open())",
            chromium == "ready",
            chromium_hints.get(chromium or "", browser_hint),
        ),
        (
            "desktop (pyautogui)",
            _has_module("pyautogui"),
            extra_install_hint("desktop"),
        ),
        (
            "android direct (adb — built in, needs the adb binary)",
            _adb_binary_found(),
            "install Android platform-tools and put adb on PATH "
            "(https://developer.android.com/tools/releases/platform-tools)",
        ),
        (
            "android/ios via server (Appium)",
            _has_module("appium"),
            extra_install_hint("appium"),
        ),
        (
            "selenium (bring-your-own driver)",
            _has_module("selenium"),
            package_install_hint("selenium"),
        ),
    ]

    console.print("\n[bold]Backends[/bold] — you only need the one you plan to drive:")
    # Informational (not a gate): the direct iOS backend is built into the core
    # package; its only requirement — WebDriverAgent running on the device —
    # can't be probed from here.
    console.print(
        f"  {ok} ios direct (WDA — built in; needs WebDriverAgent running on the device)"
    )
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
            f"\n{bad} No backend installed. Quickest start: " + escape(browser_hint)
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


@cli.command(cls=_GroupedCommand)
@click.argument("instruction")
@_task_options
# Browser — basic
@_option("--url", "-u", group="Browser options", default="", help="URL to open (optional, AI navigates if omitted)")
@_option("--headless", group="Browser options", is_flag=True, help="Run browser in headless mode")
@_option("--viewport", group="Browser options", default="1280x800", help="Viewport size as WIDTHxHEIGHT")
# Browser — advanced
@_option("--channel", group="Browser options", default="", help="Browser channel: chrome, msedge, etc. (uses installed browser instead of bundled Chromium)")
@_option("--user-data-dir", group="Browser options", default="", help="Persistent browser profile directory (keeps cookies/history across runs)")
@_option("--browser-arg", group="Browser options", multiple=True, help="Extra Chromium launch arg, repeatable (e.g. --browser-arg=--disable-blink-features=AutomationControlled)")
@_option("--cdp-url", group="Browser options", default="", help="Connect to existing Chrome via CDP (e.g. http://localhost:9222 or wss://chrome.browserless.io?token=xxx). Mutually exclusive with --headless/--user-data-dir/--channel/--browser-arg.")
@_debug_options()
@click.pass_context
def browser(
    ctx: click.Context,
    instruction: str,
    name: str,
    model: str,
    language: str,
    max_steps: int,
    knowledge: str,
    url: str,
    headless: bool,
    viewport: str,
    channel: str,
    user_data_dir: str,
    browser_arg: tuple[str, ...],
    cdp_url: str,
    overlay: bool,
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
    vp = _parse_viewport(viewport)

    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, record=record, task_name=name or _default_task_name(instruction),
        overlay=overlay,
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
        _run_local(
            bot, page, instruction, max_steps,
            base_url=ctx.obj["base_url"], knowledge=knowledge,
        )
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
    record: bool = False,
    knowledge: str = "",
    overlay: bool = False,
) -> None:
    """Shared android/ios body: build the bot, open an Appium session, run.

    ``record`` uses Appium's own screen-recording API (record_device), so it
    captures the device screen on both android and ios.
    """
    appium_webdriver = require("appium.webdriver", "appium")

    # Build the bot first: it validates the API key and reaches the server, and
    # may sys.exit() on failure. Creating the Appium driver before that would
    # leak the remote session (driver.quit() lives in the finally below, which
    # never runs if _make_bot exits before the try is entered).
    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, record=record, record_device=record,
        task_name=name or _default_task_name(instruction), overlay=overlay,
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
            _run_local(
                bot, driver, instruction, max_steps,
                base_url=ctx.obj["base_url"], knowledge=knowledge,
            )
        finally:
            # The Appium recording lives in the session: flush it to disk
            # before quit() destroys it (bot.close() would be too late). A
            # no-op when nothing is recording.
            bot.stop_recording()
            driver.quit()
    finally:
        bot.close()


def _run_direct(
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
    record: bool = False,
    record_mjpeg_url: str = "",
    record_device: bool = False,
    record_window: bool = False,
    knowledge: str = "",
    overlay: bool = False,
) -> None:
    """Shared direct-engine body: build the bot, connect the device, run.

    ``connect`` resolves the device + optional app launch and returns the bind
    target. Like _run_appium, the bot is built first (it validates the API key
    and may sys.exit()); there is no remote session to quit, so the only
    teardown is bot.close(). Recording is device-side for android/ios —
    ``record_mjpeg_url`` for ios (WDA's MJPEG stream), ``record_device`` for
    android (adb screenrecord, resolved from the AdbDevice target) — and
    host-side for desktop, where ``record_window`` makes it follow the bound
    window instead of grabbing the full screen.
    """
    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, record=record, record_mjpeg_url=record_mjpeg_url,
        record_device=record_device, record_window=record_window,
        task_name=name or _default_task_name(instruction), overlay=overlay,
    )
    try:
        try:
            target = connect()
        except Exception as e:
            # Same contract as _run_appium: a setup failure before _run_local
            # takes over reporting must be recorded, or the finally:bot.close()
            # would complete the task as succeeded.
            _fail_setup(bot, e)
        _run_local(
            bot, target, instruction, max_steps,
            base_url=ctx.obj["base_url"], knowledge=knowledge,
        )
    finally:
        bot.close()


def _adb_launch_app(dev: Any, package: str, activity: str) -> None:
    """Launch an app over adb: explicit activity via ``am start -W``, else the
    LAUNCHER intent via monkey (no need to know the activity name)."""
    if activity:
        component = f"{package}/{activity}"
        out = dev.shell(f"am start -W -n {component}")
        if "Error" in out or "does not exist" in out:
            raise RuntimeError(
                f"could not launch {component}: {out.strip().splitlines()[-1]}"
            )
    else:
        out = dev.shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )
        if "No activities found" in out or "aborted" in out.lower():
            raise RuntimeError(
                f"could not launch {package}: no LAUNCHER activity found "
                "(is the package name right? try --app-activity)"
            )


@cli.command(cls=_GroupedCommand)
@click.argument("instruction")
@_task_options
@_option("--device", "-d", group="Android options", default="", help="Which device: an adb serial from `adb devices` (e.g. emulator-5554 or 192.168.1.8:5555). Optional when exactly one device is connected. With --appium-url: passed as deviceName.")
@_option("--appium-url", group="Android options", default="http://localhost:4723", help="Appium server URL — passing this flag switches the run to the Appium engine", show_default="direct adb, no server")
# Android — app launch
@_option("--app-package", group="Android options", default="", help="App package to launch (e.g. com.android.settings)")
@_option("--app-activity", group="Android options", default="", help="App activity to launch")
# Android — device-screen recording: adb screenrecord (direct engine) or
# Appium's recording API — both capture the phone screen, not the host's.
@_option("--record", group="Android options", is_flag=True, help="Record the device screen to report-dir/recording.mp4 (direct engine: adb screenrecord, ffmpeg merges runs over 3 min; Appium engine: Appium's recording API)")
@_debug_options(record=False)
@click.pass_context
def android(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, knowledge: str, device: str, appium_url: str, app_package: str, app_activity: str, record: bool, overlay: bool, report: bool, report_dir: str, annotate: bool) -> None:
    """Run an AI task on an Android device (direct over adb; --appium-url for Appium).

    \b
    Default — drives the device straight over adb. Zero Python dependencies;
    the only requirement is an adb binary (platform-tools) on PATH:
      qirabot android "Open settings"                    # the only adb device
      qirabot android "..." -d emulator-5554             # pick one of several
      qirabot android "..." -d 192.168.1.8:5555          # network device (adb connect)
      qirabot android "..." --app-package com.android.settings --app-activity .Settings
    \b
    Appium — passing --appium-url selects the Appium engine; needs a running
    server (npm i -g appium && appium driver install uiautomator2 && appium):
      qirabot android "..." --appium-url http://localhost:4723 -d emulator-5554
    \b
    Recording — --record saves the device screen (works on both engines):
      qirabot android "..." --record
    """
    if _flag_given(ctx, "appium_url"):
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
            report, report_dir, annotate, record=record, knowledge=knowledge,
            overlay=overlay,
        )
        return

    from qirabot.adb import AdbDevice

    dev = AdbDevice(serial=device or None)

    def connect() -> Any:
        # Resolve the serial now so 0/many/unauthorized/offline devices fail
        # with their actionable errors inside _fail_setup's reporting.
        dev.serial  # noqa: B018 — resolution side effect
        if app_package:
            _adb_launch_app(dev, app_package, app_activity)
        return dev

    _run_direct(
        ctx, instruction, name, model, language, max_steps, connect,
        report, report_dir, annotate,
        record=record, record_device=record, knowledge=knowledge,
        overlay=overlay,
    )


def _check_wda_ready(client: Any, wda_url: str) -> None:
    """Fail fast, with the full fix, when WebDriverAgent isn't answering."""
    if client.is_ready():
        return
    raise RuntimeError(
        f"WDA is not running (nothing answered at {wda_url}); start "
        "WebDriverAgent first (USB real device: `iproxy 8100 8100` alongside "
        "it; Xcode: run the WebDriverAgentRunner test scheme on the device, "
        "or `tidevice3 runwda` / pymobiledevice3), then retry — or pass "
        "--appium-url to have Appium build and launch WDA"
    )


def _wda_mjpeg_url(wda_url: str) -> str:
    """Default WDA MJPEG stream URL for ``wda_url``: same host, port 9100.

    9100 is WDA's default mjpegServerPort; like 8100, a USB real device needs
    its own forward (`iproxy 9100 9100`).
    """
    from urllib.parse import urlsplit

    url = wda_url if wda_url.startswith("http") else f"http://{wda_url}"
    host = urlsplit(url).hostname or "127.0.0.1"
    return f"http://{host}:9100"


def _check_mjpeg_ready(mjpeg_url: str) -> None:
    """Fail fast when --record was asked for but the MJPEG stream isn't up.

    Recording is the one thing that can't be salvaged after the fact — a
    silent best-effort skip would only be discovered after a full (possibly
    300-step) run. Probe before the task is even created and exit with the
    fix instead.
    """
    from qirabot.recording import check_mjpeg_stream

    err = check_mjpeg_stream(mjpeg_url)
    if err:
        raise click.ClickException(
            f"{err}. WDA streams the device screen on port 9100 — USB real "
            "device: run `iproxy 9100 9100` (alongside the usual 8100 forward) "
            "and retry, or point --mjpeg-url at the stream."
        )


@cli.command(cls=_GroupedCommand)
@click.argument("instruction")
@_task_options
@_option("--wda-url", group="iOS options", default="http://127.0.0.1:8100", help="WebDriverAgent URL — this is how the default engine picks the device (USB real device: run `iproxy 8100 8100` and keep the default; another device = its WDA address)")
# No -d short here, unlike android: on ios --device switches the engine to
# Appium, and an engine switch should be typed out deliberately, not inherited
# as muscle memory from `qirabot android -d`.
@_option("--device", group="iOS options", default="", help="Simulator device type (a name from `xcrun simctl list devicetypes`, e.g. \"iPhone 15\") — passing this flag switches the run to the Appium engine (simulators only). Real devices: keep the default engine, which selects the device via --wda-url.")
@_option("--appium-url", group="iOS options", default="http://localhost:4723", help="Appium server URL — passing this flag switches the run to the Appium engine", show_default="direct WDA, no server")
# iOS — app launch
@_option("--bundle-id", group="iOS options", default="", help="App bundle id to launch (e.g. com.tencent.xin)")
# iOS — device-screen recording: the default engine transcodes WDA's MJPEG
# stream with ffmpeg; the Appium engine uses Appium's recording API. Either
# way this captures the phone screen, unlike the desktop --record.
@_option("--record", group="iOS options", is_flag=True, help="Record the device screen to report-dir/recording.mp4 (default engine: WDA's MJPEG stream, requires ffmpeg, USB real device also needs `iproxy 9100 9100`; Appium engine: Appium's recording API)")
@_option("--mjpeg-url", group="iOS options", default="", help="WDA MJPEG stream URL for --record (default: --wda-url's host on port 9100; direct engine only)")
@_debug_options(record=False)
@click.pass_context
def ios(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, knowledge: str, wda_url: str, device: str, appium_url: str, bundle_id: str, record: bool, mjpeg_url: str, overlay: bool, report: bool, report_dir: str, annotate: bool) -> None:
    """Run an AI task on an iOS device (direct via WDA; --appium-url/--device for Appium).

    \b
    Default — talks to WebDriverAgent directly (built in, zero extra installs).
    WDA must be running on the device (USB real device: `iproxy 8100 8100`):
      qirabot ios "..." --bundle-id com.tencent.xin          # WDA on 127.0.0.1:8100
      qirabot ios "..." --wda-url http://192.168.1.20:8100   # another device's WDA
    \b
    Appium — passing --appium-url or --device (simulator) selects the Appium
    engine; needs a running server (npm i -g appium && appium driver install
    xcuitest && appium), and can auto build/sign WDA for you:
      qirabot ios "..." --device "iPhone 15" --bundle-id com.apple.Preferences
    \b
    Recording — --record saves the device screen. Default engine: WDA's MJPEG
    stream (port 9100; USB real device: also `iproxy 9100 9100`). Appium
    engine: Appium's own recording API, no extra setup:
      qirabot ios "..." --record
    """
    if _flag_given(ctx, "appium_url") or _flag_given(ctx, "device"):
        if _flag_given(ctx, "wda_url"):
            raise click.UsageError("--wda-url only applies to the direct engine (drop --appium-url/--device)")
        if _flag_given(ctx, "mjpeg_url"):
            raise click.UsageError("--mjpeg-url only applies to the direct engine (the Appium engine records via Appium's own API)")
        require("appium.webdriver", "appium")
        from appium.options.ios import XCUITestOptions

        options = XCUITestOptions()
        if device:
            options.device_name = device
        if bundle_id:
            options.bundle_id = bundle_id

        _run_appium(
            ctx, instruction, name, model, language, max_steps, appium_url, options,
            report, report_dir, annotate, record=record, knowledge=knowledge,
            overlay=overlay,
        )
        return

    if _flag_given(ctx, "mjpeg_url") and not record:
        raise click.UsageError("--mjpeg-url only applies with --record")
    record_mjpeg_url = ""
    if record:
        record_mjpeg_url = mjpeg_url or _wda_mjpeg_url(wda_url)
        _check_mjpeg_ready(record_mjpeg_url)

    from qirabot.wda import WdaClient

    client = WdaClient(wda_url)

    def connect() -> Any:
        _check_wda_ready(client, wda_url)
        if bundle_id:
            client.app_launch(bundle_id)
        return client

    _run_direct(
        ctx, instruction, name, model, language, max_steps, connect,
        report, report_dir, annotate,
        record=record, record_mjpeg_url=record_mjpeg_url, knowledge=knowledge,
        overlay=overlay,
    )


def _launch_desktop_app(app: str, app_wait: float) -> None:
    """--app side effect shared by both desktop engines; exits 1 on failure."""
    from qirabot import launch_app

    try:
        launch_app(app, wait=app_wait)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(cls=_GroupedCommand)
@click.argument("instruction")
@_task_options
@_option("--window-title", group="Desktop options", default="", help="Bind to the window whose title matches this regex — selects the built-in Windows window backend (screenshots/coords become window-relative, input is game-readable scancodes, recording follows the window). Windows only.")
@_option("--hwnd", group="Desktop options", default=0, type=int, help="Bind to a specific window handle — selects the built-in Windows window backend. Windows only.")
@_option("--ambiguous", group="Desktop options", default="error", type=click.Choice(["error", "largest"]), help="What to do when several windows match --window-title: 'error' fails listing the candidates; 'largest' picks the biggest matching window — for games whose launcher/overlay windows share the main window's title.")
# Desktop — app launch
@_option("--app", group="Desktop options", default="", help="Launch/activate an app before the task. macOS: app name (\"WeChat\") or bundle id; Windows: exe path, registered name, or UWP AppUserModelID; Linux: executable.")
@_option("--app-wait", group="Desktop options", default=2.0, type=float, help="Seconds to wait after --app launch for the window to appear")
@_debug_options()
@click.pass_context
def desktop(ctx: click.Context, instruction: str, name: str, model: str, language: str, max_steps: int, knowledge: str, window_title: str, hwnd: int, ambiguous: str, app: str, app_wait: float, overlay: bool, report: bool, report_dir: str, annotate: bool, record: bool) -> None:
    """Run an AI task on the desktop (pyautogui; --window-title/--hwnd for one Windows window).

    \b
    Default — pyautogui, drives the whole screen (macOS/Windows/Linux):
      qirabot desktop "Create a note titled Groceries" --app Notes
    \b
    Windows window backend (built in, zero extra installs) — passing
    --window-title or --hwnd binds to one window: screenshots and clicks are
    window-relative, and keys go out as DirectInput scancodes that games can
    read (virtual-key input often can't reach them):
      qirabot desktop "..." --window-title "Genshin"
      qirabot desktop "..." --app "C:/game.exe" --app-wait 15 --window-title "..."
    """
    if ambiguous != "error" and not window_title:
        raise click.UsageError(
            "--ambiguous largest only applies with --window-title "
            "(--hwnd already names one window)"
        )
    if window_title or hwnd:
        if window_title and hwnd:
            raise click.UsageError("--window-title and --hwnd are mutually exclusive")
        if sys.platform != "win32":
            # macOS's CGEvent has no concept of delivering input to a
            # background window, so a real window-bound backend cannot exist
            # there — fail with the workable alternative, don't degrade.
            raise click.UsageError(
                "--window-title/--hwnd need the Windows window backend, which "
                "only exists on Windows; on macOS/Linux use the default "
                "full-screen mode and bring the target window to the front"
            )
        from qirabot.windows import Window

        # Validate the key before the --app side effect (same contract as the
        # pyautogui path below).
        _require_api_key(ctx)
        if app:
            _launch_desktop_app(app, app_wait)

        window = Window(
            hwnd=hwnd or None, title_re=window_title or None, ambiguous=ambiguous,
        )

        def connect() -> Any:
            window.hwnd  # noqa: B018 — resolve now for actionable errors
            return window

        # record_window unconditionally: it only takes effect when a recording
        # actually starts (--record here, or QIRA_RECORD=1 from the env), and
        # then makes it follow the bound window instead of the full screen.
        _run_direct(
            ctx, instruction, name, model, language, max_steps, connect,
            report, report_dir, annotate, record=record, record_window=True,
            knowledge=knowledge, overlay=overlay,
        )
        return

    pyautogui = require("pyautogui", "desktop")

    # Validate the key before the --app side effect: without this, a missing
    # key would launch the app first and only then error out.
    _require_api_key(ctx)

    if app:
        _launch_desktop_app(app, app_wait)

    bot = _make_bot(
        ctx, model=model, language=language, report=report, report_dir=report_dir,
        annotate=annotate, record=record, task_name=name or _default_task_name(instruction),
        overlay=overlay,
    )
    try:
        _run_local(
            bot, pyautogui, instruction, max_steps,
            base_url=ctx.obj["base_url"], knowledge=knowledge,
        )
    finally:
        bot.close()


def main() -> None:
    # The SDK never reads .env implicitly; the CLI is the "calling script" in
    # that contract, so it opts in here — before click parses options, so the
    # envvar fallbacks (QIRA_API_KEY etc.) see the values. Best-effort, and
    # exported variables always win over .env entries. Remember whether the
    # key came from .env so `login --status` can say so.
    global _KEY_FROM_DOTENV
    had_env_key = "QIRA_API_KEY" in os.environ
    load_dotenv()
    _KEY_FROM_DOTENV = not had_env_key and "QIRA_API_KEY" in os.environ
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
