#!/usr/bin/env python3
"""Persist local quota snapshots and forecast rolling-window exhaustion."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[3]
CODEX_QUERY = ROOT / "skills" / "codex-quota" / "scripts" / "query_codex_quota.py"
AGQUOTA_JS = ROOT / "skills" / "antigravity-quota" / "scripts" / "agquota.js"
AGQUOTA_PY = ROOT / "skills" / "antigravity-quota" / "scripts" / "agquota.py"
KIMI_QUOTA = ROOT / "skills" / "kimi-quota" / "scripts" / "kimi_quota.py"
MIN_FORECAST_SPAN_HOURS = 6.0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect and forecast local agent quota usage."
    )
    parser.add_argument("command", choices=("collect", "report"))
    parser.add_argument(
        "--days", type=int, default=30, help="History lookback for report output."
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    parser.add_argument("--db", help="Override the private SQLite database path.")
    parser.add_argument(
        "--openclaw-bin", default="openclaw", help="OpenClaw executable or path."
    )
    parser.add_argument(
        "--timeout", type=float, default=25.0, help="Per-command timeout in seconds."
    )
    return parser.parse_args(argv)


def default_db_path() -> Path:
    root = Path(
        os.environ.get("AGENT_QUOTA_QUERY_DATA_DIR", "~/.local/share/agent-quota-query")
    ).expanduser()
    return root / "usage-trends.sqlite3"


def now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def run_json(command: Sequence[str], timeout: float) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    if completed.returncode:
        raise RuntimeError(
            (completed.stderr or completed.stdout or "command failed").strip()
        )
    decoder = json.JSONDecoder()
    for index, char in enumerate(completed.stdout):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(completed.stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise RuntimeError("command did not return JSON")


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS quota_snapshots (
          observed_at TEXT NOT NULL,
          provider TEXT NOT NULL,
          limit_id TEXT NOT NULL,
          limit_name TEXT NOT NULL,
          window_label TEXT NOT NULL,
          used_percent REAL NOT NULL,
          remaining_percent REAL NOT NULL,
          resets_at INTEGER,
          PRIMARY KEY (observed_at, provider, limit_id, window_label)
        );
        CREATE TABLE IF NOT EXISTS cron_snapshots (
          observed_at TEXT NOT NULL,
          model_ref TEXT NOT NULL,
          total_jobs INTEGER NOT NULL,
          enabled_jobs INTEGER NOT NULL,
          failed_jobs INTEGER NOT NULL,
          PRIMARY KEY (observed_at, model_ref)
        );
        CREATE TABLE IF NOT EXISTS collection_events (
          observed_at TEXT NOT NULL,
          source TEXT NOT NULL,
          status TEXT NOT NULL,
          detail TEXT,
          PRIMARY KEY (observed_at, source)
        );
        """
    )


def collect_codex_quota(timeout: float) -> Mapping[str, Any]:
    if not CODEX_QUERY.is_file():
        raise RuntimeError("Codex quota skill is missing: %s" % CODEX_QUERY)
    return run_json(
        [sys.executable, str(CODEX_QUERY), "--json", "--timeout", str(timeout)],
        timeout + 5,
    )


def collect_antigravity_quota(timeout: float) -> Mapping[str, Any]:
    if AGQUOTA_PY.is_file():
        return run_json(
            [sys.executable, str(AGQUOTA_PY), "--json", "--timeout", str(timeout)],
            timeout + 10,
        )
    if AGQUOTA_JS.is_file():
        node = shutil.which("node")
        if not node:
            raise RuntimeError(
                "Node.js is required for Antigravity quota collection but was not found on PATH."
            )
        return run_json([node, str(AGQUOTA_JS), "--json"], timeout)
    raise RuntimeError(
        "Antigravity quota skill is missing: neither %s nor %s found"
        % (AGQUOTA_PY, AGQUOTA_JS)
    )


def collect_kimi_quota(timeout: float) -> Mapping[str, Any]:
    if not KIMI_QUOTA.is_file():
        raise RuntimeError("Kimi quota skill is missing: %s" % KIMI_QUOTA)
    opencli_bin = shutil.which("opencli")
    if not opencli_bin:
        raise RuntimeError(
            "opencli is required for Kimi quota collection but was not found on PATH."
        )
    return run_json(
        [
            sys.executable,
            str(KIMI_QUOTA),
            "--json",
            "--opencli-bin",
            opencli_bin,
            "--timeout",
            str(timeout),
        ],
        timeout + 15,
    )


def collect_cron(openclaw_bin: str, timeout: float) -> List[Mapping[str, Any]]:
    executable = (
        shutil.which(openclaw_bin) if not Path(openclaw_bin).is_file() else openclaw_bin
    )
    if not executable:
        raise RuntimeError("OpenClaw CLI was not found: %s" % openclaw_bin)
    data = run_json([str(executable), "cron", "list", "--all", "--json"], timeout)
    jobs = data.get("jobs", [])
    return (
        [job for job in jobs if isinstance(job, Mapping)]
        if isinstance(jobs, list)
        else []
    )


def save_snapshot(
    connection: sqlite3.Connection,
    observed_at: str,
    quota: Mapping[str, Any],
    ag_quota: Mapping[str, Any],
    kimi_quota: Mapping[str, Any],
    jobs: Iterable[Mapping[str, Any]],
) -> Dict[str, int]:
    quota_rows = 0
    for limit in quota.get("limits", []):
        if not isinstance(limit, Mapping):
            continue
        for window in limit.get("windows", []):
            if not isinstance(window, Mapping):
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO quota_snapshots(
                  observed_at, provider, limit_id, limit_name, window_label,
                  used_percent, remaining_percent, resets_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observed_at,
                    "codex",
                    str(limit.get("limitId", "unknown")),
                    str(limit.get("name", "unknown")),
                    str(window.get("label", "rolling")),
                    float(window.get("usedPercent", 0)),
                    float(window.get("remainingPercent", 0)),
                    window.get("resetsAt"),
                ),
            )
            quota_rows += 1

    for model in ag_quota.get("models", []):
        if not isinstance(model, Mapping):
            continue
        remaining = float(model.get("remainingPercent", 0))
        used = max(0.0, 100.0 - remaining)
        reset_time = model.get("resetTime")
        resets_at = None
        if isinstance(reset_time, str) and reset_time:
            try:
                resets_at = int(datetime.fromisoformat(reset_time).timestamp())
            except (ValueError, OSError):
                pass
        label = model.get("label", "unknown")
        model_id = model.get("modelId", label)
        connection.execute(
            """
            INSERT OR REPLACE INTO quota_snapshots(
              observed_at, provider, limit_id, limit_name, window_label,
              used_percent, remaining_percent, resets_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_at,
                "antigravity",
                model_id,
                label,
                "rolling",
                used,
                remaining,
                resets_at,
            ),
        )
        quota_rows += 1

    for model in kimi_quota.get("models", []):
        if not isinstance(model, Mapping):
            continue
        remaining = float(model.get("remainingPercent", 0))
        used = float(model.get("usedPercent", max(0, 100 - remaining)))
        reset_time = model.get("resetTime")
        resets_at = None
        if isinstance(reset_time, str) and reset_time:
            try:
                resets_at = int(datetime.fromisoformat(reset_time).timestamp())
            except (ValueError, OSError):
                pass
        label = model.get("label", "unknown")
        model_id = model.get("modelId", label)
        window_label = model.get("windowLabel", "rolling")
        connection.execute(
            """
            INSERT OR REPLACE INTO quota_snapshots(
              observed_at, provider, limit_id, limit_name, window_label,
              used_percent, remaining_percent, resets_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_at,
                "kimi",
                model_id,
                label,
                window_label,
                used,
                remaining,
                resets_at,
            ),
        )
        quota_rows += 1

    counters: Dict[str, Counter] = {}
    for job in jobs:
        payload = job.get("payload", {})
        state = job.get("state", {})
        if not isinstance(payload, Mapping) or not isinstance(state, Mapping):
            continue
        model = str(payload.get("model") or "agent-default")
        counter = counters.setdefault(model, Counter())
        counter["total"] += 1
        counter["enabled"] += int(bool(job.get("enabled")))
        counter["failed"] += int(state.get("lastStatus") == "error")
    for model, counts in counters.items():
        connection.execute(
            """
            INSERT OR REPLACE INTO cron_snapshots(
              observed_at, model_ref, total_jobs, enabled_jobs, failed_jobs
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (observed_at, model, counts["total"], counts["enabled"], counts["failed"]),
        )
    connection.commit()
    return {"quotaRows": quota_rows, "cronModelGroups": len(counters)}


def load_window_samples(
    connection: sqlite3.Connection, cutoff: str
) -> Dict[tuple, List[Dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT observed_at, provider, limit_id, limit_name, window_label,
               used_percent, remaining_percent, resets_at
        FROM quota_snapshots WHERE observed_at >= ?
        ORDER BY observed_at
        """,
        (cutoff,),
    ).fetchall()
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        item = {
            "observedAt": row[0],
            "provider": row[1],
            "limitId": row[2],
            "limitName": row[3],
            "windowLabel": row[4],
            "usedPercent": row[5],
            "remainingPercent": row[6],
            "resetsAt": row[7],
        }
        grouped.setdefault((row[1], row[2], row[4]), []).append(item)
    return grouped


def forecast(
    samples: Sequence[Mapping[str, Any]], reference: datetime
) -> Dict[str, Any]:
    latest = samples[-1]
    reset = latest.get("resetsAt")
    segment = [sample for sample in samples if sample.get("resetsAt") == reset]
    result: Dict[str, Any] = {
        "observations": len(segment),
        "usedPercent": latest.get("usedPercent"),
        "remainingPercent": latest.get("remainingPercent"),
        "resetsAt": reset,
        "forecast": "insufficient_data",
    }
    if len(segment) < 2:
        return result
    first_time = datetime.fromisoformat(str(segment[0]["observedAt"]))
    last_time = datetime.fromisoformat(str(segment[-1]["observedAt"]))
    observed_span_hours = (last_time - first_time).total_seconds() / 3600.0
    result["observedSpanHours"] = round(observed_span_hours, 3)
    if observed_span_hours < MIN_FORECAST_SPAN_HOURS:
        result["forecast"] = "insufficient_timespan"
        result["minimumObservationSpanHours"] = MIN_FORECAST_SPAN_HOURS
        return result
    points = []
    for sample in segment:
        observed = datetime.fromisoformat(str(sample["observedAt"]))
        points.append(
            (
                (observed - first_time).total_seconds() / 86400.0,
                float(sample["usedPercent"]),
            )
        )
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    denominator = sum((point[0] - mean_x) ** 2 for point in points)
    if denominator <= 0:
        return result
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    result["usedPercentPerDay"] = round(slope, 3)
    if slope <= 0:
        result["forecast"] = "stable_or_declining_usage"
        return result
    current_used = float(latest["usedPercent"])
    exhaustion = reference + timedelta(days=max(0.0, (100.0 - current_used) / slope))
    result["forecast"] = "increasing_usage"
    result["estimatedExhaustionAt"] = exhaustion.isoformat(timespec="seconds")
    if isinstance(reset, (int, float)):
        reset_time = datetime.fromtimestamp(reset, timezone.utc).astimezone()
        projected = current_used + slope * max(
            0.0, (reset_time - reference).total_seconds() / 86400.0
        )
        result["projectedUsedAtResetPercent"] = round(projected, 1)
        result["risk"] = (
            "likely_exhaustion_before_reset" if projected >= 100 else "within_window"
        )
    return result


def build_report(connection: sqlite3.Connection, days: int) -> Dict[str, Any]:
    cutoff = (now() - timedelta(days=max(1, days))).isoformat(timespec="seconds")
    grouped = load_window_samples(connection, cutoff)
    forecasts = []
    reference = now()
    for key, samples in grouped.items():
        if not samples:
            continue
        item = forecast(samples, reference)
        item.update({"provider": key[0], "limitId": key[1], "windowLabel": key[2]})
        forecasts.append(item)
    cron_rows = connection.execute(
        """
        SELECT model_ref, total_jobs, enabled_jobs, failed_jobs, observed_at
        FROM cron_snapshots WHERE observed_at >= ?
        ORDER BY observed_at DESC
        """,
        (cutoff,),
    ).fetchall()
    latest_cron: Dict[str, Dict[str, Any]] = {}
    for row in cron_rows:
        latest_cron.setdefault(
            row[0],
            {
                "model": row[0],
                "totalJobs": row[1],
                "enabledJobs": row[2],
                "failedJobs": row[3],
                "observedAt": row[4],
            },
        )
    event_rows = connection.execute(
        """
        SELECT source, status, detail, observed_at FROM collection_events
        WHERE observed_at >= ? AND status != 'ok'
        ORDER BY observed_at DESC
        """,
        (cutoff,),
    ).fetchall()
    return {
        "lookbackDays": days,
        "forecasts": forecasts,
        "cronModels": list(latest_cron.values()),
        "collectionWarnings": [
            {"source": row[0], "status": row[1], "detail": row[2], "observedAt": row[3]}
            for row in event_rows
        ],
    }


def render(report: Mapping[str, Any]) -> str:
    lines = ["Agent usage trends"]
    forecasts = report.get("forecasts", [])
    if not forecasts:
        lines.append("- No quota history yet. Run collect again after time has passed.")
    for item in forecasts:
        provider = item.get("provider", "")
        prefix = f"{provider}/" if provider else ""
        lines.append(
            "- {prefix}{name} [{window}]: {remaining}% remaining, {observations} samples, {forecast}".format(
                prefix=prefix,
                name=item["limitId"],
                window=item["windowLabel"],
                remaining=item["remainingPercent"],
                observations=item["observations"],
                forecast=item["forecast"],
            )
        )
        if item.get("usedPercentPerDay") is not None:
            lines.append("  - observed usage: %s%%/day" % item["usedPercentPerDay"])
        if item.get("estimatedExhaustionAt"):
            lines.append("  - estimated exhaustion: %s" % item["estimatedExhaustionAt"])
    lines.append("Cron model health")
    for item in report.get("cronModels", []):
        lines.append(
            "- {model}: {enabledJobs} enabled, {failedJobs} last-run failures".format(
                **item
            )
        )
    for item in report.get("collectionWarnings", []):
        lines.append("- Collection warning (%s): %s" % (item["source"], item["detail"]))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as connection:
        init_db(connection)
        if args.command == "collect":
            observed_at = now().isoformat(timespec="seconds")
            quota: Mapping[str, Any] = {"limits": []}
            ag_quota: Mapping[str, Any] = {"models": []}
            kimi_quota_data: Mapping[str, Any] = {"models": []}
            jobs: List[Mapping[str, Any]] = []
            warnings: Dict[str, str] = {}
            try:
                quota = collect_codex_quota(args.timeout)
            except RuntimeError as exc:
                warnings["codex"] = str(exc)
            try:
                ag_quota = collect_antigravity_quota(args.timeout)
            except RuntimeError as exc:
                warnings["antigravity"] = str(exc)
            try:
                kimi_quota_data = collect_kimi_quota(args.timeout)
            except RuntimeError as exc:
                warnings["kimi"] = str(exc)
            try:
                jobs = collect_cron(args.openclaw_bin, args.timeout)
            except RuntimeError as exc:
                warnings["openclaw"] = str(exc)
            summary = save_snapshot(
                connection, observed_at, quota, ag_quota, kimi_quota_data, jobs
            )
            for source in ("codex", "antigravity", "kimi", "openclaw"):
                connection.execute(
                    "INSERT OR REPLACE INTO collection_events(observed_at, source, status, detail) VALUES (?, ?, ?, ?)",
                    (
                        observed_at,
                        source,
                        "warning" if source in warnings else "ok",
                        warnings.get(source),
                    ),
                )
            connection.commit()
            output = {
                "database": str(db_path),
                **summary,
                "warnings": warnings,
                "report": build_report(connection, args.days),
            }
        else:
            output = build_report(connection, args.days)
    print(
        json.dumps(output, ensure_ascii=False, indent=2)
        if args.json
        else render(output.get("report", output))
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
