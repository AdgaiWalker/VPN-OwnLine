"""自动化回归测试：验证 ProviderRegistry, AtomicJsonStore, config_paths 架构与契约。"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit import config_paths
from nodekit.store import AtomicJsonStore
from providers.base import Provider
from providers import ProviderRegistry


class DummyProvider(Provider):
    name = "dummy"

    def available(self) -> bool:
        return True

    def open_port(self, ip: str, port: int, proto: str = "TCP", dry_run: bool = False):
        if ip == "1.2.3.4":
            return ("opened", "已通过安全组放行")
        return ("skip", "不在管控范围")


class ProviderDaemonArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_dir = Path(self.tmp.name)

    def test_atomic_json_store_lifecycle(self):
        file_path = self.tmp_dir / "test.json"
        self.assertEqual(AtomicJsonStore.load(file_path, default={"a": 1}), {"a": 1})

        AtomicJsonStore.dump(file_path, {"name": "test-val", "count": 10})
        loaded = AtomicJsonStore.load(file_path)
        self.assertEqual(loaded["name"], "test-val")
        self.assertEqual(loaded["count"], 10)

        updated = AtomicJsonStore.update(
            file_path,
            lambda d: {**d, "count": d["count"] + 1},
        )
        self.assertEqual(updated["count"], 11)
        self.assertEqual(AtomicJsonStore.load(file_path)["count"], 11)

    def test_provider_registry_routing(self):
        reg = ProviderRegistry(modules=[])
        # 手动注入 dummy provider
        dummy = DummyProvider()
        reg.load_all = lambda errors=None: [dummy]

        st, msg, provider_name = reg.open_port("1.2.3.4", 443)
        self.assertEqual(st, "opened")
        self.assertEqual(provider_name, "dummy")

        st, msg, provider_name = reg.open_port("9.9.9.9", 443)
        self.assertEqual(st, "skip")
        self.assertIn("手动放行", msg)

    def test_config_paths_invariants(self):
        self.assertTrue(str(config_paths.DATA_DIR).endswith("web-data") or "data" in str(config_paths.DATA_DIR).lower())
        self.assertEqual(config_paths.NODES_FILE.name, "nodes.json")
        self.assertEqual(config_paths.STATUS_FILE.name, "status.json")


if __name__ == "__main__":
    unittest.main()
