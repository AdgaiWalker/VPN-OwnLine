#!/usr/bin/env python3
"""端口动态决策与智能避让函数的单元测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import ports


def check(name, cond):
    if not cond:
        print(f"FAIL: {name}")
        sys.exit(1)
    print(f"PASS: {name}")


def main():
    print("=== 测试 ports 动态决策函数 ===")

    # 1. 用户显式指定端口
    res1 = ports.resolve_node_ports({"name": "自定义机", "port": 20443})
    check("显式指定端口优先采纳", res1["tcp_port"] == 20443 and res1["is_custom"] is True)

    # 2. 干净的 Linux 机器 -> 443
    res2 = ports.resolve_node_ports({"name": "硅谷母机"}, os_type="linux")
    check("干净 Linux 机器默认使用 443", res2["tcp_port"] == 443 and res2["is_fallback"] is False)

    # 3. Windows 机器 -> 动态避让至 8443
    res3 = ports.resolve_node_ports({"name": "新加坡 Windows 宝塔机"}, os_type="windows")
    check("Windows 机器自动避让至 8443", res3["tcp_port"] == 8443 and res3["is_fallback"] is True)

    # 4. Linux 机器但已有 Web 业务 (443 被占) -> 动态避让
    res4 = ports.resolve_node_ports({"name": "已有博客机"}, os_type="linux", has_web_server=True)
    check("已有 Web 业务自动避让", res4["tcp_port"] == 8443 and res4["is_fallback"] is True)

    # 5. 8443 也被占 -> 递归寻找下一个空闲候选端口
    res5 = ports.resolve_node_ports(
        {"name": "拥挤机"},
        os_type="windows",
        occupied_ports={443, 8443},
    )
    check("多端口冲突时寻找下一空闲端口", res5["tcp_port"] == 20443 and res5["is_fallback"] is True)

    # 6. 安全候选端口建议函数
    existing = [{"name": "A", "port": 443}, {"name": "B", "port": 8443}]
    suggestions = ports.suggest_safe_ports(existing)
    check("推荐安全端口列表排除已占用端口", 443 not in suggestions and 8443 not in suggestions and 20443 in suggestions)

    print("\n通过 6 项")


if __name__ == "__main__":
    main()
