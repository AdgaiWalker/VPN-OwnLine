#!/usr/bin/env python3
"""host_traffic_tests.py: Linux 物理网卡流量采集器纯函数与采集路径单元测试。"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import host_traffic as H  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  OK {name}")
    else:
        print(f"  FAIL: {name} {detail}", file=sys.stderr)
        sys.exit(1)


SAMPLE_NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 52784576  324038    0    0    0     0          0         0 52784576  324038    0    0    0     0       0          0
  eth0: 164218586918 206236709    0    0    0     0          0         0 173306847355 143806046    0    0    0     0       0          0
docker0: 1024       10    0    0    0     0          0         0 2048          20    0    0    0     0       0          0
tun0:   5000000   1000    0    0    0     0          0         0 6000000     1200    0    0    0     0       0          0
"""


def main():
    # 1. 网卡解析测试
    stats = H.parse_net_dev(SAMPLE_NET_DEV)
    check("正确解析物理与虚拟网卡", "eth0" in stats and "lo" in stats and stats["eth0"]["tx_bytes"] == 173306847355)

    # 2. 物理网卡过滤判定
    check("正确识别物理网卡排除虚拟网卡", H.is_physical_interface("eth0") and not H.is_physical_interface("docker0") and not H.is_physical_interface("lo"))

    # 3. 主网卡自动择优选择
    primary = H.select_primary_interface(stats)
    check("自动挑选流量最大的物理主网卡", primary == "eth0")

    # 4. 显式配置套餐限额时计算真实用量与百分比
    usage = H.calculate_host_usage(SAMPLE_NET_DEV, quota_limit_gb=500.0)
    check("配置限额时计算用量与百分比准确", usage is not None and abs(usage["used"] - 161.4) < 0.2 and abs(usage["percent"] - 32.3) < 0.2 and usage["quota_configured"] is True)

    # 5. 未配置套餐限额时不虚报 500GB 固定总额
    usage_nolimit = H.calculate_host_usage(SAMPLE_NET_DEV)
    check("未配置限额时诚实返回 total=None 且保留真实已用流量",
          usage_nolimit is not None and abs(usage_nolimit["used"] - 161.4) < 0.2
          and usage_nolimit["total"] is None and usage_nolimit["percent"] is None
          and usage_nolimit["quota_configured"] is False)

    # 6. local=True 本机节点直读文件，不走 SSH
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
        tf.write(SAMPLE_NET_DEV)
        dev_file = tf.name
    try:
        def forbid_ssh(*a, **k):
            raise AssertionError("local=True 节点不应发起 SSH")
        local_res = H.collect_remote_traffic(
            {"host": "203.0.113.10", "local": True},
            runner=forbid_ssh,
            local_net_dev=dev_file,
        )
        check("local=True 本机公网 IP 节点直读本机流量", local_res is not None and local_res["interface"] == "eth0")
    finally:
        os.unlink(dev_file)

    # 7. 远端节点采集携带 node_ctl 密钥与自定义 ssh_port
    seen = []
    def fake_ssh(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=SAMPLE_NET_DEV, stderr="")

    rem_res = H.collect_remote_traffic(
        {"host": "203.0.113.20", "ssh_user": "ubuntu", "ssh_port": 22022, "quota_limit_gb": 1000},
        runner=fake_ssh,
    )
    check("远端采集使用 node_ctl 密钥与自定义端口 22022",
          rem_res is not None and "-i" in seen[0] and "/root/.ssh/node_ctl" in seen[0]
          and seen[0][1:3] == ["-p", "22022"] and abs(rem_res["percent"] - 16.1) < 0.2)

    # 8. 空输入容错
    check("空字符串安全容错不崩溃", H.calculate_host_usage("") is None and H.parse_net_dev("") == {})

    print(f"\n通过 {passed} 项")


if __name__ == "__main__":
    main()
