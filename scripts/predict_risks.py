#!/usr/bin/env python3
"""通过 TypeSafe AI Jev 运行架构与运维盲区风险预测。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.nodekit import jev

SYSTEM_STATE = """
梯子系统架构与运行状态全景：
1. 节点与拓扑：
   - 硅谷 (Ubuntu 24.04, 43.153.56.137)：主控面板 (admin.py:8000 + Caddy:8443)，同时也是 Reality (TCP 443, SNI: gateway.icloud.com) 与 Hysteria2 (UDP 8443) 的落地节点。
   - 北京 (Ubuntu 24.04, 49.233.210.101)：国内中转机，iptables 转发 TCP 443 / UDP 8443 直连硅谷；兼任国内探活端与异地备份存储端。
   - 广州 (OpenCloudOS 9, 43.140.37.38)：国内中转机，iptables 转发 TCP 443 到硅谷。用户明确决定不续费，到期日为 2026-11-12 (约 13 天后停机)。
   - 新加坡 (Windows Server 2022, 43.163.4.104)：独立落地节点。装有宝塔面板，80/443 端口被宝塔 Nginx 占用，因此 sing-box Reality 运行在非标 8443 端口。由 Windows 任务计划管理，缺少自动化 addnode.sh 脚本支持。

2. 订阅与网络：
   - 订阅链接通过主控 /s/<token> 下发，目前使用免域名证书 (sslip.io 或直接 IP/域名)，Reality SNI 使用 gateway.icloud.com。
   - 双协议架构：Reality (TCP) + Hysteria2 (UDP)。国内各省运营商（电信/联通/移动）对 UDP 进行不同程度的 QoS 限速与阻断。

3. 计费与运维：
   - 腾讯云轻量应用服务器 (Lighthouse)，每月固定流量包（1TB-2TB）。
   - 中转机采用 iptables NAT 转发，进出各计费一次（双向计费）。
   - 主控定时任务：探活 (每1分钟)、用量刷新 (每10分钟)、异地增量备份 (每6小时)。
"""

QUESTIONS = {
    # 1. 架构单点故障
    "spof_silicon_valley": jev.make_choice(
        "若硅谷主控节点因云厂商停机、IP被封或硬件故障下线，对整个网络的影响程度？",
        {
            "catastrophic": "灾难性：主控面板、直连出口、北京中转、广州中转全部瘫痪（全网不可用）",
            "major": "严重：仅新加坡 Windows 独立可用，其余所有节点与面板全部不可用",
            "moderate": "中度：部分节点受影响，但主干自动切换",
            "minor": "轻微：几乎无影响",
        },
    ),

    # 2. 广州服务器到期下线风险
    "guangzhou_expiry_impact": jev.make_choice(
        "广州服务器在 2026-11-12 到期下线后，若未在客户端/订阅中移除，会造成何种影响？",
        {
            "silent_failure": "客户端选择广州节点时静默黑洞超时，用户报障并体验断网",
            "auto_fallback": "客户端自动测速切换到北京，完全无感",
            "subscription_break": "订阅下发崩溃",
        },
    ),

    # 3. Windows / 宝塔非标端口与配置漂移风险
    "windows_port_8443_risk": jev.make_choice(
        "新加坡节点在 Windows 环境下因宝塔占用 443 而被迫使用 8443 端口提供 Reality 服务，其风险表现？",
        {
            "high_risk": "非标 8443 端口极易受到 GFW 主动探测、阻断，且部分企业网络/公共 Wi-Fi 封锁 8443 出站",
            "medium_risk": "仅偶发丢包，整体稳定",
            "low_risk": "完全等同于 443 标准端口",
        },
    ),

    "windows_config_drift": jev.make_choice(
        "新加坡 Windows 节点脱离了 Linux 下的 addnode.sh / rotate.sh 统一自动化，长期运维的潜在问题？",
        {
            "severe_drift": "高风险：主控秘钥轮转或协议升级时，Windows 节点配置失步甚至失效，成为孤儿节点",
            "manageable": "中度风险：需人工介入更新，易遗漏",
            "trivial": "低风险：几乎不需要维护",
        },
    ),

    # 4. 协议与运营商 QoS
    "hysteria2_udp_throttling": jev.make_choice(
        "在晚高峰时段，中国大陆境内电信/联通/移动宽带对 Hysteria2 (UDP 协议) 的 QoS 限速与阻断概率？",
        {
            "very_likely": "极高：晚高峰大面积 UDP 丢包、限速至几十 KB/s，必须依赖 Reality (TCP) 作为主力兜底",
            "occasional": "偶尔：仅个别省份运营商限制",
            "rare": "极罕见：UDP 表现与 TCP 一致稳定",
        },
    ),

    # 5. 域名与 SNI 污染
    "sslip_io_sub_fragility": jev.make_choice(
        "订阅下发依赖 sslip.io 免费自签名/动态 DNS 解析，其长期脆弱性如何？",
        {
            "vulnerable": "高危脆弱：sslip.io 极易被 GFW SNI/DNS 污染或官方限流，导致用户客户端无法刷新订阅",
            "moderately_safe": "中度风险：偶尔解析超时",
            "bulletproof": "高可用无风险",
        },
    ),

    # 6. 腾讯云流量双向计费超额
    "relay_double_traffic_exhaustion": jev.make_choice(
        "北京/广州作为 iptables 转发节点，流量进出双向计费对免费/低配流量包的消耗风险？",
        {
            "high_drain": "高消耗：用户跑 1GB 流量实际消耗中转机 2GB 流量包，极易提前耗尽并产生超额高额账单",
            "medium_drain": "中度：若用量不大仍在配额内",
            "no_risk": "无风险",
        },
    ),

    # 7. 异地备份与恢复可用性
    "backup_recovery_readiness": jev.make_score(
        "系统目前的异地备份与灾难恢复准备度综合评分 (0=无准备, 4=企业级高可用灾备)",
        [
            "0 - 仅单机本地存储，一旦掉盘全丢",
            "1 - 简单手动备份，无异地定期同步",
            "2 - 已实现异地定期增量备份，但恢复仍需半自动脚本",
            "3 - 异地备份 + 一键自愈验证，基本能在 15 分钟内拉起新主控",
            "4 - 跨可用区热备多活，无缝自动故障转移",
        ],
    ),
}


def run_prediction():
    print("=" * 60)
    print("📡 正在调用 TypeSafe AI System One (Jev) 模型进行架构盲区预测...")
    print("=" * 60)

    cfg = jev.get_config()
    print(f"API Endpoint : {cfg['endpoint']}")
    print(f"Model ID     : {cfg['model']}")
    print(f"API Key      : {cfg['api_key'][:15]}...{cfg['api_key'][-6:]}")
    print(f"预测问题数量 : {len(QUESTIONS)} 项")
    print("-" * 60)

    res = jev.call_systemone(state=SYSTEM_STATE, questions=QUESTIONS)
    if not res["ok"]:
        print(f"❌ 预测失败: {res.get('error')}")
        return None

    print(f"✅ 预测成功！模型版本: {res['model']}")
    print(f"Token 消耗   : 输入 {res['usage'].get('input_tokens')} / 输出 {res['usage'].get('output_tokens')}")
    print("=" * 60)
    print("📊 预测结果矩阵：\n")

    answers = res["answers"]
    for qkey, ans in answers.items():
        q_type = ans.get("type")
        print(f"【{qkey}】({q_type})")
        if q_type == "choice":
            print(f"  🎯 预测选择: {ans.get('choice')} (置信度: {ans.get('confidence', 0):.2f})")
            print("  📈 各项概率:")
            for opt, prob in ans.get("probabilities", {}).items():
                bar = "█" * int(prob * 20)
                print(f"     - {opt:<24}: {prob*100:5.1f}% | {bar}")
        elif q_type == "score":
            print(f"  🎯 综合评分: {ans.get('score')} / 4.00 (置信度: {ans.get('confidence', 0):.2f})")
            legend = ans.get("legend", {})
            print("  📈 分布概率:")
            for idx, prob in ans.get("probabilities", {}).items():
                label = legend.get(str(idx), idx)
                bar = "█" * int(prob * 20)
                print(f"     - {label:<30}: {prob*100:5.1f}% | {bar}")
        elif q_type == "noul":
            val = ans.get("noul", 0)
            bar = "█" * int(val * 20)
            print(f"  🎯 判定概率: {val*100:.1f}% | {bar}")
        print()

    return res


if __name__ == "__main__":
    run_prediction()
