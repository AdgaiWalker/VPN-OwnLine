#!/usr/bin/env python3
"""通过 TypeSafe AI Jev 决策下一步行动路线：在分客群适配战略确立后，评估最高 ROI 的推进方向。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.nodekit import jev

DECISION_STATE = """
当前系统现状与上下文：
1. 节点与网络拓扑现状：
   - 硅谷 walker-sv (Ubuntu 24.04)：主控面板 + Reality 443 + HY2 443 出口，运行健康。
   - 北京 walker-bj (Ubuntu 24.04)：sing-box 双落地 urltest 中继（硅谷主 + 新加坡备），混沌演练通过。
   - 广州 (OpenCloudOS 9)：13 天后到期（2026-11-12），已纳入 lifecycle 排空，运行健康。
   - 新加坡 (Windows Server 2022)：宝塔 Nginx 占 443，Reality 运行于 8443 出口，双视角探测通过。
2. 架构与测试现状：
   - 离网单元测试：12 套测试集，238 项单测全部通过。
   - 生产真实验收：./scripts/verify.sh 20 项生产校验全部通过（0 失败）。
3. 刚确立的核心战略（Jev 评分 3.66/4.0）：
   - 「不争取用一套系统规避所有风险，而是对不同需求的用户做不同的适配」。
   - 已完成《23-分客群精准适配与风险隔离战略方案》，确立 4 大客群：
     ① 客服外贸安全办公 (profile=office: 严密国内白名单直连，双机中继高可用，绝对防封号)；
     ② 手机小白极简模式 (profile=lite: 极简单一智能优选开关，微信跳出防呆)；
     ③ 经济纯直连省流 (profile=direct: 100% 过滤排除国内中继，0 中继流量开销，免 KYC 海外机)；
     ④ 研发极客全能模式 (profile=pro: 全节点暴露，TUN 模式，一键复制终端代理命令)。
4. 待决策的推进候选路径：
   - 路径 A【落地分客群订阅与前端场景交付闭环】：
     将刚推演确立的战略落成实际代码：在 subscriptions.py / admin.py 中支持 ?profile=office|lite|direct|pro，并在 web/index.html 增加 4 大场景选择卡片与对应一键导入按钮，部署上线并验真。
   - 路径 B【新加坡 Windows 宝塔 443 端口 SNI 预分流实施】：
     执行 deploy/windows_sni.ps1，在新加坡 Windows 上通过 Nginx Stream SNI 预分流将 Reality 从 8443 端口迁移回标准 443 端口。
   - 路径 C【售前 IP 脏度与 GFW 阻断快速自检工具】：
     开发一个极简轻量的自动化检测脚本，让用户买新机后 10 秒内自检 IP 是否被墙（方便 15 分钟退款）。
   - 路径 D【灾备冷备无损拉起实机演练】：
     在备用容器/虚机中实际跑一遍 deploy/restore_master.sh，实测从北京冷备拉起面板的时间与数据完整度。
   - 路径 E【封版发布 v0.3.0】：
     系统已极为完备，收敛开发，更新 RELEASE 文档并打 tag 封版。
"""

QUESTIONS = {
    # 1. 下一步推进的最高优先级路径
    "next_priority_action": jev.make_choice(
        "综合紧迫度、产出比（ROI）、用户痛点解决程度，接下来最应该优先推进哪一步？",
        {
            "path_a_implement_segmentation": "路径 A：落地分客群订阅代码与前端场景交付（将战略即刻变成用户可用的产品功能）",
            "path_b_windows_sni_migration": "路径 B：实施新加坡 Windows 443 端口 SNI 预分流迁移（消除 8443 端口特征）",
            "path_c_precheck_tool": "路径 C：开发售前 IP 脏度与被墙快速检测工具",
            "path_d_dr_drill": "路径 D：执行异地冷备恢复实机演练",
            "path_e_release_v030": "路径 E：直接封版发布 v0.3.0 并结束本期开发",
        },
    ),

    # 2. 推进路径 A（分客群落地）的直接业务价值
    "path_a_business_value": jev.make_score(
        "评估立即完成路径 A（分客群订阅参数与前端场景切换）对解决实际用户摩擦的价值评分",
        [
            "0 - 毫无价值，纯属理论空谈",
            "1 - 价值微弱",
            "2 - 一般改善",
            "3 - 价值显著：彻底解决客服微信风控和小白报障两大核心痛点",
            "4 - 质的飞跃：战略与系统形成闭环，产品体验与抗脆弱性达到生产级最佳实践",
        ],
    ),

    # 3. 如果此刻止步不前（不实现分客群适配）的潜在风险
    "risk_of_not_implementing": jev.make_choice(
        "若停留在文档层面而不把分客群适配落入代码与UI，系统面临的最大隐患是？",
        {
            "high_risk_of_leak": "高危：用户继续使用大一统订阅，客服随时可能因全局规则导致微信封号，中继流量仍会被日常流量刷爆",
            "medium_friction": "中度摩擦：客服和小白需要管理员手动写配置文件",
            "low_impact": "无影响，现有系统也能凑合用",
        },
    ),

    # 4. 后续执行建议节奏
    "recommended_sequence": jev.make_choice(
        "若要系统性持续推进，推荐的工程步骤排序应该如何规划？",
        {
            "a_then_verify_then_release": "先完成路径 A（分客群落地与前端交付），然后线上验收，最后封版发布",
            "b_first_then_a": "先做 Windows 443 迁移，再做分客群",
            "stop_and_document": "仅完善文档，不做任何代码变动",
        },
    ),
}

def main():
    print("=" * 68)
    print("TypeSafe AI Jev · 决策下一步行动路线 (Next Step Decision)")
    print("=" * 68)

    cfg = jev.get_config()
    print(f"API Endpoint : {cfg['endpoint']}")
    print(f"Model ID     : {cfg['model']}")
    print(f"审理问题数量 : {len(QUESTIONS)} 项")
    print("-" * 68)

    res = jev.call_systemone(state=DECISION_STATE, questions=QUESTIONS)
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
        "jev_next_step_decision.json",
    )
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    print(f"\nJev 决策结果已保存至: {out_file}")

if __name__ == "__main__":
    main()
