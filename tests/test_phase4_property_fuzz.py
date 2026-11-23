"""Phase 4 property-based fuzzing and edge-case regression tests."""
from __future__ import annotations

import datetime
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nodekit import links, quota_guard, reconcile, traffic_stats  # noqa: E402

try:
    from hypothesis import given, settings, strategies as st  # type: ignore

    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False


def _ctrl_or_ws(value: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _shuffle_dict(obj, rng: random.Random):
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return {k: _shuffle_dict(v, rng) for k, v in items}
    if isinstance(obj, list):
        return [_shuffle_dict(x, rng) for x in obj]
    return obj


class Phase4RegressionTests(unittest.TestCase):
    def test_links_isp_proxy_edge_regressions(self):
        for bad in ("", "   ", ":8080:u:p", ":8080", "socks5://\n:8080", "1.2.3.4:99999", "1.2.3.4:0"):
            with self.subTest(bad=bad):
                with self.assertRaises(links.LinkError):
                    links.parse_isp_proxy(bad)

        parsed = links.parse_isp_proxy("user:1234:pass@1.2.3.4:8080")
        self.assertEqual(parsed["server"], "1.2.3.4")
        self.assertEqual(parsed["server_port"], 8080)
        self.assertEqual(parsed["username"], "user")
        self.assertEqual(parsed["password"], "1234:pass")

        curl_res = links.parse_isp_proxy('curl --proxy "http://u1:p1@198.51.100.10:3128/" https://ipv4.webshare.io/')
        self.assertEqual(curl_res["type"], "http")
        self.assertEqual(curl_res["server"], "198.51.100.10")
        self.assertEqual(curl_res["server_port"], 3128)

        four_part = links.parse_isp_proxy("198.51.100.11:1080:wuser:wp:ss")
        self.assertEqual(four_part["type"], "socks")
        self.assertEqual(four_part["server"], "198.51.100.11")
        self.assertEqual(four_part["server_port"], 1080)
        self.assertEqual(four_part["password"], "wp:ss")

    def test_quota_reset_day_calendar_and_type_boundaries(self):
        self.assertIsNone(quota_guard.parse_reset_day(True))
        self.assertIsNone(quota_guard.parse_reset_day(False))
        self.assertIsNone(quota_guard.parse_reset_day(float("nan")))
        self.assertIsNone(quota_guard.parse_reset_day(float("inf")))
        self.assertIsNone(quota_guard.parse_reset_day(float("-inf")))
        self.assertIsNone(quota_guard.parse_reset_day("2026-02-29"))
        self.assertIsNone(quota_guard.parse_reset_day("2026-02-31"))
        self.assertIsNone(quota_guard.parse_reset_day("foo-bar-15"))
        self.assertEqual(quota_guard.parse_reset_day("2024-02-29"), 29)
        self.assertEqual(quota_guard.parse_reset_day("2028-02-29T08:00:00Z"), 29)
        self.assertEqual(quota_guard.parse_reset_day("23"), 23)
        self.assertEqual(quota_guard.parse_reset_day(23.0), 23)
        self.assertIsNone(quota_guard.parse_reset_day(23.5))

    def test_traffic_stats_sanitizes_corrupt_numbers_and_preserves_ssot(self):
        now = datetime.datetime(2028, 2, 29, 10, 0, tzinfo=traffic_stats.CN_TZ)
        history = {"nodes": {"1.2.3.4": {"last_seen_used": float("nan"), "daily_totals": {"2028-02-29": "bad"}, "snapshots": []}}}
        traffic_stats.record_history_snapshot(history, {"used": "nan", "total": -100}, "1.2.3.4", now=now)
        traffic_stats.record_history_snapshot(history, {"used": 5.5, "total": 500}, "1.2.3.4", now=now)
        traffic_stats.record_history_snapshot(history, {"used": 2.0, "total": 500}, "1.2.3.4", now=now)
        dt = history["nodes"]["1.2.3.4"]["daily_totals"]["2028-02-29"]
        self.assertTrue(math.isfinite(dt))
        self.assertGreaterEqual(dt, 2.0)

        g = traffic_stats.generate_usage_guidance(100, 500, "2028-02-01", "2028-03-01", 1, now=now)
        self.assertGreaterEqual(g["days_remaining"], 1)
        self.assertLessEqual(g["days_remaining"], 2)
        self.assertNotIn("可随心看高清/测速", g["text"])


if HAS_HYPOTHESIS:

    class Phase4HypothesisPropertyTests(unittest.TestCase):
        @settings(max_examples=150, deadline=None, derandomize=True)
        @given(text=st.text(max_size=120))
        def test_prop_parse_isp_proxy_never_crashes(self, text):
            try:
                res = links.parse_isp_proxy(text)
            except links.LinkError:
                return
            self.assertIn(res["type"], ("socks", "http"))
            self.assertIsInstance(res["server"], str)
            self.assertFalse(_ctrl_or_ws(res["server"]))
            self.assertTrue(1 <= int(res["server_port"]) <= 65535)

        @settings(max_examples=120, deadline=None, derandomize=True)
        @given(
            proto=st.sampled_from(["socks5", "http"]),
            ip=st.from_regex(r"198\.51\.100\.[1-9][0-9]?", fullmatch=True),
            port=st.integers(min_value=1, max_value=65535),
            user=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=16),
            password=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=16),
        )
        def test_prop_parse_isp_proxy_formats_roundtrip(self, proto, ip, port, user, password):
            four = links.parse_isp_proxy(f"{ip}:{port}:{user}:{password}")
            self.assertEqual((four["server"], four["server_port"], four["username"], four["password"]), (ip, port, user, password))
            curl_cmd = links.parse_isp_proxy(f'curl --proxy "{proto}://{user}:{password}@{ip}:{port}/" https://api.ipify.org')
            expected_type = "socks" if proto == "socks5" else "http"
            self.assertEqual((curl_cmd["type"], curl_cmd["server"], curl_cmd["server_port"]), (expected_type, ip, port))

        @settings(max_examples=150, deadline=None, derandomize=True)
        @given(text=st.text(max_size=160))
        def test_prop_parse_vless_never_crashes(self, text):
            try:
                res = links.parse(text)
            except links.LinkError:
                return
            self.assertIn("host", res)
            self.assertTrue(1 <= int(res["port"]) <= 65535)

        @settings(max_examples=120, deadline=None, derandomize=True)
        @given(
            h1=st.integers(min_value=1, max_value=223),
            h4=st.integers(min_value=1, max_value=254),
            port=st.integers(min_value=1, max_value=65535),
            u_hex=st.text(alphabet="0123456789abcdef", min_size=32, max_size=32),
            pbk=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-", min_size=8, max_size=43),
            sid=st.text(alphabet="0123456789abcdef", min_size=2, max_size=16),
            sni=st.sampled_from(["www.apple.com", "www.bing.com", "cdn.cloudflare.com"]),
        )
        def test_prop_vless_build_parse_roundtrip(self, h1, h4, port, u_hex, pbk, sid, sni):
            uuid = f"{u_hex[:8]}-{u_hex[8:12]}-4{u_hex[13:16]}-8{u_hex[17:20]}-{u_hex[20:32]}"
            node = {"name": "n-1", "host": f"{h1}.51.100.{h4}", "port": port, "uuid": uuid, "pbk": pbk, "sid": sid, "sni": sni}
            parsed = links.parse(links.build(node))
            for k in ("host", "port", "uuid", "pbk", "sid", "sni"):
                self.assertEqual(parsed[k], node[k])

        @settings(max_examples=150, deadline=None, derandomize=True)
        @given(
            val=st.one_of(
                st.none(),
                st.booleans(),
                st.integers(min_value=-100, max_value=200),
                st.floats(allow_nan=True, allow_infinity=True),
                st.text(max_size=40),
                st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2035, 12, 31)).map(lambda d: d.isoformat()),
            )
        )
        def test_prop_parse_reset_day_invariants(self, val):
            res = quota_guard.parse_reset_day(val)
            if isinstance(val, bool):
                self.assertIsNone(res)
            elif res is not None:
                self.assertIsInstance(res, int)
                self.assertTrue(1 <= res <= 31)

        @settings(max_examples=120, deadline=None, derandomize=True)
        @given(
            used=st.one_of(
                st.floats(min_value=-50, max_value=5000, allow_nan=False, allow_infinity=False),
                st.sampled_from([float("nan"), float("inf"), float("-inf")]),
                st.none(),
                st.text(max_size=10),
            ),
            total=st.one_of(
                st.floats(min_value=-50, max_value=5000, allow_nan=False, allow_infinity=False),
                st.sampled_from([float("nan"), float("inf"), float("-inf")]),
                st.none(),
                st.text(max_size=10),
            ),
        )
        def test_prop_evaluate_instance_quota_invariants(self, used, total):
            ev = quota_guard.evaluate_instance_quota({"used": used, "total": total})
            self.assertIn(ev["status"], ("unknown", "normal", "warning", "tripped"))
            if ev["is_tripped"]:
                self.assertEqual(ev["status"], "tripped")
            if ev["status"] != "unknown":
                self.assertTrue(math.isfinite(ev["percent"]))
                self.assertGreater(ev["total_gb"], 0)
                self.assertGreaterEqual(ev["used_gb"], 0)

        @settings(max_examples=100, deadline=None, derandomize=True)
        @given(
            samples=st.lists(st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False), min_size=1, max_size=20),
            total=st.floats(min_value=10.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
            days_ahead=st.integers(min_value=0, max_value=31),
        )
        def test_prop_traffic_stats_accounting_and_ssot(self, samples, total, days_ahead):
            base_now = datetime.datetime(2028, 2, 27, 12, 0, tzinfo=traffic_stats.CN_TZ)
            history = {}
            for idx, used in enumerate(samples):
                t = base_now + datetime.timedelta(hours=idx * 6)
                traffic_stats.record_history_snapshot(history, {"used": used, "total": total}, "43.153.56.137", now=t)
            last_used = samples[-1]
            end_str = (base_now.date() + datetime.timedelta(days=days_ahead)).isoformat()
            usage = {
                "43.153.56.137": {"used": last_used, "total": total, "start": "2028-02-01", "end": end_str},
                "198.51.100.99": {"used": 999.0, "total": 1000.0, "start": "2028-02-01", "end": end_str},
            }
            active = [{"name": "exit-1", "host": "43.153.56.137", "role": "exit"}]
            agg = traffic_stats.aggregate_all_traffic_stats(usage, history, now=base_now, active_nodes=active)
            guidance = agg["total"]["guidance"]
            self.assertEqual(agg["total"]["total_quota_gb"], round(total, 2))
            self.assertEqual(agg["total"]["this_month_gb"], round(last_used, 2))
            self.assertEqual(guidance["remaining_gb"], max(0.0, round(round(total, 2) - round(last_used, 2), 2)))
            self.assertGreaterEqual(guidance["days_remaining"], 1)
            self.assertTrue(math.isfinite(guidance["daily_budget_gb"]))
            if guidance["days_remaining"] <= 2:
                self.assertNotIn("可随心看高清/测速", guidance["text"])

        @settings(max_examples=80, deadline=None, derandomize=True)
        @given(
            s1=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", min_size=10, max_size=24),
            s2=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", min_size=10, max_size=24),
            seed=st.integers(min_value=0, max_value=10000),
        )
        def test_prop_reconcile_diff_redacts_secrets_and_hash_order_invariant(self, s1, s2, seed):
            if s1 == s2:
                return
            cfg_a = {"inbounds": [{"type": "vless", "users": [{"uuid": s1}], "tls": {"reality": {"private_key": s1, "short_id": ["abcd"]}}}]}
            cfg_b = {"inbounds": [{"type": "vless", "users": [{"uuid": s2}], "tls": {"reality": {"private_key": s2, "short_id": ["abcd"]}}}]}
            diffs = reconcile.diff_configs(cfg_a, cfg_b, redact=True)
            joined = "\n".join(diffs)
            self.assertNotIn(s1, joined)
            self.assertNotIn(s2, joined)
            self.assertIn("[REDACTED]", joined)
            shuffled = _shuffle_dict(cfg_a, random.Random(seed))
            self.assertEqual(reconcile.canonical_sha256(cfg_a), reconcile.canonical_sha256(shuffled))


if __name__ == "__main__":
    unittest.main()
