"""受控节点远端 sing-box 配置原子同步与真实出网闭环。

核心铁律（零假通过）：
1. 控制面变更（中转绑定/解绑/切换、HY2 极速通道开关、静态住宅 ISP 挂载）必须真实改写目标机
   `/opt/sing-box/config.json`，严禁只改主控 `nodes.json`。
2. 改写前先读取目标机现网 `config.json`，原样保留入站 VLESS Reality `private_key`、
   `uuid`、`short_id`、`port`、`sni`，确保客户端已导入订阅零中断。
3. 目标机原子更新流程：备份 `.ownline.bak` → 写 `.staged` (`0600`) → `sing-box check` →
   覆盖 `config.json` → `systemctl restart sing-box` → 真实代理出网探测 (`verify.run`)。
4. 任一环节失败立即自动恢复 `.ownline.bak` 并重启还原，返回真实失败原因，绝不亮假绿灯。
"""
import base64
import json
import os
import secrets
import shlex
import subprocess
import tempfile
import time

from . import provenance as prov_mod
from . import templates
from . import verify as verify_mod

CFG_PATH = "/opt/sing-box/config.json"
BIN_PATH = "/opt/sing-box/sing-box"
HY2_CERT_PATH = "/opt/sing-box/hy2.crt"
HY2_KEY_PATH = "/opt/sing-box/hy2.key"
DEFAULT_RUNNER = subprocess.run


def is_local_node(node):
    if not node or not isinstance(node, dict):
        return False
    if node.get("local") is True:
        return True
    host = (node.get("host") or "").strip()
    if host in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        return True
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                c = json.load(f)
            ibs = c.get("inbounds") or []
            if ibs and node.get("uuid") and node.get("port"):
                u = (ibs[0].get("users") or [{}])[0].get("uuid")
                p = int(ibs[0].get("listen_port") or 0)
                if u == node.get("uuid") and p == int(node.get("port")):
                    return True
        except Exception:
            pass
    return False


def check_controllable(node, allow_windows=False):
    """校验节点是否允许通过本机或 SSH 原子改写 sing-box 配置。"""
    if not isinstance(node, dict):
        return False, "节点数据无效"
    if node.get("source") == "external":
        return False, "外部节点无 SSH 控制权限，无法改写远端配置"
    if node.get("source") == "reverse_join":
        return False, "免密反向接入节点未向主控授权 SSH 控制权，仅支持订阅分发与连通探测，请在目标机本地维护配置"
    if node.get("cleanup_pending"):
        return False, "节点处于待人工清理状态，无法修改配置"
    if prov_mod.is_windows(node):
        return False, "Windows 受控分支已冻结（未经真机验证），请登录主机人工维护或迁至 Linux 受控节点"
    if not is_local_node(node) and not (node.get("host") or "").strip():
        return False, "节点缺少主机地址"
    return True, ""


def run_target(node, script, runner=None, timeout=25):
    """在 Linux 目标节点执行脚本（本机 bash 或 SSH base64 bash）。"""
    runner = runner or DEFAULT_RUNNER
    if prov_mod.is_windows(node):
        raise RuntimeError("Windows 受控分支已冻结，拒绝执行远程命令")
    if is_local_node(node):
        return runner(["bash", "-c", script], capture_output=True, text=True, timeout=timeout)
    user = (node.get("ssh_user") or "root").strip() or "root"
    port = int(node.get("ssh_port") or 22)
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    shell_exec = "bash" if user == "root" else "sudo -n bash"
    remote_cmd = "echo %s | base64 -d | %s" % (b64, shell_exec)
    cmd = verify_mod.ssh_cmd(user, node["host"], timeout=min(timeout, 12), port=port) + [remote_cmd]
    return runner(cmd, capture_output=True, text=True, timeout=timeout)


def extract_live_params(live_cfg, fallback_node=None):
    """从目标机现网 config.json 提取入站核心密钥与附加组件（保留原 private_key 不变）。"""
    fallback_node = fallback_node or {}
    if not isinstance(live_cfg, dict):
        raise ValueError("远端配置不是合法 JSON 对象")
    inbounds = live_cfg.get("inbounds") or []
    vless_ib = next((ib for ib in inbounds if ib.get("type") == "vless"), None)
    if not vless_ib:
        raise ValueError("远端配置缺少 vless 入站定义")

    users = vless_ib.get("users") or []
    tls = vless_ib.get("tls") or {}
    reality = tls.get("reality") or {}
    short_ids = reality.get("short_id") or []
    if isinstance(short_ids, str):
        short_ids = [short_ids]

    port = int(vless_ib.get("listen_port") or fallback_node.get("port") or 443)
    uid = (users[0].get("uuid") if users else None) or fallback_node.get("uuid") or ""
    sni = tls.get("server_name") or fallback_node.get("sni") or "www.apple.com"
    private_key = reality.get("private_key") or ""
    sid = (short_ids[0] if short_ids else "") or fallback_node.get("sid") or ""

    if not private_key:
        raise ValueError("远端配置缺少 reality private_key，拒绝覆盖以免破坏现有连接")
    if not uid or not sid:
        raise ValueError("远端配置缺少 uuid 或 short_id")

    hy2_ib = next((ib for ib in inbounds if ib.get("type") == "hysteria2"), None)
    hy2_info = None
    if hy2_ib:
        hy2_users = hy2_ib.get("users") or [{}]
        hy2_tls = hy2_ib.get("tls") or {}
        hy2_obfs = hy2_ib.get("obfs") or {}
        if hy2_users[0].get("password") and hy2_obfs.get("password"):
            hy2_info = {
                "port": int(hy2_ib.get("listen_port") or port),
                "password": hy2_users[0]["password"],
                "obfs_password": hy2_obfs["password"],
                "sni": hy2_tls.get("server_name") or "www.apple.com",
            }

    outbounds = live_cfg.get("outbounds") or []
    isp_ob = next(
        (ob for ob in outbounds if ob.get("tag") == "isp-out" or ob.get("type") in ("socks", "http")),
        None,
    )
    isp_info = None
    if isp_ob and isp_ob.get("server") and isp_ob.get("server_port"):
        isp_info = {
            "type": isp_ob.get("type", "socks"),
            "server": str(isp_ob["server"]),
            "server_port": int(isp_ob["server_port"]),
        }
        if isp_ob.get("username"):
            isp_info["username"] = str(isp_ob["username"])
        if isp_ob.get("password"):
            isp_info["password"] = str(isp_ob["password"])
        route_rules = (live_cfg.get("route") or {}).get("rules") or []
        has_udp_reject = any(
            isinstance(r, dict) and r.get("network") == "udp" and r.get("action") == "reject"
            for r in route_rules
        )
        if isp_info["type"] != "http" and live_cfg.get("dns") and not has_udp_reject:
            isp_info["udp"] = True

    endpoints = live_cfg.get("endpoints") or []
    warp_ep = next((ep for ep in endpoints if ep.get("tag") == "warp-out" or ep.get("type") == "wireguard"), None)
    warp_info = None
    if warp_ep and warp_ep.get("private_key"):
        peers = warp_ep.get("peers") or [{}]
        warp_info = {
            "type": "wireguard",
            "private_key": warp_ep["private_key"],
            "local_address": warp_ep.get("address") or ["172.16.0.2/32"],
            "server": peers[0].get("address") or "engage.cloudflareclient.com",
            "server_port": peers[0].get("port") or 2408,
            "peer_public_key": peers[0].get("public_key") or "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
            "mtu": warp_ep.get("mtu") or 1280,
        }
    else:
        warp_ob = next((ob for ob in outbounds if ob.get("tag") == "warp-out" and ob.get("type") == "socks"), None)
        if warp_ob:
            warp_info = {
                "type": "socks",
                "server": warp_ob.get("server") or "127.0.0.1",
                "server_port": int(warp_ob.get("server_port") or 40000),
            }

    return {
        "port": port,
        "uuid": uid,
        "sni": sni,
        "private_key": private_key,
        "sid": str(sid),
        "hy2": hy2_info,
        "isp": isp_info,
        "warp": warp_info,
    }


def read_live_config(node, runner=None, cfg_path=None, allow_windows=False):
    """读取 Linux 目标机上的 `config.json` 并解析为 dict。"""
    ok, reason = check_controllable(node)
    if not ok:
        return False, reason, None
    actual_cfg_path = cfg_path or CFG_PATH
    script = "cat %s" % shlex.quote(actual_cfg_path)
    try:
        res = run_target(node, script, runner=runner, timeout=15)
    except Exception as exc:
        return False, "连接节点读取配置失败：%s" % str(exc)[:120], None
    if res is None or res.returncode != 0:
        detail = ((getattr(res, "stderr", "") or getattr(res, "stdout", "") or "").strip())[:140]
        return False, "无法读取节点现网配置%s" % (("：" + detail) if detail else ""), None
    try:
        cfg = json.loads(res.stdout or "")
    except Exception:
        return False, "节点现网配置不是合法 JSON", None
    return True, "", cfg


def _build_apply_script(cfg_json_text, cfg_path=CFG_PATH, bin_path=BIN_PATH, ensure_hy2_cert=None, prov_json_text=None, prov_path=None, expected=None):
    b64_cfg = base64.b64encode(cfg_json_text.encode()).decode("ascii")
    b64_prov = base64.b64encode(prov_json_text.encode()).decode("ascii")
    prov_path = prov_path or prov_mod.PROVENANCE_PATH_LINUX
    q_cfg, q_bak, q_stg = map(shlex.quote, (cfg_path, cfg_path + ".ownline.bak", cfg_path + ".ownline.staged"))
    q_prov, q_prov_bak, q_prov_stg = map(shlex.quote, (prov_path, prov_path + ".ownline.bak", prov_path + ".staged"))
    q_bin = shlex.quote(bin_path)
    hy2_prep = ""
    if ensure_hy2_cert:
        q_crt = shlex.quote(ensure_hy2_cert.get("cert_path") or HY2_CERT_PATH)
        q_key = shlex.quote(ensure_hy2_cert.get("key_path") or HY2_KEY_PATH)
        port = int(ensure_hy2_cert.get("port") or 443)
        hy2_prep = f"""
if [ ! -s {q_crt} ] || [ ! -s {q_key} ]; then
  echo {shlex.quote(ensure_hy2_cert['cert_b64'])} | base64 -d > {q_crt}
  echo {shlex.quote(ensure_hy2_cert['key_b64'])} | base64 -d > {q_key}
  chmod 600 {q_key}
  chmod 644 {q_crt}
  if getent group sing-box >/dev/null 2>&1; then
    chgrp sing-box {q_key} {q_crt}
    chmod 640 {q_key}
  fi
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow {port}/udp >/dev/null 2>&1 || true
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --add-port={port}/udp --permanent >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi
"""
    return f"""test -x {q_bin}
changed=0
restore_pair() {{
  test "$(sha256sum {q_bak} | cut -d' ' -f1)" = {shlex.quote(expected['config_sha256'])} &&
  test "$(sha256sum {q_prov_bak} | cut -d' ' -f1)" = {shlex.quote(expected['manifest_sha256'])} &&
  cp -pf {q_bak} {q_cfg} && cp -pf {q_prov_bak} {q_prov}
}}
finish() {{
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$changed" = 1 ]; then
    if restore_pair && [ ! -f /var/lib/ownline/quota-paused ]; then
      systemctl restart sing-box >/dev/null 2>&1 || true
    fi
  fi
  rm -f {q_stg} {q_prov_stg}
  exit "$rc"
}}
trap finish EXIT
cp -pf {q_cfg} {q_bak}
cp -pf {q_prov} {q_prov_bak}
{hy2_prep}
echo {shlex.quote(b64_cfg)} | base64 -d > {q_stg}
echo {shlex.quote(b64_prov)} | base64 -d > {q_prov_stg}
chmod 600 {q_stg} {q_prov_stg}
if getent group sing-box >/dev/null 2>&1; then
  chgrp sing-box {q_stg}
  chmod 640 {q_stg}
fi
{q_bin} check -c {q_stg}
changed=1
mv -f {q_stg} {q_cfg}
mv -f {q_prov_stg} {q_prov}
if [ ! -f /var/lib/ownline/quota-paused ]; then
  systemctl restart sing-box && systemctl is-active --quiet sing-box
fi
"""


def generate_self_signed_cert_pem(sni="www.apple.com"):
    """使用 OpenSSL 生成通用自签名证书及私钥（PEM 文本，RSA 2048 跨平台兼容）。"""
    with tempfile.TemporaryDirectory() as td:
        crt_file = os.path.join(td, "cert.crt")
        key_file = os.path.join(td, "cert.key")
        cmd = [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-days", "365", "-nodes",
            "-subj", f"/CN={sni}",
            "-keyout", key_file,
            "-out", crt_file,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=10)
        with open(crt_file, "r") as f:
            crt_pem = f.read()
        with open(key_file, "r") as f:
            key_pem = f.read()
    return crt_pem, key_pem


def apply_config(node, new_cfg, runner=None, cfg_path=None, bin_path=None, ensure_hy2_cert=None, master_secret=None, allow_windows=False):
    """通过共享归属门禁后，在目标锁内成对更新配置及存证。"""
    ok, reason = check_controllable(node)
    if not ok:
        return False, reason
    errs = templates.validate(new_cfg)
    if errs:
        return False, "配置模板校验未通过：" + "；".join(errs)
    actual_cfg_path = cfg_path or CFG_PATH
    actual_bin_path = bin_path or BIN_PATH
    execute = lambda n, script, **kw: run_target(n, script, runner=runner, **kw)
    try:
        secret = prov_mod.secret_for_node(node) if master_secret is None else master_secret
    except (OSError, ValueError):
        return False, "未提供有效的独立主控签名密钥"
    ok, reason, snapshot = prov_mod.verify_target(node, execute, secret, cfg_path=actual_cfg_path)
    if not ok:
        return False, "服务归属核验失败：" + reason
    new_cfg = json.loads(json.dumps(new_cfg))
    cfg_text = json.dumps(new_cfg, ensure_ascii=False, indent=2) + "\n"
    manifest = prov_mod.sign_provenance(prov_mod.node_identity(node), prov_mod.compute_config_sha256(cfg_text), secret,
                                        installed_at=snapshot["manifest"]["installed_at"])
    cert = dict(ensure_hy2_cert) if ensure_hy2_cert else None
    if cert and not (cert.get("cert_b64") and cert.get("key_b64")):
        try:
            crt_pem, key_pem = generate_self_signed_cert_pem(cert.get("sni") or "www.apple.com")
            cert.update(cert_b64=base64.b64encode(crt_pem.encode()).decode("ascii"),
                        key_b64=base64.b64encode(key_pem.encode()).decode("ascii"))
        except Exception:
            return False, "无法生成 RSA 2048 HY2 证书，未改写配置"
    body = _build_apply_script(cfg_text, cfg_path=actual_cfg_path, bin_path=actual_bin_path, ensure_hy2_cert=cert,
                               prov_json_text=json.dumps(manifest, ensure_ascii=False),
                               prov_path=snapshot["provenance_path"], expected=snapshot)
    try:
        res = execute(node, prov_mod.guarded_script(node, snapshot, body), timeout=30)
    except Exception:
        return False, "SSH 下发配置超时或连接异常，请核实原任务状态"
    if res is None or res.returncode != 0:
        return False, "远端应用配置失败，未确认配置变更成功"
    return True, ""


def rollback_config(node, runner=None, cfg_path=None, master_secret=None, execute_remote_fn=None, bin_path=None):
    """只有现网与备份均具有有效归属时，才成对恢复配置及存证。"""
    ok, _ = check_controllable(node)
    if not ok:
        return False
    actual_cfg_path = cfg_path or CFG_PATH
    execute = execute_remote_fn or (lambda n, script, **kw: run_target(n, script, runner=runner, **kw))
    ok, _, current = prov_mod.verify_target(node, execute, master_secret, cfg_path=actual_cfg_path)
    if not ok:
        return False
    ok, _, backup = prov_mod.verify_target(node, execute, master_secret, cfg_path=actual_cfg_path + ".ownline.bak",
                                           provenance_path=current["provenance_path"] + ".ownline.bak")
    if not ok:
        return False
    cfg, prov = shlex.quote(actual_cfg_path), shlex.quote(current["provenance_path"])
    bak, prov_bak = shlex.quote(actual_cfg_path + ".ownline.bak"), shlex.quote(current["provenance_path"] + ".ownline.bak")
    binary = shlex.quote(bin_path or BIN_PATH)
    body = f"""test "$(sha256sum {bak} | cut -d' ' -f1)" = {backup['config_sha256']}
test "$(sha256sum {prov_bak} | cut -d' ' -f1)" = {backup['manifest_sha256']}
{binary} check -c {bak}
cp -pf {bak} {cfg}
cp -pf {prov_bak} {prov}
if [ ! -f /var/lib/ownline/quota-paused ]; then
  systemctl restart sing-box && systemctl is-active --quiet sing-box
fi
"""
    try:
        res = execute(node, prov_mod.guarded_script(node, current, body), timeout=25)
        return bool(res is not None and res.returncode == 0)
    except Exception:
        return False


def _landing_from_exit(exit_node):
    if not isinstance(exit_node, dict):
        return None, "目标海外出口节点不存在"
    if exit_node.get("type") == "hysteria2":
        return None, "中转落地必须指向海外节点的 VLESS Reality 主通道，不能指向 HY2 子通道"
    if exit_node.get("role") in ("relay", "standalone"):
        return None, "不能将国内中转或国内独立服务器作为海外落地目标"
    missing = [k for k in ("host", "uuid", "pbk", "sid") if not exit_node.get(k)]
    if missing:
        return None, "目标落地节点缺少必要 Reality 参数（%s）" % ", ".join(missing)
    return {
        "host": exit_node["host"],
        "port": int(exit_node.get("port") or 443),
        "uuid": exit_node["uuid"],
        "pbk": exit_node["pbk"],
        "sid": str(exit_node["sid"]),
        "sni": exit_node.get("sni") or exit_node["host"],
    }, ""


def bind_relay(relay_node, exit_node, fallback_exit_node=None,
               runner=None, verifier=None,
               cfg_path=CFG_PATH, bin_path=BIN_PATH, master_secret=None):
    """真实登录中转机改写 relay 配置 + 重启 sing-box + 端到端出网验真（失败自动回滚）。"""
    verifier = verifier or verify_mod.run
    ok, reason = check_controllable(relay_node)
    if not ok:
        return {"ok": False, "error": reason}
    landing, err = _landing_from_exit(exit_node)
    if err:
        return {"ok": False, "error": err}
    if (relay_node.get("host") or "").strip() == landing["host"]:
        return {"ok": False, "error": "中转节点不能绑定自身作为落地目标"}

    fallback_landing = None
    if fallback_exit_node and (fallback_exit_node.get("host") != landing["host"]):
        fb_cand, fb_err = _landing_from_exit(fallback_exit_node)
        if not fb_err and fb_cand["host"] != (relay_node.get("host") or "").strip():
            fallback_landing = fb_cand

    ok_read, err_read, live_cfg = read_live_config(relay_node, runner=runner, cfg_path=cfg_path)
    if not ok_read:
        return {"ok": False, "error": err_read}
    try:
        live = extract_live_params(live_cfg, fallback_node=relay_node)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    new_cfg = templates.relay_config(
        port=live["port"],
        uuid=live["uuid"],
        sni=live["sni"],
        private_key=live["private_key"],
        sid=live["sid"],
        landing=landing,
        fallback_landing=fallback_landing,
    )
    applied, apply_err = apply_config(relay_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
    if not applied:
        return {"ok": False, "error": apply_err}

    probe_node = dict(relay_node)
    probe_node.update({
        "port": live["port"],
        "uuid": live["uuid"],
        "sni": live["sni"],
        "sid": live["sid"],
        "role": "relay",
        "landing": landing,
    })
    vr = verifier(probe_node) or {"health": "proxy", "detail": "中转探测无响应"}
    exit_cc = (vr.get("exit_country") or "").upper()
    if vr.get("health") != "ok" or exit_cc == "CN":
        rolled_back = rollback_config(relay_node, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
        detail = vr.get("detail") or vr.get("health") or "未知错误"
        if exit_cc == "CN":
            detail = "中转出口仍位于中国大陆 (%s)" % (vr.get("exit_ip") or "CN")
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功，请登录服务器检查"
        return {
            "ok": False,
            "rolled_back": rolled_back,
            "verify": vr,
            "error": "中转配置已下发但真实出网探测未通过（%s），%s" % (detail, rb_note),
        }

    landing_policy = {"active_target": landing["host"]}
    landing_policy["primary"] = {
        "host": landing["host"],
        "name": exit_node.get("name") or landing["host"],
        "port": landing["port"],
    }
    if fallback_landing and fallback_exit_node:
        landing_policy["fallback"] = {
            "host": fallback_landing["host"],
            "name": fallback_exit_node.get("name") or fallback_landing["host"],
            "port": fallback_landing["port"],
        }

    return {
        "ok": True,
        "landing": landing,
        "fallback_landing": fallback_landing,
        "landing_policy": landing_policy,
        "verify": vr,
        "exit_ip": vr.get("exit_ip") or exit_node.get("exit_ip") or landing["host"],
        "exit_country": vr.get("exit_country") or exit_node.get("exit_country") or "",
        "health_detail": vr.get("detail") or ("中转：经落地出网，出口 %s" % (vr.get("exit_ip") or landing["host"])),
    }


def switch_relay(relay_node, target_exit_node, fallback_exit_node=None,
                 runner=None, verifier=None,
                 cfg_path=CFG_PATH, bin_path=BIN_PATH, master_secret=None):
    """切换中转节点的首选海外落地（本质是保留原私钥重新下发 relay_config 并真实探测）。"""
    return bind_relay(
        relay_node=relay_node,
        exit_node=target_exit_node,
        fallback_exit_node=fallback_exit_node,
        runner=runner,
        verifier=verifier,
        cfg_path=cfg_path,
        bin_path=bin_path,
        master_secret=master_secret,
    )


def unbind_relay(relay_node, runner=None,
                 tcp_check=None, tls_check=None,
                 cfg_path=CFG_PATH, bin_path=BIN_PATH, master_secret=None):
    """解除中转绑定：改写远端为无落地直连配置，校验服务与握手正常，失败回滚。"""
    tcp_check = tcp_check or verify_mod.tcp_ok
    tls_check = tls_check or verify_mod.tls_ok
    ok, reason = check_controllable(relay_node)
    if not ok:
        return {"ok": False, "error": reason}
    ok_read, err_read, live_cfg = read_live_config(relay_node, runner=runner, cfg_path=cfg_path)
    if not ok_read:
        return {"ok": False, "error": err_read}
    try:
        live = extract_live_params(live_cfg, fallback_node=relay_node)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    new_cfg = templates.exit_config(
        port=live["port"],
        uuid=live["uuid"],
        sni=live["sni"],
        private_key=live["private_key"],
        sid=live["sid"],
        hy2=None,
        isp=None,
    )
    applied, apply_err = apply_config(relay_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
    if not applied:
        return {"ok": False, "error": apply_err}

    host = relay_node.get("host") or "127.0.0.1"
    if not tcp_check(host, live["port"]) or not tls_check(host, live["port"], live["sni"]):
        rolled_back = rollback_config(relay_node, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功，请检查服务器"
        return {
            "ok": False,
            "rolled_back": rolled_back,
            "error": "解除中转后节点端口或 Reality 握手异常，%s" % rb_note,
        }

    return {
        "ok": True,
        "health": "unknown",
        "health_detail": "国内独立服务器（未绑定中转，不进订阅）",
    }


def toggle_hy2(vless_node, existing_hy2_node=None, enabled=True,
               open_firewall_fn=None, runner=None, verifier=None,
               cfg_path=None, bin_path=None, master_secret=None):
    """在海外出口机上真实开启或移除 Hysteria2 QUIC 入站，并执行端到端验真。"""
    verifier = verifier or verify_mod.run
    ok, reason = check_controllable(vless_node)
    if not ok:
        return {"ok": False, "error": reason}
    if vless_node.get("role") in ("relay", "standalone"):
        return {"ok": False, "error": "仅海外出口节点支持开启 Hysteria2 极速通道"}

    actual_cfg_path = cfg_path or CFG_PATH
    actual_bin_path = bin_path or BIN_PATH

    ok_read, err_read, live_cfg = read_live_config(vless_node, runner=runner, cfg_path=actual_cfg_path)
    if not ok_read:
        return {"ok": False, "error": err_read}
    try:
        live = extract_live_params(live_cfg, fallback_node=vless_node)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    active_isp = live["isp"] if live["isp"] is not None else vless_node.get("isp")

    if enabled:
        prev = existing_hy2_node or live["hy2"] or {}
        hy2_port = int(prev.get("port") or live["port"])
        hy2_params = {
            "port": hy2_port,
            "password": prev.get("password") or secrets.token_hex(12),
            "obfs_password": prev.get("obfs_password") or secrets.token_hex(8),
            "sni": prev.get("sni") or "www.apple.com",
        }
        firewall_note = ""
        cert_dir = os.path.dirname(actual_cfg_path) or "/opt/sing-box"
        cert_path = os.path.join(cert_dir, "hy2.crt")
        key_path = os.path.join(cert_dir, "hy2.key")

        new_cfg = templates.exit_config(
            port=live["port"],
            uuid=live["uuid"],
            sni=live["sni"],
            private_key=live["private_key"],
            sid=live["sid"],
            hy2=hy2_params,
            isp=active_isp,
            warp=live.get("warp"),
        )
        for ib in new_cfg.get("inbounds", []):
            if ib.get("type") == "hysteria2":
                ib["tls"]["certificate_path"] = cert_path
                ib["tls"]["key_path"] = key_path

        applied, apply_err = apply_config(
            vless_node,
            new_cfg,
            runner=runner,
            cfg_path=actual_cfg_path,
            bin_path=actual_bin_path,
            master_secret=master_secret,
            ensure_hy2_cert={
                "sni": hy2_params["sni"],
                "port": hy2_port,
                "cert_path": cert_path,
                "key_path": key_path,
            },
        )
        if not applied:
            return {"ok": False, "error": apply_err, "firewall_note": firewall_note}

        if open_firewall_fn and not is_local_node(vless_node):
            try:
                fw_st, fw_msg = open_firewall_fn(vless_node["host"], hy2_port, proto="UDP")
                firewall_note = fw_msg or fw_st or ""
            except Exception as exc:
                firewall_note = str(exc)[:80]

        hy2_record = dict(existing_hy2_node or {})
        hy2_record.update({
            "name": (existing_hy2_node or {}).get("name") or (vless_node["name"] + "-HY2"),
            "type": "hysteria2",
            "host": vless_node["host"],
            "port": hy2_port,
            "password": hy2_params["password"],
            "obfs_password": hy2_params["obfs_password"],
            "sni": hy2_params["sni"],
            "role": vless_node.get("role") or "exit",
            "source": vless_node.get("source") or "builtin",
            "ssh_user": vless_node.get("ssh_user") or "root",
            "ssh_port": int(vless_node.get("ssh_port") or 22),
            "enabled": True,
        })
        for field in ("control_secret", "provenance_id"):
            if vless_node.get(field):
                hy2_record[field] = vless_node[field]
        if vless_node.get("local") is True:
            hy2_record["local"] = True
        if vless_node.get("quota_control_managed") is True:
            hy2_record["quota_control_managed"] = True
        if vless_node.get("expire_at") and not hy2_record.get("expire_at"):
            hy2_record["expire_at"] = vless_node["expire_at"]

        time.sleep(0.3)
        vr = verifier(hy2_record) or {"health": "proxy", "detail": "HY2 探测无响应"}
        if vr.get("health") != "ok":
            time.sleep(0.8)
            vr = verifier(hy2_record) or {"health": "proxy", "detail": "HY2 探测无响应"}
        if vr.get("health") != "ok":
            rolled_back = rollback_config(vless_node, runner=runner, cfg_path=actual_cfg_path, bin_path=actual_bin_path, master_secret=master_secret)
            rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功，请检查服务器"
            fw_tip = ("（云防火墙提示：%s）" % firewall_note) if firewall_note else ""
            return {
                "ok": False,
                "rolled_back": rolled_back,
                "verify": vr,
                "error": "已写入 HY2 配置但 QUIC/UDP 真实出网验真失败：%s，%s%s"
                         % (vr.get("detail") or vr.get("health"), rb_note, fw_tip),
            }

        hy2_record["health"] = "ok"
        hy2_record["exit_ip"] = vr.get("exit_ip") or vless_node.get("exit_ip") or ""
        hy2_record["exit_country"] = vr.get("exit_country") or vless_node.get("exit_country") or ""
        hy2_record["health_detail"] = vr.get("detail") or ""
        return {
            "ok": True,
            "enabled": True,
            "hy2_node": hy2_record,
            "verify": vr,
            "firewall_note": firewall_note,
        }

    # 关闭 HY2：从远端配置移除 hysteria2 inbound，保留原 VLESS Reality 与 ISP
    new_cfg = templates.exit_config(
        port=live["port"],
        uuid=live["uuid"],
        sni=live["sni"],
        private_key=live["private_key"],
        sid=live["sid"],
        hy2=None,
        isp=active_isp,
        warp=live.get("warp"),
    )
    applied, apply_err = apply_config(
        vless_node,
        new_cfg,
        runner=runner,
        cfg_path=actual_cfg_path,
        bin_path=actual_bin_path,
        master_secret=master_secret,
    )
    if not applied:
        return {"ok": False, "error": apply_err}

    time.sleep(0.3)
    vr = verifier(vless_node) or {"health": "proxy", "detail": "主节点探测无响应"}
    if vr.get("health") != "ok":
        time.sleep(0.8)
        vr = verifier(vless_node) or {"health": "proxy", "detail": "主节点探测无响应"}
    if vr.get("health") != "ok":
        rolled_back = rollback_config(vless_node, runner=runner, cfg_path=actual_cfg_path, bin_path=actual_bin_path, master_secret=master_secret)
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功"
        return {
            "ok": False,
            "rolled_back": rolled_back,
            "verify": vr,
            "error": "移除 HY2 后主通道验真失败（%s），%s" % (vr.get("detail") or vr.get("health"), rb_note),
        }

    return {"ok": True, "enabled": False, "verify": vr}


def sync_isp(vless_node, isp_cfg, runner=None, verifier=None,
             cfg_path=CFG_PATH, bin_path=BIN_PATH, master_secret=None):
    """在海外出口机（本机或远端 SSH）真实挂载或卸载静态住宅 ISP 链式代理并验真。"""
    verifier = verifier or verify_mod.run
    ok, reason = check_controllable(vless_node)
    if not ok:
        return {"ok": False, "error": reason}
    if vless_node.get("role") in ("relay", "standalone"):
        return {"ok": False, "error": "国内中转或独立节点不支持挂载海外静态住宅出口"}

    ok_read, err_read, live_cfg = read_live_config(vless_node, runner=runner, cfg_path=cfg_path)
    if not ok_read:
        return {"ok": False, "error": err_read}
    try:
        live = extract_live_params(live_cfg, fallback_node=vless_node)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    new_cfg = templates.exit_config(
        port=live["port"],
        uuid=live["uuid"],
        sni=live["sni"],
        private_key=live["private_key"],
        sid=live["sid"],
        hy2=live["hy2"],
        isp=isp_cfg,
        warp=live.get("warp"),
    )
    applied, apply_err = apply_config(vless_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
    if not applied:
        return {"ok": False, "error": apply_err}

    vr = verifier(vless_node) or {"health": "proxy", "detail": "探测无响应"}
    if vr.get("health") != "ok":
        rolled_back = rollback_config(vless_node, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功"
        return {
            "ok": False,
            "rolled_back": rolled_back,
            "verify": vr,
            "error": "静态住宅代理挂载后出网探测失败（%s），%s" % (vr.get("detail") or vr.get("health"), rb_note),
        }

    return {
        "ok": True,
        "verify": vr,
        "exit_ip": vr.get("exit_ip") or "",
        "exit_country": vr.get("exit_country") or "",
        "health_detail": vr.get("detail") or "",
    }


def toggle_warp(vless_node, enabled=True, warp_creds=None,
                runner=None, verifier=None, cfg_path=CFG_PATH, bin_path=BIN_PATH, master_secret=None):
    """在海外出口机上真实开启或关闭 Cloudflare WARP 清洁出网通道，并执行验真与故障回滚。"""
    verifier = verifier or verify_mod.run
    ok, reason = check_controllable(vless_node)
    if not ok:
        return {"ok": False, "error": reason}
    if vless_node.get("role") in ("relay", "standalone"):
        return {"ok": False, "error": "国内中转或独立节点不支持开启 WARP 清洁出口"}

    ok_read, err_read, live_cfg = read_live_config(vless_node, runner=runner, cfg_path=cfg_path)
    if not ok_read:
        return {"ok": False, "error": err_read}
    try:
        live = extract_live_params(live_cfg, fallback_node=vless_node)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    active_isp = live["isp"] if live["isp"] is not None else vless_node.get("isp")

    target_warp = None
    if enabled:
        if warp_creds and isinstance(warp_creds, dict) and warp_creds.get("private_key"):
            target_warp = warp_creds
        else:
            execute = lambda n, script, **kw: run_target(n, script, runner=runner, **kw)
            owned, reason, _ = prov_mod.verify_target(vless_node, execute, master_secret, cfg_path=cfg_path)
            if not owned:
                return {"ok": False, "error": "服务归属核验失败：" + reason}
            try:
                from . import warp_client
            except ImportError:
                import warp_client
            w_res = warp_client.register_warp()
            if not w_res.get("ok"):
                return {"ok": False, "error": "Cloudflare WARP 凭据注册失败: %s" % w_res.get("error")}
            target_warp = w_res

    new_cfg = templates.exit_config(
        port=live["port"],
        uuid=live["uuid"],
        sni=live["sni"],
        private_key=live["private_key"],
        sid=live["sid"],
        hy2=live["hy2"],
        isp=active_isp,
        warp=target_warp,
    )

    applied, apply_err = apply_config(vless_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
    if not applied:
        return {"ok": False, "error": apply_err}

    vr = verifier(vless_node) or {"health": "ok"}
    if vr.get("health") != "ok":
        rolled_back = rollback_config(vless_node, runner=runner, cfg_path=cfg_path, bin_path=bin_path, master_secret=master_secret)
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功"
        return {
            "ok": False,
            "rolled_back": rolled_back,
            "verify": vr,
            "error": "WARP 状态调整后主通道验真失败（%s），%s" % (vr.get("detail") or vr.get("health"), rb_note),
        }

    return {
        "ok": True,
        "enabled": enabled,
        "warp": target_warp,
        "verify": vr,
    }
