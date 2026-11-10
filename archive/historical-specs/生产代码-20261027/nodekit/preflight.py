"""预检：在装任何东西之前，判断这台机器能不能装。

设计原则：所有判断逻辑都是**纯函数**（吃字符串、吐结论），
这样可以在没有 SSH 的情况下单测，不依赖网络。
"""
import re

OS_FAMILY = {
    "ubuntu": "debian", "debian": "debian", "linuxmint": "debian", "kali": "debian", "pop": "debian",
    "centos": "rhel", "rocky": "rhel", "almalinux": "rhel", "rhel": "rhel", "fedora": "rhel",
    "alinux": "rhel", "anolis": "rhel", "openeuler": "rhel", "opencloudos": "rhel",
    "tencentos": "rhel", "kylin": "rhel", "uniontech": "debian", "uos": "debian",
    "alpine": "alpine",
}

# 各家族的最低支持版本
MIN_VERSION = {"debian": (11, 0), "rhel": (8, 0)}
# ubuntu 单独规定（20.04 起）
UBUNTU_MIN = (20, 4)
# 有些发行版用自己的版本号（阿里云 3、openEuler 22、麒麟 V10）
DISTRO_MIN = {"alinux": (3, 0), "openeuler": (20, 0), "kylin": (10, 0)}

ARCH_MAP = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

# 需要目标机执行的探测命令（一次 ssh 全部跑完）
PROBE_CMD = (
    "cat /etc/os-release 2>/dev/null; "
    "echo '---ARCH---'; uname -m; "
    "echo '---SYSTEMD---'; command -v systemctl || echo none; "
    "echo '---DISK---'; df -mP / | tail -1; "
    "echo '---TOOLS---'; command -v curl || echo none; command -v tar || echo none; "
    "echo '---INSTALLED---'; test -x /opt/sing-box/sing-box && echo yes || echo no"
)


def parse_version(v):
    parts = re.findall(r"\d+", v or "")
    major = int(parts[0]) if parts else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    return (major, minor)


def parse_os_release(text):
    """从 /etc/os-release 文本里取 (id, version, family)。"""
    data = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    distro = (data.get("ID") or "").lower()
    version = data.get("VERSION_ID") or ""
    if not distro:
        pretty = (data.get("PRETTY_NAME") or "").lower()
        for key in OS_FAMILY:
            if key in pretty:
                distro = key
                break
    family = OS_FAMILY.get(distro, "unknown")
    if family == "unknown":
        for like in (data.get("ID_LIKE") or "").lower().split():
            if like in OS_FAMILY:
                family = OS_FAMILY[like]
                break
    return distro, version, family


def supported_os(distro, version, family):
    if family == "alpine":
        return False, "unsupported_os"
    if family == "unknown":
        return False, "unsupported_os"
    ver = parse_version(version)
    if distro == "ubuntu":
        return (ver >= UBUNTU_MIN), ("ok" if ver >= UBUNTU_MIN else "unsupported_os")
    if distro in DISTRO_MIN:
        need = DISTRO_MIN[distro]
        return (ver >= need), ("ok" if ver >= need else "unsupported_os")
    if family in MIN_VERSION:
        return (ver >= MIN_VERSION[family]), ("ok" if ver >= MIN_VERSION[family] else "unsupported_os")
    return False, "unsupported_os"


def map_arch(uname_m):
    return ARCH_MAP.get((uname_m or "").strip())


def parse_probe_output(text):
    """把 PROBE_CMD 的输出解析成结构。"""
    out = {"os_raw": "", "arch": "", "systemd": "", "disk_mb": 0, "curl": "", "tar": "", "installed": ""}
    parts = re.split(r"---(?:ARCH|SYSTEMD|DISK|TOOLS|INSTALLED)---", text or "")
    keys = ["os_raw", "arch", "systemd", "disk_mb", "tools"]
    for i, k in enumerate(keys):
        if i < len(parts):
            out[k] = parts[i].strip()
    m = re.search(r"---INSTALLED---\s*(\S+)", text or "")
    if m:
        out["installed"] = m.group(1)
    tools = (out.get("tools") or "").split()
    out["curl"] = "yes" if len(tools) > 0 and tools[0] != "none" else "no"
    out["tar"] = "yes" if len(tools) > 1 and tools[1] != "none" else "no"
    parts = (out.get("disk_mb") or "").split()
    try:
        out["disk_mb"] = int(parts[3]) if len(parts) >= 4 else 0
    except Exception:
        out["disk_mb"] = 0
    return out


def decide(info, min_disk_mb=200):
    """返回 (ok, reason, hints)。reason 与 PRD 的枚举一致。"""
    distro, version, family = parse_os_release(info.get("os_raw", ""))
    ok, reason = supported_os(distro, version, family)
    if not ok:
        return False, reason, ["这台是 %s %s，不在支持范围（Ubuntu 20+/Debian 11+/Rocky 9+）" % (distro or "未知系统", version)]
    if not map_arch(info.get("arch")):
        return False, "unsupported_arch", ["这台是 %s，只支持 x86_64 / arm64" % info.get("arch")]
    if info.get("systemd") in ("", "none"):
        return False, "no_systemd", ["没有 systemd，无法用服务方式常驻"]
    if info.get("disk_mb", 0) < min_disk_mb:
        return False, "disk_low", ["根分区只剩 %sMB，至少需要 %sMB" % (info.get("disk_mb"), min_disk_mb)]
    return True, "ok", []
