#!/usr/bin/env python3
"""通过 TypeSafe AI Jev 对「分客群差异化适配策略」vs「单一大一统系统规避所有风险」进行对比决策审理。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.nodekit import jev

STRATEGY_CONTEXT = """
针对梯子系统的两种不同战略路径对比：

战略方案 A【单一大一统规避一切系统】：
- 试图用一套统一的节点拓扑、单一的订阅配置模板、通用的规则引擎，去满足所有人。
- 问题：客服需要极度严密的大陆白名单防封号，研发需要全局 TUN 代理和透明抓包，小白需要零认知的单个开关，省钱用户拒绝承担中转双向计费。
- 结果：规则互相掣肘，系统极度臃肿，客服因全局漏判遭遇封号，小白因看到复杂节点列表而报障，中转流量被低价值流量刷爆。

战略方案 B【分客群精准差异化适配策略】：
- 不追求用一套系统规避所有风险，而是针对不同需求的用户做精准适配：
  1. 客服与跨境电商团队（安全防封号办公模式）：严密国内直连白名单 + 双落地自动容灾中继 + 客户端隐藏切换。
  2. 手机轻度与小白用户（极简智能选路模式）：单开关自动优选 + 微信防呆引导 + 零认知负荷。
  3. 成本敏感与备用用户（纯海外直连省流模式）：直连 Hysteria2/Reality，彻底不走国内中转，0 中继流量消耗，免 KYC 云机。
  4. 极客与研发团队（全功能全能模式）：全节点暴露可自由切换 + TUN 终端代理 + 完整规则下发。
- 订阅接口支持动态 profile 参数：?profile=office / ?profile=lite / ?profile=direct / ?profile=pro。
- 网页面板提供「场景模式切换器」，按用户真实使用场景精准交付。
"""

QUESTIONS = {
    # 1. 风险隔离度提升
    "risk_isolation_gain": jev.make_choice(
        "相比单一大一统系统，采用分客群适配策略对各群体特定风险（如客服封号、中转流量被刷爆）的隔离有效性？",
        {
            "dramatic_improvement": "显著提升：不同群体的利益冲突被物理/配置隔离，客服绝不受极客全局代理影响，流量预算清晰划分",
            "moderate_improvement": "中等提升：有一定隔离效果",
            "negligible": "微弱或无差别",
        },
    ),

    # 2. 客服报障与维护成本
    "maintenance_overhead_reduction": jev.make_choice(
        "小白用户与客服团队面对「极简化/场景化」定制交付时，报障咨询率（Ticket Rate）的变化趋势？",
        {
            "sharp_drop": "大幅下降：小白不再被多节点选择困惑，客服开箱即用不封号，管理员答疑成本降低 70% 以上",
            "minor_drop": "小幅下降",
            "no_change": "无变化",
        },
    ),

    # 3. 系统抗脆弱性与架构灵活性
    "architectural_antifragility": jev.make_choice(
        "当某类用户需求变更或某个海外机房受阻时，分客群适配策略对系统整体稳定性的保护效果？",
        {
            "high_antifragile": "高抗脆弱：单一画像策略调整不牵连其他人群，例如直连廉价节点故障只影响省流模式，核心客服业务不受丝毫波及",
            "medium": "中等保护",
            "low": "低保护",
        },
    ),

    # 4. 整体架构优劣性综合评分
    "overall_strategy_score": jev.make_score(
        "评估「分客群差异化适配」相较于「一套大一统系统规避所有风险」的战略优越度评分",
        [
            "0 - 无差异或过度设计",
            "1 - 仅轻微改善，增加维护负担",
            "2 - 方案良好，解决了部分冲突",
            "3 - 方案优秀，显著降低跨群体风险外溢与运维摩擦",
            "4 - 战略最优解：彻底化解多群体目标冲突，实现高抗脆弱与高ROI交付",
        ],
    ),
}

def main():
    print("=" * 68)
    print("TypeSafe AI Jev · 战略评估：分客群差异化适配 vs 大一统系统")
    print("=" * 68)

    cfg = jev.get_config()
    print(f"API Endpoint : {cfg['endpoint']}")
    print(f"Model ID     : {cfg['model']}")
    print(f"审理问题数量 : {len(QUESTIONS)} 项")
    print("-" * 68)

    res = jev.call_systemone(state=STRATEGY_CONTEXT, questions=QUESTIONS)
    if not res["ok"]:
        print(f"❌ 审理失败: {res.get('error')}")
        sys.exit(1)

    print(f"✅ 审理成功！模型版本: {res['model']}")
    print(f"Token 消耗   : 输入 {res['usage'].get('input_tokens')} / 输出 {res['usage'].get('output_tokens')}")
    print("=" * 68)
    print("📊 Jev 审理决策矩阵：\n")

    answers = res["answers"]
    for qkey, ans in answers.items():
        qtype = ans.get("type")
        print(f"🔍 问题标识: [{qkey}] ({qtype})")
        if qtype == "choice":
            print(f"   🏆 最优推演: {ans.get('choice')} (置信度: {ans.get('confidence', 0)*100:.1f}%)")
            dist_str = ", ".join([f"{k}: {v*100:.1f}%" for k, v in ans.get("probabilities", {}).items()])
            print(f"   📈 概率分布: {dist_str}")
        elif qtype == "score":
            print(f"   ⭐ 加权得分: {ans.get('score', 0):.2f} / 4.0 (置信度: {ans.get('confidence', 0)*100:.1f}%)")
            probs = ans.get("probabilities", {})
            prob_str = ", ".join([f"档位{k}: {v*100:.1f}%" for k, v in probs.items() if v > 0])
            print(f"   📈 评分分布: {prob_str}")
        print("-" * 68)

    out_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "jev_segmentation_evaluation.json",
    )
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    print(f"\nJev 审理详细结果已持久化至: {out_file}")

if __name__ == "__main__":
    main()
