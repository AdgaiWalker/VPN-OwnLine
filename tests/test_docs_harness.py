import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import check_docs_harness as cdh

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
    return tmp


class DocsHarnessTests(unittest.TestCase):
    def test_live_repository_passes_docs_harness(self):
        errors, _warnings = cdh.check_docs_harness(ROOT)
        self.assertEqual(errors, [])

    def test_rejects_broken_relative_link(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "README.md").write_text(
                '<a id="ai-assisted-setup"></a>\n[Broken](docs/nope.md)\n',
                encoding="utf-8",
            )
            errors, _ = cdh.check_docs_harness(repo)
            self.assertTrue(any("Broken relative link" in e for e in errors), errors)

    def test_rejects_oversized_agents_md(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "AGENTS.md").write_text("line\n" * 85, encoding="utf-8")
            errors, _ = cdh.check_docs_harness(repo)
            self.assertTrue(any("exceeds 80 lines" in e for e in errors), errors)

    def test_rejects_closed_row_in_backlog(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "docs" / "backlog.md").write_text(
                "# Backlog\n\n| ID | Priority | Status | Item | Entrypoint | Last-Reviewed |\n"
                "|---|---|---|---|---|---|\n"
                "| BL-01 | P0 | DONE | Closed item | `deploy/release.py` | 2026-11-23 |\n",
                encoding="utf-8",
            )
            errors, _ = cdh.check_docs_harness(repo)
            self.assertTrue(any("invalid status 'DONE'" in e for e in errors), errors)

    def test_rejects_implemented_plan_in_docs_plans(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _make_minimal_repo(Path(td))
            (repo / "docs" / "plans" / "2026-11-23-sample-plan.md").write_text(
                "# Sample\n\n> Status: IMPLEMENTED\n",
                encoding="utf-8",
            )
            errors, _ = cdh.check_docs_harness(repo)
            self.assertTrue(any("Status: ACTIVE" in e for e in errors), errors)

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
            errors, _ = cdh.check_docs_harness(repo)
            self.assertTrue(any("Superseded ADR #adr-002" in e for e in errors), errors)

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
            errors, _ = cdh.check_docs_harness(repo)
            self.assertTrue(any("Retired directory" in e for e in errors), errors)
            self.assertTrue(any("stale archive/ rows" in e for e in errors), errors)
            shutil.rmtree(repo / "archive")


if __name__ == "__main__":
    unittest.main()
