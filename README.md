# Agent Quota Query

Reusable Agent Skills for checking authenticated AI-agent usage limits without
exporting credentials. The repository is structured so more agents can be added
under `skills/` over time.

## Available Skills

| Skill | Purpose |
| --- | --- |
| [`codex-quota`](skills/codex-quota/) | Check Codex rolling limits, reset times, optional credits, and model-specific buckets. |
| [`antigravity-quota`](skills/antigravity-quota/) | Check Antigravity (agy) CLI model quota via pexpect `/usage` interaction. |
| [`kimi-quota`](skills/kimi-quota/) | Check Kimi Code quota via kimi CLI `/usage` (preferred) or opencli browser fallback. |
| [`openclaw-usage-trends`](skills/openclaw-usage-trends/) | Persist Codex + Antigravity + Kimi quota and OpenClaw cron snapshots, then forecast rolling-window exhaustion. |

## Quick Start

### Codex

```text
python skills/codex-quota/scripts/query_codex_quota.py
python skills/codex-quota/scripts/query_codex_quota.py --json
```

### Antigravity

```text
python skills/antigravity-quota/scripts/agquota.py
python skills/antigravity-quota/scripts/agquota.py --json
```

Requires `pexpect` (`pip install pexpect`) and the `agy` CLI authenticated.

### Kimi Code

```text
python skills/kimi-quota/scripts/kimi_quota.py
python skills/kimi-quota/scripts/kimi_quota.py --json
```

Primary: `kimi` CLI via pexpect (`pip install pexpect`).  
Fallback: `opencli` browser extraction (`--force-opencli`).

### Usage Trends (all providers)

```text
python skills/openclaw-usage-trends/scripts/usage_trends.py collect   # snapshot now
python skills/openclaw-usage-trends/scripts/usage_trends.py report    # view trends
```

Automated via OpenClaw `command` cron (no LLM tokens consumed):

```text
openclaw cron add --name agent-quota-collect --every 6h \
  --command "python3 /path/to/agent-quota-query/skills/openclaw-usage-trends/scripts/usage_trends.py collect" \
  --command-cwd /path/to/agent-quota-query
```

## Install the Skill

Copy `skills/codex-quota` into your agent's Skill directory. For Codex, the
destination is normally `.codex/skills/codex-quota` inside your user profile.
Restart Codex after adding the Skill so it is discovered in a new session.

## Add another agent

Add each integration as a self-contained directory:

```text
skills/
├── codex-quota/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── scripts/
├── antigravity-quota/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── scripts/
├── kimi-quota/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── scripts/
└── openclaw-usage-trends/
    ├── SKILL.md
    ├── agents/openai.yaml
    └── scripts/
```

Keep provider-specific protocols inside each Skill. Normalize the user-facing
result around remaining percentage, used percentage, reset time, and optional
credit balance so multiple agents can be compared later.

## Test

The test suite uses only the Python standard library:

```text
python -m unittest discover -s tests -v
```

On Windows, `py -3 -m unittest discover -s tests -v` is an equivalent fallback.

## Compatibility
## Compatibility

- Linux, macOS, and Windows
- Python 3.9+
- Codex CLI with the app-server v2 rate-limit method
- Antigravity CLI (`agy`) 1.1+ with `pexpect`
- Kimi Code CLI 0.23+ with `pexpect`, or opencli browser session
- OpenClaw CLI for cron-based automated collection
