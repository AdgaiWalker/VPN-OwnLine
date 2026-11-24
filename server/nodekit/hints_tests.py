"""hints 单元测试：全离网且零命令行术语泄漏。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import hints

ok = 0
FORBIDDEN_CLI_TOKENS = (
    "journalctl",
    "curl -I",
    "authorized_keys",
    "配 sudo 免密",
    "sudo bash",
    "一键自愈修复",
)


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


check("配置校验失败有专属提示", "校验" in hints.hint_from_log(["配置校验失败：decode short_id"]) and "未改动" in hints.hint_from_log(["配置校验失败：x"]))
check("服务起不来指引管理后台日志", "核心服务日志" in hints.hint_from_log(["安装失败：服务没有启动成功"]))
check("下载全失败指引查带宽而非命令行 curl", "带宽" in hints.hint_from_log(["全部下载源都失败"]))
check("密码错提示重置密码或改用私钥", "私钥" in hints.hint_from_log(["Permission denied (publickey)."]))
check("sudo 密码提示改用 root 或云商免密账号", "root" in hints.hint_from_log(["sudo: a password is required"]) and "ubuntu" in hints.hint_from_log(["sudo: a password is required"]))
check("curl 失败归到下载", "下载" in hints.hint_from_log(["curl: (7) Failed to connect"]))
check("22 端口提示查防火墙", "22 端口" in hints.hint_from_log(["ssh: connect to host 1.2.3.4 port 22: Connection timed out"]))
check("架构不支持", "x86_64" in hints.hint_from_log(["unsupported arch：armv7l"]))
check("磁盘满", "系统盘" in hints.hint_from_log(["tar: write error: No space left on device"]))
check("预检原因原样带出", "这台是 centos 7" in hints.hint_from_log(["预检未通过：这台是 centos 7，不在支持范围"]))
check("兜底不会空着", len(hints.hint_from_log([])) > 10)
check("兜底提到密码与端口", "密码" in hints.hint_from_log(["something weird happened"]) and "80" in hints.hint_from_log(["something weird happened"]))

check("私钥被拒有专属图形引导", "私钥" in hints.hint_from_log(["root@1.2.3.4: Permission denied (publickey)."]))
check("私钥被拒（publickey,password 变体）", "重置密码" in hints.hint_from_log(["root@1.2.3.4: Permission denied (publickey,password)."]))
check("端口冲突给出诚实排障提示且不承诺不存在的自愈按钮", "空白" in hints.hint_from_log(["listen tcp 0.0.0.0:8443: bind: address already in use"]))
check("Windows端口冲突识别", "8443" in hints.hint_from_log(["failed to bind: WSAEADDRINUSE"]))

for sample in (
    hints.DEFAULT,
    *[text for _, text in hints.RULES],
):
    for bad in FORBIDDEN_CLI_TOKENS:
        assert bad not in sample, f"hints.py 不得包含命令行或无效术语 {bad!r}: {sample}"
ok += 1
print("  OK 全量 hints 零 CLI 泄漏门禁")

print("通过 %d 项" % ok)
