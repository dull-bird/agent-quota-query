---
name: openclaw-usage-trends
description: Collect local Codex quota snapshots and OpenClaw cron model health into a private SQLite history, then report consumption trends and rolling-window exhaustion forecasts. Use when the user asks for agent usage trends, quota history, token budget forecasting, OpenClaw cron model allocation, or scheduled low-cost usage monitoring.
---

# OpenClaw Usage Trends

Use the bundled script. It calls only the existing read-only Codex quota
endpoint and the local OpenClaw CLI. It never reads credentials or estimates
unavailable provider token usage.

## Collect A Snapshot

```text
python <skill-dir>/scripts/usage_trends.py collect
```

The default database is `~/.local/share/agent-quota-query/usage-trends.sqlite3`.
Set `AGENT_QUOTA_QUERY_DATA_DIR` to keep the private history elsewhere.

## Read Trends And Forecasts

```text
python <skill-dir>/scripts/usage_trends.py report
python <skill-dir>/scripts/usage_trends.py report --days 30 --json
```

Explain that a forecast requires at least two samples in the same rolling reset
window. It projects the observed percentage slope, not an exact token cost.

## Scheduling

Use an OpenClaw `command` cron for collection. Do not spend an LLM call on this
rule-based operation. Keep delivery disabled unless the user explicitly wants a
separate alert workflow.

## Safety

- Report provider/model names, percentages, reset times, and cron counts only.
- Never display API keys, auth profiles, task prompts, recipient IDs, or raw
  OpenClaw configuration.
- Distinguish actual Codex quota observations from Kimi/MiniMax health signals;
  the latter do not prove token consumption without a provider usage API.
