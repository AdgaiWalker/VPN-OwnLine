"""Round-trip complete subscriptions through an independently installed YAML parser."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit.subscriptions import render_clash_yaml


def parse_yaml(text):
    if importlib.util.find_spec("yaml"):
        import yaml
        return yaml.safe_load(text)
    ruby = shutil.which("ruby")
    if ruby:
        result = subprocess.run(
            [ruby, "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load(STDIN.read))"],
            input=text, text=True, capture_output=True, check=True, timeout=10,
        )
        return json.loads(result.stdout)
    raise unittest.SkipTest("A system YAML parser (PyYAML or Ruby Psych) is needed for full document parsing")


class SubscriptionSerializationTests(unittest.TestCase):
    def test_all_profiles_preserve_names_and_protocol_string_types(self):
        special = 'US "Primary" \\ edge\nsecond line\t# []: \u0085\u2028'
        vless = {
            "name": special, "health": "ok", "host": "198.51.100.4", "port": 443,
            "uuid": "12345678", "pbk": "true", "sid": "12345678", "sni": "null",
        }
        hy2 = {
            "name": "QUIC 'quoted'", "type": "hysteria2", "health": "ok",
            "host": "2001:db8::8", "port": "8443", "password": '12: 34\n"secret"',
            "sni": "false", "obfs_password": "001234",
        }
        for profile in ("all", "pro", "direct", "office", "lite"):
            with self.subTest(profile=profile):
                data = parse_yaml(render_clash_yaml([vless, hy2], profile=profile))
                main, quic = data["proxies"]
                self.assertEqual(main["name"], special)
                self.assertEqual(main["uuid"], "12345678")
                self.assertEqual(main["reality-opts"], {"public-key": "true", "short-id": "12345678"})
                self.assertEqual(main["servername"], "null")
                self.assertEqual(quic["password"], hy2["password"])
                self.assertEqual(quic["obfs-password"], "001234")
                self.assertEqual(quic["sni"], "false")
                self.assertIsInstance(main["port"], int)
                self.assertIsInstance(quic["port"], int)
                for group in data["proxy-groups"]:
                    self.assertIn(special, group["proxies"])

    def test_unknown_profile_cannot_inject_yaml_via_comment(self):
        node = {"name": "A", "host": "198.51.100.4", "port": 443, "uuid": "id"}
        data = parse_yaml(render_clash_yaml([node], profile="all\nmalicious: injected"))
        self.assertNotIn("malicious", data)
        self.assertEqual(data["proxies"][0]["name"], "A")


if __name__ == "__main__":
    unittest.main()
