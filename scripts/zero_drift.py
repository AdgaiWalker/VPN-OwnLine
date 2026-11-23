#!/usr/bin/env python3
"""zero-drift: config-driven documentation and AI context hygiene harness.

Zero third-party dependencies (Python 3.10+ stdlib only).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]

TOOL_VERSION = "0.1.0"
SCHEMA_VERSION = 1

DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "out",
    ".ops-private",
    ".backups-private",
}

ARCHIVE_SEGMENTS = {"archive", "archives", "historical", "deprecated", "归档"}
VENDOR_SEGMENTS = {".agents", ".claude", ".cursor", ".codex", "vendor", "third_party", "skills"}
CONTENT_SEGMENTS = {"content", "contents", "public", "static", "output", "outputs", "posts", "blog", "articles"}

FENCED_BLOCK_RE = re.compile(r"(```.*?```|~~~.*?~~~)", re.DOTALL)
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")
INT_RE = re.compile(r"^[+-]?(?:0|[1-9](?:_?[0-9])*)$")
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "file://", "data:", "tel:", "javascript:")


# ---------------------------------------------------------------------------
# Pure-Python TOML subset parser (Python 3.10+ compatibility)
# ---------------------------------------------------------------------------

def _skip_ws_and_comments(text: str, pos: int, *, allow_newlines: bool) -> int:
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch in (" ", "\t", "\r"):
            pos += 1
        elif allow_newlines and ch == "\n":
            pos += 1
        elif ch == "#":
            while pos < n and text[pos] != "\n":
                pos += 1
            if not allow_newlines:
                break
        else:
            break
    return pos


def _parse_basic_string(text: str, pos: int) -> tuple[str, int]:
    """Parse double-quoted TOML string starting at index of opening quote."""
    assert text[pos] == '"'
    pos += 1
    n = len(text)
    out: list[str] = []
    escapes = {
        '"': '"',
        "\\": "\\",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    while pos < n:
        ch = text[pos]
        if ch == '"':
            return "".join(out), pos + 1
        if ch in ("\n", "\r"):
            raise ValueError("Unterminated basic string before newline")
        if ch == "\\":
            pos += 1
            if pos >= n:
                raise ValueError("Unterminated escape in basic string")
            esc = text[pos]
            if esc in escapes:
                out.append(escapes[esc])
                pos += 1
            elif esc == "u":
                hex_part = text[pos + 1 : pos + 5]
                if len(hex_part) != 4:
                    raise ValueError("Invalid \\uXXXX escape")
                out.append(chr(int(hex_part, 16)))
                pos += 5
            elif esc == "U":
                hex_part = text[pos + 1 : pos + 9]
                if len(hex_part) != 8:
                    raise ValueError("Invalid \\UXXXXXXXX escape")
                out.append(chr(int(hex_part, 16)))
                pos += 9
            else:
                raise ValueError(f"Unsupported escape \\{esc} in TOML basic string")
        else:
            out.append(ch)
            pos += 1
    raise ValueError("Unterminated basic string at EOF")


def _parse_literal_string(text: str, pos: int) -> tuple[str, int]:
    """Parse single-quoted TOML literal string starting at opening quote."""
    assert text[pos] == "'"
    pos += 1
    n = len(text)
    start = pos
    while pos < n:
        ch = text[pos]
        if ch == "'":
            return text[start:pos], pos + 1
        if ch in ("\n", "\r"):
            raise ValueError("Unterminated literal string before newline")
        pos += 1
    raise ValueError("Unterminated literal string at EOF")


def _parse_key_segment(text: str, pos: int) -> tuple[str, int]:
    n = len(text)
    pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
    if pos >= n:
        raise ValueError("Expected TOML key")
    if text[pos] == '"':
        return _parse_basic_string(text, pos)
    if text[pos] == "'":
        return _parse_literal_string(text, pos)
    m = BARE_KEY_RE.match(text, pos)
    if not m:
        raise ValueError(f"Invalid TOML bare key at offset {pos}")
    return m.group(0), m.end()


def _parse_dotted_key(text: str, pos: int) -> tuple[list[str], int]:
    parts: list[str] = []
    while True:
        seg, pos = _parse_key_segment(text, pos)
        parts.append(seg)
        pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
        if pos < len(text) and text[pos] == ".":
            pos += 1
            continue
        return parts, pos


def _parse_toml_value(text: str, pos: int) -> tuple[Any, int]:
    n = len(text)
    if pos >= n:
        raise ValueError("Expected TOML value")
    ch = text[pos]
    if ch == '"':
        return _parse_basic_string(text, pos)
    if ch == "'":
        return _parse_literal_string(text, pos)
    if ch == "[":
        pos += 1
        items: list[Any] = []
        while True:
            pos = _skip_ws_and_comments(text, pos, allow_newlines=True)
            if pos >= n:
                raise ValueError("Unterminated TOML array")
            if text[pos] == "]":
                return items, pos + 1
            item, pos = _parse_toml_value(text, pos)
            items.append(item)
            pos = _skip_ws_and_comments(text, pos, allow_newlines=True)
            if pos >= n:
                raise ValueError("Unterminated TOML array after element")
            if text[pos] == ",":
                pos += 1
                continue
            if text[pos] == "]":
                return items, pos + 1
            raise ValueError(f"Expected ',' or ']' in TOML array at offset {pos}")

    start = pos
    while pos < n and text[pos] not in (" ", "\t", "\r", "\n", "#", ",", "]"):
        pos += 1
    token = text[start:pos]
    if token == "true":
        return True, pos
    if token == "false":
        return False, pos
    if INT_RE.match(token):
        return int(token.replace("_", "")), pos
    raise ValueError(f"Unsupported TOML value {token!r} at offset {start}")


def parse_toml_fallback(text: str) -> dict[str, Any]:
    """Parse a clean TOML subset (tables, strings, ints, bools, arrays, comments)."""
    root: dict[str, Any] = {}
    current: dict[str, Any] = root
    n = len(text)
    pos = 0

    while True:
        pos = _skip_ws_and_comments(text, pos, allow_newlines=True)
        if pos >= n:
            break
        if text[pos] == "[":
            pos += 1
            path_parts, pos = _parse_dotted_key(text, pos)
            pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
            if pos >= n or text[pos] != "]":
                raise ValueError(f"Expected ']' closing table header at offset {pos}")
            pos += 1
            pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
            if pos < n and text[pos] != "\n":
                raise ValueError(f"Unexpected trailing characters after table header at offset {pos}")
            target = root
            for part in path_parts:
                nxt = target.get(part)
                if nxt is None:
                    nxt = {}
                    target[part] = nxt
                elif not isinstance(nxt, dict):
                    raise ValueError(f"Table path conflict at {part!r}")
                target = nxt
            current = target
            continue

        key_parts, pos = _parse_dotted_key(text, pos)
        pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
        if pos >= n or text[pos] != "=":
            raise ValueError(f"Expected '=' after key at offset {pos}")
        pos += 1
        pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
        val, pos = _parse_toml_value(text, pos)
        pos = _skip_ws_and_comments(text, pos, allow_newlines=False)
        if pos < n and text[pos] != "\n":
            raise ValueError(f"Unexpected trailing characters after value at offset {pos}")

        target = current
        for part in key_parts[:-1]:
            nxt = target.setdefault(part, {})
            if not isinstance(nxt, dict):
                raise ValueError(f"Key path conflict at {part!r}")
            target = nxt
        leaf = key_parts[-1]
        if leaf in target:
            raise ValueError(f"Duplicate TOML key {leaf!r}")
        target[leaf] = val

    return root


def load_toml(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(raw)
    return parse_toml_fallback(raw)


def _version_tuple(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in raw.strip().split("."):
        m = re.match(r"^(\d+)", piece)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


# ---------------------------------------------------------------------------
# Shared Helpers (Git, Globs, Markdown Links, Fingerprints)
# ---------------------------------------------------------------------------

def _git_output(root: Path, args: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _repo_sha(root: Path) -> str | None:
    out = _git_output(root, ["rev-parse", "--short", "HEAD"])
    return out.strip() if out and out.strip() else None


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    pat = pattern.strip().lstrip("./")
    i = 0
    out = ["^"]
    n = len(pat)
    while i < n:
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == n:
            out.append("(?:/.*)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def _walk_repo_files(root: Path, *, suffix: str | None = None) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_SKIP_DIRS)
        for name in sorted(filenames):
            if suffix and not name.lower().endswith(suffix):
                continue
            found.append(Path(dirpath) / name)
    return found


def _resolve_scope_files(root: Path, include_globs: list[str], exclude_globs: list[str]) -> list[Path]:
    inc_res = [_glob_to_regex(g) for g in include_globs]
    exc_res = [_glob_to_regex(g) for g in exclude_globs]
    matched: list[Path] = []
    for path in _walk_repo_files(root, suffix=".md"):
        rel = path.relative_to(root).as_posix()
        if not any(r.match(rel) for r in inc_res):
            continue
        if any(r.match(rel) for r in exc_res):
            continue
        matched.append(path)
    return sorted(matched)


def _strip_code_fences(text: str) -> str:
    return FENCED_BLOCK_RE.sub("", text)


def _parse_md_target(raw_href: str) -> str:
    href = raw_href.strip()
    if href.startswith("<") and ">" in href:
        href = href[1 : href.index(">")].strip()
    else:
        href = re.sub(r"""\s+["'][^"']*["']\s*$""", "", href).strip()
    return href


def _extract_md_links(text: str) -> list[str]:
    """Extract Markdown link targets while ignoring fenced code blocks and inline code spans."""
    body = _strip_code_fences(text)
    hrefs: list[str] = []
    for line in body.splitlines():
        for m in MD_LINK_RE.finditer(line):
            prefix = line[: m.start()]
            # Skip matches embedded inside inline `code` spans on the same line
            if prefix.count("`") % 2 == 1:
                continue
            hrefs.append(_parse_md_target(m.group(2)))
    return hrefs


def _is_broken_target(md_path: Path, target_part: str) -> Path | None:
    """Return resolved Path even if missing, or None when invalid/external."""
    try:
        cand = (md_path.parent / target_part).resolve()
        if cand.exists():
            return cand
        decoded = unquote(target_part)
        if decoded != target_part:
            cand_dec = (md_path.parent / decoded).resolve()
            if cand_dec.exists():
                return cand_dec
        return cand
    except (OSError, ValueError):
        return None


def _make_issue(
    code: str,
    path: str,
    message: str,
    base_key: str,
    seen_counts: dict[str, int],
) -> dict[str, str]:
    base_fp = f"{code}|{base_key}"
    occ = seen_counts.get(base_fp, 0) + 1
    seen_counts[base_fp] = occ
    fp = base_fp if occ == 1 else f"{base_fp}@{occ}"
    return {
        "code": code,
        "path": path,
        "message": message,
        "fingerprint": fp,
    }


def _classify_markdown_bucket(rel_posix: str) -> str:
    parts = [p.lower() for p in Path(rel_posix).parts[:-1]]
    if any(seg in ARCHIVE_SEGMENTS for seg in parts):
        return "archive"
    if any(seg in VENDOR_SEGMENTS for seg in parts):
        return "vendor_or_skills"
    if any(seg in CONTENT_SEGMENTS for seg in parts):
        return "content"
    return "engineering"


def _inspect_codegraph_db(
    db_path: Path,
    forbid_prefixes: list[str],
) -> tuple[dict[str, Any], list[tuple[str, str, int]], str | None]:
    """Read-only inspection of .codegraph/codegraph.db if present."""
    stats: dict[str, Any] = {
        "present": False,
        "total_files": 0,
        "total_nodes": 0,
        "forbidden_hits": {},
    }
    hits: list[tuple[str, str, int]] = []
    if not db_path.is_file():
        return stats, hits, None

    stats["present"] = True
    try:
        con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for table, default_col in (("files", "path"), ("nodes", "file_path")):
                cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
                if not cols:
                    continue
                col = default_col if default_col in cols else ("path" if "path" in cols else "")
                if not col:
                    continue
                total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                stats[f"total_{table}"] = int(total)
                for prefix in forbid_prefixes:
                    norm = prefix.strip().rstrip("/") + "/"
                    cnt = int(
                        con.execute(
                            f"SELECT count(*) FROM {table} WHERE {col} LIKE ? OR {col} LIKE ?",
                            (f"{norm}%", f"%/{norm}%"),
                        ).fetchone()[0]
                    )
                    if cnt > 0:
                        hits.append((table, norm, cnt))
                        stats["forbidden_hits"][f"{table}:{norm}"] = cnt
        finally:
            con.close()
    except sqlite3.Error as exc:
        return stats, hits, f"Could not inspect {db_path.name}: {exc}"
    return stats, hits, None


# ---------------------------------------------------------------------------
# Subcommand: audit
# ---------------------------------------------------------------------------

def run_audit(root: Path, *, today: _dt.date | None = None) -> dict[str, Any]:
    root = root.resolve()
    today = today or _dt.date.today()
    now_ts = int(_dt.datetime.combine(today, _dt.time(23, 59, 59)).timestamp())

    buckets: dict[str, dict[str, int]] = {
        b: {"files": 0, "lines": 0, "bytes": 0}
        for b in ("engineering", "vendor_or_skills", "content", "archive")
    }
    eng_paths: list[Path] = []

    for path in _walk_repo_files(root, suffix=".md"):
        rel = path.relative_to(root).as_posix()
        bucket = _classify_markdown_bucket(rel)
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8", errors="replace")
        buckets[bucket]["files"] += 1
        buckets[bucket]["lines"] += len(text.splitlines())
        buckets[bucket]["bytes"] += len(raw_bytes)
        if bucket == "engineering":
            eng_paths.append(path)

    # Entrypoint sizing
    entry_candidates = [root / "AGENTS.md", root / "CLAUDE.md"]
    entry_path = next((p for p in entry_candidates if p.is_file()), None)
    if entry_path is not None:
        raw = entry_path.read_bytes()
        entry_info: dict[str, Any] = {
            "path": entry_path.relative_to(root).as_posix(),
            "exists": True,
            "lines": len(raw.decode("utf-8", errors="replace").splitlines()),
            "bytes": len(raw),
        }
    else:
        entry_info = {"path": "AGENTS.md", "exists": False, "lines": 0, "bytes": 0}

    # Broken relative links in engineering bucket only
    broken_links: list[dict[str, str]] = []
    for md_path in eng_paths:
        rel_src = md_path.relative_to(root).as_posix()
        text = md_path.read_text(encoding="utf-8", errors="replace")
        for href in _extract_md_links(text):
            if not href or href.startswith("#") or href.startswith(EXTERNAL_SCHEMES):
                continue
            target_part, _, _ = href.partition("#")
            if not target_part:
                continue
            cand = _is_broken_target(md_path, target_part)
            decoded = _is_broken_target(md_path, unquote(target_part))
            if (cand is None or not cand.exists()) and (decoded is None or not decoded.exists()):
                broken_links.append({"source": rel_src, "href": href})

    # Staleness in engineering bucket via single git log pass (fallback mtime)
    git_mtimes: dict[str, int] = {}
    git_log_dates = _git_output(root, ["log", "--name-only", "--format=DATE:%ct", "--", "*.md"])
    if git_log_dates is not None:
        cur_ts = 0
        for line in git_log_dates.splitlines():
            if line.startswith("DATE:"):
                try:
                    cur_ts = int(line[5:])
                except ValueError:
                    cur_ts = 0
            elif line.strip() and cur_ts > 0:
                git_mtimes.setdefault(line.strip(), cur_ts)

    stale_30 = 0
    stale_60 = 0
    stale_samples: list[dict[str, Any]] = []
    for md_path in eng_paths:
        rel = md_path.relative_to(root).as_posix()
        ts = git_mtimes.get(rel) or int(md_path.stat().st_mtime)
        age_days = max(0, (now_ts - ts) // 86400)
        if age_days > 30:
            stale_30 += 1
        if age_days > 60:
            stale_60 += 1
        stale_samples.append({"path": rel, "age_days": age_days})
    stale_samples.sort(key=lambda item: (-item["age_days"], item["path"]))

    # Last 50 commits churn
    churn_out = _git_output(root, ["log", "-n", "50", "--numstat", "--format=COMMIT:%H"])
    churn_metrics: dict[str, Any] | None = None
    if churn_out is not None:
        commits_sampled = 0
        code_commits = 0
        doc_only_commits = 0
        md_edits_in_code_commits = 0
        cur_md = 0
        cur_other = 0
        in_commit = False

        def _flush_commit() -> None:
            nonlocal commits_sampled, code_commits, doc_only_commits, md_edits_in_code_commits
            if not in_commit:
                return
            commits_sampled += 1
            if cur_other > 0:
                code_commits += 1
                md_edits_in_code_commits += cur_md
            elif cur_md > 0:
                doc_only_commits += 1

        for line in churn_out.splitlines():
            if line.startswith("COMMIT:"):
                _flush_commit()
                in_commit = True
                cur_md = 0
                cur_other = 0
            elif "\t" in line:
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    fpath = parts[2].strip()
                    if fpath.lower().endswith(".md"):
                        cur_md += 1
                    elif fpath:
                        cur_other += 1
        _flush_commit()
        churn_metrics = {
            "commits_sampled": commits_sampled,
            "code_commits": code_commits,
            "doc_only_commits": doc_only_commits,
            "doc_only_ratio": round(doc_only_commits / commits_sampled, 3) if commits_sampled else 0.0,
            "avg_md_per_code_commit": round(md_edits_in_code_commits / code_commits, 2) if code_commits else 0.0,
        }

    # HEAD tree archive share
    tree_out = _git_output(root, ["ls-tree", "-r", "-l", "HEAD"])
    head_tree_metrics: dict[str, Any] | None = None
    if tree_out is not None:
        total_bytes = 0
        archive_bytes = 0
        for line in tree_out.splitlines():
            # Format: "<mode> <type> <sha> <size>\t<path>"
            if "\t" not in line:
                continue
            meta, path_part = line.split("\t", 1)
            fields = meta.split()
            if len(fields) >= 4 and fields[3].isdigit():
                size = int(fields[3])
                total_bytes += size
                if _classify_markdown_bucket(path_part) == "archive" or any(
                    seg in ARCHIVE_SEGMENTS for seg in (p.lower() for p in Path(path_part).parts[:-1])
                ):
                    archive_bytes += size
        head_tree_metrics = {
            "total_bytes": total_bytes,
            "archive_bytes": archive_bytes,
            "archive_share": round(archive_bytes / total_bytes, 4) if total_bytes else 0.0,
        }

    cg_stats, _hits, _cg_warn = _inspect_codegraph_db(root / ".codegraph" / "codegraph.db", ["archive/"])

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "command": "audit",
        "repo_root": str(root),
        "repo_sha": _repo_sha(root),
        "passed": True,
        "exit_code": 0,
        "metrics": {
            "markdown_buckets": buckets,
            "entrypoint": entry_info,
            "broken_engineering_links_count": len(broken_links),
            "broken_engineering_links_sample": broken_links[:50],
            "engineering_staleness": {
                "over_30d": stale_30,
                "over_60d": stale_60,
                "oldest_sample": stale_samples[:10],
            },
            "git_churn_last_50": churn_metrics,
            "head_tree": head_tree_metrics,
            "codegraph": cg_stats,
        },
        "errors": [],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Subcommand: check
# ---------------------------------------------------------------------------

def _check_adr_single(
    root: Path,
    adr_cfg: dict[str, Any],
    errors: list[dict[str, str]],
    seen_counts: dict[str, int],
) -> tuple[Path | None, set[str], re.Pattern[str] | None]:
    adr_rel = str(adr_cfg.get("path", "docs/adr.md"))
    adr_path = root / adr_rel
    anchor_pat = adr_cfg.get("anchor_pattern", '<a\\s+id="(adr-\\d+)"\\s*>\\s*</a>')
    link_pat = adr_cfg.get("index_link_pattern", "#(adr-\\d+)")
    sup_pat = adr_cfg.get("superseded_pattern", "\\[STATUS:\\s*SUPERSEDED\\b")
    idx_heading = adr_cfg.get("active_index_heading", "## Active ADR Index")

    anchor_re = re.compile(anchor_pat)
    link_re = re.compile(link_pat)
    sup_re = re.compile(sup_pat)

    if not adr_path.is_file():
        errors.append(
            _make_issue("adr_missing", adr_rel, f"Missing {adr_rel}", adr_rel, seen_counts)
        )
        return adr_path, set(), link_re

    text = adr_path.read_text(encoding="utf-8", errors="replace")
    all_anchors: set[str] = {
        m.group(1) if m.lastindex else m.group(0)
        for m in anchor_re.finditer(text)
    }

    pos = text.find(idx_heading)
    if pos == -1:
        errors.append(
            _make_issue(
                "adr_index_missing",
                adr_rel,
                f"{adr_rel} missing section header {idx_heading!r}",
                adr_rel,
                seen_counts,
            )
        )
        return adr_path, all_anchors, link_re

    rest = text[pos + len(idx_heading) :]
    next_h2 = re.search(r"\n##\s+", rest)
    idx_block = rest[: next_h2.start()] if next_h2 else rest
    indexed_ids = [
        m.group(1) if m.lastindex else m.group(0)
        for m in link_re.finditer(idx_block)
    ]
    if not indexed_ids:
        errors.append(
            _make_issue(
                "adr_index_empty",
                adr_rel,
                f"{adr_rel} Active Index contains no indexed ADR entries",
                adr_rel,
                seen_counts,
            )
        )
        return adr_path, all_anchors, link_re

    headings_by_id: dict[str, str] = {}
    for line in text.splitlines():
        if not re.match(r"^#{2,3}\s+", line):
            continue
        m = anchor_re.search(line)
        if m:
            aid = m.group(1) if m.lastindex else m.group(0)
            headings_by_id[aid] = line

    for aid in indexed_ids:
        if aid not in headings_by_id:
            errors.append(
                _make_issue(
                    "adr_index_broken_anchor",
                    adr_rel,
                    f"{adr_rel} Active Index references missing anchor #{aid}",
                    f"{adr_rel}#{aid}",
                    seen_counts,
                )
            )
        elif sup_re.search(headings_by_id[aid]):
            errors.append(
                _make_issue(
                    "adr_superseded_in_index",
                    adr_rel,
                    f"Superseded ADR #{aid} must not remain in Active Index",
                    f"{adr_rel}#{aid}",
                    seen_counts,
                )
            )

    indexed_set = set(indexed_ids)
    for aid, heading in headings_by_id.items():
        if not sup_re.search(heading) and aid not in indexed_set:
            errors.append(
                _make_issue(
                    "adr_missing_from_index",
                    adr_rel,
                    f"Active/partial ADR #{aid} missing from {idx_heading!r}",
                    f"{adr_rel}#{aid}",
                    seen_counts,
                )
            )

    return adr_path, all_anchors, link_re


def _check_adr_directory(
    root: Path,
    adr_cfg: dict[str, Any],
    errors: list[dict[str, str]],
    seen_counts: dict[str, int],
) -> None:
    dir_rel = str(adr_cfg.get("dir", "docs/adr"))
    adr_dir = root / dir_rel
    if not adr_dir.is_dir():
        errors.append(_make_issue("adr_dir_missing", dir_rel, f"Missing {dir_rel}", dir_rel, seen_counts))
        return
    sup_pat = adr_cfg.get("superseded_pattern", "\\[STATUS:\\s*SUPERSEDED\\b")
    sup_re = re.compile(sup_pat)
    index_rel = adr_cfg.get("index_file")
    index_text = ""
    if index_rel:
        idx_path = root / str(index_rel)
        if not idx_path.is_file():
            errors.append(_make_issue("adr_index_missing", str(index_rel), f"Missing {index_rel}", str(index_rel), seen_counts))
            return
        index_text = idx_path.read_text(encoding="utf-8", errors="replace")

    for p in sorted(adr_dir.iterdir()):
        if not p.is_file() or p.name.startswith(".") or not p.name.lower().endswith(".md"):
            continue
        if index_rel and (root / str(index_rel)).resolve() == p.resolve():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:15])
        is_sup = bool(sup_re.search(head))
        if index_rel:
            in_index = p.name in index_text
            if not is_sup and not in_index:
                rel = p.relative_to(root).as_posix()
                errors.append(_make_issue("adr_missing_from_index", rel, f"Active ADR {rel} missing from {index_rel}", rel, seen_counts))
            elif is_sup and in_index:
                rel = p.relative_to(root).as_posix()
                errors.append(_make_issue("adr_superseded_in_index", rel, f"Superseded ADR {rel} must not remain in {index_rel}", rel, seen_counts))


def _check_backlog_section(
    root: Path,
    cfg: dict[str, Any],
    today: _dt.date,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    seen_counts: dict[str, int],
) -> list[dict[str, Any]]:
    stale_items: list[dict[str, Any]] = []
    mode = str(cfg.get("mode", "external"))
    if mode == "external":
        return stale_items

    rel_path = str(cfg.get("path", "docs/backlog.md"))
    backlog_path = root / rel_path
    if not backlog_path.is_file():
        errors.append(_make_issue("backlog_missing", rel_path, f"Missing {rel_path}", rel_path, seen_counts))
        return stale_items

    raw_bytes = backlog_path.read_bytes()
    max_bytes = cfg.get("max_bytes")
    if isinstance(max_bytes, int) and len(raw_bytes) > max_bytes:
        errors.append(
            _make_issue(
                "backlog_max_bytes",
                rel_path,
                f"{rel_path} exceeds {max_bytes} bytes ({len(raw_bytes)})",
                rel_path,
                seen_counts,
            )
        )

    text = raw_bytes.decode("utf-8", errors="replace")
    stale_days = int(cfg.get("stale_days", 30))

    if mode == "checklist":
        forbid_checked = bool(cfg.get("forbid_checked", True))
        if forbid_checked:
            for lineno, line in enumerate(text.splitlines(), 1):
                if re.match(r"^\s*[-*]\s+\[[xX]\]\s+(.+)$", line):
                    errors.append(
                        _make_issue(
                            "backlog_checked_item",
                            rel_path,
                            f"{rel_path}:{lineno} completed checklist item must be deleted from active backlog",
                            f"{rel_path}|{line.strip()}",
                            seen_counts,
                        )
                    )
        return stale_items

    if mode != "table":
        errors.append(_make_issue("backlog_invalid_mode", rel_path, f"Unsupported backlog mode {mode!r}", rel_path, seen_counts))
        return stale_items

    id_re = re.compile(str(cfg.get("id_pattern", r"^[A-Z]+-\d+$")))
    pri_pat = cfg.get("priority_pattern")
    pri_re = re.compile(str(pri_pat)) if pri_pat else None
    allowed_statuses = set(cfg.get("allowed_statuses", ["OPEN", "BLOCKED", "VERIFYING"]))
    check_entrypoints = bool(cfg.get("check_entrypoints", True))

    seen_ids: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 6:
            continue
        if cells[0] == "ID" or set("".join(cells)).issubset({"-", ":", " "}):
            continue
        bid, pri, status, _item, entrypoints, reviewed = cells

        if not id_re.match(bid):
            errors.append(_make_issue("backlog_invalid_id", rel_path, f"{rel_path}:{lineno} invalid ID {bid!r}", f"{rel_path}|{bid}", seen_counts))
        elif bid in seen_ids:
            errors.append(_make_issue("backlog_duplicate_id", rel_path, f"{rel_path}:{lineno} duplicate ID {bid!r}", f"{rel_path}|{bid}", seen_counts))
        seen_ids.add(bid)

        if pri_re and not pri_re.match(pri):
            errors.append(_make_issue("backlog_invalid_priority", rel_path, f"{rel_path}:{lineno} invalid priority {pri!r}", f"{rel_path}|{bid}|{pri}", seen_counts))

        if status not in allowed_statuses:
            errors.append(
                _make_issue(
                    "backlog_invalid_status",
                    rel_path,
                    f"{rel_path}:{lineno} invalid status {status!r} (must be one of {sorted(allowed_statuses)}; delete closed rows)",
                    f"{rel_path}|{bid}|{status}",
                    seen_counts,
                )
            )

        try:
            reviewed_date = _dt.date.fromisoformat(reviewed)
            age_days = (today - reviewed_date).days
            if age_days > stale_days:
                msg = f"Doc-GC notice: {bid} in {rel_path} not reviewed for {age_days} days ({reviewed})"
                warnings.append(_make_issue("backlog_stale", rel_path, msg, f"{rel_path}|{bid}", seen_counts))
                stale_items.append({"id": bid, "path": rel_path, "reviewed": reviewed, "age_days": age_days})
        except ValueError:
            errors.append(_make_issue("backlog_invalid_date", rel_path, f"{rel_path}:{lineno} invalid Last-Reviewed date {reviewed!r}", f"{rel_path}|{bid}|date", seen_counts))

        if check_entrypoints:
            ep_items = [x.strip().strip("`") for x in entrypoints.split(",") if x.strip()]
            if not ep_items:
                errors.append(_make_issue("backlog_empty_entrypoint", rel_path, f"{rel_path}:{lineno} empty Entrypoint", f"{rel_path}|{bid}|ep", seen_counts))
            for ep in ep_items:
                if not (root / ep).exists():
                    errors.append(_make_issue("backlog_missing_entrypoint", rel_path, f"{rel_path}:{lineno} missing entrypoint {ep!r}", f"{rel_path}|{bid}|{ep}", seen_counts))

    return stale_items


def _check_plans_section(
    root: Path,
    cfg: dict[str, Any],
    errors: list[dict[str, str]],
    seen_counts: dict[str, int],
) -> list[dict[str, str]]:
    bad_plans: list[dict[str, str]] = []
    dir_rel = str(cfg.get("dir", "docs/plans"))
    plans_dir = root / dir_rel
    if not plans_dir.is_dir():
        return bad_plans

    name_re = re.compile(str(cfg.get("filename_pattern", r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")))
    status_re = re.compile(str(cfg.get("status_pattern", r"\bStatus:\s*(ACTIVE|PARTIAL)\b")))
    header_lines = int(cfg.get("header_lines", 10))

    for p in sorted(plans_dir.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(root).as_posix()
        if not name_re.match(p.name):
            errors.append(
                _make_issue(
                    "plan_invalid_filename",
                    rel,
                    f"Invalid plan filename in {dir_rel}/: {p.name}",
                    rel,
                    seen_counts,
                )
            )
            bad_plans.append({"path": rel, "reason": "invalid_filename"})
        head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:header_lines])
        if not status_re.search(head):
            errors.append(
                _make_issue(
                    "plan_missing_active_status",
                    rel,
                    f"{rel} must declare 'Status: ACTIVE' or 'Status: PARTIAL' in its top {header_lines} lines",
                    rel,
                    seen_counts,
                )
            )
            bad_plans.append({"path": rel, "reason": "non_active_status"})
    return bad_plans


def run_check(
    root: Path,
    *,
    config_path: Path | None = None,
    ratchet: bool = False,
    update_baseline: bool = False,
    baseline_path_override: Path | None = None,
    today: _dt.date | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    today = today or _dt.date.today()
    cfg_path = (config_path or (root / "zero-drift.toml")).resolve()

    def _config_error(msg: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "command": "check",
            "repo_root": str(root),
            "repo_sha": _repo_sha(root),
            "passed": False,
            "exit_code": 2,
            "metrics": {},
            "errors": [{"code": "config_error", "path": str(cfg_path), "message": msg, "fingerprint": f"config_error|{cfg_path.name}"}],
            "warnings": [],
        }

    if not cfg_path.is_file():
        return _config_error(f"Config file not found: {cfg_path}")
    try:
        cfg = load_toml(cfg_path)
    except (OSError, ValueError, Exception) as exc:
        return _config_error(f"Invalid TOML config {cfg_path}: {exc}")

    meta = cfg.get("meta", {})
    min_ver = meta.get("min_tool_version")
    if isinstance(min_ver, str) and _version_tuple(TOOL_VERSION) < _version_tuple(min_ver):
        return _config_error(f"zero_drift {TOOL_VERSION} is older than required min_tool_version {min_ver}")

    raw_errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    seen_counts: dict[str, int] = {}

    # 1. Scope: forbidden paths
    scope_cfg = cfg.get("scope", {})
    for rel in scope_cfg.get("forbid_paths", []):
        rel_str = str(rel).strip()
        if (root / rel_str).exists():
            raw_errors.append(
                _make_issue(
                    "forbid_path",
                    rel_str,
                    f"Forbidden path must not exist in HEAD: {rel_str}",
                    rel_str,
                    seen_counts,
                )
            )

    # 2. Entrypoint checks (lines + UTF-8 bytes)
    entry_cfg = cfg.get("entrypoint")
    entry_metrics: dict[str, Any] = {}
    if isinstance(entry_cfg, dict) and entry_cfg:
        ep_rel = str(entry_cfg.get("path", "AGENTS.md"))
        ep_path = root / ep_rel
        if not ep_path.is_file():
            raw_errors.append(_make_issue("entrypoint_missing", ep_rel, f"Missing {ep_rel}", ep_rel, seen_counts))
            entry_metrics = {"path": ep_rel, "exists": False, "lines": 0, "bytes": 0}
        else:
            raw_bytes = ep_path.read_bytes()
            line_count = len(raw_bytes.decode("utf-8", errors="replace").splitlines())
            byte_count = len(raw_bytes)
            entry_metrics = {"path": ep_rel, "exists": True, "lines": line_count, "bytes": byte_count}
            max_lines = entry_cfg.get("max_lines")
            max_bytes = entry_cfg.get("max_bytes")
            if isinstance(max_lines, int) and line_count > max_lines:
                raw_errors.append(
                    _make_issue(
                        "entrypoint_max_lines",
                        ep_rel,
                        f"{ep_rel} exceeds {max_lines} lines ({line_count})",
                        ep_rel,
                        seen_counts,
                    )
                )
            if isinstance(max_bytes, int) and byte_count > max_bytes:
                raw_errors.append(
                    _make_issue(
                        "entrypoint_max_bytes",
                        ep_rel,
                        f"{ep_rel} exceeds {max_bytes} bytes ({byte_count})",
                        ep_rel,
                        seen_counts,
                    )
                )

    # 3. Compat contracts (required files + anchors)
    compat_cfg = cfg.get("compat", {})
    for req_file in compat_cfg.get("required_files", []):
        rel_f = str(req_file)
        if not (root / rel_f).is_file():
            raw_errors.append(
                _make_issue("compat_file_missing", rel_f, f"Missing compat file {rel_f}", rel_f, seen_counts)
            )
    for req_anchor in compat_cfg.get("required_anchors", []):
        spec = str(req_anchor)
        file_part, _, anchor_id = spec.partition("#")
        fpath = root / file_part
        if not fpath.is_file():
            raw_errors.append(
                _make_issue("compat_anchor_file_missing", file_part, f"Missing compat anchor file {file_part}", spec, seen_counts)
            )
            continue
        ftext = fpath.read_text(encoding="utf-8", errors="replace")
        if f'id="{anchor_id}"' not in ftext and f"id='{anchor_id}'" not in ftext:
            raw_errors.append(
                _make_issue(
                    "compat_anchor_missing",
                    file_part,
                    f"{file_part} missing compat anchor id={anchor_id!r}",
                    spec,
                    seen_counts,
                )
            )

    # 4. ADR check + anchor collection
    adr_cfg = cfg.get("adr", {})
    adr_mode = str(adr_cfg.get("mode", "none"))
    adr_file: Path | None = None
    adr_anchors: set[str] = set()
    adr_link_re: re.Pattern[str] | None = None
    if adr_mode == "single-file":
        adr_file, adr_anchors, adr_link_re = _check_adr_single(root, adr_cfg, raw_errors, seen_counts)
    elif adr_mode == "directory":
        _check_adr_directory(root, adr_cfg, raw_errors, seen_counts)

    # 5. Relative Markdown links in scoped files
    include_globs = [str(g) for g in scope_cfg.get("include_globs", ["AGENTS.md", "README.md", "docs/**/*.md"])]
    exclude_globs = [str(g) for g in scope_cfg.get("exclude_globs", [])]
    scoped_md = _resolve_scope_files(root, include_globs, exclude_globs)

    for md_path in scoped_md:
        rel_src = md_path.relative_to(root).as_posix()
        text = md_path.read_text(encoding="utf-8", errors="replace")
        for href in _extract_md_links(text):
            if not href or href.startswith(EXTERNAL_SCHEMES):
                continue
            if href.startswith("#"):
                if (
                    adr_file is not None
                    and md_path.resolve() == adr_file.resolve()
                    and adr_link_re is not None
                ):
                    m = adr_link_re.fullmatch(href)
                    if m:
                        aid = m.group(1) if m.lastindex else m.group(0)
                        if aid not in adr_anchors:
                            raw_errors.append(
                                _make_issue(
                                    "broken_adr_anchor",
                                    rel_src,
                                    f"Broken ADR anchor in {rel_src}: {href}",
                                    f"{rel_src}|{href}",
                                    seen_counts,
                                )
                            )
                continue

            target_part, _, fragment = href.partition("#")
            if not target_part:
                continue
            cand = _is_broken_target(md_path, target_part)
            decoded = _is_broken_target(md_path, unquote(target_part))
            resolved: Path | None = None
            if cand is not None and cand.exists():
                resolved = cand
            elif decoded is not None and decoded.exists():
                resolved = decoded

            if resolved is None:
                raw_errors.append(
                    _make_issue(
                        "broken_relative_link",
                        rel_src,
                        f"Broken relative link in {rel_src}: {href}",
                        f"{rel_src}|{href}",
                        seen_counts,
                    )
                )
                continue

            if fragment and adr_file is not None and resolved == adr_file.resolve() and adr_link_re is not None:
                m = adr_link_re.fullmatch("#" + fragment)
                if m:
                    aid = m.group(1) if m.lastindex else m.group(0)
                    if aid not in adr_anchors:
                        raw_errors.append(
                            _make_issue(
                                "broken_adr_fragment",
                                rel_src,
                                f"Broken ADR fragment in {rel_src}: {href}",
                                f"{rel_src}|{href}",
                                seen_counts,
                            )
                        )

    # 6. Backlog & Plans state machines
    backlog_cfg = cfg.get("backlog")
    if isinstance(backlog_cfg, dict) and backlog_cfg:
        _check_backlog_section(root, backlog_cfg, today, raw_errors, warnings, seen_counts)

    plans_cfg = cfg.get("plans")
    if isinstance(plans_cfg, dict) and plans_cfg:
        _check_plans_section(root, plans_cfg, raw_errors, seen_counts)

    # 7. CodeGraph hygiene
    cg_cfg = cfg.get("codegraph", {})
    cg_enabled = cg_cfg.get("enabled", "auto")
    cg_db_rel = str(cg_cfg.get("db_path", ".codegraph/codegraph.db"))
    cg_prefixes = [str(p) for p in cg_cfg.get("forbid_prefixes", ["archive/"])]
    cg_stats: dict[str, Any] = {"present": False}
    if cg_enabled is not False and str(cg_enabled).lower() != "false":
        db_path = root / cg_db_rel
        if not db_path.is_file():
            if cg_enabled is True or str(cg_enabled).lower() == "true":
                raw_errors.append(
                    _make_issue(
                        "codegraph_missing",
                        cg_db_rel,
                        f"Missing CodeGraph database {cg_db_rel}",
                        cg_db_rel,
                        seen_counts,
                    )
                )
        else:
            cg_stats, cg_hits, cg_warn = _inspect_codegraph_db(db_path, cg_prefixes)
            if cg_warn:
                warnings.append(_make_issue("codegraph_inspect_warn", cg_db_rel, cg_warn, cg_db_rel, seen_counts))
            for table, norm, cnt in cg_hits:
                raw_errors.append(
                    _make_issue(
                        "codegraph_polluted",
                        cg_db_rel,
                        f"{cg_db_rel} table {table} contains {cnt} stale {norm} rows; run 'codegraph index'",
                        f"{table}|{norm}",
                        seen_counts,
                    )
                )

    # 8. Ratchet / baseline handling
    ratchet_cfg = cfg.get("ratchet", {})
    baseline_rel = str(baseline_path_override or ratchet_cfg.get("baseline_file", ".zero-drift-baseline.json"))
    baseline_path = Path(baseline_rel) if Path(baseline_rel).is_absolute() else (root / baseline_rel)
    use_ratchet = ratchet or bool(ratchet_cfg.get("enabled", False))

    if update_baseline:
        fps = sorted({e["fingerprint"] for e in raw_errors})
        payload = {
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fingerprints": fps,
        }
        baseline_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "command": "check",
            "mode": "update-baseline",
            "repo_root": str(root),
            "repo_sha": _repo_sha(root),
            "passed": True,
            "exit_code": 0,
            "metrics": {
                "scoped_markdown_files": len(scoped_md),
                "entrypoint": entry_metrics,
                "baseline_file": str(baseline_path),
                "baseline_recorded": len(fps),
            },
            "errors": [],
            "warnings": warnings,
        }

    suppressed: list[dict[str, str]] = []
    resolved_from_baseline: list[str] = []
    active_errors = raw_errors
    mode_label = "strict"

    if use_ratchet:
        mode_label = "ratchet"
        if not baseline_path.is_file():
            return _config_error(f"Ratchet enabled but baseline file missing: {baseline_path}")
        try:
            bl_data = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline_fps = set(bl_data.get("fingerprints", []))
        except (OSError, ValueError, TypeError) as exc:
            return _config_error(f"Invalid baseline file {baseline_path}: {exc}")

        seen_fps = {e["fingerprint"] for e in raw_errors}
        suppressed = [e for e in raw_errors if e["fingerprint"] in baseline_fps]
        active_errors = [e for e in raw_errors if e["fingerprint"] not in baseline_fps]
        resolved_from_baseline = sorted(baseline_fps - seen_fps)

    passed = len(active_errors) == 0
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "command": "check",
        "mode": mode_label,
        "repo_root": str(root),
        "repo_sha": _repo_sha(root),
        "passed": passed,
        "exit_code": 0 if passed else 1,
        "metrics": {
            "scoped_markdown_files": len(scoped_md),
            "entrypoint": entry_metrics,
            "error_count": len(active_errors),
            "warning_count": len(warnings),
            "suppressed_count": len(suppressed),
            "resolved_from_baseline_count": len(resolved_from_baseline),
            "codegraph": cg_stats,
        },
        "errors": active_errors,
        "warnings": warnings,
    }
    if use_ratchet:
        result["suppressed_by_baseline"] = suppressed
        result["resolved_from_baseline"] = resolved_from_baseline
    return result


# ---------------------------------------------------------------------------
# Subcommand: gc
# ---------------------------------------------------------------------------

def run_gc(
    root: Path,
    *,
    config_path: Path | None = None,
    today: _dt.date | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    today = today or _dt.date.today()
    cfg_path = (config_path or (root / "zero-drift.toml")).resolve()
    cfg: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            cfg = load_toml(cfg_path)
        except (OSError, ValueError, Exception) as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "tool_version": TOOL_VERSION,
                "command": "gc",
                "repo_root": str(root),
                "repo_sha": _repo_sha(root),
                "passed": False,
                "exit_code": 2,
                "metrics": {},
                "errors": [{"code": "config_error", "path": str(cfg_path), "message": str(exc), "fingerprint": f"config_error|{cfg_path.name}"}],
                "warnings": [],
            }

    stale_days = int(cfg.get("backlog", {}).get("stale_days", 30))
    dummy_errors: list[dict[str, str]] = []
    dummy_warnings: list[dict[str, str]] = []
    seen_counts: dict[str, int] = {}

    stale_backlog: list[dict[str, Any]] = []
    backlog_cfg = cfg.get("backlog")
    if isinstance(backlog_cfg, dict) and backlog_cfg:
        stale_backlog = _check_backlog_section(root, backlog_cfg, today, dummy_errors, dummy_warnings, seen_counts)

    stale_plans: list[dict[str, str]] = []
    plans_cfg = cfg.get("plans")
    if isinstance(plans_cfg, dict) and plans_cfg:
        stale_plans = _check_plans_section(root, plans_cfg, dummy_errors, seen_counts)

    audit_res = run_audit(root, today=today)
    oldest = audit_res["metrics"]["engineering_staleness"]["oldest_sample"]
    stale_docs = [item for item in oldest if item["age_days"] > stale_days]

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "command": "gc",
        "repo_root": str(root),
        "repo_sha": _repo_sha(root),
        "passed": True,
        "exit_code": 0,
        "metrics": {
            "stale_threshold_days": stale_days,
            "stale_backlog_count": len(stale_backlog),
            "non_active_plans_count": len(stale_plans),
            "stale_engineering_docs_count": len(stale_docs),
        },
        "candidates": {
            "backlog": stale_backlog,
            "plans": stale_plans,
            "engineering_docs": stale_docs,
        },
        "errors": [],
        "warnings": dummy_warnings,
    }


# ---------------------------------------------------------------------------
# Human / JSON CLI Entrypoint
# ---------------------------------------------------------------------------

def _print_human_audit(res: dict[str, Any]) -> None:
    m = res["metrics"]
    print(f"AUDIT zero-drift v{TOOL_VERSION} root={res['repo_root']} sha={res['repo_sha']}")
    for name, b in m["markdown_buckets"].items():
        print(f"  bucket[{name}]: files={b['files']} lines={b['lines']} bytes={b['bytes']}")
    ep = m["entrypoint"]
    print(f"  entrypoint[{ep['path']}]: exists={ep['exists']} lines={ep['lines']} bytes={ep['bytes']}")
    print(f"  broken_engineering_links: {m['broken_engineering_links_count']}")
    for sample in m["broken_engineering_links_sample"][:10]:
        print(f"    - {sample['source']}: {sample['href']}")
    st = m["engineering_staleness"]
    print(f"  staleness: >30d={st['over_30d']} >60d={st['over_60d']}")
    if m["git_churn_last_50"]:
        ch = m["git_churn_last_50"]
        print(
            f"  churn(last {ch['commits_sampled']}): code={ch['code_commits']} "
            f"doc_only={ch['doc_only_commits']} ({ch['doc_only_ratio']*100:.1f}%) "
            f"avg_md_per_code={ch['avg_md_per_code_commit']}"
        )
    if m["head_tree"]:
        ht = m["head_tree"]
        print(f"  head_tree: total={ht['total_bytes']}B archive={ht['archive_bytes']}B ({ht['archive_share']*100:.1f}%)")
    cg = m["codegraph"]
    if cg.get("present"):
        print(f"  codegraph: files={cg['total_files']} nodes={cg['total_nodes']} hits={cg['forbidden_hits']}")


def _print_human_check(res: dict[str, Any], *, gc_report: bool) -> None:
    if gc_report:
        for w in res["warnings"]:
            print(f"WARN: {w['message']}", file=sys.stderr)
    if res["exit_code"] != 0:
        for e in res["errors"]:
            print(f"FAIL: {e['message']}", file=sys.stderr)
        return
    m = res["metrics"]
    if res.get("mode") == "update-baseline":
        print(f"OK: baseline updated ({m.get('baseline_recorded', 0)} fingerprints -> {m.get('baseline_file')}).")
        return
    extra = ""
    if res.get("mode") == "ratchet":
        extra = f", ratchet suppressed={m['suppressed_count']}, resolved={m['resolved_from_baseline_count']}"
    print(f"OK: zero-drift check passed ({m['scoped_markdown_files']} scoped docs{extra}).")


def _print_human_gc(res: dict[str, Any]) -> None:
    m = res["metrics"]
    c = res["candidates"]
    print(f"GC candidates (threshold >{m['stale_threshold_days']}d):")
    print(f"  backlog_stale: {m['stale_backlog_count']}")
    for item in c["backlog"]:
        print(f"    - {item['id']} ({item['reviewed']}, {item['age_days']}d)")
    print(f"  non_active_plans: {m['non_active_plans_count']}")
    for item in c["plans"]:
        print(f"    - {item['path']} ({item['reason']})")
    print(f"  stale_engineering_docs: {m['stale_engineering_docs_count']}")
    for item in c["engineering_docs"]:
        print(f"    - {item['path']} ({item['age_days']}d)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zero_drift",
        description="Config-driven documentation & AI context hygiene harness.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Zero-config read-only repository baseline audit")
    p_audit.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root (default: cwd)")
    p_audit.add_argument("--json", action="store_true", help="Emit deterministic JSON receipt")

    p_check = sub.add_parser("check", help="Validate repository against zero-drift.toml")
    p_check.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root (default: cwd)")
    p_check.add_argument("--config", type=Path, default=None, help="Config path (default: <root>/zero-drift.toml)")
    p_check.add_argument("--ratchet", action="store_true", help="Allow baseline errors, fail only on new drift")
    p_check.add_argument("--update-baseline", action="store_true", help="Write current failures into ratchet baseline")
    p_check.add_argument("--baseline-file", type=Path, default=None, help="Override ratchet baseline file path")
    p_check.add_argument("--gc-report", action="store_true", help="Print non-fatal Doc-GC notices to stderr")
    p_check.add_argument("--json", action="store_true", help="Emit deterministic JSON receipt")

    p_gc = sub.add_parser("gc", help="List stale docs, stale backlog rows, and closed plans")
    p_gc.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root (default: cwd)")
    p_gc.add_argument("--config", type=Path, default=None, help="Config path (default: <root>/zero-drift.toml)")
    p_gc.add_argument("--json", action="store_true", help="Emit deterministic JSON receipt")

    args = parser.parse_args(argv)

    if args.command == "audit":
        res = run_audit(args.root)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            _print_human_audit(res)
        return res["exit_code"]

    if args.command == "check":
        res = run_check(
            args.root,
            config_path=args.config,
            ratchet=args.ratchet,
            update_baseline=args.update_baseline,
            baseline_path_override=args.baseline_file,
        )
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            _print_human_check(res, gc_report=args.gc_report)
        return res["exit_code"]

    if args.command == "gc":
        res = run_gc(args.root, config_path=args.config)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            if res["exit_code"] != 0:
                for e in res["errors"]:
                    print(f"FAIL: {e['message']}", file=sys.stderr)
            else:
                _print_human_gc(res)
        return res["exit_code"]

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
