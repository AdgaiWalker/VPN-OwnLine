import os
import json
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nodekit import logger

ok = 0


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        sys.stderr.write("FAIL: %s %s\n" % (name, extra))
        sys.exit(1)


tmpdir = tempfile.mkdtemp()
old_data = logger.DATA
old_log_file = logger.LOG_FILE
logger.DATA = tmpdir
logger.LOG_FILE = os.path.join(tmpdir, "events.log")

try:
    logger.log("INFO", "SUB", "客户端拉取订阅成功")
    logger.log("WARN", "PROBE", "节点北京国内连不上")
    logger.log("ERROR", "ALERT", "连续失败告警触发")

    logs = logger.read_logs()
    check("日志写入并倒序读取", len(logs) == 3 and logs[0]["level"] == "ERROR")
    check("日志字段结构正确", logs[0]["src"] == "ALERT" and "告警触发" in logs[0]["msg"])

    bad = logger.read_logs(level_filter="BAD")
    check("按 BAD 级别过滤 (WARN+ERROR)", len(bad) == 2 and bad[0]["level"] == "ERROR")

    info_only = logger.read_logs(level_filter="INFO")
    check("按 INFO 级别过滤", len(info_only) == 1 and info_only[0]["src"] == "SUB")

    sub_only = logger.read_logs(src_filter="SUB")
    check("按来源过滤 (SUB)", len(sub_only) == 1 and sub_only[0]["msg"] == "客户端拉取订阅成功")

    with open(logger.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "old", "level": "WARN", "src": "ADMIN",
                            "msg": "非法 Token=oldsecret 新订阅: https://example.test/s/subsecret/sr",
                            "details": {"SecretKey": "cloudsecret", "nested": [{"password": "pwsecret"}]}}) + "\n")
    historical = json.dumps(logger.read_logs(limit=1), ensure_ascii=False)
    check("历史结构化日志中订阅 token 脱敏", "oldsecret" not in historical and "subsecret" not in historical)
    check("历史嵌套字段中的密钥与密码脱敏", "cloudsecret" not in historical and "pwsecret" not in historical)
    logger.log("INFO", "TEST", 'SecretId=akidvalue password="mypass" vless://privateproxy')
    with open(logger.LOG_FILE, encoding="utf-8") as f:
        written = f.read()
    check("新日志写入前屏蔽常见凭据和代理链接", "akidvalue" not in written and "mypass" not in written and "privateproxy" not in written)
    check("私钥 PEM 整段脱敏", "privatepem" not in logger.redact_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nprivatepem\n-----END OPENSSH PRIVATE KEY-----"))
    check("Bearer 令牌脱敏", "authsecret" not in logger.redact_text("Authorization: Bearer authsecret"))

    for i in range(60):
        logger.log("INFO", "TEST", f"msg {i}")
    logger.rotate_if_needed(max_lines=30)
    rot_logs = logger.read_logs(limit=100)
    check("超限自动截断", len(rot_logs) <= 30)

    res = logger.get_syslog("evil_service")
    check("非法服务白名单拦截", not res["ok"] and "不允许" in res["error"])

    res2 = logger.get_syslog("sing-box", lines=20)
    check("合法服务白名单允许", "error" not in res2 or "不允许" not in res2["error"])
    pem_output = ("运行日志\n-----BEGIN OPENSSH PRIVATE KEY-----\nprivatebodysecret\n"
                  "-----END OPENSSH PRIVATE KEY-----\n任务结束\n")
    mock_result = SimpleNamespace(returncode=0, stdout=pem_output, stderr="")
    with patch.object(logger.os.path, "exists", return_value=True), patch.object(logger.subprocess, "run", return_value=mock_result):
        result = logger.get_syslog("sing-box")
        check("文件日志跨行私钥完整脱敏", "privatebodysecret" not in "\n".join(result["lines"]) and "任务结束" in result["lines"])
    with patch.object(logger.os.path, "exists", return_value=False), patch.object(logger.subprocess, "run", return_value=mock_result):
        result = logger.get_syslog("admin")
        check("系统日志跨行私钥完整脱敏", "privatebodysecret" not in "\n".join(result["lines"]) and "任务结束" in result["lines"])

finally:
    logger.DATA = old_data
    logger.LOG_FILE = old_log_file
    shutil.rmtree(tmpdir, ignore_errors=True)

print("通过 %d 项" % ok)
