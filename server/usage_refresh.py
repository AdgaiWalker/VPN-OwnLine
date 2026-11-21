#!/usr/bin/env python3
"""每 10 分钟：问所有已接入的云要实例和流量，写 servers.json / usage.json

规矩：**查询失败就不覆盖旧文件**。一次 API 抖动不该让面板显示"你没有服务器"。
"""
import json
import os
import sys
import time

sys.path.insert(0, "/opt/web")
import providers
from nodekit.store import AtomicJsonStore

DATA = os.environ.get("LADDER_DATA", "/opt/web-data")


def write_json(path, data):
    AtomicJsonStore.dump(path, data)


def main():
    inst = providers.load_all()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    errs = []

    servers = []
    for p in inst:
        try:
            servers += p.list_instances()
        except Exception as e:
            errs.append("%s: %s" % (getattr(p, "name", "?"), str(e)[:80]))

    if servers:
        write_json(os.path.join(DATA, "servers.json"), {"servers": servers, "_ts": ts})
    else:
        errs.append("实例列表为空，保留上一次的 servers.json")

    out = {}
    for p in inst:
        try:
            got = p.traffic()
            if got:
                out.update(got)
        except Exception as e:
            errs.append("%s traffic: %s" % (getattr(p, "name", "?"), str(e)[:80]))

    # 保底：对未接入云 API 的通用 Linux 节点，直接读取 /proc/net/dev 物理网卡流量
    try:
        nodes_file = os.path.join(DATA, "nodes.json")
        if os.path.exists(nodes_file):
            from nodekit import host_traffic
            nodes_data = json.load(open(nodes_file, encoding="utf-8"))
            for n in (nodes_data or []):
                host = n.get("host")
                if host and host not in out and n.get("source") != "external":
                    ht = host_traffic.collect_remote_traffic(n)
                    if ht:
                        out[host] = ht
    except Exception as e:
        errs.append("host_traffic fallback: %s" % str(e)[:80])

    if out:
        out["_ts"] = ts
        write_json(os.path.join(DATA, "usage.json"), out)

        # 多维度流量时序与日/周/月/年消耗统计
        try:
            from nodekit import traffic_stats
            hist_file = os.path.join(DATA, "traffic_history.json")
            history = {}
            if os.path.exists(hist_file):
                try:
                    history = json.load(open(hist_file, encoding="utf-8"))
                except Exception:
                    history = {}
            for host, item in out.items():
                if not host.startswith("_") and isinstance(item, dict):
                    traffic_stats.record_history_snapshot(history, item, host)
            write_json(hist_file, history)

            nodes_file = os.path.join(DATA, "nodes.json")
            active_nodes = None
            if os.path.exists(nodes_file):
                try:
                    active_nodes = json.load(open(nodes_file, encoding="utf-8"))
                except Exception:
                    active_nodes = None

            stats_report = traffic_stats.aggregate_all_traffic_stats(out, history, active_nodes=active_nodes)
            write_json(os.path.join(DATA, "traffic_stats.json"), stats_report)
        except Exception as e:
            errs.append("traffic_stats: %s" % str(e)[:80])

        # 流量 85% 水位物理断流与自愈守护
        try:
            if active_nodes is not None:
                nodes = active_nodes
            else:
                nodes_file = os.path.join(DATA, "nodes.json")
                nodes = json.load(open(nodes_file, encoding="utf-8")) if os.path.exists(nodes_file) else []
                from nodekit import quota_guard
                actions = quota_guard.enforce_quota(nodes, out)
                if actions:
                    print("Quota actions:", json.dumps(actions, ensure_ascii=False))
        except Exception as e:
            errs.append("quota enforce: %s" % str(e)[:80])
    else:
        errs.append("用量为空，保留上一次的 usage.json")

    print(json.dumps({
        "servers": [(s.get("provider"), s.get("region"), s.get("name"), s.get("ip")) for s in servers],
        "errors": errs,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
