"""Cross-platform local control engine CLI & structured JSON tool interface."""

import argparse
from contextlib import suppress
import getpass
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import webbrowser

from server.nodekit import local_diag, system_updater
from server.nodekit.local_vault import SUPPORTED_SLOTS, VaultError

ROOT = Path(__file__).resolve().parents[1]
_PEM_HEADER_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")


class CliError(RuntimeError):
    def __init__(self, code, message, exit_code=1, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.detail = detail or {}


def default_state_path(root=None):
    override = os.environ.get("OWNLINE_LOCAL_STATE", "").strip()
    if override:
        return Path(override)
    base = Path(root) if root is not None else ROOT
    return base / ".ops-private" / "local_agent.json"


def is_gui_available():
    if os.environ.get("OWNLINE_HEADLESS", "").strip() == "1":
        return False
    has_ssh = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))
    if sys.platform == "darwin" or sys.platform.startswith("win"):
        if has_ssh and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class LocalDaemonClient:
    def __init__(self, origin, token, timeout=30):
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
            raise CliError("DAEMON_INVALID_ORIGIN", "本地守护进程地址无效。")
        self.origin = origin.rstrip("/")
        self.host_header = parsed.netloc
        self.port = parsed.port
        self.token = token
        self.timeout = timeout

    def _request(self, method, path, body=None, timeout=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout or self.timeout)
        headers = {
            "Host": self.host_header,
            "Cookie": "ownline_setup=" + self.token,
        }
        raw = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Origin"] = self.origin
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=raw, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except OSError as exc:
            raise CliError("DAEMON_UNREACHABLE", f"无法连接本地守护进程: {exc}") from None
        finally:
            conn.close()
        try:
            parsed = json.loads(data.decode("utf-8")) if data else {}
        except ValueError:
            parsed = {"message": data.decode("utf-8", errors="replace")}
        return resp.status, parsed

    def get_json(self, path, timeout=None):
        return self._request("GET", path, timeout=timeout)

    def post_json(self, path, body, timeout=None):
        return self._request("POST", path, body=body, timeout=timeout)


def _read_state(state_path):
    path = Path(state_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("origin") and data.get("token"):
            return data
    except Exception:
        return None
    return None


def _connect_existing(state_path):
    info = _read_state(state_path)
    if not info:
        return None
    client = LocalDaemonClient(info["origin"], info["token"], timeout=2)
    try:
        status, _ = client.get_json("/api/status", timeout=1.5)
        if status == 200:
            client.timeout = 90
            return client
    except CliError:
        return None
    return None


def ensure_daemon(state_path=None, *, autostart=True, diag_log=None, timeout=10.0):
    target_state = Path(state_path) if state_path is not None else default_state_path()
    client = _connect_existing(target_state)
    if client is not None:
        return client
    if not autostart:
        raise CliError("DAEMON_NOT_RUNNING", "本地守护进程未运行，请先执行 python3 ownline.py serve 或 ui。")

    target_state.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-B",
        "-m",
        "server.local_setup",
        "--no-browser",
        "--state-file",
        str(target_state),
    ]
    if diag_log is not None:
        cmd.extend(["--diag-log", str(diag_log)])

    popen_kwargs = {
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        client = _connect_existing(target_state)
        if client is not None:
            return client
        if proc.poll() is not None:
            raise CliError("DAEMON_START_FAILED", f"本地守护进程启动失败 (exit={proc.returncode})。")
        time.sleep(0.05)
    raise CliError("DAEMON_START_TIMEOUT", "等待本地守护进程就绪超时。")


def _read_plain(prompt_text, prompt_fn):
    if prompt_fn is input:
        sys.stderr.write(prompt_text)
        sys.stderr.flush()
        line = sys.stdin.readline()
        return line.rstrip("\r\n")
    return prompt_fn(prompt_text)


def _prompt_slot_tty(
    slot,
    *,
    target_hint="",
    username="root",
    ssh_port=22,
    dashboard_url="",
    prompt_fn=input,
    secret_prompt_fn=getpass.getpass,
):
    if slot == "ssh":
        host = str(target_hint or "").strip() or _read_plain("目标服务器公网 IP 或域名: ", prompt_fn).strip()
        if not host:
            raise VaultError("VAULT_SSH_HOST_REQUIRED", "未填写服务器地址。")
        raw = secret_prompt_fn("SSH 密码 (或输入 key:/私钥文件路径，或粘贴私钥): ")
        if not raw:
            raise VaultError("VAULT_CANCELLED", "已取消输入。")
        if raw.startswith("key:"):
            key_path = Path(raw[4:].strip()).expanduser()
            if not key_path.is_file():
                raise VaultError("VAULT_SSH_KEY_INVALID", f"私钥文件不存在: {key_path}")
            key_text = key_path.read_text(encoding="utf-8")
            passphrase = secret_prompt_fn("私钥口令 (无口令直接回车): ")
            payload = {
                "host": host,
                "username": username or "root",
                "ssh_port": int(ssh_port or 22),
                "private_key": key_text,
            }
            if passphrase:
                payload["passphrase"] = passphrase
            return payload
        if _PEM_HEADER_RE.search(raw):
            passphrase = secret_prompt_fn("私钥口令 (无口令直接回车): ")
            payload = {
                "host": host,
                "username": username or "root",
                "ssh_port": int(ssh_port or 22),
                "private_key": raw,
            }
            if passphrase:
                payload["passphrase"] = passphrase
            return payload
        return {
            "host": host,
            "username": username or "root",
            "ssh_port": int(ssh_port or 22),
            "password": raw,
        }

    if slot == "tencent_api":
        sid = secret_prompt_fn("腾讯云只读 SecretId: ").strip()
        skey = secret_prompt_fn("腾讯云只读 SecretKey: ").strip()
        return {"secret_id": sid, "secret_key": skey}

    if slot == "webshare_isp":
        proxy_url = secret_prompt_fn("Webshare 静态住宅代理串 (curl / ip:port:user:pass / URL): ").strip()
        return {"proxy_url": proxy_url}

    if slot == "panel_auth":
        pwd = secret_prompt_fn("管理面板密码: ")
        return {
            "dashboard_url": dashboard_url or target_hint or "",
            "username": username or "admin",
            "password": pwd,
        }

    raise VaultError("VAULT_SLOT_UNSUPPORTED", f"不支持的凭据类型: {slot}")


def run_vault_request(
    slot,
    *,
    label="",
    target_hint="",
    username="root",
    ssh_port=22,
    dashboard_url="",
    mode="auto",
    timeout=300,
    no_browser=False,
    client=None,
    state_path=None,
    diag_log=None,
    open_browser_fn=webbrowser.open,
    prompt_fn=input,
    secret_prompt_fn=getpass.getpass,
    poll_interval=0.25,
):
    if slot not in SUPPORTED_SLOTS:
        raise VaultError("VAULT_SLOT_UNSUPPORTED", f"不支持的凭据类型: {slot}")

    resolved_mode = mode
    if resolved_mode == "auto":
        resolved_mode = "browser" if is_gui_available() else "tty"

    active_client = client or ensure_daemon(state_path=state_path, autostart=True, diag_log=diag_log)
    status_code, req = active_client.post_json(
        "/api/vault/request",
        {
            "slot": slot,
            "label": label,
            "target_hint": target_hint,
            "ttl": max(5, int(timeout)),
        },
    )
    if status_code not in (200, 201):
        raise CliError(req.get("code", "VAULT_REQUEST_FAILED"), req.get("message", "创建凭据请求失败。"))

    req_id = req["request_id"]
    if resolved_mode == "tty":
        with suppress(Exception):
            local_diag.emit_event("vault_tty_fallback", {"slot": slot}, log_path=diag_log)
        payload = None
        try:
            payload = _prompt_slot_tty(
                slot,
                target_hint=target_hint,
                username=username,
                ssh_port=ssh_port,
                dashboard_url=dashboard_url,
                prompt_fn=prompt_fn,
                secret_prompt_fn=secret_prompt_fn,
            )
            sub_code, res = active_client.post_json(
                "/api/vault/submit",
                {"request_id": req_id, "payload": payload},
            )
            if sub_code != 200:
                raise CliError(res.get("code", "VAULT_SUBMIT_FAILED"), res.get("message", "提交凭据失败。"))
            return {
                "ok": True,
                "mode": "tty",
                "handle": res["handle"],
                "slot": res["slot"],
                "summary": res["summary"],
                "expires_in_seconds": res["expires_in_seconds"],
            }
        except BaseException:
            with suppress(Exception):
                active_client.post_json("/api/vault/cancel", {"request_id": req_id})
            raise
        finally:
            if isinstance(payload, dict):
                payload.clear()

    if not no_browser:
        with suppress(Exception):
            open_browser_fn(req["vault_url"])
    sys.stderr.write(f"请在本机浏览器页面完成凭据输入: {req['vault_url']}\n")
    sys.stderr.flush()

    deadline = time.monotonic() + max(1, int(timeout))
    while time.monotonic() < deadline:
        st_code, st = active_client.get_json(
            "/api/vault/status?id=" + urllib.parse.quote(req_id, safe=""),
            timeout=10,
        )
        if st_code != 200:
            raise CliError(st.get("code", "VAULT_STATUS_ERROR"), st.get("message", "读取凭据状态失败。"))
        state = st.get("state")
        if state == "submitted":
            return {
                "ok": True,
                "mode": "browser",
                "handle": st["handle"],
                "slot": st["slot"],
                "summary": st["summary"],
            }
        if state == "cancelled":
            raise CliError("VAULT_CANCELLED", "用户已取消凭据输入。")
        if state == "expired":
            raise CliError("VAULT_REQUEST_EXPIRED", "凭据输入已超时。")
        time.sleep(min(poll_interval, max(0.05, deadline - time.monotonic())))

    with suppress(Exception):
        active_client.post_json("/api/vault/cancel", {"request_id": req_id})
    raise CliError("VAULT_REQUEST_TIMEOUT", "等待用户完成凭据输入超时。")


def run_doctor(*, check_update=False, state_path=None, diag_log=None):
    py_ver = ".".join(str(x) for x in sys.version_info[:3])
    py_ok = sys.version_info >= (3, 10)
    deps = {
        "paramiko": importlib.util.find_spec("paramiko") is not None,
        "bcrypt": importlib.util.find_spec("bcrypt") is not None,
    }
    web_files = {
        name: (ROOT / "web" / name).is_file()
        for name in ("index.html", "local-setup.html", "local-vault.html")
    }
    version_info = system_updater.get_version_info(base_dir=ROOT)
    resolved_state = Path(state_path) if state_path is not None else default_state_path()
    daemon_running = _connect_existing(resolved_state) is not None
    resolved_diag = Path(diag_log) if diag_log is not None else local_diag.default_log_path(ROOT)

    result = {
        "ok": py_ok and all(deps.values()) and all(web_files.values()),
        "platform": sys.platform,
        "python": py_ver,
        "python_ok": py_ok,
        "gui_available": is_gui_available(),
        "dependencies": deps,
        "web_bundles": web_files,
        "version": version_info.get("version"),
        "commit": version_info.get("commit"),
        "daemon_running": daemon_running,
        "diag_log": str(resolved_diag),
    }
    if check_update:
        result["update"] = system_updater.check_update()
    with suppress(Exception):
        local_diag.emit_event(
            "local_cli_doctor",
            {"ok": result["ok"], "platform": sys.platform, "gui_available": result["gui_available"]},
            log_path=resolved_diag,
        )
    return result


def _emit_output(payload, as_json):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if isinstance(payload, str):
            print(payload)
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ownline",
        description="Evergreen OwnLine cross-platform local orchestration engine.",
    )
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON（供本地 Agent 调用）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="检查本机环境、依赖、前端构建与可选更新")
    p_doc.add_argument("--check-update", action="store_true")
    p_doc.add_argument("--json", action="store_true")

    p_upd = sub.add_parser("update-check", help="检查最新软件版本")
    p_upd.add_argument("--force", action="store_true")
    p_upd.add_argument("--json", action="store_true")

    p_ui = sub.add_parser("ui", help="启动跨平台本机回退安装页面")
    p_ui.add_argument("--port", type=int, default=0)
    p_ui.add_argument("--no-browser", action="store_true")

    p_srv = sub.add_parser("serve", help="仅启动本机守护进程（不自动弹浏览器）")
    p_srv.add_argument("--port", type=int, default=0)

    p_stop = sub.add_parser("stop", help="关闭本机守护进程并清空全部内存凭据")
    p_stop.add_argument("--json", action="store_true")

    p_vault = sub.add_parser("vault", help="盲签凭据库（明文绝不进终端历史/Agent 上下文）")
    vsub = p_vault.add_subparsers(dest="vault_cmd", required=True)

    p_vreq = vsub.add_parser("request", help="发起一次盲签凭据输入并获取句柄")
    p_vreq.add_argument("--slot", required=True, choices=SUPPORTED_SLOTS)
    p_vreq.add_argument("--label", default="")
    p_vreq.add_argument("--hint", default="")
    p_vreq.add_argument("--user", default="root")
    p_vreq.add_argument("--port", type=int, default=22)
    p_vreq.add_argument("--dashboard-url", default="")
    p_vreq.add_argument("--mode", choices=("auto", "browser", "tty"), default="auto")
    p_vreq.add_argument("--timeout", type=int, default=300)
    p_vreq.add_argument("--no-browser", action="store_true")
    p_vreq.add_argument("--json", action="store_true")

    p_vlist = vsub.add_parser("list", help="列出当前有效的非敏感凭据摘要")
    p_vlist.add_argument("--json", action="store_true")

    p_vclr = vsub.add_parser("clear", help="清空指定或全部内存凭据句柄")
    p_vclr.add_argument("--handle", default=None)
    p_vclr.add_argument("--json", action="store_true")

    p_chk = sub.add_parser("check", help="使用盲签句柄执行目标服务器 SSH 预检")
    p_chk.add_argument("--vault-handle", required=True)
    p_chk.add_argument("--fingerprint", default="")
    p_chk.add_argument("--host", default="")
    p_chk.add_argument("--user", default="")
    p_chk.add_argument("--port", type=int, default=0)
    p_chk.add_argument("--json", action="store_true")

    p_tc = sub.add_parser("tencent-instances", help="使用盲签句柄只读查询腾讯云 CVM 公网实例")
    p_tc.add_argument("--vault-handle", required=True)
    p_tc.add_argument("--product", default="cvm", choices=("cvm", "lighthouse"))
    p_tc.add_argument("--json", action="store_true")

    p_inst = sub.add_parser("install", help="凭已确认的 check_token 触发首台服务器安装")
    p_inst.add_argument("--check-token", required=True)
    p_inst.add_argument("--confirm", action="store_true")
    p_inst.add_argument("--json", action="store_true")

    p_st = sub.add_parser("status", help="查询当前本地安装状态")
    p_st.add_argument("--json", action="store_true")

    p_logs = sub.add_parser("logs", help="查看脱敏后的本地诊断日志")
    p_logs.add_argument("--limit", type=int, default=30)
    p_logs.add_argument("--json", action="store_true")

    p_evt = sub.add_parser("events", help="输出本地诊断事件注册表")
    p_evt.add_argument("--markdown", action="store_true")
    p_evt.add_argument("--json", action="store_true")

    return parser


def main(argv=None, *, state_path=None, diag_log=None, prompt_fn=input, secret_prompt_fn=getpass.getpass):
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))

    try:
        if args.command == "doctor":
            res = run_doctor(check_update=args.check_update, state_path=state_path, diag_log=diag_log)
            _emit_output(res, as_json or True)
            return 0 if res["ok"] else 1

        if args.command == "update-check":
            res = system_updater.check_update(force=args.force)
            with suppress(Exception):
                local_diag.emit_event(
                    "local_update_checked",
                    {"ok": bool(res.get("ok")), "has_update": bool(res.get("has_update"))},
                    log_path=diag_log,
                )
            _emit_output(res, True)
            return 0 if res.get("ok") else 1

        if args.command in ("ui", "serve"):
            from server import local_setup

            ls_args = ["--port", str(args.port)]
            if args.command == "serve" or getattr(args, "no_browser", False):
                ls_args.append("--no-browser")
            if state_path is not None:
                ls_args.extend(["--state-file", str(state_path)])
            if diag_log is not None:
                ls_args.extend(["--diag-log", str(diag_log)])
            local_setup.main(ls_args)
            return 0

        if args.command == "stop":
            client = ensure_daemon(state_path=state_path, autostart=False)
            code, res = client.post_json("/api/quit", {})
            _emit_output({"ok": code == 200, **res}, True)
            return 0 if code == 200 else 1

        if args.command == "vault":
            if args.vault_cmd == "request":
                res = run_vault_request(
                    args.slot,
                    label=args.label,
                    target_hint=args.hint,
                    username=args.user,
                    ssh_port=args.port,
                    dashboard_url=args.dashboard_url,
                    mode=args.mode,
                    timeout=args.timeout,
                    no_browser=args.no_browser,
                    state_path=state_path,
                    diag_log=diag_log,
                    prompt_fn=prompt_fn,
                    secret_prompt_fn=secret_prompt_fn,
                )
                _emit_output(res, True)
                return 0
            if args.vault_cmd == "list":
                client = _connect_existing(state_path or default_state_path())
                handles = []
                if client is not None:
                    code, data = client.get_json("/api/vault/handles")
                    if code == 200:
                        handles = data.get("handles", [])
                _emit_output({"ok": True, "handles": handles}, True)
                return 0
            if args.vault_cmd == "clear":
                client = _connect_existing(state_path or default_state_path())
                cleared = 0
                if client is not None:
                    code, data = client.post_json("/api/vault/clear", {"handle": args.handle})
                    if code == 200:
                        cleared = data.get("cleared", 0)
                _emit_output({"ok": True, "cleared": cleared}, True)
                return 0

        if args.command == "check":
            client = ensure_daemon(state_path=state_path, autostart=False)
            body = {"vault_handle": args.vault_handle}
            if args.fingerprint:
                body["fingerprint"] = args.fingerprint
            if args.host:
                body["host"] = args.host
            if args.user:
                body["username"] = args.user
            if args.port:
                body["ssh_port"] = args.port
            code, res = client.post_json("/api/check", body)
            if code != 200:
                err_code = res.get("code", "CHECK_FAILED")
                _emit_output({"ok": False, "code": err_code, **res}, True)
                return 2 if err_code == "HOST_KEY_CONFIRMATION" else 1
            _emit_output({"ok": bool(res.get("check_token")), **res}, True)
            return 0 if res.get("check_token") else 1

        if args.command == "tencent-instances":
            client = ensure_daemon(state_path=state_path, autostart=False)
            code, res = client.post_json(
                "/api/tencent/instances",
                {"vault_handle": args.vault_handle, "product": args.product},
            )
            _emit_output({"ok": code == 200, **res}, True)
            return 0 if code == 200 else 1

        if args.command == "install":
            if not args.confirm:
                raise CliError("CONFIRM_REQUIRED", "触发安装必须显式传入 --confirm。")
            client = ensure_daemon(state_path=state_path, autostart=False)
            code, res = client.post_json(
                "/api/install",
                {"check_token": args.check_token, "confirm": True},
            )
            _emit_output({"ok": code in (200, 202), **res}, True)
            return 0 if code in (200, 202) else 1

        if args.command == "status":
            client = _connect_existing(state_path or default_state_path())
            if client is None:
                _emit_output({"ok": True, "state": "idle", "daemon_running": False}, True)
                return 0
            code, res = client.get_json("/api/status")
            _emit_output({"ok": code == 200, "daemon_running": True, **res}, True)
            return 0 if code == 200 else 1

        if args.command == "logs":
            events = local_diag.read_recent_events(args.limit, log_path=diag_log)
            _emit_output({"ok": True, "events": events}, True)
            return 0

        if args.command == "events":
            if args.markdown and not as_json:
                print(local_diag.render_events_markdown(), end="")
            else:
                _emit_output({"ok": True, "events": local_diag.EVENT_REGISTRY}, True)
            return 0

    except (VaultError, CliError) as exc:
        err = {
            "ok": False,
            "code": getattr(exc, "code", "CLI_ERROR"),
            "message": getattr(exc, "message", str(exc)),
        }
        _emit_output(err, True)
        return getattr(exc, "exit_code", 1)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
