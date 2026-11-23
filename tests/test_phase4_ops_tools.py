"""Offline unit tests for Phase 4 external SLA probe and billing reconcile tools."""
from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


external_probe = _load_module("external_probe", "scripts/ops/external_probe.py")
billing_reconcile = _load_module("billing_reconcile", "scripts/ops/billing_reconcile.py")


class Phase4OpsToolsTests(unittest.TestCase):
    def test_external_probe_report_p50_p95_availability_and_leaks(self):
        now = datetime.datetime(2026, 11, 23, 13, 0, tzinfo=external_probe.CN_TZ)
        with tempfile.TemporaryDirectory() as td:
            hist = Path(td) / "history.jsonl"
            samples = [
                {"ts": (now - datetime.timedelta(days=10)).isoformat(), "ok": False, "https_ok": False, "rtt_ms": 9999.0, "stealth_ok": False, "isp_leak": True},
                {"ts": (now - datetime.timedelta(days=2)).isoformat(), "ok": True, "https_ok": True, "rtt_ms": 100.0, "stealth_ok": True, "isp_leak": False},
                {"ts": (now - datetime.timedelta(days=1)).isoformat(), "ok": True, "https_ok": True, "rtt_ms": 200.0, "stealth_ok": True, "isp_leak": False},
                {"ts": (now - datetime.timedelta(hours=12)).isoformat(), "ok": True, "https_ok": True, "rtt_ms": 300.0, "stealth_ok": True, "isp_leak": False},
                {"ts": (now - datetime.timedelta(hours=6)).isoformat(), "ok": True, "https_ok": True, "rtt_ms": 400.0, "stealth_ok": False, "isp_leak": False},
                {"ts": (now - datetime.timedelta(hours=1)).isoformat(), "ok": False, "https_ok": True, "rtt_ms": 500.0, "stealth_ok": True, "isp_leak": True},
            ]
            for rec in samples:
                external_probe.append_record(rec, hist)

            loaded = external_probe.load_records(hist)
            self.assertEqual(len(loaded), 6)
            rep = external_probe.summarize_history(loaded, days=7, now=now)
            self.assertEqual(rep["sample_count"], 5)
            self.assertEqual(rep["ok_count"], 4)
            self.assertEqual(rep["fail_count"], 1)
            self.assertEqual(rep["availability_pct"], 80.0)
            self.assertEqual(rep["disconnect_rate_pct"], 20.0)
            self.assertEqual(rep["p50_ms"], 300.0)
            self.assertEqual(rep["p95_ms"], 500.0)
            self.assertEqual(rep["stealth_pass_rate_pct"], 80.0)
            self.assertEqual(rep["isp_leak_count"], 1)

    def test_billing_reconcile_statuses_and_file_parsers(self):
        with tempfile.TemporaryDirectory() as td:
            usage_p = Path(td) / "usage.json"
            usage_p.write_text(json.dumps({
                "43.153.56.137": {"used": 298.3, "total": 512.0, "end": "2026-11-23"},
                "_ts": "2026-11-23T04:00:00Z",
            }))
            stats_p = Path(td) / "stats.json"
            stats_p.write_text(json.dumps({
                "total": {"this_month_gb": 298.3},
                "nodes": {"43.153.56.137": {"used_gb": 298.3, "end": "2026-11-23"}},
            }))
            csv_p = Path(td) / "tencent.csv"
            csv_p.write_text("PeriodEnd,UsedGB,ResetDay\n2026-11-23,301.0,23\n")
            off_json_p = Path(td) / "official.json"
            off_json_p.write_text(json.dumps({"used_gb": 360.0, "reset_day": 23}))

            pm_usage = billing_reconcile.extract_panel_metrics(json.loads(usage_p.read_text()), host="43.153.56.137")
            pm_stats = billing_reconcile.extract_panel_metrics(json.loads(stats_p.read_text()))
            self.assertEqual(pm_usage, {"panel_gb": 298.3, "panel_reset_day": 23})
            self.assertEqual(pm_stats, {"panel_gb": 298.3, "panel_reset_day": 23})

            csv_off = billing_reconcile.parse_official_file(csv_p)
            aligned = billing_reconcile.reconcile_billing(
                pm_stats["panel_gb"], csv_off["official_gb"],
                panel_reset_day=pm_stats["panel_reset_day"], official_reset_day=csv_off["official_reset_day"],
            )
            self.assertEqual(aligned["status"], "aligned")
            self.assertTrue(aligned["reset_day_match"])

            minor = billing_reconcile.reconcile_billing(300.0, 330.0, panel_reset_day=23, official_reset_day=23)
            self.assertEqual(minor["status"], "minor_drift")

            off_j = billing_reconcile.parse_official_file(off_json_p)
            disc = billing_reconcile.reconcile_billing(
                pm_usage["panel_gb"], off_j["official_gb"],
                panel_reset_day=pm_usage["panel_reset_day"], official_reset_day=off_j["official_reset_day"],
            )
            self.assertEqual(disc["status"], "discrepancy")

            mismatch_reset = billing_reconcile.reconcile_billing(300.0, 300.0, panel_reset_day=23, official_reset_day=24)
            self.assertFalse(mismatch_reset["reset_day_match"])
            self.assertEqual(mismatch_reset["status"], "minor_drift")


if __name__ == "__main__":
    unittest.main()
