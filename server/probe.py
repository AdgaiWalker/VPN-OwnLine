#!/usr/bin/env python3
import json, socket, subprocess, time

nodes = json.load(open("/opt/web/nodes.json", encoding="utf-8"))
out = {}
for n in nodes:
    t0 = time.time()
    ok = False
    reason = ""
    try:
        s = socket.create_connection((n["host"], int(n["port"])), timeout=4)
        s.close()
    except Exception:
        out[n["name"]] = {"ok": False, "ms": 0, "reason": "port"}
        continue
    try:
        p = subprocess.run(["bash", "-c", "echo | timeout 6 openssl s_client -connect %s:%s -servername %s 2>&1" % (n["host"], n["port"], n["sni"])],
                           capture_output=True, text=True, timeout=10)
        ok = "CONNECTED" in p.stdout
        if not ok:
            reason = "tls"
    except Exception:
        reason = "tls"
    out[n["name"]] = {"ok": ok, "ms": int((time.time() - t0) * 1000) if ok else 0, "reason": reason}
out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
json.dump(out, open("/opt/web/status.json", "w", encoding="utf-8"), ensure_ascii=False)
