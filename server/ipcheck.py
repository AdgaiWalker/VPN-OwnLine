#!/usr/bin/env python3
"""每 6 小时：查每个节点 IP 的归属与「是否被标记为机房/代理」，写 iphealth.json

数据源 ip-api.com（免费、无需 key）。只做记录，不做判断——
风险分怎么解读交给人和文档，脚本不给结论。
"""
import json
import os
import time
import urllib.request
from nodekit.store import AtomicJsonStore

NODES = os.environ.get("LADDER_DATA", "/opt/web-data") + "/nodes.json"
OUT = os.environ.get("LADDER_DATA", "/opt/web-data") + "/iphealth.json"
FIELDS = "status,country,regionName,city,isp,org,as,asname,hosting,proxy,mobile"


def query(ip):
    url = "http://ip-api.com/json/%s?fields=%s" % (ip, FIELDS)
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"status": "fail", "error": str(e)[:80]}


def main():
    try:
        with open(NODES, encoding="utf-8") as f:
            nodes = json.load(f)
    except Exception:
        nodes = []
    out = {}
    for n in nodes:
        vps_host = str(n.get("host") or "").strip()
        target_ip = str(n.get("exit_ip") or vps_host).strip()
        if not target_ip or target_ip in out:
            continue
        d = query(target_ip)
        entry = {
            "country": d.get("country", ""),
            "city": d.get("city", ""),
            "asn": (d.get("as") or "").split(" ")[0],
            "org": d.get("org") or d.get("isp") or "",
            "hosting": bool(d.get("hosting")),
            "proxy": bool(d.get("proxy")),
            "mobile": bool(d.get("mobile")),
            "status": d.get("status", "fail"),
        }
        if vps_host and target_ip != vps_host:
            entry["vps_host"] = vps_host
        out[target_ip] = entry
        time.sleep(1.4)  # ip-api 免费额度：45 次/分钟
    out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    AtomicJsonStore.dump(OUT, out)
    print(json.dumps({k: (v.get("asn"), v.get("hosting"), v.get("proxy")) for k, v in out.items() if k != "_ts"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
