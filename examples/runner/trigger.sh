#!/usr/bin/env bash
#
# Trigger a Qirabot job on a remote runner — run this on YOUR machine.
#
# Sends a local script to the runner's POST /run and streams the job's output
# live as it runs (the runner streams stdout/stderr line by line). The stream
# ends with a "--- exit N ---" marker; this script exits with that same code, so
# it's CI/scripting friendly.
#
# Usage:
#   export QIRA_RUNNER_URL="http://VM_HOST:8765"
#   export QIRA_RUNNER_TOKEN="some-shared-secret"   # must match the runner's token
#   ./trigger.sh sample_job.py
#
# Env:
#   QIRA_RUNNER_URL    runner base URL (default http://localhost:8765)
#   QIRA_RUNNER_TOKEN  shared secret sent as X-Runner-Token (omit if runner has none)

set -uo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <script.py>" >&2
  exit 64
fi

script="$1"
url="${QIRA_RUNNER_URL:-http://localhost:8765}"
token="${QIRA_RUNNER_TOKEN:-}"

if [[ ! -f "$script" ]]; then
  echo "error: no such file: $script" >&2
  exit 66
fi

# -N disables curl's output buffering so the live stream shows up immediately.
args=(-sS -N --data-binary "@$script" -H "Content-Type: text/plain")
[[ -n "$token" ]] && args+=(-H "X-Runner-Token: $token")

echo "→ POST $url/run  ($script)  — streaming live, Ctrl+C aborts the remote job" >&2

# Stream each line through, echoing it, and capture the trailing exit marker so
# this script can exit with the job's return code.
rc=1
# `|| [[ -n "$line" ]]` also prints a final line with no trailing newline
# (error responses like a 401 body aren't newline-terminated).
while IFS= read -r line || [[ -n "$line" ]]; do
  printf '%s\n' "$line"
  if [[ "$line" == "--- exit "* ]]; then
    n="${line#--- exit }"   # e.g. "0 ---" or "-9 (timed out) ---"
    rc="${n%% *}"
  fi
done < <(curl "${args[@]}" "$url/run")

exit "$rc"
