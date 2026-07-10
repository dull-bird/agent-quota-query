import importlib.util
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "codex-quota"
    / "scripts"
    / "query_codex_quota.py"
)
SPEC = importlib.util.spec_from_file_location("query_codex_quota", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReportTests(unittest.TestCase):
    def test_build_report_keeps_independent_limit_buckets(self):
        report = MODULE.build_report(
            {
                "rateLimits": {},
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitId": "codex",
                        "limitName": None,
                        "planType": "plus",
                        "primary": {
                            "usedPercent": 76,
                            "windowDurationMins": 300,
                            "resetsAt": 1783672985,
                        },
                        "secondary": {
                            "usedPercent": 12,
                            "windowDurationMins": 10080,
                            "resetsAt": 1784259785,
                        },
                        "credits": {
                            "hasCredits": False,
                            "unlimited": False,
                            "balance": "0",
                        },
                        "rateLimitReachedType": None,
                    },
                    "special-model": {
                        "limitId": "special-model",
                        "limitName": "Special Model",
                        "primary": {
                            "usedPercent": 31,
                            "windowDurationMins": 300,
                            "resetsAt": None,
                        },
                    },
                },
                "rateLimitResetCredits": {"availableCount": 2, "credits": []},
            }
        )

        self.assertEqual(
            [item["limitId"] for item in report["limits"]], ["codex", "special-model"]
        )
        self.assertEqual(report["limits"][0]["windows"][0]["remainingPercent"], 24)
        self.assertEqual(report["limits"][0]["windows"][1]["label"], "1w")
        self.assertEqual(report["limits"][1]["windows"][0]["remainingPercent"], 69)
        self.assertEqual(report["availableResetCredits"], 2)

    def test_legacy_single_bucket_is_supported(self):
        report = MODULE.build_report(
            {
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {"usedPercent": 0, "windowDurationMins": 60},
                }
            }
        )
        self.assertEqual(len(report["limits"]), 1)
        self.assertEqual(report["limits"][0]["windows"][0]["remainingPercent"], 100)

    def test_human_output_explains_remaining_and_used(self):
        text = MODULE.render_human(
            {
                "limits": [
                    {
                        "name": "Codex",
                        "limitId": "codex",
                        "windows": [
                            {
                                "label": "5h",
                                "remainingPercent": 24,
                                "usedPercent": 76,
                                "resetsAtLocal": "2026-07-10T16:43:05+08:00",
                            }
                        ],
                        "credits": {"balance": "0"},
                    }
                ],
                "availableResetCredits": 0,
            }
        )
        self.assertIn("24% remaining (76% used)", text)
        self.assertIn("credits: 0", text)


if __name__ == "__main__":
    unittest.main()
