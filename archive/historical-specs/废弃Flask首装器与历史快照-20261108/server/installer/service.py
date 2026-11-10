"""Single-owner installation API and an independently supervised, single worker."""

import fcntl
import json
import os
import re
import secrets
import socket
import socketserver
import struct
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

from . import downloads, provision, tencent_discovery
from .state import Problem, Store
from .transport import SSH, credentials, inspect, normalize

DEPENDENCY_MESSAGES = {
    81: "系统软件源暂不可用，请检查网络后复查原任务。",
    82: "Caddy 安装来源暂不可用，请检查网络后复查原任务。",
    83: "sing-box 安装包不可用或校验失败，请检查网络后复查原任务。",
}


class Config:
    def __init__(self, path):
        self.raw = json.loads(Path(path).read_text())
        self.data = Path(self.raw["data_dir"]).resolve()
        self.source = Path(self.raw["source_dir"]).resolve()
        self.origin = self.raw["origin"].rstrip("/")
        self.dev = self.raw.get("development", False)
        parsed = urlsplit(self.origin)
        if parsed.scheme != "https" and not (
            self.dev and parsed.hostname in ("localhost", "127.0.0.1")
        ):
            raise ValueError(
                "A trusted HTTPS origin is required outside explicit localhost development"
            )
        if not self.raw.get("auth_hash") or len(self.raw.get("csrf_key", "")) < 32:
            raise ValueError("Authentication and CSRF configuration are required")
        self.store = Store(self.data)
        self.socket = str(self.data / "worker.sock")
        self.allowed = self.raw.get("allowed_targets", [])
        if not self.dev and (
            self.raw.get("tls_ca_file") or self.raw.get("verification_url")
        ):
            raise ValueError(
                "Test delivery overrides are restricted to development mode"
            )


def recv(sock, count):
    out = bytearray()
    while len(out) < count:
        part = sock.recv(count - len(out))
        if not part:
            raise ConnectionError("incomplete message")
        out.extend(part)
    return bytes(out)


def receive(sock):
    size = struct.unpack("!I", recv(sock, 4))[0]
    if size > 262144:
        raise ValueError("message too large")
    return json.loads(recv(sock, size))


def send(sock, value):
    data = json.dumps(value).encode()
    sock.sendall(struct.pack("!I", len(data)) + data)


def rpc(config, method, body):
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(15)
            sock.connect(config.socket)
            send(sock, {"method": method, "body": body})
            answer = receive(sock)
    except (OSError, ValueError, ConnectionError):
        raise Problem(
            "WORKER_UNAVAILABLE", "安装执行器暂不可用，请稍后查询原任务。", 503
        ) from None
    if "error" in answer:
        error = answer["error"]
        raise Problem(
            error["code"],
            error["message"],
            error.get("status", 400),
            error.get("detail"),
        )
    return answer


def public(job):
    result = {
        k: job[k]
        for k in (
            "id",
            "kind",
            "state",
            "stage",
            "result",
            "error_code",
            "created",
            "updated",
            "events",
        )
    }
    result["target"] = {
        k: job["request"].get(k) for k in ("host", "ssh_port", "username")
    }
    return result


def create_app(config):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 150000
    signer = URLSafeTimedSerializer(config.raw["csrf_key"], salt="installer-csrf")

    @app.before_request
    def authenticate():
        auth = request.authorization
        if (
            not auth
            or auth.username != config.raw.get("auth_user", "admin")
            or not check_password_hash(config.raw["auth_hash"], auth.password or "")
        ):
            return (
                jsonify(code="AUTH_REQUIRED", message="请先登录安装入口。"),
                401,
                {"WWW-Authenticate": 'Basic realm="OwnLine installer"'},
            )
        if (
            not config.dev
            and request.headers.get("X-Forwarded-Proto", request.scheme) != "https"
        ):
            raise Problem("HTTPS_REQUIRED", "请通过可信 HTTPS 安装入口访问。", 403)
        if request.method == "POST":
            if request.headers.get("Origin") != config.origin or not request.is_json:
                raise Problem("ORIGIN_REJECTED", "请求来源或内容类型不符合要求。", 403)
            try:
                if (
                    signer.loads(request.headers.get("X-CSRF-Token", ""), max_age=1800)
                    != "single-owner"
                ):
                    raise BadSignature("invalid")
            except BadSignature:
                raise Problem(
                    "CSRF_REJECTED", "页面验证已过期，请刷新后继续原任务。", 403
                ) from None
            if not isinstance(request.get_json(), dict):
                raise Problem("INVALID_BODY", "请求内容必须为对象。")

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(Problem)
    def problem(error):
        return jsonify(
            code=error.code, message=error.message, detail=error.detail
        ), error.status

    @app.errorhandler(400)
    def invalid(_):
        return jsonify(code="INVALID_BODY", message="请求内容不是有效 JSON 对象。"), 400

    @app.errorhandler(413)
    def large(_):
        return jsonify(code="BODY_TOO_LARGE", message="输入内容过大。"), 413

    @app.get("/")
    def page():
        return send_from_directory(config.source / "web", "setup.html")

    @app.get("/setup.<extension>")
    def static(extension):
        if extension not in ("js", "css"):
            raise Problem("NOT_FOUND", "文件不存在。", 404)
        return send_from_directory(config.source / "web", "setup." + extension)

    @app.get("/<string:filename>")
    def web_asset(filename):
        allowed = ("qr-sub.png", "icon.png", "quota.json", "usage.json", "status.json")
        if filename in allowed:
            file_path = config.source / "web" / filename
            if file_path.exists():
                return send_from_directory(config.source / "web", filename)
            return jsonify({})
        raise Problem("NOT_FOUND", "文件不存在。", 404)

    @app.get("/api/setup")
    def setup():
        return jsonify(
            csrf_token=signer.dumps("single-owner"),
            scope="fresh-linux-controller",
            development=config.dev,
        )

    @app.get("/api/logs")
    def get_logs():
        try:
            from server.nodekit import logger
            limit = min(int(request.args.get("limit", 80)), 200)
            lvl = request.args.get("level")
            src = request.args.get("src")
            return jsonify(logs=logger.read_logs(limit=limit, level_filter=lvl, src_filter=src))
        except Exception:
            return jsonify(logs=[])

    @app.post("/api/checks")
    def check():
        body = request.get_json()
        target = normalize(body, config.allowed)
        secret = credentials(body)
        release, archive = provision.bundle(config.source, config.data)
        return jsonify(
            rpc(
                config,
                "check",
                {
                    "target": target,
                    "secret": secret,
                    "release_id": release,
                    "archive": archive,
                },
            )
        ), 202

    @app.post("/api/tencent/instances")
    def tencent_instances():
        body = request.get_json()
        return jsonify(tencent_discovery.discover(body.get("secret_id"), body.get("secret_key")))

    @app.post("/api/tencent/resetpw")
    def tencent_resetpw():
        body = request.get_json()
        return jsonify(
            tencent_discovery.reset_password(
                body.get("secret_id"),
                body.get("secret_key"),
                body.get("instance_id"),
                body.get("region_id"),
            )
        )

    @app.get("/api/jobs/<jid>")
    def job(jid):
        return jsonify(public(config.store.get(jid)))

    @app.post("/api/jobs")
    def install():
        body = request.get_json()
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key):
            raise Problem("IDEMPOTENCY_REQUIRED", "缺少有效提交标识。")
        checked = config.store.get(str(body.get("check_job_id", "")))
        if checked["kind"] != "check" or checked["state"] != "succeeded":
            raise Problem("CHECK_REQUIRED", "请先完成只读连接检查。", 409)
        if body.get("confirm_install") is not True:
            raise Problem(
                "CONFIRMATION_REQUIRED", "请确认安装目标和完整安装范围。", 409
            )
        req = dict(checked["request"])
        # Resolve and bind again immediately before creating a task; DNS changes require a new check.
        target = normalize(
            {
                "host": req["host"],
                "ssh_port": req["ssh_port"],
                "username": req["username"],
                "fingerprint": checked["result"]["fingerprint"],
            },
            config.allowed,
        )
        if target["address"] != req["address"]:
            raise Problem("TARGET_CHANGED", "目标地址发生变化，请重新检查。", 409)
        domain = (
            str(body.get("domain") or req["address"].replace(".", "-") + ".sslip.io")
            .lower()
            .strip()
        )
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]", domain):
            raise Problem("INVALID_DOMAIN", "管理页域名格式不正确。")
        req.update(
            fingerprint=checked["result"]["fingerprint"],
            machine_id=checked["result"]["machine_id"],
            check_job_id=checked["id"],
            domain=domain,
        )
        # Deduplication happens before TTL checks so a delayed retry still returns its original task.
        jid, created = config.store.create("install", req, key)
        if created and time.time() > checked["result"]["expires_at"]:
            config.store.update(
                jid,
                "failed",
                "check",
                "检查结果已过期，请重新检查。",
                error="CHECK_EXPIRED",
            )
            raise Problem("CHECK_EXPIRED", "检查结果已过期，请重新检查。", 409)
        return jsonify(job_id=jid, reused=not created), 202

    @app.post("/api/jobs/<jid>/credentials")
    def renew(jid):
        body = request.get_json()
        return jsonify(
            rpc(
                config,
                "renew",
                {
                    "job_id": jid,
                    "secret": credentials(body),
                    "reset_delivery": body.get("reset_delivery_password") is True,
                },
            )
        ), 202

    @app.get("/api/jobs/<jid>/delivery")
    def delivery(jid):
        config.store.get(jid)
        return jsonify(rpc(config, "delivery", {"job_id": jid}))

    return app


class Worker:
    def __init__(self, config):
        self.config, self.store = config, config.store
        self.secrets, self.deliveries = {}, {}
        self.lock = threading.RLock()
        self.stopped = threading.Event()

    def keep(self, secret):
        with self.lock:
            now = time.time()
            self.secrets = {k: v for k, v in self.secrets.items() if v[0] > now}
            if len(self.secrets) >= 32:
                raise Problem("TOO_MANY_CHECKS", "待处理连接过多，请稍后重试。", 429)
            ref = secrets.token_hex(24)
            self.secrets[ref] = (now + 600, secret)
            return ref

    def prune(self):
        with self.lock:
            now = time.time()
            self.secrets = {k: v for k, v in self.secrets.items() if v[0] > now}
            self.deliveries = {
                k: v
                for k, v in self.deliveries.items()
                if v.get("expires", now + 1) > now
            }

    def take(self, ref):
        with self.lock:
            entry = self.secrets.get(ref)
            if not entry or entry[0] < time.time():
                raise Problem(
                    "CREDENTIALS_EXPIRED", "临时登录信息已失效，请重新输入。", 409
                )
            return dict(entry[1])

    def dispatch(self, method, body):
        if method == "check":
            req = dict(body["target"])
            req.update(
                credential_ref=self.keep(body["secret"]),
                release_id=body["release_id"],
                archive=body["archive"],
            )
            jid, _ = self.store.create("check", req)
            return {"job_id": jid}
        if method == "renew":
            job = self.store.get(body["job_id"])
            if job["state"] in ("queued", "running", "verifying"):
                raise Problem("TASK_RUNNING", "原任务仍在执行，请先查询状态。", 409)
            req = job["request"]
            req.update(
                credential_ref=self.keep(body["secret"]),
                reconcile=True,
                reset_delivery=bool(body["reset_delivery"]),
            )
            with self.store.db() as db:
                db.execute(
                    "UPDATE jobs SET request=? WHERE id=?", (json.dumps(req), job["id"])
                )
            self.store.update(
                job["id"], "queued", "reconcile", "已收到登录信息，正在复查原任务。"
            )
            return {"job_id": job["id"]}
        if method == "delivery":
            job = self.store.get(body["job_id"])
            with self.lock:
                item = self.deliveries.get(job["id"])
                if not item or item.get("expires", 0) < time.time():
                    raise Problem(
                        "DELIVERY_UNAVAILABLE",
                        "交付信息已失效；请重新提供 SSH 登录信息并明确确认恢复网页登录信息。",
                        409,
                    )
                if job["state"] != "succeeded":
                    raise Problem("DELIVERY_NOT_READY", "服务尚未通过完整验证。", 409)
                return {
                    k: item[k]
                    for k in (
                        "management_url",
                        "username",
                        "password",
                        "subscription_url",
                    )
                }
        raise Problem("INVALID_OPERATION", "不支持此操作。")

    def run_one(self, jid):
        job = self.store.get(jid)
        req = job["request"]
        ssh = None
        try:
            secret = self.take(req["credential_ref"])
            ssh = SSH(req, secret)
            if job["kind"] == "check":
                result = inspect(ssh)
                result["expires_at"] = time.time() + 300
                result["target"] = req["host"]
                if result.get("os") == "windows":
                    message = (
                        "检测到 Windows 和运行中的 sing-box；现有服务未改动。"
                        if result.get("singbox_running") else
                        "检测到 Windows；现有服务未改动。"
                    )
                    raise Problem(
                        "WINDOWS_NODE_UNSUPPORTED",
                        message + "当前入口只支持安装 Linux 管理端，Windows 节点自动接入尚未实现。",
                        422,
                        result,
                    )
                if not result["compatible"]:
                    raise Problem(
                        "INCOMPATIBLE",
                        "本轮首次安装要求 root、Debian/Ubuntu、systemd、受支持架构及足够磁盘。",
                        422,
                        result,
                    )
                if result["existing"]:
                    raise Problem(
                        "EXISTING_INSTALLATION",
                        "检测到已有配置，本轮最小闭环不会覆盖或接管它。",
                        409,
                        result,
                    )
                self.store.update(
                    jid,
                    "succeeded",
                    "checked",
                    "只读检查通过，等待你确认开始安装。",
                    result,
                )
                return
            snapshot = inspect(ssh)
            if (
                snapshot["machine_id"] != req["machine_id"]
                or ssh.fingerprint != req["fingerprint"]
            ):
                raise Problem(
                    "IDENTITY_CHANGED", "服务器身份与已确认目标不同，请重新核对。", 409
                )
            state = provision.status(ssh, jid)
            with self.lock:
                delivery = self.deliveries.get(jid)
            if state["state"] == "not_started":
                if snapshot["existing"]:
                    raise Problem(
                        "TARGET_CHANGED",
                        "连接检查后目标出现已有配置，安装已停止。",
                        409,
                    )
                if not snapshot["compatible"]:
                    raise Problem("INCOMPATIBLE", "目标已不满足本轮安装条件。", 422)
                delivery = provision.fresh_delivery()
                delivery["expires"] = time.time() + 3600
                with self.lock:
                    self.deliveries[jid] = delivery
                self.store.update(
                    jid,
                    "running",
                    "prepare",
                    "正在准备安装资源；需要时自动使用镜像或缓存。",
                )
                prepared = {}
                if not snapshot.get("singbox_installed"):
                    prepared["sing-box"] = downloads.prepare(
                        ssh,
                        "sing-box",
                        snapshot["architecture"],
                        self.config.source,
                        self.config.data,
                    )
                if not snapshot.get("caddy_installed"):
                    prepared["caddy"] = downloads.prepare(
                        ssh,
                        "caddy",
                        snapshot["architecture"],
                        self.config.source,
                        self.config.data,
                        required=False,
                    )
                self.store.update(
                    jid,
                    "running",
                    "prepare",
                    "安装资源已准备，正在启动目标机上的独立安装任务。",
                )
                provision.deploy(
                    ssh,
                    jid,
                    req,
                    req["archive"],
                    delivery,
                    tls_internal=self.config.dev
                    and self.config.raw.get("test_internal_tls", False),
                    prepared=prepared,
                )
            elif state["state"] == "failed" and state.get("exit_code") in (81, 82, 83):
                if not req.get("reconcile"):
                    raise Problem(
                        "DEPENDENCY_UNAVAILABLE",
                        DEPENDENCY_MESSAGES[state["exit_code"]],
                        503,
                    )
                # Before node configuration no management credential has been published.
                if not delivery:
                    delivery = provision.fresh_delivery()
                    delivery["expires"] = time.time() + 3600
                    with self.lock:
                        self.deliveries[jid] = delivery
                self.store.update(
                    jid, "running", "prepare", "正在重新准备安装资源并核对原任务。"
                )
                prepared = {}
                if not snapshot.get("singbox_installed"):
                    prepared["sing-box"] = downloads.prepare(
                        ssh,
                        "sing-box",
                        snapshot["architecture"],
                        self.config.source,
                        self.config.data,
                    )
                if not snapshot.get("caddy_installed"):
                    prepared["caddy"] = downloads.prepare(
                        ssh,
                        "caddy",
                        snapshot["architecture"],
                        self.config.source,
                        self.config.data,
                        required=False,
                    )
                provision.start(
                    ssh,
                    jid,
                    req,
                    delivery,
                    tls_internal=self.config.dev
                    and self.config.raw.get("test_internal_tls", False),
                    prepared=prepared,
                    resume=True,
                )
            deadline = time.monotonic() + 1800
            stage = None
            while True:
                state = provision.status(ssh, jid)
                if state.get("stage") != stage:
                    stage = state.get("stage")
                    self.store.update(
                        jid,
                        "running",
                        "install",
                        "目标正在执行安装阶段 %s/10。" % stage,
                    )
                if state["state"] == "installed":
                    break
                if state["state"] in ("failed", "interrupted"):
                    if state.get("exit_code") in (81, 82, 83):
                        raise Problem(
                            "DEPENDENCY_UNAVAILABLE",
                            DEPENDENCY_MESSAGES[state["exit_code"]],
                            503,
                        )
                    raise Problem(
                        "REMOTE_INTERRUPTED",
                        "目标安装中断；已保留原任务，请核对失败阶段，未自动重装。",
                        409,
                    )
                if time.monotonic() > deadline:
                    raise Problem(
                        "PROGRESS_UNKNOWN",
                        "等待超时，请复查原任务；目标安装可能仍在执行。",
                        503,
                    )
                if self.stopped.wait(1):
                    return
            if state.get("quota_paused"):
                raise Problem(
                    "QUOTA_PROTECTED",
                    "目标处于流量保护状态，不能将代理重新启动或报告服务可用。",
                    409,
                )
            if any(
                state["services"].get(name) != "active"
                for name in ("admin", "caddy", "sing-box")
            ):
                raise Problem(
                    "SERVICES_UNAVAILABLE", "安装完成，但目标服务未全部可用。", 409
                )
            if not delivery:
                if not req.get("reset_delivery"):
                    raise Problem(
                        "DELIVERY_CONFIRMATION",
                        "目标安装已完成。交付密码因执行器重启丢失，请明确确认恢复网页登录信息。",
                        409,
                    )
                delivery = provision.fresh_delivery()
                provision.reset_delivery(ssh, jid, delivery["password"])
                with self.lock:
                    self.deliveries[jid] = delivery
            delivery["sub_token"] = state["sub_token"]
            url = (
                self.config.raw.get("verification_url")
                or "https://" + req["domain"] + ":8443/"
            )
            self.store.update(
                jid, "verifying", "verify", "正在验证 HTTPS、网页登录保护和订阅。"
            )
            verified = False
            for _ in range(30):
                try:
                    sub = provision.verify(
                        url, delivery, self.config.raw.get("tls_ca_file")
                    )
                    verified = True
                    break
                except (Problem, OSError):
                    if self.stopped.wait(2):
                        return
            if not verified:
                raise Problem(
                    "DELIVERY_NOT_VERIFIED",
                    "HTTPS、登录或订阅验证未完成。原安装不会重跑，请检查域名、证书及网络后复查。",
                    409,
                )
            try:
                cleaned = bool(provision.cleanup(ssh, jid).get("ok"))
            except (Problem, OSError):
                cleaned = False
            delivery.update(
                management_url=url, subscription_url=sub, expires=time.time() + 1800
            )
            self.store.update(
                jid,
                "succeeded",
                "delivered",
                "管理网页与订阅已验证，请打开后确认。",
                {
                    "management_url": url,
                    "username": "admin",
                    "node_count": state.get("nodes", 0),
                    "installation_cache_cleaned": cleaned,
                    "verification_scope": "isolated-test-ca"
                    if self.config.dev
                    else "public-trust",
                },
            )
            with self.lock:
                self.secrets.pop(req["credential_ref"], None)
        except Problem as error:
            if error.code in ("CREDENTIALS_EXPIRED",):
                new_state = "awaiting_credentials"
            elif job["kind"] == "check":
                new_state = (
                    "needs_attention"
                    if error.code == "HOST_KEY_CONFIRMATION"
                    else "failed"
                )
            else:
                new_state = "needs_attention"
            self.store.update(
                jid,
                new_state,
                "attention",
                error.message,
                error.detail or {},
                error.code,
            )
        except Exception:
            self.store.update(
                jid,
                "needs_attention",
                "reconcile",
                "执行状态暂时无法确认，请重新提供登录信息复查原任务。",
                error="EXECUTION_UNKNOWN",
            )
        finally:
            if ssh:
                ssh.close()

    def run(self):
        config = self.config
        lock_file = open(config.data / "worker.lock", "a")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A worker is already running")
        self.store.recover()
        Path(config.socket).unlink(missing_ok=True)
        worker = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(15)
                try:
                    data = receive(self.request)
                    answer = worker.dispatch(data["method"], data["body"])
                except Problem as error:
                    answer = {
                        "error": {
                            "code": error.code,
                            "message": error.message,
                            "status": error.status,
                            "detail": error.detail,
                        }
                    }
                except Exception:
                    answer = {
                        "error": {
                            "code": "WORKER_ERROR",
                            "message": "执行器请求未完成。",
                            "status": 503,
                        }
                    }
                send(self.request, answer)

        server = socketserver.ThreadingUnixStreamServer(config.socket, Handler)
        server.daemon_threads = True
        os.chmod(config.socket, 0o600)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            while not self.stopped.is_set():
                self.prune()
                jid = self.store.next()
                if jid:
                    self.run_one(jid)
                else:
                    self.stopped.wait(0.25)
        finally:
            server.shutdown()
            server.server_close()
            Path(config.socket).unlink(missing_ok=True)
            lock_file.close()
