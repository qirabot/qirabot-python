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
import json
import time
from pathlib import Path
from typing import Any

_CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       margin: 0; padding: 24px; background: #f6f7f9; color: #1a1a1a; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #666; font-size: 12px; margin-bottom: 16px; }
.stats { color: #555; font-size: 12px; margin: -10px 0 16px;
         font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.summary { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
.badge { padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.pass { background: #d7f5dd; color: #06632b; }
.fail { background: #fbdcdc; color: #8a1010; }
.neutral { background: #e6e8eb; color: #444; }
.notice { background: #fff4d6; color: #7a5200; padding: 10px 14px; border-radius: 8px;
          margin-bottom: 18px; font-size: 13px; }
section { background: #fff; border: 1px solid #e3e5e8; border-radius: 10px;
          margin-bottom: 18px; overflow: hidden; }
section > h2 { font-size: 15px; margin: 0; padding: 12px 16px; background: #fafbfc;
              border-bottom: 1px solid #eceef0; display: flex; gap: 10px; align-items: center; }
.steps { display: grid; grid-template-columns: 48px 120px 1fr 200px; gap: 0; }
.steps > div { padding: 10px 12px; border-bottom: 1px solid #f0f1f3; }
.head { font-weight: 600; color: #888; font-size: 11px; text-transform: uppercase;
        background: #fcfcfd; }
.act { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }
.steps > div.fail-row { background: #fff5f5; }
.steps > .act.fail-row { color: #8a1010; }
.detail { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
          color: #333; white-space: pre-wrap; word-break: break-word; }
.detail .out { color: #555; }
.detail .decision { display: block; color: #777; font-style: italic; font-size: 11px;
                    font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
                    margin-bottom: 4px; }
.shot img { width: 100%; border-radius: 6px; border: 1px solid #e3e5e8; display: block;
            transition: transform .08s ease; }
.shot a { display: block; cursor: zoom-in; }
.shot a:hover img { transform: scale(1.02); }
video { max-width: 100%; border-radius: 8px; margin-bottom: 18px; }
/* Lightbox */
.lightbox { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,.88);
            display: none; }
.lightbox.open { display: flex; flex-direction: column; }
.lb-bar { display: flex; gap: 12px; align-items: baseline; padding: 12px 18px;
          color: #f0f0f0; background: rgba(0,0,0,.45); }
.lb-label { color: #9aa0a6; font-size: 12px; }
.lb-act { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 700; }
.lb-count { color: #9aa0a6; font-size: 12px; margin-left: auto; }
.lb-close { cursor: pointer; font-size: 18px; line-height: 1; color: #f0f0f0; padding: 0 4px; }
.lb-close:hover { color: #fff; }
.lb-stage { flex: 1; position: relative; display: flex; align-items: center;
            justify-content: center; overflow: auto; padding: 16px; }
.lb-stage img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 6px;
                box-shadow: 0 10px 40px rgba(0,0,0,.5); }
.lb-nav { position: absolute; top: 50%; transform: translateY(-50%); cursor: pointer;
          font-size: 44px; line-height: 1; color: #fff; opacity: .55; user-select: none;
          padding: 8px 14px; -webkit-user-select: none; }
.lb-nav:hover { opacity: 1; }
.lb-prev { left: 8px; }
.lb-next { right: 8px; }
.lb-caption { padding: 12px 18px; color: #d8dadd; background: rgba(0,0,0,.45);
              font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
              white-space: pre-wrap; word-break: break-word; max-height: 22vh; overflow: auto; }
.lb-caption:empty { display: none; }
.lb-caption .out { color: #a9c7ff; }
@media (prefers-color-scheme: dark) {
  body { background: #16181c; color: #e8e8e8; }
  section { background: #1e2126; border-color: #2c3036; }
  section > h2 { background: #22262c; border-color: #2c3036; }
  .head { background: #1a1d22; }
  .steps > div { border-color: #262a30; }
  .steps > div.fail-row { background: #3a1d1d; }
  .steps > .act.fail-row { color: #f3a6a6; }
  .stats { color: #9aa0a6; }
  .detail .decision { color: #9aa0a6; }
  .notice { background: #3a2f12; color: #f0d493; }
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
    if sx is not None and sy is not None and ex is not None and ey is not None:
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


def _fmt_tokens(n: int) -> str:
    """Compact token count: 1234 -> ``1.2k``, 980 -> ``980``."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _fmt_ms(ms: int) -> str:
    """Human duration from milliseconds: ``820ms`` / ``23.4s`` / ``2m03s``."""
    if ms < 1000:
        return f"{ms}ms"
    secs = ms / 1000
    if secs < 60:
        return f"{secs:.1f}s"
    return f"{int(secs // 60)}m{int(secs % 60):02d}s"


def _render_stats(stats: dict[str, int], model: str) -> str:
    """A one-line run summary (steps · tokens · timing · model).

    Returns an empty string when there were no AI steps, so non-AI runs
    (standalone click/type actions) don't get a meaningless zero line.
    """
    if not stats.get("ai_steps"):
        return ""
    inp = stats.get("input_tokens", 0)
    out = stats.get("output_tokens", 0)
    think = stats.get("thinking_tokens", 0)
    # thinking tokens are already counted within output tokens (Anthropic
    # semantics), so the total is input + output — do not add thinking again.
    total = inp + out
    bits = [f"{stats['ai_steps']} AI steps"]
    if total:
        bits.append(
            f"{_fmt_tokens(total)} tokens "
            f"(in {_fmt_tokens(inp)} / out {_fmt_tokens(out)} / think {_fmt_tokens(think)})"
        )
    if stats.get("step_duration_ms"):
        bits.append(_fmt_ms(stats["step_duration_ms"]))
    if model:
        bits.append(f"model {model}")
    return f"<div class='stats'>{html.escape(' · '.join(bits))}</div>"


_LIGHTBOX_JS = """
const SHOTS = __SHOTS__;
let lbIdx = 0;
const lb = document.getElementById('lightbox');
function renderLb() {
  const s = SHOTS[lbIdx];
  if (!s) return;
  document.getElementById('lb-img').src = s.src;
  document.getElementById('lb-img').alt = s.label;
  document.getElementById('lb-act').textContent = s.action;
  document.getElementById('lb-label').textContent = s.label;
  document.getElementById('lb-detail').innerHTML = s.detail;
  document.getElementById('lb-count').textContent = (lbIdx + 1) + ' / ' + SHOTS.length;
}
function openLb(i) { lbIdx = i; renderLb(); lb.classList.add('open'); return false; }
function closeLb() { lb.classList.remove('open'); }
function stepLb(d) {
  if (!SHOTS.length) return;
  lbIdx = (lbIdx + d + SHOTS.length) % SHOTS.length;
  renderLb();
}
lb.addEventListener('click', function (e) {
  const t = e.target;
  if (t === lb || t.id === 'lb-stage' || t.id === 'lb-close') closeLb();
});
document.getElementById('lb-prev').addEventListener('click', function (e) {
  e.stopPropagation(); stepLb(-1);
});
document.getElementById('lb-next').addEventListener('click', function (e) {
  e.stopPropagation(); stepLb(1);
});
document.addEventListener('keydown', function (e) {
  if (!lb.classList.contains('open')) return;
  if (e.key === 'Escape') closeLb();
  else if (e.key === 'ArrowLeft') stepLb(-1);
  else if (e.key === 'ArrowRight') stepLb(1);
});
"""


def _lightbox(shots: list[dict[str, str]]) -> str:
    """The lightbox overlay markup + script, with ``shots`` data inlined.

    Returns an empty string when there are no screenshots to view.
    """
    if not shots:
        return ""
    # json.dumps handles all string escaping; guard against a literal "</script>"
    # (or any "</...") inside the data prematurely closing the script element.
    data = json.dumps(shots, ensure_ascii=False).replace("</", "<\\/")
    script = _LIGHTBOX_JS.replace("__SHOTS__", data)
    return (
        "<div id='lightbox' class='lightbox' role='dialog' aria-modal='true'>"
        "<div class='lb-bar'>"
        "<span class='lb-label' id='lb-label'></span>"
        "<span class='lb-act' id='lb-act'></span>"
        "<span class='lb-count' id='lb-count'></span>"
        "<span class='lb-close' id='lb-close' title='Close (Esc)'>✕</span>"
        "</div>"
        "<div class='lb-stage' id='lb-stage'>"
        "<span class='lb-nav lb-prev' id='lb-prev' title='Previous (←)'>‹</span>"
        "<img id='lb-img' alt=''>"
        "<span class='lb-nav lb-next' id='lb-next' title='Next (→)'>›</span>"
        "</div>"
        "<div class='lb-caption' id='lb-detail'></div>"
        "</div>"
        f"<script>{script}</script>"
    )


def write_html(
    log: list[dict[str, Any]],
    path: str | Path,
    *,
    title: str = "",
    task_id: str = "",
    outcomes: dict[str, bool] | None = None,
    recording: str = "",
    record_error: str = "",
    stats: dict[str, int] | None = None,
    model: str = "",
) -> Path:
    """Render ``log`` to a self-contained HTML report at ``path``."""
    outcomes = outcomes or {}
    stats = stats or {}
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
    parts.append(_render_stats(stats, model))

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
    elif record_error:
        parts.append(f"<div class='notice'>⚠ {html.escape(record_error)}</div>")

    # Sections. Every step with a thumbnail also becomes a lightbox "shot" so the
    # viewer can page across all screenshots regardless of which section they're in.
    shots: list[dict[str, str]] = []
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
            detail = ""
            decision = e.get("decision") or ""
            if decision:
                detail += f"<span class='decision'>{html.escape(decision)}</span>"
            detail += html.escape(_summarize_params(e.get("params") or {}))
            output = e.get("output") or ""
            if output:
                detail += f"<br><span class='out'>{html.escape(output)}</span>"
            # A step explicitly recorded as failed gets a ✗ and a tinted row;
            # otherwise the terminal step gets the completion ✓.
            failed = e.get("success") is False
            row_cls = " fail-row" if failed else ""
            mark = " ✗" if failed else (" ✓" if e.get("finished") else "")
            action = (e.get("action_type") or "") + mark
            shot = ""
            thumb = e.get("thumb") or ""
            full = e.get("screenshot") or ""
            if thumb:
                idx = len(shots)
                shots.append({
                    "src": full or thumb,
                    "action": action,
                    "detail": detail,
                    "label": f"{sec} · #{i}",
                })
                img = f"<img src='{thumb}' loading='lazy'>"
                href = html.escape(full or "#")
                shot = f"<a href='{href}' onclick='return openLb({idx})'>{img}</a>"
            num_div = f"<div class='fail-row'>{i}</div>" if failed else f"<div>{i}</div>"
            parts.append(
                num_div
                + f"<div class='act{row_cls}'>{html.escape(action)}</div>"
                f"<div class='detail{row_cls}'>{detail}</div>"
                f"<div class='shot{row_cls}'>{shot}</div>"
            )
        parts.append("</div></section>")

    parts.append(_lightbox(shots))
    parts.append("</body></html>")
    out.write_text("".join(parts), encoding="utf-8")
    return out
