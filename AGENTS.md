# Agent Quota Query repository rules

## Repository structure

- Put each provider integration in `skills/<agent>-quota/`.
- Require a `SKILL.md` with non-empty `name` and `description` frontmatter.
- Keep provider-specific protocol code inside that Skill. Share code only after
  at least two integrations need the same stable abstraction.

## Cross-platform requirements

- Support Windows 10/11, macOS, and Linux unless Skill frontmatter explicitly
  narrows the platform.
- Use Python 3 and `pathlib` for reusable automation.
- Do not make Bash, WSL, GNU utilities, POSIX permission bits, `/tmp`, `/home`,
  or a Unix-only scheduler the sole supported path.
- Show commands with `python`; mention `py -3` as the Windows fallback.
- Resolve command shims with `shutil.which`, including `.cmd` variants on
  Windows.
- Store private state under `Path.home()` or an explicit environment override.
  Apply restrictive modes on POSIX when possible; rely on the current user's
  profile ACL on Windows and do not claim POSIX modes are enforced there.

## Quota-query safety

- Default to read-only quota and usage methods.
- Never inspect, export, print, save, or request browser cookies, access tokens,
  credential files, authorization headers, signed URLs, or private keys.
- Treat reading usage, purchasing credits, redeeming resets, changing spend
  limits, and publishing data as separate operations.
- Require explicit confirmation before any state-changing account action.
- Do not commit real quota snapshots or personal account identifiers as test
  fixtures. Use synthetic values.

## Verification

- Run the provider script against the installed client when available.
- Run unit tests with `python -m unittest discover -s tests -v`.
- Validate each Skill with the Skill Creator `quick_validate.py` tool.
- Scan publishable files for secrets, personal identifiers, absolute user-home
  paths, credential-like filenames, and generated caches before pushing.
