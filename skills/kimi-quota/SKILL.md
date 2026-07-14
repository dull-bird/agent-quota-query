---
name: kimi-quota
description: Check Kimi Code Plan quota and usage via opencli browser. Use when the user asks about their Kimi Code usage, remaining quota, rate limits, membership tier, or weekly allowance. Works by extracting data from the Kimi Code console page through the local browser session.
---

# Kimi Quota

Check your Kimi Code Plan quota and usage via opencli browser extraction.
Requires an authenticated browser session on kimi.com.

## Query the quota

1. Locate this Skill directory and substitute its absolute path for
   `<skill-dir>` below.
2. Run the bundled script in JSON mode:

   ```text
   python <skill-dir>/scripts/kimi_quota.py --json
   ```

3. Report each window's `remainingPercent`, `usedPercent`, and `resetTime`
   separately.

Use human-readable output for direct terminal use by omitting `--json`.

## Diagnose failures

- If opencli is not found, ask the user to install opencli and retry.
- If the browser is not logged in, run `opencli kimi login` and ask the
  user to sign in, then retry.
- If the console page cannot be reached, the user may need to navigate
  to https://www.kimi.com/code/console manually in the browser.

## Safety boundaries

- Use only the read-only opencli browser extract command.
- Never read, print, copy, or request cookies, access tokens, or API keys
  beyond what is visible on the console page.
- Never call any state-changing endpoint or click purchase/upgrade buttons.
- Do not describe the quota as API billing balance. Kimi Code plan limits
  and API billing are different counters.
