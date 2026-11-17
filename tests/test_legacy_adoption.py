"""Legacy adoption is an explicit, state-bound metadata operation, never a restart."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
spec = importlib.util.spec_from_file_location("adopt_legacy", ROOT / "deploy/adopt_legacy.py")
adoption = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adoption)
from nodekit import provenance


class LegacyAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.data = root / "data"
        self.data.mkdir()
        self.cfg, self.manifest, self.caddy = root / "config.json", root / "manifest.json", root / "Caddyfile"
        self.node = {"local": True, "host": "198.51.100.2", "name": "fixture", "port": 443, "uuid": "fixture-uuid"}
        (self.data / "nodes.json").write_text(json.dumps([self.node]))
        self.cfg.write_text(json.dumps({"inbounds": [{"type": "vless", "listen_port": 443, "users": [{"uuid": "fixture-uuid"}]}]}))
        self.sha = provenance.compute_config_sha256(self.cfg.read_bytes())
        template = (ROOT / "deploy/install.sh").read_text().split("<< CADDYEOF\n", 1)[1].split("\nCADDYEOF", 1)[0]
        self.caddy.write_text(template.replace("$SETUP_JOB", "a" * 32).replace("$PASS_HASH", "$2b$14$" + "A" * 53)
                              .replace("${DOMAIN}", "fixture.example").replace("$TLS_DIRECTIVE", ""))
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0, "/opt/sing-box/sing-box run -c " + str(self.cfg), ""))
        self.options = dict(data=self.data, cfg=self.cfg, manifest=self.manifest, caddy=self.caddy,
                            lock=root / "lock", runner=self.runner)

    def assert_untouched(self):
        self.assertFalse(self.manifest.exists())
        self.assertFalse((self.data / "master_secret").exists())
        self.runner.assert_not_called()

    def test_no_confirmation_no_adoption(self):
        with self.assertRaises(ValueError):
            adoption.adopt(self.node["host"], self.sha, **self.options)
        self.assert_untouched()

    def test_readonly_preparation_never_signs_or_changes_service(self):
        result = adoption.adopt(self.node["host"], self.sha, inspect_only=True, **self.options)
        self.assertEqual(result["status"], "eligible_for_explicit_confirmation")
        self.assertFalse(self.manifest.exists())
        self.assertFalse((self.data / "master_secret").exists())
        self.runner.assert_called_once()
        self.assertEqual(self.runner.call_args.args[0][:3], ["systemctl", "show", "sing-box"])

    def test_config_drift_or_wrong_local_record_never_gets_signed(self):
        with self.assertRaises(ValueError):
            adoption.adopt(self.node["host"], "0" * 64, confirmed=True, **self.options)
        self.assert_untouched()
        (self.data / "nodes.json").write_text(json.dumps([dict(self.node, uuid="different")]))
        with self.assertRaises(ValueError):
            adoption.adopt(self.node["host"], self.sha, confirmed=True, **self.options)
        self.assert_untouched()

    def test_shared_gateway_never_gets_adopted(self):
        self.caddy.write_text(self.caddy.read_text() + "\nhttps://another.example { respond 200 }\n")
        with self.assertRaises(ValueError):
            adoption.adopt(self.node["host"], self.sha, confirmed=True, **self.options)
        self.assert_untouched()

    def test_explicit_proxy_scope_does_not_adopt_or_modify_custom_gateway(self):
        self.caddy.write_text("custom gateway fixture")
        before = self.caddy.read_bytes()
        with self.assertRaises(ValueError):
            adoption.adopt(self.node["host"], self.sha, scope="proxy", **self.options)
        self.assert_untouched()
        result = adoption.adopt(self.node["host"], self.sha, confirmed=True, scope="proxy", **self.options)
        self.assertEqual(result["status"], "adopted_without_restart")
        self.assertEqual(self.caddy.read_bytes(), before)
        self.assertTrue(provenance.verify_provenance(json.loads(self.manifest.read_bytes()), provenance.load_master_secret(self.data))[0])
        self.assertEqual(self.runner.call_args.args[0][:3], ["systemctl", "show", "sing-box"])

    def test_confirmed_matching_state_only_writes_private_metadata(self):
        result = adoption.adopt(self.node["host"], self.sha, confirmed=True, **self.options)
        self.assertEqual(result["status"], "adopted_without_restart")
        before = self.manifest.read_bytes()
        signed = json.loads(before)
        self.assertTrue(provenance.verify_provenance(signed, provenance.load_master_secret(self.data))[0])
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.sha, provenance.compute_config_sha256(self.cfg.read_bytes()))
        self.assertEqual(adoption.adopt(self.node["host"], self.sha, confirmed=True, **self.options)["status"], "already_owned")
        self.assertEqual(before, self.manifest.read_bytes())
        for call in self.runner.call_args_list:
            self.assertEqual(call.args[0][:3], ["systemctl", "show", "sing-box"])

    def test_foreign_existing_manifest_is_not_replaced(self):
        self.manifest.write_text('{"foreign": true}')
        before = self.manifest.read_bytes()
        with self.assertRaises((ValueError, OSError)):
            adoption.adopt(self.node["host"], self.sha, confirmed=True, **self.options)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertFalse((self.data / "master_secret").exists())


if __name__ == "__main__":
    unittest.main()
