#!/usr/bin/env python3
"""Offline documentation & harness integrity gate for VPN-OwnLine."""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sqlite3
import sys
from pathlib import Path

AGENTS_MAX_LINES = 80
STALE_BACKLOG_DAYS = 30
LEGACY_DIRS = (
    "archive",
    "research",
    "prompt",
    "docs/核心文档",
    "docs/设计",
    "docs/归档",
)

FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PLAN_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")
PLAN_STATUS_RE = re.compile(r"\bStatus:\s*(ACTIVE|PARTIAL)\b")
BACKLOG_ID_RE = re.compile(r"^BL-\d+$")
BACKLOG_PRI_RE = re.compile(r"^P[012]$")
BACKLOG_STATUS_ALLOWED = {"OPEN", "BLOCKED", "VERIFYING"}
ADR_ANCHOR_RE = re.compile(r'<a\s+id="(adr-\d+)"\s*>\s*</a>')
ADR_STATUS_SUPERSEDED_RE = re.compile(r"\[STATUS:\s*SUPERSEDED\b")
ADR_INDEX_LINK_RE = re.compile(r"#(adr-\d+)")


def _strip_code_fences(text: str) -> str:
    return FENCED_BLOCK_RE.sub("", text)


def _check_markdown_links(root: Path, files: list[Path], errors: list[str]) -> None:
    adr_file = root / "docs" / "adr.md"
    adr_anchors: set[str] = set()
    if adr_file.is_file():
        adr_anchors = set(ADR_ANCHOR_RE.findall(adr_file.read_text(encoding="utf-8", errors="replace")))

    for md_path in files:
        text = md_path.read_text(encoding="utf-8", errors="replace")
        body = _strip_code_fences(text)
        rel_src = md_path.relative_to(root).as_posix()
        for m in MD_LINK_RE.finditer(body):
            raw_href = m.group(1).strip()
            if not raw_href or raw_href.startswith(("http://", "https://", "mailto:", "file://")):
                continue
            if raw_href.startswith("#"):
                anchor = raw_href[1:]
                if md_path == adr_file and anchor.startswith("adr-") and anchor not in adr_anchors:
                    errors.append(f"Broken ADR anchor in {rel_src}: {raw_href}")
                continue
            target_part, _, fragment = raw_href.partition("#")
            resolved = (md_path.parent / target_part).resolve()
            if not resolved.exists():
                errors.append(f"Broken relative link in {rel_src}: {raw_href}")
                continue
            if fragment.startswith("adr-") and resolved == adr_file.resolve() and fragment not in adr_anchors:
                errors.append(f"Broken ADR fragment in {rel_src}: {raw_href}")


def _check_backlog(root: Path, errors: list[str], warnings: list[str], today: _dt.date) -> None:
    backlog = root / "docs" / "backlog.md"
    if not backlog.is_file():
        errors.append("Missing docs/backlog.md")
        return

    lines = backlog.read_text(encoding="utf-8", errors="replace").splitlines()
    seen_ids: set[str] = set()
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 6:
            continue
        if cells[0] == "ID" or set("".join(cells)).issubset({"-", ":", " "}):
            continue
        bid, pri, status, _item, entrypoints, reviewed = cells
        if not BACKLOG_ID_RE.match(bid):
            errors.append(f"docs/backlog.md:{lineno} invalid ID {bid!r}")
        elif bid in seen_ids:
            errors.append(f"docs/backlog.md:{lineno} duplicate ID {bid!r}")
        seen_ids.add(bid)

        if not BACKLOG_PRI_RE.match(pri):
            errors.append(f"docs/backlog.md:{lineno} invalid priority {pri!r}")
        if status not in BACKLOG_STATUS_ALLOWED:
            errors.append(
                f"docs/backlog.md:{lineno} invalid status {status!r} "
                f"(must be one of {sorted(BACKLOG_STATUS_ALLOWED)}; delete closed rows)"
            )
        try:
            reviewed_date = _dt.date.fromisoformat(reviewed)
            age_days = (today - reviewed_date).days
            if age_days > STALE_BACKLOG_DAYS:
                warnings.append(
                    f"Doc-GC notice: {bid} in docs/backlog.md not reviewed for {age_days} days ({reviewed})"
                )
        except ValueError:
            errors.append(f"docs/backlog.md:{lineno} invalid Last-Reviewed date {reviewed!r}")

        ep_items = [x.strip().strip("`") for x in entrypoints.split(",") if x.strip()]
        if not ep_items:
            errors.append(f"docs/backlog.md:{lineno} empty Entrypoint")
        for ep in ep_items:
            if not (root / ep).exists():
                errors.append(f"docs/backlog.md:{lineno} missing entrypoint {ep!r}")


def _check_plans(root: Path, errors: list[str]) -> None:
    plans_dir = root / "docs" / "plans"
    if not plans_dir.is_dir():
        return
    for p in sorted(plans_dir.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if not PLAN_NAME_RE.match(p.name):
            errors.append(f"Invalid plan filename in docs/plans/: {p.name} (expected YYYY-MM-DD-<topic>.md)")
        head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:10])
        if not PLAN_STATUS_RE.search(head):
            errors.append(
                f"docs/plans/{p.name} must declare 'Status: ACTIVE' or 'Status: PARTIAL' in its top 10 lines"
            )


def _check_adr_index(root: Path, errors: list[str]) -> None:
    adr_path = root / "docs" / "adr.md"
    if not adr_path.is_file():
        errors.append("Missing docs/adr.md")
        return

    text = adr_path.read_text(encoding="utf-8", errors="replace")
    idx_header = "## 当前生效 ADR 索引"
    pos = text.find(idx_header)
    if pos == -1:
        errors.append(f"docs/adr.md missing section header {idx_header!r}")
        return

    rest = text[pos + len(idx_header):]
    next_h2 = re.search(r"\n##\s+", rest)
    idx_block = rest[: next_h2.start()] if next_h2 else rest
    indexed_ids = ADR_INDEX_LINK_RE.findall(idx_block)
    if not indexed_ids:
        errors.append("docs/adr.md Active Index contains no #adr-NNN entries")
        return

    indexed_set = set(indexed_ids)
    headings_by_id: dict[str, str] = {}
    for line in text.splitlines():
        if not re.match(r"^#{2,3}\s+", line):
            continue
        m = ADR_ANCHOR_RE.search(line)
        if m:
            headings_by_id[m.group(1)] = line

    for aid in indexed_ids:
        if aid not in headings_by_id:
            errors.append(f"docs/adr.md Active Index references missing anchor #{aid}")
        elif ADR_STATUS_SUPERSEDED_RE.search(headings_by_id[aid]):
            errors.append(f"Superseded ADR #{aid} must not remain in Active Index")

    for aid, heading in headings_by_id.items():
        if not ADR_STATUS_SUPERSEDED_RE.search(heading) and aid not in indexed_set:
            errors.append(f"Active/partial ADR #{aid} missing from '{idx_header}'")


def _check_codegraph(root: Path, errors: list[str], warnings: list[str]) -> None:
    db_path = root / ".codegraph" / "codegraph.db"
    if not db_path.is_file():
        return
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for table, default_col in (("files", "path"), ("nodes", "file_path")):
                cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
                col = default_col if default_col in cols else ("path" if "path" in cols else "")
                if not col:
                    continue
                cnt = con.execute(
                    f"SELECT count(*) FROM {table} WHERE {col} LIKE 'archive/%' OR {col} LIKE '%/archive/%'"
                ).fetchone()[0]
                if cnt > 0:
                    errors.append(
                        f".codegraph/codegraph.db table {table} contains {cnt} stale archive/ rows; run 'codegraph index'"
                    )
        finally:
            con.close()
    except sqlite3.Error as exc:
        warnings.append(f"Could not inspect .codegraph/codegraph.db: {exc}")


def check_docs_harness(root: Path, *, today: _dt.date | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    today = today or _dt.date.today()

    # 1. Retired directories must not exist in HEAD working tree
    for rel in LEGACY_DIRS:
        if (root / rel).exists():
            errors.append(f"Retired directory must not exist in HEAD: {rel}")

    # 2. AGENTS.md size cap
    agents_md = root / "AGENTS.md"
    if not agents_md.is_file():
        errors.append("Missing AGENTS.md")
    else:
        line_count = len(agents_md.read_text(encoding="utf-8", errors="replace").splitlines())
        if line_count > AGENTS_MAX_LINES:
            errors.append(f"AGENTS.md exceeds {AGENTS_MAX_LINES} lines ({line_count})")

    # 3. v0.8.1 backward-compat links
    if not (root / "docs" / "server-buying-guide.md").is_file():
        errors.append("Missing v0.8.1 compat file docs/server-buying-guide.md")
    readme_md = root / "README.md"
    if not readme_md.is_file():
        errors.append("Missing README.md")
    elif 'id="ai-assisted-setup"' not in readme_md.read_text(encoding="utf-8", errors="replace"):
        errors.append('README.md missing backward-compat anchor id="ai-assisted-setup"')

    # 4. Relative Markdown links across active docs
    md_files: list[Path] = []
    for candidate in (agents_md, readme_md, root / "GLOSSARY.md", root / "skills" / "ownline-local" / "SKILL.md"):
        if candidate.is_file():
            md_files.append(candidate)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        md_files.extend(sorted(docs_dir.rglob("*.md")))
    _check_markdown_links(root, md_files, errors)

    # 5. State machines & ADR index
    _check_backlog(root, errors, warnings, today)
    _check_plans(root, errors)
    _check_adr_index(root, errors)

    # 6. CodeGraph hygiene (if DB present locally)
    _check_codegraph(root, errors, warnings)

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate VPN-OwnLine docs harness and state machines.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="Repository root")
    parser.add_argument("--gc-report", action="store_true", help="Print non-fatal Doc-GC notices")
    args = parser.parse_args(argv)

    errors, warnings = check_docs_harness(args.root.resolve())
    if args.gc_report:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: docs harness checks passed (links, state machines, ADR index, AGENTS cap, CodeGraph hygiene).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
