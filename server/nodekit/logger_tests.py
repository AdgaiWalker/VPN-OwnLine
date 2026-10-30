import os
import shutil
import sys
import tempfile

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

    for i in range(60):
        logger.log("INFO", "TEST", f"msg {i}")
    logger.rotate_if_needed(max_lines=30)
    rot_logs = logger.read_logs(limit=100)
    check("超限自动截断", len(rot_logs) <= 30)

    res = logger.get_syslog("evil_service")
    check("非法服务白名单拦截", not res["ok"] and "不允许" in res["error"])

    res2 = logger.get_syslog("sing-box", lines=20)
    check("合法服务白名单允许", "error" not in res2 or "不允许" not in res2["error"])

finally:
    logger.DATA = old_data
    logger.LOG_FILE = old_log_file
    shutil.rmtree(tmpdir, ignore_errors=True)

print("通过 %d 项" % ok)
