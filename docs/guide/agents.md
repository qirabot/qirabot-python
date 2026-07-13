---
title: Use with AI Agents — Claude Code Plugin & Agent-Friendly CLI
description: Let an AI agent drive GUIs through Qirabot - the Claude Code plugin with its qirabot skill, preflight checks and starter templates, plus llms.txt and an exit-code-friendly CLI for any other agent.
---

# Use with AI Agents

Qirabot isn't only a library you code against — it's a capability an AI
agent can pick up and use. Tell your agent *"automate this signup flow and
verify the confirmation email screen"* and let it write and run the script.
Two ways in:

## Claude Code plugin

The [qirabot plugin](https://github.com/qirabot/claude-plugins) packages an
Agent Skill that teaches Claude Code how to operate Qirabot end to end.
Install it once:

```text
/plugin marketplace add qirabot/claude-plugins
/plugin install qirabot@qirabot
```

Claude then invokes the skill automatically whenever a task involves
automating, testing, or scraping a UI (it's also callable explicitly as
`/qirabot:qirabot`). The skill ships with:

- **A preflight script** — checks the Python env, backend deps, and API key
  *before* writing any code, and prints the exact fix command for anything
  missing. No more scripts that fail three steps in.
- **Condensed SDK + CLI references** — the agent codes against an accurate
  API surface instead of guessing.
- **Starter templates** for browser, Android (adb), iOS (WDA and Appium),
  and bring-your-own-driver bolt-on — the agent adapts a working skeleton
  rather than starting blank.

The plugin contains instructions and helpers only; the `qirabot` package
itself is installed at runtime by the preflight bootstrap.

## Any other agent (Cursor, Copilot, …)

Two properties make Qirabot easy for arbitrary agents to drive:

**The CLI is a natural agent tool.** One shell command runs a whole
natural-language task — no code generation needed for one-shot jobs:

```bash
qirabot browser "Fill the signup form as Jane Doe and stop at the captcha" --url example.com
```

Exit codes are machine-checkable (`0` pass, `1` fail, `130` interrupted),
and every run writes an [HTML report](/advanced/reports) with per-step
screenshots the agent (or you) can inspect when something goes wrong. All
commands: [CLI Reference](/guide/cli).

**The docs are agent-readable.** Point your agent at:

- `https://qirabot.com/docs/llms.txt` — index with per-page summaries
- `https://qirabot.com/docs/llms-full.txt` — the complete docs in one file
- every page as raw Markdown by swapping `.html` for `.md`, e.g.
  `https://qirabot.com/docs/reference/methods.md`

In Cursor, add them via the `@Docs` feature; in other tools, reference the
URLs in your rules file or paste them into context.

## Why agents + vision automation fit

An agent writing Playwright still has to guess selectors it can't see, and
they break on the next redesign. With Qirabot the agent describes elements
the way it reasons — in language — and the same skill covers surfaces
code-first stacks can't reach: native mobile apps, desktop software, and
games. See [What is Qirabot](/) and the
[platform support matrix](/reference/api#platform-support-matrix).
