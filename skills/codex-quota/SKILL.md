---
name: codex-quota
description: Check the current authenticated Codex account's rolling usage limits, remaining percentages, reset times, credit balance, and available rate-limit resets. Use when the user asks about Codex quota, remaining usage, rate limits, five-hour or weekly allowance, reset time, credits, or whether Codex is close to its limit.
---

# Codex Quota

Read the quota snapshot from the locally authenticated Codex CLI without
opening credential files or exposing tokens.

## Query the quota

1. Locate this Skill directory and substitute its absolute path for
   `<skill-dir>` below.
2. Run the bundled script in JSON mode:

   ```text
   python <skill-dir>/scripts/query_codex_quota.py --json
   ```

   On Windows, use `py -3` if `python` is not the Python 3 launcher:

   ```text
   py -3 <skill-dir>/scripts/query_codex_quota.py --json
   ```

3. Report every item in `limits` separately. Preserve the returned model or
   limit name because Codex may meter some models independently.
4. Include each window's `remainingPercent`, `usedPercent`, and
   `resetsAtLocal`. Include the credit balance and available reset-credit count
   when present.
5. Explain that the percentage represents resource usage in a rolling window,
   not a fixed number of messages. Task cost varies with model, context size,
   duration, and complexity.

Use human-readable output for direct terminal use by omitting `--json`.

## Diagnose failures

- If the Codex executable is missing, ask the user to install or update the
  official Codex CLI and retry.
- If authentication is missing, run `codex login status` and ask the user to
  sign in with `codex login` when needed.
- If the app-server method is unavailable, report the installed version from
  `codex --version`. The protocol is experimental and may change between Codex
  releases.
- Use Codex Settings > Usage as the UI fallback when the local protocol does
  not return a snapshot.

## Safety boundaries

- Use only the read-only `account/rateLimits/read` app-server method.
- Never read, print, copy, or request `auth.json`, browser cookies, access
  tokens, authorization headers, or signed URLs.
- Never call `account/rateLimitResetCredit/consume`; querying must not redeem a
  reset credit or change account state.
- Do not describe the credit balance as API billing balance. ChatGPT/Codex plan
  limits, optional Codex credits, API billing, and per-thread token usage are
  different counters.
