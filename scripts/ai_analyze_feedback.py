#!/usr/bin/env python3
"""AI 反馈智能收集与聚类分析 CLI 工具.

用法：
  python3 scripts/ai_analyze_feedback.py
  python3 scripts/ai_analyze_feedback.py --json
"""

import json
import os
import sys

# 将工程根目录与 server 加入 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from server.nodekit.ai_feedback import analyze_feedback_entries
except ModuleNotFoundError:
    from nodekit.ai_feedback import analyze_feedback_entries

DATA_DIR = os.environ.get("DATA_DIR") or ("/opt/web-data" if os.path.exists("/opt/web-data") else os.path.join(BASE_DIR, "tests", "data"))


def load_feedbacks():
    fb_file = os.path.join(DATA_DIR, "feedback.jsonl")
    if not os.path.exists(fb_file):
        return []
    items = []
    with open(fb_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
    return items


def main():
    as_json = "--json" in sys.argv
    entries = load_feedbacks()
    analysis = analyze_feedback_entries(entries)

    if as_json:
        print(json.dumps(analysis, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(" 🤖 Evergreen · OwnLine AI 反馈智能聚类分析简报")
    print("=" * 60)
    print(f"数据源路径: {os.path.join(DATA_DIR, 'feedback.jsonl')}")
    print(f"反馈总样本: {analysis['total_count']} 条")
    print(f"健康紧急度: {analysis['urgency'].upper()}")
    print(f"整体概括  : {analysis['summary']}")
    print("-" * 60)

    clusters = analysis.get("clusters") or []
    if not clusters:
        print("暂无异常聚类，系统各节点运行稳定。")
    else:
        for i, c in enumerate(clusters, 1):
            nodes_text = ", ".join(c["affected_nodes"]) if c["affected_nodes"] else "全局/未绑定单一节点"
            print(f"[{i}] {c['name']} (共 {c['count']} 次反馈)")
            print(f"    受影响节点: {nodes_text}")
            if c.get("sample_quotes"):
                print(f"    用户原声  : \"{c['sample_quotes'][0]}\"")
            print(f"    AI排查建议: {c['proposed_fix']}")
            print()

    action_items = analysis.get("action_items") or []
    if action_items:
        print("=" * 60)
        print(" 📋 AI 推荐修复动作待办:")
        for idx, item in enumerate(action_items, 1):
            print(f"  {idx}. {item}")
        print("=" * 60)


if __name__ == "__main__":
    main()
