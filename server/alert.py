#!/usr/bin/env python3
"""状态变化告警与死人开关（纯标准库，零额外依赖）。

规则：
  1. 连续 2 轮（约 2 分钟）探活失败（海外 ok=False 或国内 cn_ok=False）才发红灯告警（防抖）。
  2. 从「已告警」状态恢复正常时，发一条恢复通知。
  3. 每轮探活后若配置了 heartbeat_url（如 healthchecks.io 免费档），顺手 ping 一下：
     主控整机挂掉超过阈值时，由外部死人开关向手机发告警。
  4. 配置文件 /opt/web-data/alert.json 可选：未配置时只更新状态机文件 alert_state.json，不报错。
"""
import json
import os
import time
import urllib.parse
import urllib.request

DATA = os.environ.get("LADDER_DATA", "/opt/web-data")
CFG_PATH = os.path.join(DATA, "alert.json")
STATE_PATH = os.path.join(DATA, "alert_state.json")
STATUS_PATH = os.path.join(DATA, "status.json")
FAIL_THRESHOLD = 2


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def evaluate(status, prev_state, fail_threshold=FAIL_THRESHOLD):
    """纯函数：输入本轮 status 与上一轮 state，返回 (new_state, messages)。"""
    nodes_prev = (prev_state or {}).get("nodes") or {}
    nodes_next = {}
    msgs = []

    for name, st in (status or {}).items():
        if name.startswith("_") or not isinstance(st, dict):
            continue
        p = dict(nodes_prev.get(name) or {"streak": 0, "alerted": False, "reason": ""})
        bad_reason = ""
        if st.get("ok") is False:
            bad_reason = "海外探活失败(%s)" % (st.get("reason") or "port")
        elif st.get("cn_ok") is False:
            bad_reason = "国内连不上/疑似被墙(%s)" % (st.get("cn_reason") or "port")

        if bad_reason:
            p["streak"] = int(p.get("streak") or 0) + 1
            p["reason"] = bad_reason
            if p["streak"] >= fail_threshold and not p.get("alerted"):
                p["alerted"] = True
                msgs.append("🔴 节点异常：%s — %s（连续 %d 次）" % (name, bad_reason, p["streak"]))
        else:
            if p.get("alerted"):
                ms_txt = "%dms" % st["ms"] if st.get("ms") is not None else "ok"
                if st.get("cn_ms") is not None:
                    ms_txt += " / 国内 %dms" % st["cn_ms"]
                msgs.append("🟢 节点恢复：%s（%s）" % (name, ms_txt))
            p["streak"] = 0
            p["alerted"] = False
            p["reason"] = ""
        nodes_next[name] = p

    new_state = {
        "nodes": nodes_next,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return new_state, msgs


def send_message(cfg, text):
    """按 alert.json 发送单条文本（支持 Telegram Bot 与通用 Webhook）。"""
    if not cfg or not text:
        return False
    sent = False
    tg_token = (cfg.get("telegram_bot_token") or "").strip()
    tg_chat = (cfg.get("telegram_chat_id") or "").strip()
    if tg_token and tg_chat:
        url = "https://api.telegram.org/bot%s/sendMessage" % tg_token
        body = urllib.parse.urlencode({"chat_id": tg_chat, "text": text}).encode()
        try:
            req = urllib.request.Request(url, data=body, method="POST")
            with urllib.request.urlopen(req, timeout=8) as r:
                sent = (r.status == 200) or sent
        except Exception:
            pass

    webhook = (cfg.get("webhook_url") or "").strip()
    if webhook:
        try:
            payload = json.dumps({"text": text, "content": text}, ensure_ascii=False).encode()
            req = urllib.request.Request(webhook, data=payload,
                                         headers={"Content-Type": "application/json; charset=utf-8"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=8) as r:
                sent = (200 <= r.status < 300) or sent
        except Exception:
            pass
    return sent


def ping_heartbeat(cfg):
    hb = ((cfg or {}).get("heartbeat_url") or "").strip()
    if not hb:
        return False
    try:
        with urllib.request.urlopen(hb, timeout=6) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def check_and_notify(status=None):
    if status is None:
        status = _load_json(STATUS_PATH, {})
    prev = _load_json(STATE_PATH, {})
    new_state, msgs = evaluate(status, prev)
    _save_json(STATE_PATH, new_state)
    cfg = _load_json(CFG_PATH, {})
    for m in msgs:
        try:
            from nodekit import logger
            lvl = "ERROR" if m.get("level") == "alert" else "SUCCESS"
            logger.log(lvl, "ALERT", m.get("title", "") + ": " + m.get("content", ""))
        except Exception:
            pass
        send_message(cfg, m)
    ping_heartbeat(cfg)
    return msgs


if __name__ == "__main__":
    for m in check_and_notify():
        print(m)
