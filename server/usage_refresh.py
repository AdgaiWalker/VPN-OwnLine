#!/usr/bin/env python3
"""每 10 分钟：问所有已接入的云要实例和流量，写 servers.json / usage.json

不认识的云不会报错，只是不出现而已。
"""
import json
import sys
import time

sys.path.insert(0, "/opt/web")
import providers

WEB = "/opt/web"


def main():
    inst = providers.load_all()

    servers = []
    for p in inst:
        try:
            servers += p.list_instances()
        except Exception:
            pass

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump({"servers": servers, "_ts": ts}, open(WEB + "/servers.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    out = {}
    for p in inst:
        try:
            out.update(p.traffic())
        except Exception:
            pass
    out["_ts"] = ts
    json.dump(out, open(WEB + "/usage.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(json.dumps({"servers": [(s.get("provider"), s.get("region"), s.get("name"), s.get("ip")) for s in servers]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
