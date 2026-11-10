"""把安装日志翻译成「发生了什么 + 下一步做什么」。

纯函数：吃日志行，吐一句中文。不读文件、不发请求，所以能离线单测。
"""
import re

DEFAULT = "看下面的原始输出。常见原因：密码错、22 端口没开、服务器不是 Linux、或者这台机器不接受密码登录。"

# 顺序即优先级：越具体的越靠前
RULES = [
    ("配置校验失败", "生成的配置没通过 sing-box 校验，机器没被动过。\n把上面那行报错贴给我，多半是链接里的 sid 或密钥不对。"),
    ("安装失败：服务没有启动成功", "文件装上了，但服务起不来。\n先看日志：journalctl -u sing-box -n 30 --no-pager"),
    ("全部下载源都失败", "四个下载源都下不动。\n这台机器可能连不上任何外网，也可能是 DNS 坏了。\n先手动试：curl -I https://www.baidu.com"),
    ("permission denied (publickey", "这台机器不接受这把私钥。\n"
     "要么把公钥贴到目标机的 ~/.ssh/authorized_keys，要么改用 root 密码。"),
    ("permission denied", "密码不对，或者这台机器不允许 root 用密码登录。\n去云控制台 → 实例 → 重置密码（用户选 root），再用新密码试；或者改用私钥。"),
    ("sudo: a password is required", "登录的这个用户不是 root，而且 sudo 要密码。\n把用户名改成 root，或者用它自己的账号配 sudo 免密。"),
    ("host key verification failed", "这台机器的主机指纹变了（可能重装过系统）。"),
    ("unsupported arch", "这台机器的 CPU 架构不支持，目前只支持 x86_64 和 arm64。"),
    ("no space left", "服务器磁盘满了。清一下再装。"),
    ("curl:", "服务器下载 sing-box 失败。\n多半是这台机器连不上 GitHub（国内机器常见）。"),
    ("recv failure", "服务器下载 sing-box 失败。\n多半是这台机器连不上 GitHub（国内机器常见）。"),
    ("could not resolve host", "服务器解析不了域名，DNS 有问题。"),
    ("ssh: connect", "连不上这台机器的 22 端口。\n可能是防火墙没放行，或者机器没开机。"),
    ("connection timed out", "网络超时，中途断了。\n换一台机器或换个网络再试。"),
]


def hint_from_log(lines):
    txt = "\n".join(lines or []).lower()
    # 预检的中文原因自己就够清楚，原样带出来
    m = re.search(r"预检未通过：(.+)", "\n".join(lines or []))
    if m:
        return "预检没通过：%s\n换一台机器，或者先手动装好系统依赖再试。" % m.group(1).strip()
    for key, text in RULES:
        if key in txt:
            return text
    return DEFAULT
