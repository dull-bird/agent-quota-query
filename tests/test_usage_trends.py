import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "openclaw-usage-trends"
    / "scripts"
    / "usage_trends.py"
)
SPEC = importlib.util.spec_from_file_location("usage_trends", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ForecastTests(unittest.TestCase):
    def test_forecast_projects_increasing_usage(self):
        samples = [
            {
                "observedAt": "2026-07-10T00:00:00+00:00",
                "usedPercent": 10,
                "remainingPercent": 90,
                "resetsAt": 1783987200,
            },
            {
                "observedAt": "2026-07-12T00:00:00+00:00",
                "usedPercent": 30,
                "remainingPercent": 70,
                "resetsAt": 1783987200,
            },
        ]
        report = MODULE.forecast(samples, datetime(2026, 7, 12, tzinfo=timezone.utc))
        self.assertEqual(report["forecast"], "increasing_usage")
        self.assertEqual(report["usedPercentPerDay"], 10.0)
        self.assertIn("estimatedExhaustionAt", report)

    def test_forecast_requires_two_samples(self):
        report = MODULE.forecast(
            [
                {
                    "observedAt": "2026-07-12T00:00:00+00:00",
                    "usedPercent": 30,
                    "remainingPercent": 70,
                    "resetsAt": None,
                }
            ],
            datetime(2026, 7, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(report["forecast"], "insufficient_data")

    def test_forecast_rejects_a_short_sampling_span(self):
        report = MODULE.forecast(
            [
                {
                    "observedAt": "2026-07-12T00:00:00+00:00",
                    "usedPercent": 10,
                    "remainingPercent": 90,
                    "resetsAt": None,
                },
                {
                    "observedAt": "2026-07-12T00:05:00+00:00",
                    "usedPercent": 20,
                    "remainingPercent": 80,
                    "resetsAt": None,
                },
            ],
            datetime(2026, 7, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(report["forecast"], "insufficient_timespan")


class AntigravitySnapshotTests(unittest.TestCase):
    def test_save_snapshot_includes_antigravity_models(self):
        codex_quota = {
            "limits": [
                {
                    "limitId": "codex",
                    "name": "Codex",
                    "windows": [
                        {
                            "label": "5h",
                            "usedPercent": 50,
                            "remainingPercent": 50,
                            "resetsAt": None,
                        },
                    ],
                }
            ]
        }
        ag_quota = {
            "models": [
                {
                    "label": "Gemini Flash",
                    "modelId": "gemini-flash",
                    "remainingPercent": 80,
                    "isExhausted": False,
                    "resetTime": "2026-07-13T20:00:00+00:00",
                },
                {
                    "label": "Claude Opus",
                    "modelId": "claude-opus",
                    "remainingPercent": 0,
                    "isExhausted": True,
                    "resetTime": None,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            with sqlite3.connect(str(db_path)) as conn:
                MODULE.init_db(conn)
                summary = MODULE.save_snapshot(
                    conn,
                    "2026-07-13T16:00:00+08:00",
                    codex_quota,
                    ag_quota,
                    {"models": []},
                    [],
                )
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute(
                    "SELECT provider, limit_id, limit_name, remaining_percent FROM quota_snapshots ORDER BY provider, limit_id"
                ).fetchall()
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0][:3], ("antigravity", "claude-opus", "Claude Opus"))
            self.assertAlmostEqual(rows[0][3], 0.0)
            self.assertEqual(
                rows[1][:3], ("antigravity", "gemini-flash", "Gemini Flash")
            )
            self.assertAlmostEqual(rows[1][3], 80.0)
            self.assertEqual(rows[2][:3], ("codex", "codex", "Codex"))
            self.assertEqual(summary["quotaRows"], 3)

    def test_save_snapshot_handles_empty_antigravity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            with sqlite3.connect(str(db_path)) as conn:
                MODULE.init_db(conn)
                summary = MODULE.save_snapshot(
                    conn,
                    "2026-07-13T16:00:00+08:00",
                    {"limits": []},
                    {"models": []},
                    {"models": []},
                    [],
                )
            self.assertEqual(summary["quotaRows"], 0)
