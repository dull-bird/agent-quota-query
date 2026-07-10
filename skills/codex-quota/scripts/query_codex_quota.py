#!/usr/bin/env python3
"""Read Codex rolling quota data through the local app-server protocol."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, TextIO


class QuotaError(RuntimeError):
    """Raised when a safe quota snapshot cannot be obtained."""


def resolve_codex(explicit: Optional[str] = None) -> str:
    """Resolve the Codex executable, including the Windows npm shim."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate)
        located = shutil.which(explicit)
        if located:
            return located
        raise QuotaError(f"Codex executable not found: {explicit}")

    for name in ("codex", "codex.cmd"):
        located = shutil.which(name)
        if located:
            return located
    raise QuotaError(
        "Codex CLI was not found on PATH. Install Codex, then run this command again."
    )


def _command_for_codex(codex_bin: str) -> List[str]:
    command = [codex_bin, "app-server", "--stdio"]
    if os.name == "nt" and Path(codex_bin).suffix.lower() in {".bat", ".cmd"}:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/d", "/s", "/c", subprocess.list2cmdline(command)]
    return command


def _read_lines(stream: TextIO, destination: "queue.Queue[Optional[str]]") -> None:
    try:
        for line in iter(stream.readline, ""):
            destination.put(line)
    finally:
        destination.put(None)


def _send(process: subprocess.Popen[str], message: Mapping[str, Any]) -> None:
    if process.stdin is None:
        raise QuotaError("Codex app-server stdin is unavailable.")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _wait_for_response(
    lines: "queue.Queue[Optional[str]]",
    response_id: int,
    deadline: float,
) -> Mapping[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QuotaError("Timed out while waiting for Codex quota data.")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise QuotaError("Timed out while waiting for Codex quota data.") from exc
        if line is None:
            raise QuotaError(
                "Codex app-server exited before returning quota data. "
                "Run 'codex login status' and 'codex --version', then retry."
            )
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, Mapping) or message.get("id") != response_id:
            continue
        if message.get("error"):
            error = message["error"]
            if isinstance(error, Mapping):
                detail = str(error.get("message") or "unknown protocol error")
            else:
                detail = str(error)
            raise QuotaError(f"Codex rejected the quota request: {detail}")
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise QuotaError("Codex returned an invalid quota response.")
        return result


def query_rate_limits(codex_bin: str, timeout: float = 20.0) -> Mapping[str, Any]:
    """Request account/rateLimits/read from an ephemeral Codex app-server."""
    if timeout <= 0:
        raise QuotaError("Timeout must be greater than zero.")

    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        process: subprocess.Popen[str] = subprocess.Popen(
            _command_for_codex(codex_bin),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **popen_kwargs,
        )
    except OSError as exc:
        raise QuotaError(f"Could not start Codex app-server: {exc}") from exc

    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    assert process.stdout is not None
    threading.Thread(
        target=_read_lines, args=(process.stdout, lines), daemon=True
    ).start()

    deadline = time.monotonic() + timeout
    try:
        _send(
            process,
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {"name": "codex-quota", "version": "1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        _wait_for_response(lines, 1, deadline)
        _send(process, {"method": "initialized", "params": {}})
        _send(process, {"method": "account/rateLimits/read", "id": 2, "params": {}})
        return _wait_for_response(lines, 2, deadline)
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _local_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def _duration_label(minutes: Any) -> str:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return "rolling window"
    if value <= 0:
        return "rolling window"
    if value % 10080 == 0:
        return f"{value // 10080}w"
    if value % 1440 == 0:
        return f"{value // 1440}d"
    if value % 60 == 0:
        return f"{value // 60}h"
    return f"{value}m"


def _normalize_window(window: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(window, Mapping):
        return None
    try:
        used = int(window["usedPercent"])
    except (KeyError, TypeError, ValueError):
        return None
    duration = window.get("windowDurationMins")
    reset = window.get("resetsAt")
    return {
        "label": _duration_label(duration),
        "windowDurationMins": duration,
        "usedPercent": used,
        "remainingPercent": max(0, min(100, 100 - used)),
        "resetsAt": reset,
        "resetsAtLocal": _local_timestamp(reset),
    }


def _iter_snapshots(
    result: Mapping[str, Any],
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, Mapping) and by_id:
        ordered_ids = sorted(
            by_id, key=lambda value: (str(value) != "codex", str(value))
        )
        for limit_id in ordered_ids:
            snapshot = by_id[limit_id]
            if isinstance(snapshot, Mapping):
                yield str(limit_id), snapshot
        return
    snapshot = result.get("rateLimits")
    if isinstance(snapshot, Mapping):
        yield str(snapshot.get("limitId") or "codex"), snapshot


def build_report(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert the protocol payload into stable, display-oriented JSON."""
    limits: List[Dict[str, Any]] = []
    for limit_id, snapshot in _iter_snapshots(result):
        windows = [
            normalized
            for normalized in (
                _normalize_window(snapshot.get("primary")),
                _normalize_window(snapshot.get("secondary")),
            )
            if normalized is not None
        ]
        credits = snapshot.get("credits")
        limits.append(
            {
                "limitId": limit_id,
                "name": snapshot.get("limitName")
                or ("Codex" if limit_id == "codex" else limit_id),
                "windows": windows,
                "credits": dict(credits) if isinstance(credits, Mapping) else None,
                "rateLimitReachedType": snapshot.get("rateLimitReachedType"),
            }
        )

    reset_credits = result.get("rateLimitResetCredits")
    available_resets = None
    if isinstance(reset_credits, Mapping):
        available_resets = reset_credits.get("availableCount")

    return {
        "source": "codex app-server account/rateLimits/read",
        "queriedAt": datetime.now(timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
        "limits": limits,
        "availableResetCredits": available_resets,
    }


def render_human(report: Mapping[str, Any]) -> str:
    lines = ["Codex quota"]
    limits = report.get("limits")
    if not isinstance(limits, list) or not limits:
        return "Codex quota\nNo rate-limit buckets were returned."
    for item in limits:
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- {item.get('name')} [{item.get('limitId')}]")
        windows = item.get("windows")
        if isinstance(windows, list):
            for window in windows:
                if not isinstance(window, Mapping):
                    continue
                reset = window.get("resetsAtLocal") or "unknown reset time"
                lines.append(
                    "  - {label}: {remaining}% remaining ({used}% used), resets {reset}".format(
                        label=window.get("label"),
                        remaining=window.get("remainingPercent"),
                        used=window.get("usedPercent"),
                        reset=reset,
                    )
                )
        credits = item.get("credits")
        if isinstance(credits, Mapping):
            balance = credits.get("balance")
            if balance is not None:
                lines.append(f"  - credits: {balance}")
    available = report.get("availableResetCredits")
    if available is not None:
        lines.append(f"- available rate-limit resets: {available}")
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the current authenticated Codex account quota."
    )
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="request timeout in seconds"
    )
    parser.add_argument(
        "--codex-bin",
        help="explicit Codex executable path or command name (useful for diagnostics)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        codex_bin = resolve_codex(args.codex_bin)
        report = build_report(query_rate_limits(codex_bin, args.timeout))
    except QuotaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
