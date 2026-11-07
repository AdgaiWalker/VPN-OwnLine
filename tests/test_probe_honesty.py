"""测试 probe.py 的 100% 诚实延迟观测：禁止减 1000ms 修饰、禁止本机伪造 20~26ms。"""
import base64
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import probe  # noqa: E402


class ProbeHonestyTests(unittest.TestCase):
    def test_remote_probe_preserves_true_latency_and_marks_self_probe(self):
        # 直接在隔离解释器里执行 REMOTE_PROBE_PY，用桩控制耗时 1ms（本机）与 1250ms（跨洋拥塞）
        targets = [
            {"name": "国内中转本机", "host": "198.51.100.10", "port": 443, "sni": "www.apple.com"},
            {"name": "远端高延迟机", "host": "203.0.113.99", "port": 443, "sni": "www.apple.com"},
        ]
        wrapper = f"""
import base64, json, subprocess, socket, sys, time
sys.argv = ["py", "ignored", "{base64.b64encode(json.dumps(targets).encode()).decode()}", "198.51.100.10", "{base64.b64encode('国内中转本机'.encode()).decode()}"]

_clock = [100.0]
def fake_time():
    return _clock[0]

class DummySock:
    def close(self): pass

def fake_conn(addr, timeout=2.5):
    host, _ = addr
    _clock[0] += 0.001 if host == "198.51.100.10" else 1.250
    return DummySock()

class DummyProc:
    stdout = "CONNECTED\\nCipher is TLS_AES_256_GCM_SHA384\\n"

time.time = fake_time
socket.create_connection = fake_conn
subprocess.run = lambda *a, **k: DummyProc()
""" + probe.REMOTE_PROBE_PY
        p = subprocess.run([sys.executable, "-c", wrapper], capture_output=True, text=True, check=True)
        res = json.loads(p.stdout.strip().splitlines()[-1])

        # 本机测本机 1ms 就是 1ms，绝不伪造 20~26ms，且标注 self_probe=True
        self.assertEqual(res["国内中转本机"]["cn_ms"], 1)
        self.assertTrue(res["国内中转本机"]["self_probe"])
        self.assertEqual(res["国内中转本机"]["vantage"], "国内中转本机")

        # 1250ms 高延迟如实报告 ~1250ms，绝不人为减去 1000ms
        self.assertGreaterEqual(res["远端高延迟机"]["cn_ms"], 1249)
        self.assertFalse(res["远端高延迟机"]["self_probe"])

    def test_cn_probe_uses_role_and_custom_ssh_port(self):
        nodes = [
            {"name": "美西出口", "host": "203.0.113.10", "port": 443, "role": "exit"},
            {"name": "自定义中转", "host": "198.51.100.20", "port": 443, "role": "relay", "ssh_user": "ubuntu", "ssh_port": 2202},
        ]
        captured = []

        def fake_run(cmd, **kw):
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout='{"美西出口":{"cn_ok":true,"cn_ms":142}}\n', stderr="")

        with patch.object(probe.subprocess, "run", side_effect=fake_run):
            out = probe.cn_probe(nodes)
        self.assertEqual(out["美西出口"]["cn_ms"], 142)
        self.assertEqual(captured[0][1:3], ["-p", "2202"])
        self.assertIn("ubuntu@198.51.100.20", captured[0])


if __name__ == "__main__":
    unittest.main()
