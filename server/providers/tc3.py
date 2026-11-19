#!/usr/bin/env python3
"""腾讯云 Lighthouse 流量查询（TC3-HMAC-SHA256 手写签名，无 SDK 依赖）"""
import base64, hashlib, hmac, json, os, sys, time, urllib.request

CFG = os.environ.get("LADDER_DATA", "/opt/web-data") + "/tc.json"
HOST = "lighthouse.tencentcloudapi.com"
SERVICE = "lighthouse"
VERSION = "2020-03-24"
REGIONS = {"ap-singapore": "新加坡", "na-siliconvalley": "硅谷"}
API_SERVICES = {
    SERVICE: (HOST, VERSION),
    "cvm": ("cvm.tencentcloudapi.com", "2017-03-12"),
    "region": ("region.tencentcloudapi.com", "2022-06-27"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _sign(k, msg):
    return hmac.new(k, msg.encode(), hashlib.sha256).digest()

def call(action, payload, secret_id, secret_key, region, *, service=SERVICE, direct=False):
    host, version = API_SERVICES[service]
    body = json.dumps(payload, separators=(",", ":"))
    ts = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(ts))
    ct = "application/json; charset=utf-8"
    canonical = "POST\n/\n\ncontent-type:%s\nhost:%s\n\ncontent-type;host\n%s" % (ct, host, hashlib.sha256(body.encode()).hexdigest())
    scope = "%s/%s/tc3_request" % (date, service)
    sts = "TC3-HMAC-SHA256\n%d\n%s\n%s" % (ts, scope, hashlib.sha256(canonical.encode()).hexdigest())
    kd = _sign(("TC3" + secret_key).encode(), date)
    ks = _sign(kd, service)
    kg = _sign(ks, "tc3_request")
    sig = hmac.new(kg, sts.encode(), hashlib.sha256).hexdigest()
    auth = "TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=content-type;host, Signature=%s" % (secret_id, scope, sig)
    req = urllib.request.Request(
        "https://" + host, data=body.encode(),
        headers={"Authorization": auth, "Content-Type": ct, "Host": host,
                 "X-TC-Action": action, "X-TC-Version": version,
                 "X-TC-Timestamp": str(ts)},
        method="POST")
    if region:
        req.add_header("X-TC-Region", region)
    open_request = urllib.request.urlopen
    if direct:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        open_request = opener.open
    with open_request(req, timeout=20) as r:
        return json.loads(r.read().decode())

def main():
    with open(CFG, encoding="utf-8") as f:
        cfg = json.load(f)
    out = {}
    for region, label in REGIONS.items():
        try:
            res = call("DescribeInstancesTrafficPackages", {"Limit": 20, "Offset": 0}, cfg["secret_id"], cfg["secret_key"], region)
            resp = res.get("Response", {})
            if "Error" in resp:
                out[label] = {"error": resp["Error"].get("Message", "err")}
                continue
            for p in resp.get("TrafficPackageSet", []):
                out[label] = {
                    "used": round(float(p.get("TrafficUsed", 0)), 2),
                    "total": round(float(p.get("TrafficTotal", 0)), 2),
                }
        except Exception as e:
            out[label] = {"error": str(e)[:80]}
    out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
