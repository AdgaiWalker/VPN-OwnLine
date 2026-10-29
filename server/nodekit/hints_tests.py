"""hints 单元测试：全离网。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import hints

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


check("配置校验失败有专属提示", "校验" in hints.hint_from_log(["配置校验失败：decode short_id"]) and "机器没被动过" in hints.hint_from_log(["配置校验失败：x"]))
check("服务起不来提示看 journalctl", "journalctl" in hints.hint_from_log(["安装失败：服务没有启动成功"]))
check("下载全失败提示测外网", "curl -I" in hints.hint_from_log(["全部下载源都失败"]))
check("密码错提示改私钥", "私钥" in hints.hint_from_log(["Permission denied (publickey)."]))
check("sudo 密码提示换 root", "root" in hints.hint_from_log(["sudo: a password is required"]))
check("curl 失败归到下载", "下载" in hints.hint_from_log(["curl: (7) Failed to connect"]))
check("22 端口提示查防火墙", "22 端口" in hints.hint_from_log(["ssh: connect to host 1.2.3.4 port 22: Connection timed out"]))
check("架构不支持", "x86_64" in hints.hint_from_log(["unsupported arch：armv7l"]))
check("磁盘满", "磁盘" in hints.hint_from_log(["tar: write error: No space left on device"]))
check("预检原因原样带出", "这台是 centos 7" in hints.hint_from_log(["预检未通过：这台是 centos 7，不在支持范围"]))
check("兜底不会空着", len(hints.hint_from_log([])) > 10)
check("兜底提到密码", "密码" in hints.hint_from_log(["something weird happened"]))

check("私钥被拒有专属提示", "authorized_keys" in hints.hint_from_log(["root@1.2.3.4: Permission denied (publickey)."]))
check("私钥被拒（publickey,password 变体）", "authorized_keys" in hints.hint_from_log(["root@1.2.3.4: Permission denied (publickey,password)."]))
print("通过 %d 项" % ok)
