#!/usr/bin/env python3
"""Complete a target's independent panel from its already owned proxy installation."""

from copy import deepcopy
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from nodekit import provenance
from nodekit.node_manager import FileNodeStore, NodeManager


def _hex(value, length):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise ValueError("自举任务格式无效")
    return value


def _owned_config(path, manifest_path, ip, secret):
    try:
        content = path.read_bytes()
        manifest = json.loads(manifest_path.read_bytes())
        if len(content) > 2_000_000:
            raise ValueError()
        valid, _ = provenance.verify_provenance(manifest, secret)
        if not valid or manifest.get("node_id") != ip:
            raise ValueError()
        if not hmac.compare_digest(str(manifest.get("config_sha256", "")), provenance.compute_config_sha256(content)):
            raise ValueError()
        return json.loads(content)
    except (OSError, ValueError, TypeError, UnicodeError):
        raise ValueError("现有代理服务归属未验证，未执行后台安装") from None


def _records(job, config, ip):
    params = job.get("node") or {}
    if not isinstance(params, dict):
        raise ValueError("节点参数无效")
    if any(key in params for key in ("password", "private_key", "passphrase", "ssh_password", "ssh_private_key")):
        raise ValueError("后台自举不接收 SSH 登录凭据")
    name = job.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("节点名称无效")
    name = name.strip()
    role = job.get("actual_role")
    if role not in ("exit", "relay", "standalone"):
        raise ValueError("节点角色无效")
    public_key = params.get("pbk") or params.get("public_key")
    if not isinstance(public_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", public_key):
        raise ValueError("节点公钥无效")
    user = job.get("user") or job.get("ssh_user") or "root"
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", user):
        raise ValueError("节点用户名无效")
    port = int(job.get("ssh_port", 22))
    if not 1 <= port <= 65535:
        raise ValueError("SSH 端口无效")
    inbounds = config.get("inbounds") or []
    main = next((i for i in inbounds if i.get("type") == "vless"), None)
    if main is None:
        raise ValueError("现有配置缺少主通道")
    common = {
        "host": ip, "role": role, "source": "builtin", "local": True,
        "ssh_user": user, "ssh_port": port, "provenance_id": ip,
        "quota_control_managed": True, "health": "unknown",
    }
    try:
        tls = main["tls"]
        hy2 = next((i for i in inbounds if i.get("type") == "hysteria2"), None)
        warp_enabled = any(i.get("tag") == "warp-out" for i in config.get("endpoints", []) + config.get("outbounds", []))
        record = dict(common, name=name, type="vless", port=int(main["listen_port"]),
                      uuid=main["users"][0]["uuid"], pbk=public_key,
                      sni=tls["server_name"], sid=str(tls["reality"]["short_id"][0]),
                      hy2_enabled=hy2 is not None, warp_enabled=warp_enabled)
        if not record["uuid"] or not 1 <= record["port"] <= 65535:
            raise ValueError()
        if role == "relay":
            outbound = next(i for i in config.get("outbounds", []) if i.get("type") == "vless")
            landing = {
                "host": outbound["server"], "port": int(outbound["server_port"]),
                "uuid": outbound["uuid"], "sni": outbound["tls"]["server_name"],
                "pbk": outbound["tls"]["reality"]["public_key"],
                "sid": str(outbound["tls"]["reality"]["short_id"]),
            }
            requested = job.get("landing") or {}
            if requested and requested.get("host") != landing["host"]:
                raise ValueError()
            record["landing"] = landing
        result = [record]
        if hy2 is not None:
            hy2_record = dict(common, name=name + "-HY2", type="hysteria2",
                              port=int(hy2["listen_port"]), password=hy2["users"][0]["password"],
                              sni=hy2["tls"]["server_name"], obfs_password=hy2["obfs"]["password"], enabled=True)
            if not 1 <= hy2_record["port"] <= 65535:
                raise ValueError()
            result.append(hy2_record)
        return result
    except (KeyError, IndexError, TypeError, StopIteration, ValueError):
        raise ValueError("现有代理配置与自举节点不一致") from None


def _store_secret(data, secret):
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = data / "master_secret"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if not hmac.compare_digest(provenance.load_master_secret(data), secret):
            raise ValueError("已有主控签名密钥与此目标不一致") from None
    else:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(secret.hex() + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _validate_existing(manager, records):
    expected = {record["name"]: record for record in records}
    for existing in manager.list_nodes():
        wanted = expected.get(existing.get("name"))
        if wanted is None or any(existing.get(key) != wanted.get(key) for key in wanted if key != "health"):
            raise ValueError("已有节点底账与此目标不一致，未覆盖")


def bootstrap(job, repo=None, data="/opt/web-data", cfg="/opt/sing-box/config.json", runner=subprocess.run,
              *, provenance_path=None):
    """Verify ownership, retain node metadata, then install the independent panel."""
    if not isinstance(job, dict) or job.get("self_bootstrap") is not True:
        raise ValueError("缺少独立后台安装请求")
    if any(key in job for key in ("password", "private_key", "passphrase", "ssh_password", "ssh_private_key")):
        raise ValueError("后台自举不接收 SSH 登录凭据")
    job_id = _hex(job.get("job_id"), 32)
    sub_token = _hex(job.get("sub_token"), 64)
    secret = bytes.fromhex(_hex(job.get("control_secret"), 64))
    panel_hash = job.get("panel_hash")
    if not isinstance(panel_hash, str) or not re.fullmatch(r"\$2[aby]\$(?:0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}", panel_hash):
        raise ValueError("后台密码摘要无效")
    try:
        ip = str(ipaddress.IPv4Address(job.get("ip")))
    except ipaddress.AddressValueError:
        raise ValueError("独立后台需要有效 IPv4 地址") from None
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[1]
    installer = root / "deploy" / "install.sh"
    if not installer.is_file():
        raise ValueError("后台安装资源不完整")
    config_path = Path(cfg)
    manifest_path = Path(provenance_path or provenance.PROVENANCE_PATH_LINUX)
    config = _owned_config(config_path, manifest_path, ip, secret)
    records = _records(job, config, ip)
    directory = Path(data)
    manager = NodeManager(store=FileNodeStore(directory / "nodes.json"))
    _validate_existing(manager, records)
    settings_path = directory / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        if settings.get("sub_token") != sub_token or settings.get("domain") != ip.replace(".", "-") + ".sslip.io":
            raise ValueError("已有后台设置与此任务不一致，未覆盖")
    _store_secret(directory, secret)
    for record in records:
        if manager.get_node(record["name"]) is None:
            manager.add_node(deepcopy(record))
    _owned_config(config_path, manifest_path, ip, secret)
    domain = ip.replace(".", "-") + ".sslip.io"
    request = "\n".join((job_id, sub_token, panel_hash, domain, ip)) + "\n"
    result = runner(["bash", str(installer), "--setup-stdin"], input=request, text=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=1800)
    if result.returncode != 0:
        raise ValueError("独立后台安装未完成")
    return {"delivery": {"domain": domain, "sub_token": sub_token}}


def main():
    try:
        raw = sys.stdin.buffer.read(150001)
        if len(raw) > 150000:
            raise ValueError()
        result = bootstrap(json.loads(raw))
    except Exception:
        print(json.dumps({"ok": False, "error": "独立后台自举未通过，未生成交付信息"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
