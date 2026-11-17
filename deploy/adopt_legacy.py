#!/usr/bin/env python3
"""Explicit operator adoption of a verified legacy local installation; no restart."""
import argparse
import fcntl
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT)]
from nodekit import provenance
import reset_admin_password


def adopt(host, expected_sha, *, confirmed=False, inspect_only=False, scope="installation", data="/opt/web-data", cfg="/opt/sing-box/config.json",
          manifest=None, caddy="/etc/caddy/Caddyfile", lock="/run/ownline-service.lock", runner=subprocess.run):
    """Only metadata is written, after explicit exclusivity and frozen-state checks."""
    if not confirmed and not inspect_only:
        raise ValueError("必须由运维人员明确确认本项目独占此服务")
    if scope not in ("installation", "proxy"):
        raise ValueError("无效归属范围")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("必须提供事先核对的完整配置 SHA-256")
    config = Path(cfg)
    target_manifest = Path(manifest or provenance.PROVENANCE_PATH_LINUX)
    directory = Path(data)
    with open(lock, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        paths = (config, directory / "nodes.json") + ((Path(caddy),) if scope == "installation" else ())
        for path in paths:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                raise ValueError("迁移输入必须为普通文件，拒绝符号链接")
        content = config.read_bytes()
        if not hmac.compare_digest(provenance.compute_config_sha256(content), expected_sha):
            raise ValueError("现网配置已变化，未建立存证")
        current = json.loads(content)
        records = json.loads((directory / "nodes.json").read_text())
        local = [n for n in records if n.get("local") is True and n.get("host") == host]
        main = [n for n in local if n.get("type") != "hysteria2"]
        if len(main) != 1 or any(n.get("host") != host for n in records if n.get("local") is True):
            raise ValueError("本机节点身份不唯一，拒绝自动推断归属")
        node = main[0]
        inbound = next((i for i in current.get("inbounds", []) if i.get("type") == "vless"), {})
        if (not node.get("uuid") or (inbound.get("users") or [{}])[0].get("uuid") != node["uuid"]
                or int(inbound.get("listen_port", 0)) != int(node.get("port", 0))
                or provenance.node_identity(node) != host):
            raise ValueError("节点底账与运行配置不一致，未建立存证")
        if scope == "installation":
            reset_admin_password.inspect_credentials(Path(caddy).read_text())
        unit = runner(["systemctl", "show", "sing-box", "-p", "ExecStart", "--value"],
                      capture_output=True, text=True, timeout=10)
        if unit.returncode or str(config) not in unit.stdout or "/opt/sing-box/sing-box" not in unit.stdout:
            raise ValueError("运行服务路径与本产品不一致，未建立存证")
        if inspect_only:
            return {"status": "eligible_for_explicit_confirmation", "scope": scope, "node_id": host, "config_sha256": expected_sha}
        if target_manifest.is_symlink():
            raise ValueError("拒绝符号链接存证")
        if target_manifest.exists():
            secret = provenance.load_master_secret(directory)
            previous = json.loads(target_manifest.read_bytes())
            valid, _ = provenance.verify_provenance(previous, secret)
            if valid and previous.get("node_id") == host and previous.get("config_sha256") == expected_sha:
                return {"status": "already_owned", "config_sha256": expected_sha}
            raise ValueError("已有无效或不同归属的存证，拒绝覆盖")
        if config.read_bytes() != content:
            raise ValueError("迁移期间配置变化，未建立存证")
        secret = provenance.load_master_secret(directory, create=True)
        signed = provenance.sign_provenance(host, expected_sha, secret)
        if not provenance.verify_provenance(signed, secret)[0]:
            raise ValueError("存证签名验证失败")
        target_manifest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target_manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(signed, output)
            output.flush()
            os.fsync(output.fileno())
        return {"status": "adopted_without_restart", "config_sha256": expected_sha}


def main():
    parser = argparse.ArgumentParser(description="核实旧本机服务归属后建立存证；本命令不重启服务")
    parser.add_argument("--confirm-exclusive", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--scope", choices=("installation", "proxy"), default="installation")
    parser.add_argument("--host", required=True)
    parser.add_argument("--expected-config-sha", required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError("迁移需要 root 权限")
        result = adopt(args.host, args.expected_config_sha, confirmed=args.confirm_exclusive,
                       inspect_only=args.check_only, scope=args.scope)
    except Exception:
        print("归属迁移未完成；未重启服务，请核对独占确认、配置摘要和现网底账。", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
