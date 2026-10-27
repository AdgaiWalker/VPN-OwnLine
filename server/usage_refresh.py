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

DATA = os.environ.get("LADDER_DATA", "/opt/web-data")


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


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

    if out:
        out["_ts"] = ts
        write_json(os.path.join(DATA, "usage.json"), out)
    else:
        errs.append("用量为空，保留上一次的 usage.json")

    print(json.dumps({
        "servers": [(s.get("provider"), s.get("region"), s.get("name"), s.get("ip")) for s in servers],
        "errors": errs,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
