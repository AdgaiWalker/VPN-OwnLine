#!/usr/bin/env python3
"""每 6 小时：查每个节点 IP 的归属与「是否被标记为机房/代理」，写 iphealth.json

数据源 ip-api.com（免费、无需 key）。只做记录，不做判断——
风险分怎么解读交给人和文档，脚本不给结论。
"""
import json
import os
import time
import urllib.request

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
        nodes = json.load(open(NODES, encoding="utf-8"))
    except Exception:
        nodes = []
    out = {}
    for n in nodes:
        ip = n.get("host")
        if not ip:
            continue
        d = query(ip)
        out[ip] = {
            "country": d.get("country", ""),
            "city": d.get("city", ""),
            "asn": (d.get("as") or "").split(" ")[0],
            "org": d.get("org") or d.get("isp") or "",
            "hosting": bool(d.get("hosting")),
            "proxy": bool(d.get("proxy")),
            "mobile": bool(d.get("mobile")),
            "status": d.get("status", "fail"),
        }
        time.sleep(1.4)  # ip-api 免费额度：45 次/分钟
    out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: (v.get("asn"), v.get("hosting"), v.get("proxy")) for k, v in out.items() if k != "_ts"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
