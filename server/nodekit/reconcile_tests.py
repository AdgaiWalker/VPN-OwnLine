#!/usr/bin/env python3
"""reconcile.py 全离网单元测试（能力边界、配置推导、脱敏差异及沙箱收敛回滚）。"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import provenance, reconcile, remote_config, remote_config_tests, templates  # noqa: E402

SECRET = remote_config_tests.SECRET
ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, f"失败: {name} {extra}"
    ok += 1
    print(f"  OK {name}")


def test_node_capability_modes():
    cap_managed = reconcile.node_capability({"name": "us1", "host": "198.51.100.1", "source": "builtin", "quota_control_managed": True})
    check("managed 模式权限完整", cap_managed["mode"] == "managed" and cap_managed["controllable"] and cap_managed["can_quota_stop"])

    cap_ext = reconcile.node_capability({"name": "ext", "host": "198.51.100.2", "source": "external"})
    check("external 模式禁远程变更", cap_ext["mode"] == "external" and not cap_ext["controllable"] and not cap_ext["can_auto_repair"])

    cap_rj = reconcile.node_capability({"name": "rj", "host": "198.51.100.3", "source": "reverse_join", "ssh_password": "ignored"})
    check("reverse_join 模式无条件为本地运维", cap_rj["mode"] == "reverse_join" and not cap_rj["controllable"] and not cap_rj["can_quota_stop"])

    cap_win1 = reconcile.node_capability({"name": "w1", "host": "198.51.100.4", "os": "windows"})
    cap_win2 = reconcile.node_capability({"name": "w2", "host": "198.51.100.5", "ssh_user": "Administrator"})
    check("Windows 节点归类为 windows_frozen", cap_win1["mode"] == "windows_frozen" and cap_win2["mode"] == "windows_frozen" and not cap_win1["controllable"])

    cap_clean = reconcile.node_capability({"name": "del", "host": "198.51.100.6", "cleanup_pending": True})
    check("cleanup_pending 禁止远端变更", cap_clean["mode"] == "cleanup_pending" and not cap_clean["controllable"])


def test_build_desired_config_and_diff_redaction():
    live_params = {
        "port": 443,
        "uuid": "11111111-1111-4111-8111-111111111111",
        "sni": "www.apple.com",
        "private_key": "SUPER_SECRET_PRIV_KEY",
        "sid": "abcd1234",
        "hy2": None,
        "isp": None,
        "warp": None,
    }
    exit_node = {
        "name": "us1",
        "host": "198.51.100.10",
        "port": 443,
        "uuid": "11111111-1111-4111-8111-111111111111",
        "sni": "www.apple.com",
        "sid": "abcd1234",
        "role": "exit",
        "hy2_enabled": True,
        "isp": {"type": "socks", "server": "198.51.100.88", "server_port": 1080, "username": "u1", "password": "ISP_SECRET_PASSWORD"},
        "warp_enabled": True,
        "warp": {"type": "wireguard", "private_key": "WARP_KEY", "local_address": ["172.16.0.2/32"]},
    }
    hy2_node = {
        "name": "us1-HY2",
        "type": "hysteria2",
        "port": 443,
        "password": "HY2_SECRET_PASSWORD",
        "obfs_password": "HY2_OBFS_SECRET",
        "sni": "www.apple.com",
        "enabled": True,
    }
    desired = reconcile.build_desired_config(exit_node, live_params, hy2_node=hy2_node)
    check("ISP+HY2 期望配置含双入站与 DoH", [i["type"] for i in desired["inbounds"]] == ["vless", "hysteria2"] and "dns" in desired)
    check("ISP 期望配置拒绝非支持 UDP", desired["route"]["final"] == "isp-out" and {"network": "udp", "action": "reject"} in desired["route"]["rules"])

    direct_cfg = templates.exit_config(443, live_params["uuid"], "www.apple.com", "DIFFERENT_SECRET_KEY", "abcd1234")
    reordered = json.loads(json.dumps(desired))
    check("键顺序不同不触发虚假漂移", reconcile.diff_configs(desired, reordered) == [])

    diffs = reconcile.diff_configs(direct_cfg, desired, redact=True)
    joined = "\n".join(diffs)
    check("配置偏移被准确识别", len(diffs) > 0)
    check("敏感密钥与密码在差异输出中彻底脱敏", "SUPER_SECRET_PRIV_KEY" not in joined and "HY2_SECRET_PASSWORD" not in joined and "ISP_SECRET_PASSWORD" not in joined and "[REDACTED]" in joined)

    relay_node = {
        "name": "bj1",
        "host": "203.0.113.10",
        "port": 8443,
        "uuid": "22222222-2222-4222-8222-222222222222",
        "sni": "www.apple.com",
        "sid": "ef012345",
        "role": "relay",
        "landing": {"host": "198.51.100.10", "port": 443, "uuid": "11111111-1111-4111-8111-111111111111", "pbk": "PUBK", "sid": "abcd1234"},
    }
    relay_desired = reconcile.build_desired_config(relay_node, live_params)
    check("Relay 期望配置生成 landing 出站", any(o.get("tag") == "landing" for o in relay_desired["outbounds"]))


def test_sandbox_drift_reconcile_and_rollback():
    init_cfg = templates.exit_config(
        port=443,
        uuid="11111111-1111-4111-8111-111111111111",
        sni="www.apple.com",
        private_key="ORIG_PRIV_KEY",
        sid="abcd1234",
    )
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg_path, sb_bin, env, runner, ssh_calls = remote_config_tests._make_sandbox(tmp, init_cfg)
        node = {
            "name": "硅谷主节点",
            "host": "198.51.100.20",
            "port": 443,
            "uuid": "11111111-1111-4111-8111-111111111111",
            "sni": "www.apple.com",
            "sid": "abcd1234",
            "role": "exit",
            "ssh_user": "root",
            "isp": {"type": "socks", "server": "198.51.100.77", "server_port": 6297, "username": "u", "password": "p"},
        }

        # 未同步前为 drifted，apply=False 不写配置
        before_bytes = Path(cfg_path).read_bytes()
        dry_res = reconcile.reconcile_node(node, apply=False, runner=runner, cfg_path=cfg_path, bin_path=sb_bin, master_secret=SECRET)
        check("检测到现网配置与声明式底账漂移", dry_res["status"] == "drifted" and dry_res["diff_count"] > 0)
        check("dry-run 模式零写入", Path(cfg_path).read_bytes() == before_bytes and not dry_res["applied"])

        # 验证失败自动回滚
        rb_res = reconcile.reconcile_node(
            node,
            apply=True,
            runner=runner,
            verifier=lambda n: {"health": "proxy", "detail": "出口不通"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
            master_secret=SECRET,
        )
        check("收敛后验真失败自动回滚", rb_res["ok"] is False and rb_res["status"] == "rolled_back" and rb_res["rolled_back"] is True)
        check("回滚后现网配置与原始字节完全一致", Path(cfg_path).read_bytes() == before_bytes)

        # 验证成功真正收敛
        ok_res = reconcile.reconcile_node(
            node,
            apply=True,
            runner=runner,
            verifier=lambda n: {"health": "ok", "exit_ip": "198.51.100.77", "exit_country": "US", "detail": "出口 198.51.100.77"},
            cfg_path=cfg_path,
            bin_path=sb_bin,
            master_secret=SECRET,
        )
        check("收敛成功返回 converged", ok_res["ok"] is True and ok_res["status"] == "converged" and ok_res["changed"] is True)
        sync_res = reconcile.inspect_node_drift(node, runner=runner, cfg_path=cfg_path)
        check("收敛后再次检查零漂移 in_sync", sync_res["status"] == "in_sync" and sync_res["diffs"] == [])

        # 非受控节点零远端调用
        for bad_node in (
            {"name": "rj", "host": "198.51.100.3", "source": "reverse_join"},
            {"name": "ext", "host": "198.51.100.4", "source": "external"},
            {"name": "win", "host": "198.51.100.5", "os": "windows"},
        ):
            before_calls = len(ssh_calls)
            res = reconcile.reconcile_node(bad_node, apply=True, runner=runner, cfg_path=cfg_path, master_secret=SECRET)
            check(f"{bad_node['name']} 非受控节点零远端执行", res["status"] == "unmanaged" and len(ssh_calls) == before_calls)


if __name__ == "__main__":
    test_node_capability_modes()
    test_build_desired_config_and_diff_redaction()
    test_sandbox_drift_reconcile_and_rollback()
    print(f"通过 {ok} 项")
