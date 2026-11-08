#!/usr/bin/env python3
"""Linux 宿主物理网卡流量保底采集器（纯函数架构，零外部依赖）。

设计边界：
- 对未接入云厂商流量包 API 的通用 Linux 受控节点，读取 `/proc/net/dev` 物理网卡字节数作为保底观测。
- 若节点显式配置了 `quota_limit_gb`（>0），则计算百分比并联动阈值熔断；
- 若未配置 `quota_limit_gb`，如实返回已统计流量且 `total=None, percent=None`（绝不虚构 500GB 假套餐）。
"""
import subprocess

try:
    from . import verify as verify_mod
except ImportError:
    import verify as verify_mod

# 需忽略的虚拟/本地/容器网卡模式
IGNORED_INTERFACES = (
    "lo", "docker", "veth", "br-", "cni-", "flannel", "tun", "singbox", "dummy"
)


def parse_net_dev(text):
    """解析 /proc/net/dev 文本，返回各网卡 (rx_bytes, tx_bytes) 映射表。"""
    result = {}
    if not text:
        return result

    lines = text.strip().splitlines()
    for line in lines:
        if ":" not in line:
            continue
        parts = line.split(":", 1)
        iface = parts[0].strip()
        stats = parts[1].split()
        if len(stats) >= 9:
            try:
                rx_bytes = int(stats[0])
                tx_bytes = int(stats[8])
                result[iface] = {
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes,
                    "total_bytes": rx_bytes + tx_bytes,
                }
            except (ValueError, IndexError):
                continue
    return result


def is_physical_interface(iface):
    """判断是否为物理外网/主网卡（排除本地回环及虚拟容器网卡）。"""
    iface_clean = iface.strip().lower()
    for ignored in IGNORED_INTERFACES:
        if iface_clean == ignored or iface_clean.startswith(ignored):
            return False
    return True


def select_primary_interface(net_dev_stats):
    """从网卡统计中筛选出承载主要外网流量的网卡名。

    挑选规则：排除虚拟接口后，选取累计总流量（TX+RX）最大的物理网卡。
    """
    candidates = []
    for iface, stats in (net_dev_stats or {}).items():
        if is_physical_interface(iface):
            candidates.append((stats.get("total_bytes", 0), iface))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def calculate_host_usage(net_dev_text, quota_limit_gb=None):
    """从 /proc/net/dev 文本计算主机的流量统计数据。

    - 出站流量（TX）作为计费核心指标；
    - 仅当显式传入正数 `quota_limit_gb` 时计算 `total` 与 `percent`，否则设为 `None`（诚实标注未配置套餐）。
    """
    stats = parse_net_dev(net_dev_text)
    primary = select_primary_interface(stats)
    if not primary or primary not in stats:
        return None

    iface_stat = stats[primary]
    tx_bytes = iface_stat.get("tx_bytes", 0)
    used_gb = round(tx_bytes / (1024 ** 3), 2)

    total_gb = None
    pct = None
    if quota_limit_gb is not None:
        try:
            limit_val = float(quota_limit_gb)
            if limit_val > 0:
                total_gb = limit_val
                pct = round((used_gb / total_gb) * 100, 1)
        except (TypeError, ValueError):
            total_gb = None
            pct = None

    return {
        "interface": primary,
        "used": used_gb,
        "total": total_gb,
        "percent": pct,
        "quota_configured": total_gb is not None,
        "tx_bytes": tx_bytes,
        "rx_bytes": iface_stat.get("rx_bytes", 0),
        "source": "host_os",
    }


def collect_local_traffic(quota_limit_gb=None, net_dev_path="/proc/net/dev"):
    """直接读取本机 /proc/net/dev 流量。"""
    try:
        with open(net_dev_path, "r", encoding="utf-8") as f:
            text = f.read()
        return calculate_host_usage(text, quota_limit_gb=quota_limit_gb)
    except Exception:
        return None


def collect_remote_traffic(node, runner=subprocess.run, timeout=8, local_net_dev="/proc/net/dev"):
    """采集受控节点的 /proc/net/dev 物理流量（本机直读，远端走 node_ctl SSH 密钥与自定义端口）。"""
    if not isinstance(node, dict):
        return None
    host = (node.get("host") or "").strip()
    is_local = bool(node.get("local") is True or host in ("127.0.0.1", "localhost"))
    quota_limit = node.get("quota_limit_gb")

    if node.get("source") == "external" or node.get("os") == "windows" or node.get("ssh_user") == "Administrator":
        return None
    if is_local:
        return collect_local_traffic(quota_limit_gb=quota_limit, net_dev_path=local_net_dev)
    if not host:
        return None

    port = int(node.get("ssh_port") or 22)
    user = (node.get("ssh_user") or "root").strip() or "root"
    cmd = verify_mod.ssh_cmd(user, host, timeout=5, port=port) + ["cat /proc/net/dev 2>/dev/null"]
    try:
        res = runner(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0 and res.stdout:
            return calculate_host_usage(res.stdout, quota_limit_gb=quota_limit)
    except Exception:
        pass
    return None


class HostTrafficCollector:
    """物理网卡流量保底采集门面。"""

    @classmethod
    def collect(cls, node, runner=subprocess.run, timeout=8, local_net_dev="/proc/net/dev"):
        return collect_remote_traffic(node, runner=runner, timeout=timeout, local_net_dev=local_net_dev)

    @classmethod
    def parse(cls, net_dev_text, quota_limit_gb=None):
        return calculate_host_usage(net_dev_text, quota_limit_gb=quota_limit_gb)

