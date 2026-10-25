"""腾讯云轻量应用服务器（Lighthouse）适配器。

这是唯一一处知道"腾讯云"三个字的地方。
要接阿里云/华为云/Vultr，照着这个文件再写一份即可。
"""
import json
import os
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from . import tc3
from .base import Provider as Base

WEB = "/opt/web"
CFG = os.path.join(WEB, "tc.json")
SERVERS = os.path.join(WEB, "servers.json")

REGION_CN = {
    "ap-beijing": "北京", "ap-shanghai": "上海", "ap-guangzhou": "广州", "ap-chengdu": "成都",
    "ap-nanjing": "南京", "ap-hongkong": "香港", "ap-singapore": "新加坡", "na-siliconvalley": "硅谷",
    "ap-tokyo": "东京", "ap-seoul": "首尔", "eu-frankfurt": "法兰克福", "ap-jakarta": "雅加达",
    "na-ashburn": "阿什本", "ap-bangkok": "曼谷", "sa-saopaulo": "圣保罗", "ap-johorbahru": "柔佛",
}


def _local_date(iso):
    try:
        return (datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                + timedelta(hours=8)).strftime("%Y-%m-%d")
    except Exception:
        return (iso or "")[:10]


class Provider(Base):
    name = "tencent"

    def available(self):
        try:
            c = json.load(open(CFG, encoding="utf-8"))
            return bool(c.get("secret_id") and c.get("secret_key"))
        except Exception:
            return False

    def _creds(self):
        c = json.load(open(CFG, encoding="utf-8"))
        return c["secret_id"], c["secret_key"]

    def _call(self, action, payload, region="ap-singapore"):
        sid, skey = self._creds()
        return tc3.call(action, payload, sid, skey, region)

    # ---------- 读 ----------

    def list_instances(self):
        servers = []
        try:
            r = self._call("DescribeRegions", {}, "ap-singapore")
            regions = [x.get("Region") for x in r.get("Response", {}).get("RegionSet", [])]
        except Exception:
            regions = list(REGION_CN.keys())
        for reg in regions:
            label = REGION_CN.get(reg, reg)
            try:
                d = self._call("DescribeInstances", {"Limit": 50}, reg)
            except Exception:
                continue
            for i in d.get("Response", {}).get("InstanceSet", []):
                ip = (i.get("PublicAddresses") or [""])[0]
                servers.append({
                    "name": i.get("InstanceName") or "",
                    "ip": ip,
                    "id": i.get("InstanceId") or "",
                    "expire": _local_date(i.get("ExpiredTime") or ""),
                    "state": i.get("InstanceState") or "",
                    "region": label,
                    "regionId": reg,
                    "provider": "tencent",
                })
        return servers

    def traffic(self):
        out = {}
        by_ip = {s["ip"]: s for s in self._servers()}
        regions = sorted({s["regionId"] for s in by_ip.values() if s.get("regionId")})
        for reg in regions:
            label = REGION_CN.get(reg, reg)
            id2ip = {s["id"]: s["ip"] for s in by_ip.values() if s.get("regionId") == reg}
            if not id2ip:
                continue
            try:
                t = self._call("DescribeInstancesTrafficPackages", {"Limit": 50, "Offset": 0}, reg)
            except Exception:
                continue
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
        for s in by_ip.values():
            if s["ip"] in out and s.get("expire"):
                out[s["ip"]]["expire"] = s["expire"]
        return out

    def _servers(self):
        """优先用上次刷新缓存（10 分钟），没有再现场枚举。"""
        try:
            s = json.load(open(SERVERS, encoding="utf-8")).get("servers", [])
            if any(x.get("provider") == "tencent" or "lhins-" in (x.get("id") or "") for x in s):
                return s
        except Exception:
            pass
        return self.list_instances()

    def _find(self, ip):
        for s in self._servers():
            if s.get("ip") == ip:
                return s
        return None

    # ---------- 写 ----------

    def open_port(self, ip, port, dry_run=False):
        inst = self._find(ip)
        if not inst:
            return ("skip", "")
        if dry_run:
            return ("dry", "会在腾讯云放行 TCP %s（未执行）" % port)
        region = inst.get("regionId") or "ap-singapore"
        iid = inst.get("id")
        try:
            r = self._call("DescribeFirewallRules", {"InstanceId": iid, "Limit": 100, "Offset": 0}, region)
            for x in (r.get("Response") or {}).get("FirewallRuleSet", []):
                if str(x.get("Port")) == str(port) and (x.get("Protocol") or "").upper() == "TCP":
                    return ("already", "TCP %s 已经是放行状态" % port)
            c = self._call("CreateFirewallRules", {"InstanceId": iid, "FirewallRules": [{
                "Protocol": "TCP", "Port": str(port), "CidrBlock": "0.0.0.0/0",
                "Action": "ACCEPT", "FirewallRuleDescription": "sing-box"}]}, region)
            e = (c.get("Response") or {}).get("Error")
            if e:
                return ("fail", (e.get("Message") or "")[:120])
            return ("opened", "已在腾讯云控制台自动放行 TCP %s" % port)
        except Exception as e:
            return ("fail", str(e)[:120])

    def reset_password(self, ip, dry_run=False):
        inst = self._find(ip)
        if not inst:
            return ("skip", "", {})
        if dry_run:
            return ("dry", "会把 %s 的 root 密码重置并重启（未执行）" % inst.get("name", ip), {})
        region = inst.get("regionId") or "ap-singapore"
        pw = "Tz" + _uuid.uuid4().hex[:10] + "!9a"
        try:
            r1 = self._call("ResetInstancesPassword",
                            {"InstanceIds": [inst["id"]], "Password": pw, "UserName": "root"}, region)
            e1 = (r1.get("Response") or {}).get("Error")
            if e1:
                code = e1.get("Code", "")
                if "NoPermission" in code or "Unauthorized" in code:
                    return ("fail", "没有重置密码的权限：需要给子账号加「轻量应用服务器全读写」", {})
                return ("fail", "重置失败：" + (e1.get("Message") or "")[:120], {})
            reboot = True
            try:
                r2 = self._call("RebootInstances", {"InstanceIds": [inst["id"]]}, region)
                reboot = not (r2.get("Response") or {}).get("Error")
            except Exception:
                reboot = False
            return ("opened", "已在腾讯云重置 root 密码", {"password": pw, "reboot": reboot})
        except Exception as e:
            return ("fail", str(e)[:120], {})
