---
name: antigravity-quota
description: Check Google Antigravity AI model quota and token balance. Use when the user asks about their Antigravity usage, remaining tokens, model limits, quota status, or rate limits. Works by detecting the local Antigravity language server process and querying its API.
---

# Antigravity Quota

Check your Antigravity AI model quota and token balance through the local
language server process. Never reads or exports credentials.

## Query the quota

1. Locate this Skill directory and substitute its absolute path for
   `<skill-dir>` below.
2. Run the bundled script in JSON mode:

   ```text
   node <skill-dir>/scripts/agquota.js --json
   ```

3. Report each model's `remainingPercent`, `isExhausted`, and `resetTime`
   separately.

Use human-readable output for direct terminal use by omitting `--json`.

## Diagnose failures

- If the Antigravity process is not found, ask the user to launch Antigravity
  and retry. The language server must be running for this script to work.
- If the script finds a language server but it is not an Antigravity instance,
  the user may have another Codeium-based tool running. Ask them to verify.
- If the API port cannot be found, the language server may have changed its
  port layout. Report the installed version and suggest updating Antigravity.

## Safety boundaries

- Use only the local language server HTTPS API at `127.0.0.1`.
- Never read, print, copy, or request auth tokens, cookies, or signed URLs
  beyond the process-level CSRF token required by the local API.
- Never call any state-changing endpoint; querying must not modify account
  state.
- Do not describe the quota as API billing balance. Antigravity plan limits
  and API billing are different counters.
