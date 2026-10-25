#!/usr/bin/env python3
"""每 10 分钟：枚举全部地域的轻量服务器 + 流量，写 servers.json / usage.json"""
import json, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/opt/web")
import usage

REGION_CN = {
    "ap-beijing": "北京", "ap-shanghai": "上海", "ap-guangzhou": "广州", "ap-chengdu": "成都",
    "ap-nanjing": "南京", "ap-hongkong": "香港", "ap-singapore": "新加坡", "na-siliconvalley": "硅谷",
    "ap-tokyo": "东京", "ap-seoul": "首尔", "eu-frankfurt": "法兰克福", "ap-jakarta": "雅加达",
    "na-ashburn": "阿什本", "ap-bangkok": "曼谷", "sa-saopaulo": "圣保罗", "ap-johorbahru": "柔佛",
}

def loc(iso):
    try:
        return (datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
    except Exception:
        return (iso or "")[:10]

def main():
    cfg = json.load(open("/opt/web/tc.json", encoding="utf-8"))
    sid, skey = cfg["secret_id"], cfg["secret_key"]
    regions = []
    try:
        r = usage.call("DescribeRegions", {}, sid, skey, "ap-singapore")
        regions = [x.get("Region") for x in r.get("Response", {}).get("RegionSet", [])]
    except Exception:
        regions = list(REGION_CN.keys())

    servers, out = [], {}
    for reg in regions:
        label = REGION_CN.get(reg, reg)
        id2ip = {}
        try:
            d = usage.call("DescribeInstances", {"Limit": 50}, sid, skey, reg)
            for i in d.get("Response", {}).get("InstanceSet", []):
                ip = (i.get("PublicAddresses") or [""])[0]
                id2ip[i.get("InstanceId")] = ip
                servers.append({
                    "name": i.get("InstanceName") or "",
                    "ip": ip,
                    "id": i.get("InstanceId") or "",
                    "expire": loc(i.get("ExpiredTime") or ""),
                    "state": i.get("InstanceState") or "",
                    "region": label,
                    "regionId": reg,
                })
        except Exception:
            pass
        if not id2ip:
            continue
        try:
            t = usage.call("DescribeInstancesTrafficPackages", {"Limit": 50, "Offset": 0}, sid, skey, reg)
            for inst in t.get("Response", {}).get("InstanceTrafficPackageSet", []):
                ip = id2ip.get(inst.get("InstanceId"))
                if not ip:
                    continue
                for p in inst.get("TrafficPackageSet", []):
                    out[ip] = {
                        "used": round(p.get("TrafficUsed", 0) / 1073741824, 2),
                        "total": round(p.get("TrafficPackageTotal", 0) / 1073741824, 0),
                        "start": (p.get("StartTime") or "")[:10],
                        "end": (p.get("EndTime") or "")[:10],
                        "overflow": p.get("TrafficOverflow", 0),
                        "region": label,
                    }
        except Exception:
            pass

    for s in servers:
        if s["ip"] in out and s["expire"]:
            out[s["ip"]]["expire"] = s["expire"]
    out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(out, open("/opt/web/usage.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"servers": servers, "_ts": out["_ts"]}, open("/opt/web/servers.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"servers": [(s["region"], s["name"], s["ip"]) for s in servers]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
