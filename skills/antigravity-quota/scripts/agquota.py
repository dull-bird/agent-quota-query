#!/usr/bin/env python3
"""Query Antigravity CLI (agy) quota via pexpect interaction."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class AgquotaError(RuntimeError):
    pass


def resolve_agy(explicit: Optional[str] = None) -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate)
        located = shutil.which(explicit)
        if located:
            return located
        raise AgquotaError(f"agy executable not found: {explicit}")
    for name in ("agy",):
        located = shutil.which(name)
        if located:
            return located
    raise AgquotaError("agy CLI was not found on PATH.")


def _strip_ansi(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\].*?\x07", "", text)
    text = re.sub(r"\r", "", text)
    text = re.sub(r"[^\x20-\x7e\n]", " ", text)
    text = re.sub(r" {3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_usage_output(raw: str) -> Dict[str, Any]:
    models: List[Dict[str, Any]] = []
    current_group: Optional[str] = None
    current_label: Optional[str] = None

    group_pattern = re.compile(r"^([A-Z][A-Z\s&]+MODELS)$")
    limit_pattern = re.compile(r"(Weekly Limit|Five Hour Limit)")
    percent_pattern = re.compile(r"(\d+[\.\d]*)%")
    remaining_pattern = re.compile(r"(\d+[\.\d]*)%\s+remaining")
    refreshes_pattern = re.compile(r"Refreshes in\s+(.+)", re.IGNORECASE)
    quota_available_pattern = re.compile(r"Quota available", re.IGNORECASE)

    lines = raw.split("\n")
    current_limits: Dict[str, Dict[str, Any]] = {}

    for line in lines:
        group_match = group_pattern.match(line.strip())
        if group_match:
            if current_group and current_limits:
                for window_label, info in current_limits.items():
                    models.append(
                        {
                            "label": f"{current_group} {window_label}",
                            "modelId": current_group.lower().replace(" ", "-")
                            + "-"
                            + window_label.lower().replace(" ", "-"),
                            "remainingPercent": info.get("remainingPercent", 0),
                            "isExhausted": info.get("remainingPercent", 0) <= 0,
                            "resetTime": info.get("resetTime"),
                            "windowLabel": window_label,
                        }
                    )
            current_group = group_match.group(1).strip()
            current_limits = {}
            continue

        limit_match = limit_pattern.search(line)
        if limit_match and current_group:
            current_label = limit_match.group(1)
            current_limits[current_label] = {"remainingPercent": 0, "resetTime": None}
            continue

        if current_label and current_label in current_limits:
            info = current_limits[current_label]

            remaining_match = remaining_pattern.search(line)
            if remaining_match:
                info["remainingPercent"] = round(float(remaining_match.group(1)), 2)
            else:
                percents = percent_pattern.findall(line)
                if percents and not remaining_match:
                    info["remainingPercent"] = round(float(percents[-1]), 2)

            refreshes_match = refreshes_pattern.search(line)
            if refreshes_match:
                info["resetTime"] = _parse_refresh_delta(
                    refreshes_match.group(1).strip()
                )

            if quota_available_pattern.search(line):
                info["remainingPercent"] = 100.0

    if current_group and current_limits:
        for window_label, info in current_limits.items():
            models.append(
                {
                    "label": f"{current_group} {window_label}",
                    "modelId": current_group.lower().replace(" ", "-")
                    + "-"
                    + window_label.lower().replace(" ", "-"),
                    "remainingPercent": info.get("remainingPercent", 0),
                    "isExhausted": info.get("remainingPercent", 0) <= 0,
                    "resetTime": info.get("resetTime"),
                    "windowLabel": window_label,
                }
            )

    return {
        "user": {"email": None, "tier": None},
        "models": models,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _parse_refresh_delta(delta_str: str) -> Optional[str]:
    try:
        total_hours = 0
        for match in re.finditer(r"(\d+)\s*d", delta_str):
            total_hours += int(match.group(1)) * 24
        for match in re.finditer(r"(\d+)\s*h", delta_str):
            total_hours += int(match.group(1))
        for match in re.finditer(r"(\d+)\s*m", delta_str):
            total_hours += int(match.group(1)) / 60.0
        if total_hours > 0:
            reset_time = datetime.now(timezone.utc) + __import__("datetime").timedelta(
                hours=total_hours
            )
            return reset_time.isoformat()
    except Exception:
        pass
    return None


def query_agy_quota(
    agy_bin: str,
    model: str = "Gemini 3.5 Flash (Medium)",
    timeout: float = 60.0,
) -> Dict[str, Any]:
    try:
        import pexpect
    except ImportError:
        raise AgquotaError(
            "pexpect is required for agy quota queries: pip install pexpect"
        )

    env = os.environ.copy()
    env["HOME"] = str(Path.home())
    env["TERM"] = "xterm-256color"

    try:
        child = pexpect.spawn(
            agy_bin,
            ["--dangerously-skip-permissions", "--model", model],
            encoding="utf-8",
            timeout=timeout,
            env=env,
            dimensions=(50, 200),
        )
    except Exception as exc:
        raise AgquotaError(f"Could not start agy: {exc}") from exc

    buf = ""
    try:
        child.expect("for shortcuts", timeout=int(timeout * 0.6))
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
            if "Weekly Limit" in buf or "Five Hour Limit" in buf:
                time.sleep(5)
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
    if (
        "Weekly Limit" not in clean
        and "Five Hour Limit" not in clean
        and "Quota" not in clean
    ):
        raise AgquotaError(
            f"Could not retrieve /usage output from agy. Raw tail:\n{clean[-1000:]}"
        )

    return _parse_usage_output(clean)


def render_human(result: Dict[str, Any]) -> str:
    lines = ["Antigravity quota"]
    models = result.get("models", [])
    if not models:
        return "Antigravity quota\nNo model quota information was returned."
    for model in models:
        label = model.get("label", "Unknown")
        remaining = model.get("remainingPercent", 0)
        window = model.get("windowLabel", "")
        reset = model.get("resetTime")
        reset_str = f", refreshes {reset}" if reset else ""
        lines.append(f"- {label}: {remaining}% remaining{reset_str}")
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Antigravity CLI quota via agy.")
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    parser.add_argument("--agy-bin", help="explicit agy executable path")
    parser.add_argument(
        "--model", default="Gemini 3.5 Flash (Medium)", help="agy model to use"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="total timeout in seconds"
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        agy_bin = resolve_agy(args.agy_bin)
        result = query_agy_quota(agy_bin, args.model, args.timeout)
    except AgquotaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_human(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
