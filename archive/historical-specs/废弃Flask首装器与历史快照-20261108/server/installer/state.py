"""Persistent task facts; authentication material is never accepted by this store."""

import contextlib
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

ACTIVE = (
    "queued",
    "running",
    "verifying",
    "reconciling",
    "awaiting_credentials",
    "needs_attention",
)


class Problem(Exception):
    def __init__(self, code, message, status=400, detail=None):
        self.code, self.message, self.status, self.detail = (
            code,
            message,
            status,
            detail,
        )
        super().__init__(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "tasks.sqlite3"
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
              state TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '', request TEXT NOT NULL,
              request_key TEXT UNIQUE, digest TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
              error_code TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              job_id TEXT NOT NULL REFERENCES jobs(id), seq INTEGER NOT NULL,
              stage TEXT NOT NULL, message TEXT NOT NULL, created REAL NOT NULL,
              PRIMARY KEY(job_id, seq));
            CREATE UNIQUE INDEX IF NOT EXISTS one_install_per_target ON jobs(target)
              WHERE kind='install' AND state IN
              ('queued','running','verifying','reconciling','awaiting_credentials','needs_attention');
            """)
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, kind, request, key=None):
        raw = canonical(request)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        # Reject accidental secret persistence even if a future API caller bypasses normalization.
        if any(
            k in request
            for k in (
                "password",
                "private_key",
                "passphrase",
                "admin_password",
                "sub_token",
            )
        ):
            raise ValueError("Secrets cannot enter the task store")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if key:
                row = db.execute(
                    "SELECT * FROM jobs WHERE request_key=?", (key,)
                ).fetchone()
                if row:
                    if row["digest"] != digest:
                        raise Problem(
                            "IDEMPOTENCY_CONFLICT", "同一提交标识对应了不同内容。", 409
                        )
                    return row["id"], False
            if kind == "install":
                row = db.execute(
                    "SELECT id FROM jobs WHERE kind='install' AND target=? AND state IN (%s)"
                    % ",".join("?" * len(ACTIVE)),
                    (request["target_key"], *ACTIVE),
                ).fetchone()
                if row:
                    raise Problem(
                        "TARGET_BUSY",
                        "这台服务器已有未结束任务，请继续原任务。",
                        409,
                        {"job_id": row["id"]},
                    )
            jid, now = uuid.uuid4().hex, time.time()
            db.execute(
                "INSERT INTO jobs(id,kind,target,state,request,request_key,digest,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    jid,
                    kind,
                    request["target_key"],
                    "queued",
                    raw,
                    key,
                    digest,
                    now,
                    now,
                ),
            )
            return jid, True

    def get(self, jid):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise Problem("NOT_FOUND", "任务不存在。", 404)
            data = dict(row)
            data["request"], data["result"] = (
                json.loads(data["request"]),
                json.loads(data["result"]),
            )
            data["events"] = [
                dict(x)
                for x in db.execute(
                    "SELECT seq,stage,message FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 30",
                    (jid,),
                ).fetchall()
            ][::-1]
            return data

    def update(self, jid, state, stage, message, result=None, error=None):
        # message is an application constant; raw SSH/installer output never reaches this method.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            fields = "state=?,stage=?,updated=?,error_code=?"
            values = [state, stage, time.time(), error]
            if result is not None:
                fields += ",result=?"
                values.append(canonical(result))
            db.execute("UPDATE jobs SET " + fields + " WHERE id=?", (*values, jid))
            seq = db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE job_id=?", (jid,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO events VALUES(?,?,?,?,?)",
                (jid, seq, stage, message, time.time()),
            )
            db.execute("DELETE FROM events WHERE job_id=? AND seq<=?", (jid, seq - 200))

    def next(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM jobs WHERE state='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE jobs SET state='running',updated=? WHERE id=?",
                    (time.time(), row["id"]),
                )
                return row["id"]

    def recover(self):
        with self.db() as db:
            rows = db.execute(
                "SELECT id FROM jobs WHERE state IN ('running','verifying','reconciling','queued')"
            ).fetchall()
        for row in rows:
            self.update(
                row["id"],
                "awaiting_credentials",
                "reconcile",
                "执行器已重启，请重新提供 SSH 登录信息以复查原任务。",
            )
