---
title: Error Handling & Run Outcomes
description: Qirabot's exception hierarchy, the four ai() run outcomes in result.status, the max_steps retry pattern, action retries, and how failures appear in the HTML report.
---

# Error Handling

## Exceptions

```python
from qirabot import (
    Qirabot,
    QirabotError,              # base class
    AuthenticationError,       # invalid API key
    InsufficientBalanceError,  # no credits left
    QirabotTimeoutError,       # wait_for / auto-wait timeout
)

try:
    # The constructor itself can raise: it validates the API key and
    # registers the task with the server. `with` guarantees close() runs
    # if — and only if — construction succeeded.
    with Qirabot() as bot:
        page = bot.open("https://example.com")
        bot.click(page, "Login button")
except AuthenticationError:
    print("Invalid API key.")
except InsufficientBalanceError:
    print("No credits left.")
except QirabotTimeoutError:
    print("Operation timed out.")
except QirabotError as e:
    print(f"Error: {e}")
```

The full hierarchy — everything derives from `QirabotError`, so a single
`except QirabotError` is always a safe catch-all:

| Exception | When |
|---|---|
| `AuthenticationError` | API key missing or invalid (401). Not retried. |
| `InsufficientBalanceError` | Credit balance exhausted (402). Not retried. |
| `RateLimitError` | Too many requests (429). The SDK backs off and retries internally; catch it to add your own backoff. |
| `QirabotTimeoutError` | A client-side wait timed out (`wait_for`, auto-wait). |
| `QirabotConnectionError` | The server was unreachable (DNS failure, refused connection) — the request never completed, as opposed to being slow. |
| `TaskTerminatedError` | The task was terminated server-side (console stop, orphan cleaner, max-duration cap) while the script was still running. `.task_status` carries the terminal state. Not retried. |
| `ActionError` | An AI action failed server-side. |
| `MissingDependencyError` | An optional backend dependency (playwright, pyautogui, …) isn't installed — the message includes the exact `pip install "qirabot[<extra>]"` to run. Also an `ImportError`. |

`verify()` is the deliberate exception to raise-on-failure semantics: a
**failed check** doesn't raise — it returns a falsy result (a `VerifyResult`
whose `.reason` says why), so it drops straight into `assert` or `if`.
Transport and server errors (connection loss, auth, termination) still raise
like any other call.

Transient action failures are retried automatically (`retry=1`,
`retry_delay=1.0` by default — see
[Configuration](/advanced/configuration)).

## How an ai() run ended: result.status

`result.success` is the two-state verdict, but a failed run can mean very
different things:

| status | meaning | `success` |
|---|---|---|
| `"completed"` | model declared the goal achieved | `True` |
| `"goal_failed"` | model concluded the goal is unreachable (login wall, captcha) | `False` |
| `"max_steps"` | step budget ran out — a truncation, not a capability verdict | `False` |
| `"error"` | the server reported a terminal error | `False` |

The `max_steps` case deserves special handling — it's a budget problem, not
a capability one:

```python
result = bot.ai(page, "Find the cheapest flight and hold it")
if result.status == "max_steps":
    # not a real failure — the budget was too small; retry with headroom
    result = bot.ai(page, "Find the cheapest flight and hold it", max_steps=50)
```

`goal_failed` usually means the environment needs help — a login wall or
captcha. Consider a
[human-in-the-loop custom tool](/advanced/ai-tasks#human-in-the-loop) so the
model can ask instead of giving up.

## Failures in the report

Runs that end by raising never produce a `RunResult`; in the
[HTML report](/advanced/reports) their section is badged `ERROR`. The
report is written on close **even after exceptions and Ctrl+C**, with the
per-step screenshots up to the failure — usually the fastest way to see
what actually happened on screen.

The header summary is green when everything passed, amber when the only
misses are `MAX STEPS` truncations, red when anything truly failed.

## Custom-tool errors

A custom tool that raises doesn't kill the run: the exception is reported
back to the model as `ERROR: ...`, and the model can react — retry, try
another route, or finish with `goal_failed`. See
[AI Tasks & Custom Tools](/advanced/ai-tasks).
