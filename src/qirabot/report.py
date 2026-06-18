"""Self-contained HTML run report.

Pure rendering — no model calls, no network. Builds an HTML file from the
session step log that :class:`qirabot.Qirabot` accumulates during a run:

    write_html(bot._log, "report.html", title=..., outcomes=..., recording=...)

Each step carries an embedded thumbnail (base64 data URI) so the report is a
single self-contained file, plus a link to the full-resolution screenshot under
``screenshots/`` when one was saved.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Any

_CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       margin: 0; padding: 24px; background: #f6f7f9; color: #1a1a1a; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #666; font-size: 12px; margin-bottom: 16px; }
.summary { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
.badge { padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.pass { background: #d7f5dd; color: #06632b; }
.fail { background: #fbdcdc; color: #8a1010; }
.neutral { background: #e6e8eb; color: #444; }
section { background: #fff; border: 1px solid #e3e5e8; border-radius: 10px;
          margin-bottom: 18px; overflow: hidden; }
section > h2 { font-size: 15px; margin: 0; padding: 12px 16px; background: #fafbfc;
              border-bottom: 1px solid #eceef0; display: flex; gap: 10px; align-items: center; }
.steps { display: grid; grid-template-columns: 48px 120px 1fr 200px; gap: 0; }
.steps > div { padding: 10px 12px; border-bottom: 1px solid #f0f1f3; }
.head { font-weight: 600; color: #888; font-size: 11px; text-transform: uppercase;
        background: #fcfcfd; }
.act { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }
.detail { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
          color: #333; white-space: pre-wrap; word-break: break-word; }
.detail .out { color: #555; }
.shot img { width: 100%; border-radius: 6px; border: 1px solid #e3e5e8; display: block; }
video { max-width: 100%; border-radius: 8px; margin-bottom: 18px; }
@media (prefers-color-scheme: dark) {
  body { background: #16181c; color: #e8e8e8; }
  section { background: #1e2126; border-color: #2c3036; }
  section > h2 { background: #22262c; border-color: #2c3036; }
  .head { background: #1a1d22; }
  .steps > div { border-color: #262a30; }
}
"""


_COORD_KEYS = ("x", "y", "start_x", "start_y", "end_x", "end_y")


def _summarize_params(params: dict[str, Any]) -> str:
    """A compact one-line view of an action's parameters.

    Known keys get pretty formatting; everything else falls through to a
    generic ``key=value`` so a new action type never renders blank.
    """
    parts: list[str] = []
    rendered: set[str] = set()

    # Primary human-readable descriptor.
    for key in ("locate", "instruction", "assertion", "url"):
        if params.get(key):
            parts.append(str(params[key]))
            rendered.add(key)
            break

    if params.get("text"):
        parts.append(f'text="{params["text"]}"')
    rendered.add("text")

    # Scroll: keep the compact "down 500" form rather than two key=value pairs.
    if params.get("direction"):
        parts.append(f'{params["direction"]} {params.get("amount", "")}'.strip())
        rendered.update(("direction", "amount"))

    # Coordinates, formatted compactly.
    x, y = params.get("x"), params.get("y")
    if x is not None and y is not None:
        parts.append(f"({int(x)}, {int(y)})")
    sx, sy, ex, ey = (params.get(k) for k in _COORD_KEYS[2:])
    if None not in (sx, sy, ex, ey):
        parts.append(f"({int(sx)},{int(sy)})→({int(ex)},{int(ey)})")
    rendered.update(_COORD_KEYS)

    # Everything else: generic fallback so nothing silently vanishes.
    for key, val in params.items():
        if key in rendered or val in (None, "", False):
            continue
        parts.append(f"{key}={val}")

    return " ".join(parts)


def _badge(label: str, kind: str) -> str:
    return f'<span class="badge {kind}">{html.escape(label)}</span>'


def write_html(
    log: list[dict[str, Any]],
    path: str | Path,
    *,
    title: str = "",
    task_id: str = "",
    outcomes: dict[str, bool] | None = None,
    recording: str = "",
) -> Path:
    """Render ``log`` to a self-contained HTML report at ``path``."""
    outcomes = outcomes or {}
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Group entries by section, preserving first-seen order.
    sections: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in log:
        sec = entry.get("section") or "setup"
        if sec not in grouped:
            grouped[sec] = []
            sections.append(sec)
        grouped[sec].append(entry)

    def section_kind(sec: str) -> tuple[str, str]:
        if sec in outcomes:
            return ("PASS", "pass") if outcomes[sec] else ("FAIL", "fail")
        return (f"{len(grouped[sec])} steps", "neutral")

    parts: list[str] = []
    parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    parts.append(f"<title>{html.escape(title or 'Qirabot report')}</title>")
    parts.append(f"<style>{_CSS}</style></head><body>")
    parts.append(f"<h1>{html.escape(title or 'Qirabot run report')}</h1>")
    meta = time.strftime("%Y-%m-%d %H:%M:%S")
    if task_id:
        meta += f" · task {html.escape(task_id)}"
    parts.append(f"<div class='meta'>{meta}</div>")

    # Summary badges
    parts.append("<div class='summary'>")
    passed = sum(1 for s in sections if outcomes.get(s) is True)
    total_judged = sum(1 for s in sections if s in outcomes)
    if total_judged:
        kind = "pass" if passed == total_judged else "fail"
        parts.append(_badge(f"{passed}/{total_judged} passed", kind))
    for sec in sections:
        label, kind = section_kind(sec)
        parts.append(_badge(f"{sec}: {label}", kind))
    parts.append("</div>")

    if recording:
        parts.append(
            f"<video controls src='{html.escape(recording)}'></video>"
        )

    # Sections
    for sec in sections:
        label, kind = section_kind(sec)
        parts.append("<section>")
        parts.append(
            f"<h2>{html.escape(sec)} {_badge(label, kind)}</h2>"
        )
        parts.append("<div class='steps'>")
        parts.append(
            "<div class='head'>#</div><div class='head'>action</div>"
            "<div class='head'>detail</div><div class='head'>screenshot</div>"
        )
        for i, e in enumerate(grouped[sec], 1):
            detail = html.escape(_summarize_params(e.get("params") or {}))
            output = e.get("output") or ""
            if output:
                detail += f"<br><span class='out'>{html.escape(output)}</span>"
            mark = " ✓" if e.get("finished") else ""
            shot = ""
            thumb = e.get("thumb") or ""
            full = e.get("screenshot") or ""
            if thumb:
                img = f"<img src='{thumb}'>"
                shot = f"<a href='{html.escape(full)}'>{img}</a>" if full else img
            parts.append(
                f"<div>{i}</div>"
                f"<div class='act'>{html.escape(e.get('action_type') or '')}{mark}</div>"
                f"<div class='detail'>{detail}</div>"
                f"<div class='shot'>{shot}</div>"
            )
        parts.append("</div></section>")

    parts.append("</body></html>")
    out.write_text("".join(parts), encoding="utf-8")
    return out
