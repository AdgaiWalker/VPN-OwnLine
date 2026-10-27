#!/usr/bin/env python3
"""配置漂移检查：线上配置能不能被模板原样生成？

用法：
    python3 scripts/drift.py walker-sv walker-bj

做法是「往返比对」：从线上配置里取出参数，用 templates 重新生成一遍，
再和线上逐字段比。一样 = 模板覆盖了这台机器的全部现状；不一样 = 有人手改过。

为什么需要它：2026-10-27 之前，硅谷的 HY2 入站不在模板里，
模板只是「安装那一刻用过一次」，之后所有改动都是手工的。这个脚本就是让漂移可见。
"""
import json
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from nodekit import templates  # noqa: E402


def live_config(host):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
           "sudo -n cat /opt/sing-box/config.json"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise SystemExit("读不到 %s 的配置：%s" % (host, (out.stderr or "")[:120]))
    return json.loads(out.stdout)


def diff(a, b, path="", acc=None):
    """返回差异列表（只比 JSON 结构，不看键顺序）。"""
    acc = [] if acc is None else acc
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        acc.append("%s: 类型不同 %s vs %s" % (path or "根", type(a).__name__, type(b).__name__))
        return acc
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                acc.append("%s.%s: 线上没有" % (path, k))
            elif k not in b:
                acc.append("%s.%s: 模板没有" % (path, k))
            else:
                diff(a[k], b[k], "%s.%s" % (path, k), acc)
    elif isinstance(a, list):
        if len(a) != len(b):
            acc.append("%s: 元素数不同 线上 %d vs 模板 %d" % (path, len(a), len(b)))
        for i in range(min(len(a), len(b))):
            diff(a[i], b[i], "%s[%d]" % (path, i), acc)
    else:
        if a != b:
            acc.append("%s: 线上 %r vs 模板 %r" % (path, a, b))
    return acc


def render_from_live(cfg):
    """从线上配置反推参数，再用模板生成一遍。"""
    ib = cfg["inbounds"][0]
    reality = ib["tls"]["reality"]
    params = dict(
        port=ib["listen_port"],
        uuid=ib["users"][0]["uuid"],
        sni=ib["tls"]["server_name"],
        private_key=reality["private_key"],
        sid=reality["short_id"][0],
    )
    hy2 = next((i for i in cfg["inbounds"] if i.get("type") == "hysteria2"), None)
    if hy2:
        params["hy2"] = {
            "port": hy2["listen_port"],
            "password": hy2["users"][0]["password"],
            "obfs_password": hy2["obfs"]["password"],
            "sni": hy2["tls"]["server_name"],
        }
    landing = next((o for o in cfg["outbounds"] if o.get("tag") == "landing"), None)
    if landing:
        lr = landing["tls"]["reality"]
        params["landing"] = dict(host=landing["server"], port=landing["server_port"],
                                 uuid=landing["uuid"], sni=landing["tls"]["server_name"],
                                 pbk=lr["public_key"], sid=lr["short_id"])
        return templates.relay_config(**params)
    return templates.exit_config(**params)


def main():
    hosts = sys.argv[1:] or ["walker-sv", "walker-bj"]
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
