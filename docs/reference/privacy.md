---
title: Data & Privacy
description: Exactly what Qirabot uploads (screenshots, instructions, step metadata), what never leaves your machine (code, cookies, credentials), what the server stores, and the local-only report files.
---

# Data & Privacy

Qirabot is a vision service: the model needs to see the screen, and nothing
else. This page states exactly what crosses the wire.

## What is uploaded

Each AI step sends to the Qirabot server:

- a **screenshot** of the bound target (JPEG quality 80 by default —
  `screenshot_format` / `screenshot_quality` in
  [Configuration](/advanced/configuration)),
- your **instruction text** (the natural-language description or task),
- **step metadata** (action type, parameters, timing).

## What never leaves your machine

- **Your code.** The server returns coordinates and decisions; actions
  execute locally through your framework or adapter.
- **Cookies, credentials, session state.** Qirabot drives your browser or
  device; it doesn't read or transmit their storage.
- **Custom tools.** Functions passed via `custom_tools` run locally — your
  endpoints, tokens, and databases are never seen by the server, only the
  tool's string return value is fed back to the model. See
  [AI Tasks & Custom Tools](/advanced/ai-tasks).

## What the server stores

Each run is a server-side task: name, status, steps, and the step
screenshots — that's what the [dashboard](https://app.qirabot.com) shows and
what `qirabot task <id>` / `qirabot screenshot <id>` retrieve. Steps executed
without AI are uploaded to the same timeline for completeness; turn that off
with `Qirabot(sync_local_steps=False)`.

## What stays local

The [HTML report](/advanced/reports) (`report.html`, full-resolution
`screenshots/`, `recording.mp4`) is written to `./qira_runs/` on your
machine, is fully self-contained, and makes no network calls. Disable it
with `report=False`.

## Transport

All traffic is HTTPS to `app.qirabot.com` (or your own `base_url`).
Certificate verification is on by default; `verify_ssl=False` exists for
self-hosted / self-signed setups only.
