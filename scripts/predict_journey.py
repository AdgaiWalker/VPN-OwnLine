#!/usr/bin/env python3
"""通过 TypeSafe AI Jev 对用户完整链路（选云买机 -> 部署配置 -> 手机客服一键导入）进行审理与盲区预测。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.nodekit import jev

USER_JOURNEY_STATE = """
用户从买服务器到最终在手机/客户端上使用梯子的全流程现状与配置：

阶段一：用户在哪儿买服务器 (Where to buy)
- 目前主要以腾讯云轻量服务器 (Lighthouse) 为基准进行文档编写与自动化支持。
- 国内账号需要国内身份证实名认证 (KYC)；境外轻量 (硅谷、新加坡) 需要双币/外币信用卡或海外账号。
- 海外 VPS 存在「分配到的 IP 之前已被 GFW 封锁」或「被 Google/ChatGPT 判定为脏 IP/滥用欺诈风险」的可能性。
- 缺乏对 AWS Lightsail、DigitalOcean、Vultr、搬瓦工 (BandwagonHost) 等主流海外主机的购买指引与售前 IP 可用性检测建议。

阶段二：买一台服务器与初始化配置 (Buying & Provisioning)
- 用户在云控制台选配时面临：操作系统版本选择 (Ubuntu 24.04 vs 22.04 vs CentOS 7 / Windows)。
- 云厂商默认安全组/防火墙策略：很多云厂商默认仅放行 22 端口，80/443/8443/UDP 需要在控制台安全组手动添加规则。
- 登录凭据：默认分配 root 密码 vs 强制 SSH 密钥对；部分云机默认禁用 root 直接登录 (需 ubuntu/debian 用户 + sudo)。
- 系统目前有一键自举脚本 bootstrap.sh，会自动检测 OS 兼容性并配置 BBR、sing-box 与防火墙。

阶段三：最后的配置与一键导入手机/客服客户端 (1-Click Client Onboarding)
- 网页面板提供一键导入按钮：
  - Shadowrocket: shadowrocket://add/sub://<base64>
  - Clash 系: clash://install-config?url=<url>
- 移动端环境痛点：如果用户在微信、QQ、抖音等内置浏览器中打开面板链接，外部应用 Scheme (shadowrocket://, clash://) 会被微信彻底拦截，导致点击按钮没有任何反应。
- 证书与域名：使用 sslip.io 配合 Caddy tls internal (自签证书)。Shadowrocket / Clash 在拉取订阅时，若未开启「允许不安全证书 / skip-cert-verify」，可能遭遇 SSL Handshake Failed 报错。
- 客服人员与小白用户痛点：客服人员只关心「连上能用、国内微信不卡、国外能打开」，若客户端分流规则不严密（如访问国内网站也走代理绕路），会导致微信打不开或异地登录风控。
"""

QUESTIONS = {
    # 1. 选购与实名合规风险
    "buyer_cloud_kyc_barrier": jev.make_choice(
        "对于普通个人/客服团队，强制使用腾讯云等国内云厂商面临的合规与实名门槛严重度？",
        {
            "high_barrier": "高门槛：国内实名制翻墙有严重合规审计风险，境外账号又受限于外币信用卡，迫切需要免KYC的海外主流VPS推荐",
            "medium_barrier": "中等门槛：大部分人能搞定账号，但过程繁琐",
            "low_barrier": "几乎无门槛",
        },
    ),

    # 2. 售前 IP 脏度与被封锁陷阱
    "dirty_ip_precheck_omission": jev.make_choice(
        "用户新买海外 VPS 时，刚买到的 IP 本身就已被 GFW 封锁或被流媒体拉黑的概率？",
        {
            "frequent": "高发：大量便宜海外 VPS 的 IP 池被前人玩烂，买到即被墙，必须提供「付款前/付款后立刻测试被墙检测」指引",
            "occasional": "偶发：小概率事件，换一次 IP 即可",
            "rare": "极罕见",
        },
    ),

    # 3. 云控制台安全组防火墙卡点
    "firewall_security_group_friction": jev.make_choice(
        "小白用户在买好服务器后，因未在云厂商网页控制台放行 443/8443/UDP 端口而导致安装失败的概率？",
        {
            "very_high": "极大概率卡死：小白误以为服务器内部装好即可，不知道云厂商外层还有一道安全组防火墙，报障率第一",
            "medium": "中等：有指引能搞定",
            "low": "极低",
        },
    ),

    # 4. 微信内置浏览器拦截一键导入 Scheme
    "wechat_inapp_browser_trap": jev.make_choice(
        "当管理员把网页链接或二维码发给客服/朋友，对方在微信或 QQ 内置浏览器打开并点击「一键导入」时的表现？",
        {
            "silent_block": "100% 被微信拦截：微信静默拦截所有自定义 scheme (shadowrocket://, clash://)，用户点击无任何反应以为网页坏了",
            "prompt_browser": "提示在浏览器打开",
            "normal_open": "正常唤醒",
        },
    ),

    # 5. 自签证书导致客户端拉取订阅失败
    "self_signed_tls_sub_failure": jev.make_choice(
        "使用免域名 sslip.io 搭配 Caddy 自签证书时，Shadowrocket / Clash 客户端首次拉取订阅时的阻断风险？",
        {
            "high_failure": "高阻断：iOS Shadowrocket 默认开启严格 TLS 校验，自签证书直接报 SSL 握手失败且不给用户重试机会",
            "mild_warning": "弹窗提示警告但可放行",
            "seamless": "无感通过",
        },
    ),

    # 6. 客服人员国内外智能分流与防风控
    "customer_service_routing_risk": jev.make_choice(
        "客服客户端若缺乏严格的 GEOIP 规则分流（导致国内微信、企业微信、飞书、淘宝也走美国出口代理），会产生何种后果？",
        {
            "severe_disruption": "严重风控：微信/企微频繁异地登录验证甚至封号，国内网速剧烈变慢卡顿，客服无法正常办公",
            "minor_lag": "轻微卡顿但不影响账号",
            "no_impact": "完全无影响",
        },
    ),

    # 7. 全流程端到端体验准备度评分
    "user_journey_readiness": jev.make_score(
        "评估当前系统从「用户买机 -> 面板部署 -> 客服/手机一键连上」全流程的新手友好与抗踩坑准备度评分",
        [
            "0 - 仅技术极客可用，步骤充满隐藏陷阱与命令行",
            "1 - 有文档但缺乏防呆，买机/防火墙/导入必卡",
            "2 - 核心功能已跑通，但缺乏微信防拦截、IP预检与证书引导",
            "3 - 体验丝滑：涵盖购机建议、IP自检、一键导入与微信跳出引导",
            "4 - 傻瓜级：完全无感知，连手机一秒搞定",
        ],
    ),
}


def run_prediction():
    print("=" * 60)
    print("📡 正在调用 TypeSafe AI (Jev) 模型审理「买机到手机一键导入」全流程盲区...")
    print("=" * 60)

    cfg = jev.get_config()
    print(f"API Endpoint : {cfg['endpoint']}")
    print(f"Model ID     : {cfg['model']}")
    print(f"审理问题数量 : {len(QUESTIONS)} 项")
    print("-" * 60)

    res = jev.call_systemone(state=USER_JOURNEY_STATE, questions=QUESTIONS)
    if not res["ok"]:
        print(f"❌ 审理失败: {res.get('error')}")
        return None

    print(f"✅ 审理成功！模型版本: {res['model']}")
    print(f"Token 消耗   : 输入 {res['usage'].get('input_tokens')} / 输出 {res['usage'].get('output_tokens')}")
    print("=" * 60)
    print("📊 Jev 审理决策矩阵：\n")

    answers = res["answers"]
    for qkey, ans in answers.items():
        q_type = ans.get("type")
        print(f"【{qkey}】({q_type})")
        if q_type == "choice":
            print(f"  🎯 预测选择: {ans.get('choice')} (置信度: {ans.get('confidence', 0):.2f})")
            print("  📈 各项概率:")
            for opt, prob in ans.get("probabilities", {}).items():
                bar = "█" * int(prob * 20)
                print(f"     - {opt:<30}: {prob*100:5.1f}% | {bar}")
        elif q_type == "score":
            print(f"  🎯 综合评分: {ans.get('score')} / 4.00 (置信度: {ans.get('confidence', 0):.2f})")
            legend = ans.get("legend", {})
            print("  📈 分布概率:")
            for idx, prob in ans.get("probabilities", {}).items():
                label = legend.get(str(idx), idx)
                bar = "█" * int(prob * 20)
                print(f"     - {label:<35}: {prob*100:5.1f}% | {bar}")
        print()

    return res


if __name__ == "__main__":
    run_prediction()
