import contextlib
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

from scripts import zero_drift as zd

ROOT = Path(__file__).resolve().parents[1]


def _make_minimal_repo(tmp: Path) -> Path:
    (tmp / "docs" / "plans").mkdir(parents=True)
    (tmp / "deploy").mkdir(parents=True)
    (tmp / "deploy" / "release.py").write_text("# stub\n", encoding="utf-8")
    (tmp / "AGENTS.md").write_text("# Rules\n- Thin map\n", encoding="utf-8")
    (tmp / "README.md").write_text(
        '<a id="ai-assisted-setup"></a>\nSee [ADR](docs/adr.md#adr-001).\n',
        encoding="utf-8",
    )
    (tmp / "GLOSSARY.md").write_text("# Glossary\n- **Node**: server\n", encoding="utf-8")
    (tmp / "docs" / "server-buying-guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp / "docs" / "backlog.md").write_text(
        "# Backlog\n\n| ID | Priority | Status | Item | Entrypoint | Last-Reviewed |\n"
        "|---|---|---|---|---|---|\n"
        "| BL-01 | P1 | OPEN | Sample item | `deploy/release.py` | 2026-11-23 |\n",
        encoding="utf-8",
    )
    (tmp / "docs" / "plans" / "2026-11-23-sample-plan.md").write_text(
        "# Sample\n\n> Status: PARTIAL\n",
        encoding="utf-8",
    )
    (tmp / "docs" / "adr.md").write_text(
        "# ADR\n\n"
        "## 当前生效 ADR 索引\n\n"
        "- [ADR-001：Active](#adr-001)\n\n"
        '### <a id="adr-001"></a>ADR-001：Active [STATUS: IMPLEMENTED]\n\nText.\n\n'
        '### <a id="adr-002"></a>ADR-002：Old [STATUS: SUPERSEDED BY ADR-001]\n\nOld text.\n',
        encoding="utf-8",
    )
    (tmp / "zero-drift.toml").write_text(
        (ROOT / "zero-drift.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return tmp


class DocsHarnessTests(unittest.TestCase):
    def test_live_repository_passes_docs_harness(self):
        res = zd.run_check(ROOT)
        self.assertEqual(res["exit_code"], 0, res["errors"])
        self.assertTrue(res["passed"])

    def test_rejects_broken_relative_link(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "README.md").write_text(
                '<a id="ai-assisted-setup"></a>\n[Broken](docs/nope.md)\n',
                encoding="utf-8",
            )
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            msgs = [e["message"] for e in res["errors"]]
            self.assertTrue(any("Broken relative link" in m for m in msgs), msgs)

    def test_rejects_oversized_agents_md(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "AGENTS.md").write_text("line\n" * 85, encoding="utf-8")
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            msgs = [e["message"] for e in res["errors"]]
            self.assertTrue(any("exceeds 80 lines" in m for m in msgs), msgs)

    def test_rejects_agents_md_exceeding_max_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "AGENTS.md").write_text("x" * 9000 + "\n", encoding="utf-8")
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            codes = {e["code"] for e in res["errors"]}
            self.assertIn("entrypoint_max_bytes", codes, res["errors"])

    def test_rejects_closed_row_in_backlog(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "docs" / "backlog.md").write_text(
                "# Backlog\n\n| ID | Priority | Status | Item | Entrypoint | Last-Reviewed |\n"
                "|---|---|---|---|---|---|\n"
                "| BL-01 | P0 | DONE | Closed item | `deploy/release.py` | 2026-11-23 |\n",
                encoding="utf-8",
            )
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            msgs = [e["message"] for e in res["errors"]]
            self.assertTrue(any("invalid status 'DONE'" in m for m in msgs), msgs)

    def test_rejects_implemented_plan_in_docs_plans(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "docs" / "plans" / "2026-11-23-sample-plan.md").write_text(
                "# Sample\n\n> Status: IMPLEMENTED\n",
                encoding="utf-8",
            )
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            msgs = [e["message"] for e in res["errors"]]
            self.assertTrue(any("Status: ACTIVE" in m for m in msgs), msgs)

    def test_rejects_superseded_adr_in_active_index(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "docs" / "adr.md").write_text(
                "# ADR\n\n"
                "## 当前生效 ADR 索引\n\n"
                "- [ADR-001：Active](#adr-001)\n"
                "- [ADR-002：Old](#adr-002)\n\n"
                '### <a id="adr-001"></a>ADR-001：Active [STATUS: IMPLEMENTED]\n\nText.\n\n'
                '### <a id="adr-002"></a>ADR-002：Old [STATUS: SUPERSEDED BY ADR-001]\n\nOld text.\n',
                encoding="utf-8",
            )
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            msgs = [e["message"] for e in res["errors"]]
            self.assertTrue(any("Superseded ADR #adr-002" in m for m in msgs), msgs)

    def test_rejects_leftover_archive_dir_and_codegraph_pollution(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "archive").mkdir()
            (repo / ".codegraph").mkdir()
            con = sqlite3.connect(repo / ".codegraph" / "codegraph.db")
            con.execute("CREATE TABLE files (path TEXT)")
            con.execute("CREATE TABLE nodes (file_path TEXT)")
            con.execute("INSERT INTO files VALUES ('archive/old.py')")
            con.execute("INSERT INTO nodes VALUES ('archive/old.py')")
            con.commit()
            con.close()
            res = zd.run_check(repo)
            self.assertEqual(res["exit_code"], 1)
            codes = {e["code"] for e in res["errors"]}
            msgs = [e["message"] for e in res["errors"]]
            self.assertIn("forbid_path", codes, res["errors"])
            self.assertIn("codegraph_polluted", codes, res["errors"])
            self.assertTrue(any("stale archive/ rows" in m for m in msgs), msgs)
            shutil.rmtree(repo / "archive")

    def test_json_receipt_and_ratchet_mode(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "README.md").write_text(
                '<a id="ai-assisted-setup"></a>\n[Broken](docs/nope.md)\n',
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = zd.main(["check", "--root", str(repo), "--json"])
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["passed"])
            self.assertEqual(payload["schema_version"], 1)

            rc_up = zd.main(["check", "--root", str(repo), "--update-baseline"])
            self.assertEqual(rc_up, 0)
            rc_ratchet = zd.main(["check", "--root", str(repo), "--ratchet"])
            self.assertEqual(rc_ratchet, 0)

            (repo / "GLOSSARY.md").write_text("[NewBroken](docs/missing2.md)\n", encoding="utf-8")
            rc_new = zd.main(["check", "--root", str(repo), "--ratchet"])
            self.assertEqual(rc_new, 1)

    def test_python310_toml_fallback_parses_live_config(self):
        raw = (ROOT / "zero-drift.toml").read_text(encoding="utf-8")
        parsed = zd.parse_toml_fallback(raw)
        self.assertEqual(parsed["meta"]["min_tool_version"], "0.1.0")
        self.assertEqual(parsed["entrypoint"]["max_bytes"], 8192)
        if tomllib is not None:
            self.assertEqual(parsed, tomllib.loads(raw))

    def test_zero_drift_script_contains_no_ownline_hardcoding(self):
        src = (ROOT / "scripts" / "zero_drift.py").read_text(encoding="utf-8")
        lower = src.lower()
        for word in ("ownline", "sing-box", "caddy", "server-buying-guide", "ai-assisted-setup"):
            self.assertNotIn(word, lower)
        for word in ("BL-", "核心文档", "当前生效 ADR 索引"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
