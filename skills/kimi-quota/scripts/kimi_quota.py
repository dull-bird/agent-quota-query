#!/usr/bin/env python3
"""Query Kimi Code quota. Primary: kimi CLI /usage. Fallback: opencli browser."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class KimiQuotaError(RuntimeError):
    pass


def _resolve_bin(name: str, explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate)
        located = shutil.which(explicit)
        if located:
            return located
        return None
    return shutil.which(name)


def _parse_delta(delta_str: str) -> Optional[str]:
    total_hours = 0.0
    for match in re.finditer(r"(\d+)\s*d(ays?)?", delta_str, re.IGNORECASE):
        total_hours += int(match.group(1)) * 24
    for match in re.finditer(r"(\d+)\s*h(ours?)?", delta_str, re.IGNORECASE):
        total_hours += int(match.group(1))
    for match in re.finditer(r"(\d+)\s*m(in(utes?)?)?", delta_str, re.IGNORECASE):
        total_hours += int(match.group(1)) / 60.0
    if total_hours > 0:
        return (datetime.now(timezone.utc) + timedelta(hours=total_hours)).isoformat()
    return None


def _strip_ansi(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\].*?\x07", "", text)
    text = re.sub(r"\r", "", text)
    text = re.sub(r"[^\x20-\x7e\n]", " ", text)
    text = re.sub(r" {3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_cli_usage(text: str) -> Dict[str, Any]:
    models: List[Dict[str, Any]] = []
    weekly_remaining = None
    weekly_reset = None
    rate_remaining = None
    rate_reset = None
    membership = None

    for line in text.split("\n"):
        s = line.strip()

        wm = re.search(r"Weekly limit\s+(\d+[\.\d]*)%\s+used", s)
        if wm:
            used = float(wm.group(1))
            weekly_remaining = round(100.0 - used, 2)

        rm = re.search(r"5h limit\s+(\d+[\.\d]*)%\s+used", s)
        if rm:
            used = float(rm.group(1))
            rate_remaining = round(100.0 - used, 2)

        wm2 = re.search(r"Weekly (?:usage|limit)\s+(\d+[\.\d]*)%", s)
        if wm2 and weekly_remaining is None:
            weekly_remaining = round(float(wm2.group(1)), 2)

        rm2 = re.search(r"(?:Rate limit|5h limit)\s+(\d+[\.\d]*)%", s)
        if rm2 and rate_remaining is None:
            rate_remaining = round(float(rm2.group(1)), 2)

        if "resets in" in s.lower():
            dm = re.search(r"resets in\s+(.+)", s, re.IGNORECASE)
            if dm:
                reset = _parse_delta(dm.group(1).strip())
                if weekly_remaining is not None and weekly_reset is None:
                    weekly_reset = reset
                elif rate_remaining is not None and rate_reset is None:
                    rate_reset = reset

        for tier in ("Allegretto", "Andante", "Allegro", "Moderato"):
            if tier in s:
                membership = tier

    if weekly_remaining is not None:
        models.append(
            {
                "label": "Kimi Code Weekly Usage",
                "modelId": "kimi-code-weekly",
                "remainingPercent": weekly_remaining,
                "usedPercent": round(100.0 - weekly_remaining, 2),
                "isExhausted": weekly_remaining <= 0,
                "resetTime": weekly_reset,
                "windowLabel": "Weekly",
            }
        )
    if rate_remaining is not None:
        models.append(
            {
                "label": "Kimi Code Rate Limit",
                "modelId": "kimi-code-rate-limit",
                "remainingPercent": rate_remaining,
                "usedPercent": round(100.0 - rate_remaining, 2),
                "isExhausted": rate_remaining <= 0,
                "resetTime": rate_reset,
                "windowLabel": "Rate Limit",
            }
        )

    return {
        "user": {"membership": membership},
        "models": models,
        "source": "cli",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def query_via_cli(kimi_bin: str, timeout: float = 60.0) -> Dict[str, Any]:
    try:
        import pexpect
    except ImportError:
        raise KimiQuotaError(
            "pexpect is required for kimi CLI queries: pip install pexpect"
        )

    env = os.environ.copy()
    env["HOME"] = str(Path.home())
    env["TERM"] = "xterm-256color"

    child = pexpect.spawn(
        kimi_bin,
        ["--auto"],
        encoding="utf-8",
        timeout=timeout,
        env=env,
        dimensions=(50, 200),
    )
    buf = ""
    try:
        child.expect([">", "for shortcuts"], timeout=int(timeout * 0.6))
        time.sleep(2)
        child.sendline("/usage")
        time.sleep(3)
        child.sendcontrol("m")
        deadline = time.monotonic() + timeout * 0.4
        while time.monotonic() < deadline:
            time.sleep(3)
            try:
                buf += child.read_nonblocking(size=100000, timeout=5)
            except Exception:
                pass
            if "Weekly" in buf and ("limit" in buf.lower() or "usage" in buf.lower()):
                time.sleep(3)
                try:
                    buf += child.read_nonblocking(size=100000, timeout=5)
                except Exception:
                    pass
                break
    except pexpect.TIMEOUT:
        buf = (child.before or "") + buf
    except pexpect.EOF:
        buf = (child.before or "") + buf
    finally:
        child.close(force=True)

    clean = _strip_ansi(buf)
    if "Weekly" not in clean:
        raise KimiQuotaError(
            f"kimi CLI /usage did not return quota info. Tail:\n{clean[-500:]}"
        )
    return _parse_cli_usage(clean)


def _run_opencli(opencli_bin: str, args: List[str], timeout: float) -> str:
    try:
        completed = subprocess.run(
            [opencli_bin] + args,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KimiQuotaError(str(exc)) from exc
    return completed.stdout or ""


def query_via_opencli(opencli_bin: str, timeout: float = 30.0) -> Dict[str, Any]:
    stdout = _run_opencli(opencli_bin, ["kimi", "status"], timeout)
    if not ("LoggedIn" in stdout and "Yes" in stdout and "/code/console" in stdout):
        _run_opencli(
            opencli_bin,
            [
                "browser",
                "default",
                "open",
                "https://www.kimi.com/code/console?from=kfc_overview_topbar",
            ],
            timeout,
        )
        time.sleep(3)

    raw = _run_opencli(opencli_bin, ["browser", "default", "extract"], timeout)
    text = ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            text = data.get("content", "")
    except json.JSONDecodeError:
        text = raw

    if not text or ("Weekly" not in text and "Rate limit" not in text):
        raise KimiQuotaError(
            "Could not extract Kimi quota from console page via opencli."
        )

    result = _parse_cli_usage(text)
    result["source"] = "opencli"
    return result


def query_kimi_quota(
    kimi_bin: Optional[str] = None,
    opencli_bin: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    if kimi_bin:
        try:
            return query_via_cli(kimi_bin, timeout)
        except KimiQuotaError:
            pass

    resolved_kimi = shutil.which("kimi") or shutil.which("kimi-code")
    if resolved_kimi:
        try:
            return query_via_cli(resolved_kimi, timeout)
        except KimiQuotaError:
            pass

    resolved_opencli = opencli_bin or shutil.which("opencli")
    if resolved_opencli:
        return query_via_opencli(resolved_opencli, timeout)

    raise KimiQuotaError("Neither kimi CLI nor opencli was found on PATH.")


def render_human(result: Dict[str, Any]) -> str:
    lines = ["Kimi Code quota"]
    models = result.get("models", [])
    if not models:
        return "Kimi Code quota\nNo quota information was returned."
    membership = result.get("user", {}).get("membership")
    source = result.get("source", "unknown")
    if membership:
        lines.append(f"- Membership: {membership}")
    lines.append(f"- Source: {source}")
    for model in models:
        label = model.get("windowLabel", "Unknown")
        remaining = model.get("remainingPercent", 0)
        used = model.get("usedPercent", 0)
        reset = model.get("resetTime")
        reset_str = f", resets {reset}" if reset else ""
        lines.append(f"- {label}: {remaining}% remaining ({used}% used){reset_str}")
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Kimi Code quota (CLI preferred, opencli fallback)."
    )
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    parser.add_argument("--kimi-bin", help="explicit kimi CLI path")
    parser.add_argument("--opencli-bin", help="explicit opencli path")
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="total timeout in seconds"
    )
    parser.add_argument(
        "--force-opencli", action="store_true", help="skip CLI, use opencli directly"
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.force_opencli:
            opencli_bin = _resolve_bin("opencli", args.opencli_bin)
            if not opencli_bin:
                raise KimiQuotaError("opencli not found")
            result = query_via_opencli(opencli_bin, args.timeout)
        else:
            result = query_kimi_quota(
                kimi_bin=args.kimi_bin,
                opencli_bin=args.opencli_bin,
                timeout=args.timeout,
            )
    except KimiQuotaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_human(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
