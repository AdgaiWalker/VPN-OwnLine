#!/usr/bin/env python3
"""配置漂移与声明式状态收敛检查工具。

用法：
    1) 现网主机配置模板往返比对：
       python3 scripts/drift.py <ssh-host-1> [ssh-host-2 ...]
    2) 控制面底账与现网声明式收敛检查 / 对齐：
       python3 scripts/drift.py --nodes /opt/web-data/nodes.json [--name <node>] [--reconcile] [--json]
"""
import argparse
import json
import os
import subprocess
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _cand in (os.path.join(_ROOT, "server"), _ROOT):
    if os.path.isdir(os.path.join(_cand, "nodekit")) and _cand not in sys.path:
        sys.path.insert(0, _cand)
from nodekit import reconcile, remote_config, templates  # noqa: E402
from nodekit.node_manager import FileNodeStore, NodeManager  # noqa: E402


def live_config(host):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
           "sudo -n cat /opt/sing-box/config.json"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise SystemExit("读不到 %s 的配置：%s" % (host, (out.stderr or "")[:120]))
    return json.loads(out.stdout)


def diff(a, b, path="", acc=None):
    """返回结构化差异列表（忽略字典键序）。"""
    result = reconcile.diff_configs(a, b, path=path, redact=True)
    if acc is not None:
        acc.extend(result)
        return acc
    return result


def render_from_live(cfg):
    """从线上 config.json 反推完整参数（含 HY2 / ISP / WARP / Relay），再由模板渲染对比。"""
    params = remote_config.extract_live_params(cfg)
    landing = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "landing"), None)
    if landing:
        lr = (landing.get("tls") or {}).get("reality") or {}
        fallback = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "landing-fallback"), None)
        fallback_landing = None
        if fallback:
            fr = (fallback.get("tls") or {}).get("reality") or {}
            fallback_landing = dict(
                host=fallback["server"],
                port=fallback["server_port"],
                uuid=fallback["uuid"],
                sni=(fallback.get("tls") or {}).get("server_name") or fallback["server"],
                pbk=fr.get("public_key", ""),
                sid=fr.get("short_id", ""),
            )
        return templates.relay_config(
            port=params["port"],
            uuid=params["uuid"],
            sni=params["sni"],
            private_key=params["private_key"],
            sid=params["sid"],
            landing=dict(
                host=landing["server"],
                port=landing["server_port"],
                uuid=landing["uuid"],
                sni=(landing.get("tls") or {}).get("server_name") or landing["server"],
                pbk=lr.get("public_key", ""),
                sid=lr.get("short_id", ""),
            ),
            fallback_landing=fallback_landing,
        )
    return templates.exit_config(
        port=params["port"],
        uuid=params["uuid"],
        sni=params["sni"],
        private_key=params["private_key"],
        sid=params["sid"],
        hy2=params.get("hy2"),
        isp=params.get("isp"),
        warp=params.get("warp"),
    )


def _run_nodes_mode(args):
    store = FileNodeStore(args.nodes)
    nodes = store.load()
    if args.reconcile:
        nm = NodeManager(store=store, remote_cfg_mod=remote_config)
        cluster = reconcile.inspect_cluster_drift(nodes, target_name=args.name)
        results = []
        for item in cluster["results"]:
            if item.get("status") == "drifted":
                results.append(nm.reconcile_node(item["name"], apply=True))
            else:
                results.append(item)
        summary = {
            "ok": all(r.get("ok") for r in results) and not any(r.get("status") == "drifted" for r in results),
            "results": results,
        }
    else:
        summary = reconcile.inspect_cluster_drift(nodes, target_name=args.name)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for r in summary["results"]:
            st = r.get("status")
            name = r.get("name") or r.get("host")
            if st in ("in_sync", "converged"):
                print("✓ %s (%s): %s" % (name, r.get("host"), st))
            elif st == "unmanaged":
                print("- %s (%s): unmanaged [%s]" % (name, r.get("host"), (r.get("capability") or {}).get("mode", "")))
            elif st == "drifted":
                print("✗ %s (%s): drifted (%d 处)" % (name, r.get("host"), r.get("diff_count", 0)))
                for d in (r.get("diffs") or [])[:12]:
                    print("    " + d)
            else:
                print("✗ %s (%s): %s (%s)" % (name, r.get("host"), st, r.get("error") or ""))

    has_bad = any(r.get("status") in ("drifted", "error", "rolled_back") or not r.get("ok") for r in summary["results"])
    return 1 if has_bad else 0


def main():
    parser = argparse.ArgumentParser(description="检查或收敛 sing-box 配置漂移")
    parser.add_argument("hosts", nargs="*", help="SSH 主机名列表（往返模板比对）")
    parser.add_argument("--nodes", help="控制面 nodes.json 路径（声明式漂移比对）")
    parser.add_argument("--name", help="仅检查或收敛指定名称的节点")
    parser.add_argument("--reconcile", action="store_true", help="将已产生漂移的受控节点收敛至期望配置")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    if args.nodes:
        return _run_nodes_mode(args)

    env_hosts = [h for h in os.environ.get("LADDER_DRIFT_HOSTS", "").split() if h]
    hosts = args.hosts or env_hosts
    if not hosts:
        parser.print_usage(sys.stderr)
        return 2
    bad = 0
    for host in hosts:
        cfg = live_config(host)
        want = render_from_live(cfg)
        d = diff(cfg, want)
        if d:
            bad += 1
            print("✗ %s 漂移 %d 处" % (host, len(d)))
            for x in d[:12]:
                print("    " + x)
        else:
            print("✓ %s 与模板一致" % host)
    print()
    print("结论：" + ("全部一致，模板覆盖了现状" if not bad else "%d 台存在漂移" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
