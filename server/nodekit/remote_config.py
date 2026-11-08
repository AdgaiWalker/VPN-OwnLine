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

from . import provenance as prov_mod
from . import templates
from . import verify as verify_mod

CFG_PATH = "/opt/sing-box/config.json"
BIN_PATH = "/opt/sing-box/sing-box"
HY2_CERT_PATH = "/opt/sing-box/hy2.crt"
HY2_KEY_PATH = "/opt/sing-box/hy2.key"
DEFAULT_RUNNER = subprocess.run


def is_local_node(node):
    host = (node or {}).get("host") or ""
    return bool((node or {}).get("local") is True or host in ("127.0.0.1", "localhost"))


def check_controllable(node, allow_windows=False):
    """校验节点是否允许通过本机或 SSH 原子改写 sing-box 配置。"""
    if not isinstance(node, dict):
        return False, "节点数据无效"
    if node.get("source") == "external":
        return False, "外部节点无 SSH 控制权限，无法改写远端配置"
    if node.get("cleanup_pending"):
        return False, "节点处于待人工清理状态，无法修改配置"
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win and not allow_windows:
        return False, "Windows 节点暂不支持在线原子改写配置，请登录主机人工调整"
    if not is_local_node(node) and not (node.get("host") or "").strip():
        return False, "节点缺少主机地址"
    return True, ""


def run_target(node, script, runner=None, timeout=25):
    """在目标节点执行脚本（Linux 走 bash/sudo -n；Windows 走 powershell stdin Invoke-Expression）。"""
    runner = runner or DEFAULT_RUNNER
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_local_node(node):
        return runner(["bash", "-c", script], capture_output=True, text=True, timeout=timeout)
    user = (node.get("ssh_user") or ("Administrator" if is_win else "root")).strip() or "root"
    port = int(node.get("ssh_port") or 22)
    if is_win:
        win_ps = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n{script}"
        cmd = verify_mod.ssh_cmd(user, node["host"], timeout=min(timeout, 15), port=port) + [
            'powershell -NoProfile -Command "$raw = [Console]::In.ReadToEnd(); Invoke-Expression $raw"'
        ]
        try:
            res = runner(cmd, input=win_ps, capture_output=True, timeout=timeout)
            if hasattr(res, "stdout") and isinstance(res.stdout, bytes):
                res.stdout = res.stdout.decode("utf-8", errors="replace")
            if hasattr(res, "stderr") and isinstance(res.stderr, bytes):
                res.stderr = res.stderr.decode("utf-8", errors="replace")
            if hasattr(res, "stderr") and res.stderr:
                filtered = [ln for ln in res.stderr.splitlines() if not ln.startswith("**") and "openssh.com" not in ln]
                res.stderr = "\n".join(filtered).strip()
            return res
        except TypeError:
            return runner(cmd, capture_output=True, text=True, timeout=timeout)
    else:
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
                "sni": hy2_tls.get("server_name") or "www.bing.com",
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

    return {
        "port": port,
        "uuid": uid,
        "sni": sni,
        "private_key": private_key,
        "sid": str(sid),
        "hy2": hy2_info,
        "isp": isp_info,
    }


def read_live_config(node, runner=None, cfg_path=None, allow_windows=False):
    """读取目标机上的 `config.json` 并解析为 dict（支持 Linux 与 Windows 节点）。"""
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    ok, reason = check_controllable(node, allow_windows=allow_windows or is_win)
    if not ok:
        return False, reason, None
    actual_cfg_path = cfg_path or (r"C:\proxy\config.json" if is_win else CFG_PATH)
    if is_win:
        script = f"Get-Content -Raw '{actual_cfg_path}'"
    else:
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


def _build_windows_apply_script(cfg_json_text, cfg_path=r"C:\proxy\config.json", bin_path=r"C:\proxy\sing-box.exe", ensure_hy2_cert=None, prov_json_text=None):
    b64_cfg = base64.b64encode(cfg_json_text.encode("utf-8")).decode("ascii")
    stg_path = cfg_path + ".staged"
    bak_path = cfg_path + ".ownline.bak"
    hy2_prep = ""
    if ensure_hy2_cert:
        hy2_port = int(ensure_hy2_cert.get("port") or 443)
        crt_path = ensure_hy2_cert.get("cert_path") or r"C:\proxy\hy2.crt"
        key_path = ensure_hy2_cert.get("key_path") or r"C:\proxy\hy2.key"
        crt_b64 = ensure_hy2_cert.get("cert_b64") or ""
        key_b64 = ensure_hy2_cert.get("key_b64") or ""
        cert_write = ""
        if crt_b64 and key_b64:
            cert_write = f"""
[IO.File]::WriteAllBytes('{crt_path}', [Convert]::FromBase64String('{crt_b64}'))
[IO.File]::WriteAllBytes('{key_path}', [Convert]::FromBase64String('{key_b64}'))
"""
        hy2_prep = f"""
{cert_write}
netsh advfirewall firewall add rule name="OwnLine-HY2-UDP" dir=in action=allow protocol=UDP localport={hy2_port} >$null 2>&1
"""
    prov_prep = ""
    if prov_json_text:
        b64_prov = base64.b64encode(prov_json_text.encode("utf-8")).decode("ascii")
        prov_path = r"C:\proxy\.evergreen-provenance.json"
        prov_prep = f"""
[IO.File]::WriteAllBytes('{prov_path}', [Convert]::FromBase64String('{b64_prov}'))
"""
    ps_script = f"""$ErrorActionPreference = 'Stop'
{hy2_prep}
[IO.File]::WriteAllBytes('{stg_path}', [Convert]::FromBase64String('{b64_cfg}'))
& '{bin_path}' check -c '{stg_path}'
if ($LASTEXITCODE -ne 0) {{
    Remove-Item -Force '{stg_path}' -ErrorAction SilentlyContinue
    Write-Error "SINGBOX_CHECK_FAILED"
    exit 14
}}
if (Test-Path '{cfg_path}') {{
    Copy-Item -Force '{cfg_path}' '{bak_path}'
}}
Move-Item -Force '{stg_path}' '{cfg_path}'
{prov_prep}
Stop-ScheduledTask -TaskName 'sing-box' -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600
Start-ScheduledTask -TaskName 'sing-box'
"""
    return ps_script


def _build_apply_script(cfg_json_text, cfg_path=CFG_PATH, bin_path=BIN_PATH, ensure_hy2_cert=None, prov_json_text=None):
    b64_cfg = base64.b64encode(cfg_json_text.encode("utf-8")).decode("ascii")
    q_cfg = shlex.quote(cfg_path)
    q_bak = shlex.quote(cfg_path + ".ownline.bak")
    q_stg = shlex.quote(cfg_path + ".ownline.staged")
    q_bin = shlex.quote(bin_path)

    prov_prep = ""
    if prov_json_text:
        b64_prov = base64.b64encode(prov_json_text.encode("utf-8")).decode("ascii")
        prov_path = "/etc/sing-box/.evergreen-provenance.json"
        prov_prep = f"""
mkdir -p /etc/sing-box
echo {shlex.quote(b64_prov)} | base64 -d > {prov_path}
chmod 600 {prov_path}
"""

    hy2_prep = ""
    if ensure_hy2_cert:
        hy2_sni = str(ensure_hy2_cert.get("sni") or "www.bing.com")
        hy2_port = int(ensure_hy2_cert.get("port") or 443)
        q_crt = shlex.quote(ensure_hy2_cert.get("cert_path") or HY2_CERT_PATH)
        q_key = shlex.quote(ensure_hy2_cert.get("key_path") or HY2_KEY_PATH)
        q_subj = shlex.quote("/CN=" + hy2_sni)
        hy2_prep = f"""
if [ ! -s {q_crt} ] || [ ! -s {q_key} ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \\
    -days 3650 -nodes -subj {q_subj} \\
    -keyout {q_key} -out {q_crt} >/dev/null 2>&1
  chmod 600 {q_key} {q_crt}
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow {hy2_port}/udp >/dev/null 2>&1 || true
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --add-port={hy2_port}/udp --permanent >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi
"""

    inner = f"""set -euo pipefail
umask 077
if [ ! -x {q_bin} ]; then
  echo "MISSING_SINGBOX_BIN" >&2
  exit 12
fi
if [ ! -f {q_cfg} ]; then
  echo "MISSING_CONFIG_JSON" >&2
  exit 13
fi
{hy2_prep}
cp -pf {q_cfg} {q_bak}
echo {shlex.quote(b64_cfg)} | base64 -d > {q_stg}
chmod 600 {q_stg}
if ! {q_bin} check -c {q_stg}; then
  rm -f {q_stg}
  echo "SINGBOX_CHECK_FAILED" >&2
  exit 14
fi
mv -f {q_stg} {q_cfg}
{prov_prep}
if [ ! -f /var/lib/ownline/quota-paused ]; then
  if ! (systemctl restart sing-box && systemctl is-active --quiet sing-box); then
    cp -pf {q_bak} {q_cfg} || true
    systemctl restart sing-box >/dev/null 2>&1 || true
    echo "SINGBOX_RESTART_FAILED" >&2
    exit 15
  fi
fi
"""
    b64_inner = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    return (
        "if command -v flock >/dev/null 2>&1; then "
        f"flock -x -w 10 /run/ownline-service.lock bash -c 'echo {b64_inner} | base64 -d | bash'; "
        f"else echo {b64_inner} | base64 -d | bash; fi"
    )


def generate_self_signed_cert_pem(sni="www.bing.com"):
    """使用 OpenSSL 生成通用自签名证书及私钥（PEM 文本，RSA 2048 跨平台兼容）。"""
    with tempfile.TemporaryDirectory() as td:
        crt_file = os.path.join(td, "cert.crt")
        key_file = os.path.join(td, "cert.key")
        cmd = [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-days", "3650", "-nodes",
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
    """校验并原子下发新配置至目标节点并重启 sing-box。"""
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    ok, reason = check_controllable(node, allow_windows=allow_windows or is_win)
    if not ok:
        return False, reason
    errs = templates.validate(new_cfg)
    if errs:
        return False, "配置模板校验未通过：" + "；".join(errs)

    if is_win and isinstance(new_cfg.get("log"), dict):
        new_cfg["log"]["output"] = r"C:\proxy\sing-box.log"

    cfg_text = json.dumps(new_cfg, ensure_ascii=False, indent=2) + "\n"
    prov_text = None
    if master_secret:
        node_id = (node or {}).get("name") or (node or {}).get("host") or "unknown_node"
        manifest = prov_mod.sign_provenance(node_id, prov_mod.compute_config_sha256(cfg_text), master_secret)
        prov_text = json.dumps(manifest, indent=2, ensure_ascii=False)

    if is_win:
        actual_cfg_path = cfg_path or r"C:\proxy\config.json"
        actual_bin_path = bin_path or r"C:\proxy\sing-box.exe"
        win_hy2 = dict(ensure_hy2_cert) if ensure_hy2_cert else None
        if win_hy2 and not win_hy2.get("cert_b64"):
            try:
                crt_pem, key_pem = generate_self_signed_cert_pem(win_hy2.get("sni") or "www.bing.com")
                win_hy2["cert_b64"] = base64.b64encode(crt_pem.encode("utf-8")).decode("ascii")
                win_hy2["key_b64"] = base64.b64encode(key_pem.encode("utf-8")).decode("ascii")
            except Exception:
                pass
        script = _build_windows_apply_script(cfg_text, cfg_path=actual_cfg_path, bin_path=actual_bin_path, ensure_hy2_cert=win_hy2, prov_json_text=prov_text)
    else:
        actual_cfg_path = cfg_path or CFG_PATH
        actual_bin_path = bin_path or BIN_PATH
        script = _build_apply_script(cfg_text, cfg_path=actual_cfg_path, bin_path=actual_bin_path, ensure_hy2_cert=ensure_hy2_cert, prov_json_text=prov_text)

    try:
        res = run_target(node, script, runner=runner, timeout=30)
    except Exception as exc:
        return False, "SSH 下发配置超时或连接异常：%s" % str(exc)[:120]
    if res is None or res.returncode != 0:
        detail = ((getattr(res, "stderr", "") or getattr(res, "stdout", "") or "").strip())[:160]
        return False, "远端应用配置失败%s" % (("：" + detail) if detail else "")
    return True, ""


def rollback_config(node, runner=None, cfg_path=None):
    """将目标节点配置回滚至最近一次 `.ownline.bak` 并重启服务。"""
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win:
        actual_cfg_path = cfg_path or r"C:\proxy\config.json"
        bak_path = actual_cfg_path + ".ownline.bak"
        script = f"""
if (Test-Path '{bak_path}') {{
    Copy-Item -Force '{bak_path}' '{actual_cfg_path}'
    Stop-ScheduledTask -TaskName 'sing-box' -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 600
    Start-ScheduledTask -TaskName 'sing-box'
    exit 0
}} else {{
    exit 1
}}
"""
        try:
            res = run_target(node, script, runner=runner, timeout=25)
            return bool(res is not None and res.returncode == 0)
        except Exception:
            return False

    actual_cfg_path = cfg_path or CFG_PATH
    q_cfg = shlex.quote(actual_cfg_path)
    q_bak = shlex.quote(actual_cfg_path + ".ownline.bak")
    inner = (
        f"set -euo pipefail; "
        f"if [ -f {q_bak} ]; then cp -pf {q_bak} {q_cfg}; "
        f"if [ ! -f /var/lib/ownline/quota-paused ]; then systemctl restart sing-box && systemctl is-active --quiet sing-box; fi; "
        f"else exit 1; fi"
    )
    b64_inner = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    script = (
        "if command -v flock >/dev/null 2>&1; then "
        f"flock -x -w 10 /run/ownline-service.lock bash -c 'echo {b64_inner} | base64 -d | bash'; "
        f"else echo {b64_inner} | base64 -d | bash; fi"
    )
    try:
        res = run_target(node, script, runner=runner, timeout=25)
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
               cfg_path=CFG_PATH, bin_path=BIN_PATH):
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
    applied, apply_err = apply_config(relay_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path)
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
        rolled_back = rollback_config(relay_node, runner=runner, cfg_path=cfg_path)
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
                 cfg_path=CFG_PATH, bin_path=BIN_PATH):
    """切换中转节点的首选海外落地（本质是保留原私钥重新下发 relay_config 并真实探测）。"""
    return bind_relay(
        relay_node=relay_node,
        exit_node=target_exit_node,
        fallback_exit_node=fallback_exit_node,
        runner=runner,
        verifier=verifier,
        cfg_path=cfg_path,
        bin_path=bin_path,
    )


def unbind_relay(relay_node, runner=None,
                 tcp_check=None, tls_check=None,
                 cfg_path=CFG_PATH, bin_path=BIN_PATH):
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
    applied, apply_err = apply_config(relay_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path)
    if not applied:
        return {"ok": False, "error": apply_err}

    host = relay_node.get("host") or "127.0.0.1"
    if not tcp_check(host, live["port"]) or not tls_check(host, live["port"], live["sni"]):
        rolled_back = rollback_config(relay_node, runner=runner, cfg_path=cfg_path)
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
               cfg_path=None, bin_path=None):
    """在海外出口机上真实开启或移除 Hysteria2 QUIC 入站，并执行端到端验真。"""
    verifier = verifier or verify_mod.run
    is_win = (vless_node.get("os") == "windows") or (vless_node.get("ssh_user") == "Administrator")
    ok, reason = check_controllable(vless_node, allow_windows=True)
    if not ok:
        return {"ok": False, "error": reason}
    if vless_node.get("role") in ("relay", "standalone"):
        return {"ok": False, "error": "仅海外出口节点支持开启 Hysteria2 极速通道"}

    actual_cfg_path = cfg_path or (r"C:\proxy\config.json" if is_win else CFG_PATH)
    actual_bin_path = bin_path or (r"C:\proxy\sing-box.exe" if is_win else BIN_PATH)

    ok_read, err_read, live_cfg = read_live_config(vless_node, runner=runner, cfg_path=actual_cfg_path, allow_windows=True)
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
            "sni": prev.get("sni") or "www.bing.com",
        }
        firewall_note = ""
        if open_firewall_fn and not is_local_node(vless_node):
            try:
                fw_st, fw_msg = open_firewall_fn(vless_node["host"], hy2_port, proto="UDP")
                firewall_note = fw_msg or fw_st or ""
            except Exception as exc:
                firewall_note = str(exc)[:80]

        if is_win:
            cert_path = r"C:\proxy\hy2.crt"
            key_path = r"C:\proxy\hy2.key"
        else:
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
            allow_windows=True,
            ensure_hy2_cert={
                "sni": hy2_params["sni"],
                "port": hy2_port,
                "cert_path": cert_path,
                "key_path": key_path,
            },
        )
        if not applied:
            return {"ok": False, "error": apply_err, "firewall_note": firewall_note}

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
            "ssh_user": vless_node.get("ssh_user") or ("Administrator" if is_win else "root"),
            "ssh_port": int(vless_node.get("ssh_port") or 22),
            "enabled": True,
        })
        if is_win:
            hy2_record["os"] = "windows"
        if vless_node.get("local") is True:
            hy2_record["local"] = True
        if vless_node.get("quota_control_managed") is True:
            hy2_record["quota_control_managed"] = True
        if vless_node.get("expire_at") and not hy2_record.get("expire_at"):
            hy2_record["expire_at"] = vless_node["expire_at"]

        vr = verifier(hy2_record) or {"health": "proxy", "detail": "HY2 探测无响应"}
        if vr.get("health") != "ok":
            rolled_back = rollback_config(vless_node, runner=runner, cfg_path=actual_cfg_path)
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
    )
    applied, apply_err = apply_config(
        vless_node,
        new_cfg,
        runner=runner,
        cfg_path=actual_cfg_path,
        bin_path=actual_bin_path,
        allow_windows=True,
    )
    if not applied:
        return {"ok": False, "error": apply_err}

    vr = verifier(vless_node) or {"health": "proxy", "detail": "主节点探测无响应"}
    if vr.get("health") != "ok":
        rolled_back = rollback_config(vless_node, runner=runner, cfg_path=actual_cfg_path)
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功"
        return {
            "ok": False,
            "rolled_back": rolled_back,
            "verify": vr,
            "error": "移除 HY2 后主通道验真失败（%s），%s" % (vr.get("detail") or vr.get("health"), rb_note),
        }

    return {"ok": True, "enabled": False, "verify": vr}


def sync_isp(vless_node, isp_cfg, runner=None, verifier=None,
             cfg_path=CFG_PATH, bin_path=BIN_PATH):
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
    )
    applied, apply_err = apply_config(vless_node, new_cfg, runner=runner, cfg_path=cfg_path, bin_path=bin_path)
    if not applied:
        return {"ok": False, "error": apply_err}

    vr = verifier(vless_node) or {"health": "proxy", "detail": "探测无响应"}
    if vr.get("health") != "ok":
        rolled_back = rollback_config(vless_node, runner=runner, cfg_path=cfg_path)
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
