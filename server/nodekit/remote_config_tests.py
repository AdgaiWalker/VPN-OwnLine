#!/usr/bin/env python3
"""remote_config.py 全离网单元测试（在临时目录真跑 Bash 应用与回滚脚本）。"""
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import remote_config as RC  # noqa: E402
from nodekit import templates  # noqa: E402

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, f"失败: {name} {extra}"
    ok += 1
    print(f"  OK {name}")


def _make_sandbox(tmp_dir, initial_cfg):
    root = Path(tmp_dir)
    bindir = root / "bin"
    sb_dir = root / "sing-box"
    bindir.mkdir()
    sb_dir.mkdir()

    cfg_path = sb_dir / "config.json"
    cfg_path.write_text(json.dumps(initial_cfg, indent=2), encoding="utf-8")

    sb_bin = sb_dir / "sing-box"
    sb_bin.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"check\" ] && [ \"$2\" = \"-c\" ]; then\n"
        "  [ \"${SB_CHECK_FAIL:-0}\" = \"1\" ] && exit 1\n"
        "  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' \"$3\"\n"
        "  exit $?\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    sb_bin.chmod(0o755)

    systemctl = bindir / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\n"
        "echo \"$*\" >> \"" + str(root / "systemctl.log") + "\"\n"
        "case \"$1\" in\n"
        "  restart) [ \"${RESTART_FAIL:-0}\" = \"1\" ] && exit 1; exit 0;;\n"
        "  is-active) [ \"${ACTIVE_FAIL:-0}\" = \"1\" ] && exit 1; exit 0;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)

    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    ssh_calls = []

    def runner(cmd, **kwargs):
        ssh_calls.append(cmd)
        if cmd[0] == "ssh":
            remote_part = cmd[-1]
            if "| sudo -n bash" in remote_part:
                b64 = remote_part.split()[1]
                script = base64.b64decode(b64).decode("utf-8")
            elif "| bash" in remote_part:
                b64 = remote_part.split()[1]
                script = base64.b64decode(b64).decode("utf-8")
            else:
                script = remote_part
            return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=15)
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)

    return root, str(cfg_path), str(sb_bin), env, runner, ssh_calls


def test_relay_bind_switch_unbind_and_rollback():
    init_cfg = templates.exit_config(
        port=443,
        uuid="11111111-1111-4111-8111-111111111111",
        sni="www.apple.com",
        private_key="ORIG_PRIV_KEY_NEVER_LOSE",
        sid="abcd1234",
    )
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg_path, sb_bin, env, runner, ssh_calls = _make_sandbox(tmp, init_cfg)

        relay_node = {
            "name": "华北入口",
            "host": "198.51.100.10",
            "port": 443,
            "ssh_user": "ubuntu",
            "ssh_port": 2222,
            "role": "standalone",
            "quota_control_managed": True,
        }
        exit_us = {
            "name": "美西出口",
            "host": "203.0.113.10",
            "port": 443,
            "uuid": "22222222-2222-4222-8222-222222222222",
            "pbk": "US_PUB_KEY",
            "sid": "11223344",
            "sni": "www.apple.com",
            "role": "exit",
            "exit_ip": "203.0.113.10",
            "exit_country": "US",
        }
        exit_sg = {
            "name": "亚太出口",
            "host": "203.0.113.20",
            "port": 8443,
            "uuid": "33333333-3333-4333-8333-333333333333",
            "pbk": "SG_PUB_KEY",
            "sid": "55667788",
            "sni": "www.microsoft.com",
            "role": "exit",
            "exit_ip": "203.0.113.20",
            "exit_country": "SG",
        }

        # 1. 成功绑定中转（含双落地 urltest + 自定义 SSH 端口 + 非 root sudo）
        res = RC.bind_relay(
            relay_node,
            exit_us,
            fallback_exit_node=exit_sg,
            runner=runner,
            verifier=lambda n: {"health": "ok", "exit_ip": "203.0.113.10", "exit_country": "US", "detail": "中转正常"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("绑定中转成功返回 ok", res["ok"] is True, res)
        check("SSH 命令携带自定义端口 -p 2222", ssh_calls[0][1:3] == ["-p", "2222"], ssh_calls[0])
        check("非 root 用户自动使用 sudo -n bash", "sudo -n bash" in ssh_calls[0][-1], ssh_calls[0][-1])

        written = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("原样保留入站 private_key", written["inbounds"][0]["tls"]["reality"]["private_key"] == "ORIG_PRIV_KEY_NEVER_LOSE")
        check("生成双落地 urltest 出站", any(o.get("type") == "urltest" for o in written["outbounds"]), written)
        check("首选落地指向美西出口", written["outbounds"][0]["server"] == "203.0.113.10")

        # 2. 切换首选落地但模拟真实代理出网失败 → 必须自动回滚回 203.0.113.10！
        res_fail = RC.switch_relay(
            relay_node,
            exit_sg,
            fallback_exit_node=exit_us,
            runner=runner,
            verifier=lambda n: {"health": "landing", "detail": "入口和落地都通，但代理连不出去"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("探测失败拒绝假绿灯", res_fail["ok"] is False and res_fail.get("rolled_back") is True, res_fail)
        rolled = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("探测失败后远端配置已真实回滚至美西落地", rolled["outbounds"][0]["server"] == "203.0.113.10", rolled)

        # 3. 切换首选落地且真实出网成功
        res_sw = RC.switch_relay(
            relay_node,
            exit_sg,
            fallback_exit_node=exit_us,
            runner=runner,
            verifier=lambda n: {"health": "ok", "exit_ip": "203.0.113.20", "exit_country": "SG", "detail": "切流成功"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("真实切流成功", res_sw["ok"] is True and res_sw["exit_country"] == "SG", res_sw)
        sw_cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("远端首选落地已切为亚太出口", sw_cfg["outbounds"][0]["server"] == "203.0.113.20")

        # 4. 解除中转绑定 → 远端恢复单 direct 出站，私钥仍保留
        res_ub = RC.unbind_relay(
            relay_node,
            runner=runner,
            tcp_check=lambda h, p: True,
            tls_check=lambda h, p, s: True,
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("解绑中转成功", res_ub["ok"] is True, res_ub)
        ub_cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("解绑后移除中转出站只剩 direct", ub_cfg["outbounds"] == [{"type": "direct", "tag": "direct"}], ub_cfg)
        check("解绑后原 private_key 依然完好", ub_cfg["inbounds"][0]["tls"]["reality"]["private_key"] == "ORIG_PRIV_KEY_NEVER_LOSE")


def test_hy2_toggle_cert_verify_and_rollback():
    init_cfg = templates.exit_config(
        port=443,
        uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        sni="www.apple.com",
        private_key="EXIT_PRIV_KEY",
        sid="deadbeef",
    )
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg_path, sb_bin, env, runner, _ = _make_sandbox(tmp, init_cfg)
        vless_node = {
            "name": "美西节点",
            "host": "203.0.113.50",
            "port": 443,
            "uuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "pbk": "EXIT_PUB",
            "sid": "deadbeef",
            "sni": "www.apple.com",
            "role": "exit",
            "quota_control_managed": True,
        }
        fw_calls = []

        # 1. 开启 HY2 但模拟 UDP 端口未通（探测返回 proxy）→ 自动回滚，配置中不残留 HY2
        res_udp_blocked = RC.toggle_hy2(
            vless_node,
            enabled=True,
            open_firewall_fn=lambda ip, port, proto="UDP": (fw_calls.append((ip, port, proto)) or ("skip", "需手动放行")),
            runner=runner,
            verifier=lambda n: {"health": "proxy", "detail": "UDP 端口未放行"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("HY2 UDP 不通时拒绝假开启并回滚", res_udp_blocked["ok"] is False and res_udp_blocked.get("rolled_back") is True)
        check("尝试调用了云防火墙放行 UDP", fw_calls == [("203.0.113.50", 443, "UDP")], fw_calls)
        after_rb = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("回滚后远端配置未残留 HY2 入站", len(after_rb["inbounds"]) == 1)

        # 2. 开启 HY2 且真实探测通过 → 生成自签证书 + 写入 HY2 inbound + 继承 quota_control_managed
        res_on = RC.toggle_hy2(
            vless_node,
            enabled=True,
            runner=runner,
            verifier=lambda n: {"health": "ok", "exit_ip": "203.0.113.50", "exit_country": "US", "detail": "HY2 通畅"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("HY2 开启并验真成功", res_on["ok"] is True, res_on)
        hy2_rec = res_on["hy2_node"]
        check("新增 HY2 记录自动继承 quota_control_managed=True", hy2_rec.get("quota_control_managed") is True, hy2_rec)
        check("远端已生成 HY2 自签证书与私钥", (Path(cfg_path).parent / "hy2.crt").exists() and (Path(cfg_path).parent / "hy2.key").exists())
        on_cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("远端配置包含 vless + hysteria2 双入站", [i["type"] for i in on_cfg["inbounds"]] == ["vless", "hysteria2"])

        # 3. 挂载静态住宅 ISP 代理时保留已有 HY2 入站与原私钥
        isp_cfg = {"type": "socks", "server": "198.51.100.88", "server_port": 10808, "username": "u", "password": "p"}
        res_isp = RC.sync_isp(
            vless_node,
            isp_cfg,
            runner=runner,
            verifier=lambda n: {"health": "ok", "exit_ip": "198.51.100.88", "exit_country": "US", "detail": "住宅出口正常"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("远端挂载静态住宅 ISP 成功", res_isp["ok"] is True, res_isp)
        isp_written = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("挂载 ISP 后 HY2 入站仍保留", len(isp_written["inbounds"]) == 2)
        check("挂载 ISP 后路由指向 isp-out", isp_written["route"]["rules"] == [{"outbound": "isp-out"}])

        # 4. 关闭 HY2 → 远端移除 hysteria2 inbound，保留 VLESS 与 ISP
        res_off = RC.toggle_hy2(
            vless_node,
            existing_hy2_node=hy2_rec,
            enabled=False,
            runner=runner,
            verifier=lambda n: {"health": "ok", "exit_ip": "198.51.100.88", "exit_country": "US"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
        )
        check("关闭 HY2 成功", res_off["ok"] is True, res_off)
        off_cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        check("关闭 HY2 后远端配置真实移除 hysteria2 入站", [i["type"] for i in off_cfg["inbounds"]] == ["vless"])
        check("关闭 HY2 后原 ISP 出站仍保留", off_cfg["outbounds"][0]["tag"] == "isp-out")


def test_boundary_rejections():
    check("拒绝外部节点", RC.check_controllable({"source": "external"})[0] is False)
    check("拒绝 Windows 节点", RC.check_controllable({"os": "windows", "host": "203.0.113.9"})[0] is False)
    check("拒绝待清理节点", RC.check_controllable({"cleanup_pending": True, "host": "203.0.113.9"})[0] is False)


if __name__ == "__main__":
    test_relay_bind_switch_unbind_and_rollback()
    test_hy2_toggle_cert_verify_and_rollback()
    test_boundary_rejections()
    print(f"通过 {ok} 项")
