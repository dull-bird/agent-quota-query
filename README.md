# Agent Quota Query

Reusable Agent Skills for checking authenticated AI-agent usage limits without
exporting credentials. The repository is structured so more agents can be added
under `skills/` over time.

## Available Skills

| Skill | Purpose |
| --- | --- |
| [`codex-quota`](skills/codex-quota/) | Check Codex rolling limits, reset times, optional credits, and model-specific buckets. |

## Run the Codex query directly

Requires Python 3 and an authenticated Codex CLI:

```text
python skills/codex-quota/scripts/query_codex_quota.py
python skills/codex-quota/scripts/query_codex_quota.py --json
```

On Windows, use the Python launcher if needed:

```text
py -3 skills/codex-quota/scripts/query_codex_quota.py --json
```

The script resolves both ordinary executables and Windows command shims. It
starts an ephemeral local `codex app-server`, calls only the read-only
`account/rateLimits/read` method, and never reads or prints stored credentials.

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
└── another-agent-quota/
    ├── SKILL.md
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

- Windows 10/11, macOS, and Linux
- Python 3.9 or newer
- Codex CLI with the app-server v2 rate-limit method (verified with Codex CLI
  0.144.1)

The app-server protocol is experimental. If a future Codex release changes the
method, use Codex Settings > Usage while this Skill is updated.

OpenAI's current user-facing guidance is available in
[Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-chatgpt).
