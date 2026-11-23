#!/usr/bin/env python3
"""traffic_stats_tests.py: 多维度流量统计与使用配额规划引擎单元测试。"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import traffic_stats as T  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  OK {name}")
    else:
        print(f"  FAIL: {name} {detail}", file=sys.stderr)
        sys.exit(1)


MOCK_VNSTAT_JSON = """{
  "vnstatversion": "2.10",
  "jsonversion": "2",
  "interfaces": [
    {
      "name": "eth0",
      "traffic": {
        "day": [
          {"id": 0, "date": {"year": 2026, "month": 11, "day": 21}, "rx": 1048576, "tx": 2097152},
          {"id": 1, "date": {"year": 2026, "month": 11, "day": 20}, "rx": 2097152, "tx": 4194304},
          {"id": 2, "date": {"year": 2026, "month": 11, "day": 19}, "rx": 1048576, "tx": 1048576}
        ],
        "month": [
          {"id": 0, "date": {"year": 2026, "month": 11}, "rx": 10485760, "tx": 20971520}
        ],
        "year": [
          {"id": 0, "date": {"year": 2026}, "rx": 52428800, "tx": 52428800}
        ]
      }
    }
  ]
}"""


def main():
    # 1. 测试 vnStat JSON 解析 (KiB 换算为 GB)
    # day[0]: (1048576 + 2097152) KiB = 3145728 KiB = 3.0 GiB
    # day[1]: (2097152 + 4194304) KiB = 6291456 KiB = 6.0 GiB
    # 7 天累计: 3 + 6 + 2 = 11.0 GiB
    # month[0]: 30 GiB
    # year[0]: 100 GiB
    vn_parsed = T.parse_vnstat_json(MOCK_VNSTAT_JSON)
    check("正确解析 vnStat 今日流量", vn_parsed.get("today_gb") == 3.0, str(vn_parsed))
    check("正确解析 vnStat 昨日流量", vn_parsed.get("yesterday_gb") == 6.0, str(vn_parsed))
    check("正确统计 vnStat 本周流量", vn_parsed.get("this_week_gb") == 11.0, str(vn_parsed))
    check("正确解析 vnStat 本月流量", vn_parsed.get("this_month_gb") == 30.0, str(vn_parsed))
    check("正确解析 vnStat 年度流量", vn_parsed.get("this_year_gb") == 100.0, str(vn_parsed))

    # 2. 异常/空数据保底
    check("空数据保底不崩溃", T.parse_vnstat_json("") == {})
    check("非法数据保底不崩溃", T.parse_vnstat_json({"unknown": 123}) == {})

    # 3. 测试时序快照记录与增量计算
    history = {}
    base_time = datetime.datetime(2026, 11, 21, 10, 0, 0, tzinfo=datetime.timezone.utc)
    host = "43.153.56.137"

    # 首次采样 (290.0 GB)
    history = T.record_history_snapshot(history, {"used": 290.0, "total": 512.0}, host, now=base_time)
    node_h = history["nodes"][host]
    check("首次采样今日增量为 0", node_h["daily_totals"]["2026-11-21"] == 0.0)

    # 10 分钟后第二次采样 (291.5 GB，增长 1.5 GB)
    t2 = base_time + datetime.timedelta(minutes=10)
    history = T.record_history_snapshot(history, {"used": 291.5, "total": 512.0}, host, now=t2)
    check("第二次采样正确累加增量 1.5GB", node_h["daily_totals"]["2026-11-21"] == 1.5)

    # 4. 测试跨月/账单清零重置场景 (从 512GB 重置到 2.0GB)
    t3 = base_time + datetime.timedelta(minutes=20)
    history = T.record_history_snapshot(history, {"used": 2.0, "total": 512.0}, host, now=t3)
    check("月度清零后正向递增新周期用量 2.0GB", node_h["daily_totals"]["2026-11-21"] == 3.5)

    # 5. 测试行动指南生成（充足配额场景）
    guidance = T.generate_usage_guidance(
        used_gb=100.0,
        total_gb=500.0,
        start_str="2026-11-01",
        end_str="2026-11-30",
        today_used_gb=2.0,
        now=datetime.datetime(2026, 11, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
    )
    # 剩余天数: 10 天，剩余流量: 400 GB，日均建议配额: 40 GB/天，今日仅用 2GB (5%) -> pace="abundant"
    check("充足场景正确计算剩余天数与日均配额", guidance["days_remaining"] == 10 and guidance["daily_budget_gb"] == 40.0)
    check("充足场景判定为 abundant 状态", guidance["pace"] == "abundant" and "充裕" in guidance["badge"])

    # 6. 测试行动指南生成（严重超支/濒临熔断场景）
    guidance_crit = T.generate_usage_guidance(
        used_gb=490.0,
        total_gb=500.0,
        start_str="2026-11-01",
        end_str="2026-11-30",
        today_used_gb=25.0,
        now=datetime.datetime(2026, 11, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
    )
    check("濒临耗尽场景判定为 critical 预警", guidance_crit["pace"] == "critical" and "预警" in guidance_crit["badge"])

    # 7. 全系统聚合汇总报表
    mock_usage = {
        "43.153.56.137": {
            "used": 291.5, "total": 512.0, "start": "2026-10-23", "end": "2026-11-23", "region": "硅谷"
        },
        "49.233.210.101": {
            "used": 2.1, "total": 500.0, "start": "2026-10-24", "end": "2026-11-24", "region": "北京"
        },
        "43.163.4.104": {
            "used": 10.0, "total": 1024.0, "start": "2026-10-30", "end": "2026-11-30", "region": "新加坡"
        },
        "_ts": "2026-11-21T06:00:00Z"
    }
    # 7a: 未指定 active_nodes 时包含全部
    agg_all = T.aggregate_all_traffic_stats(mock_usage, history, now=t3)
    check("未指定 active_nodes 时包含全部节点", len(agg_all["nodes"]) == 3)

    # 7b: 传入 active_nodes 时过滤非活动节点（排除新加坡），并仅按活动出口节点统计总配额
    active_cluster = [
        {"name": "硅谷", "host": "43.153.56.137", "role": "exit"},
        {"name": "北京", "host": "49.233.210.101", "role": "relay"}
    ]
    agg = T.aggregate_all_traffic_stats(mock_usage, history, now=t3, active_nodes=active_cluster)
    check("正确根据 active_nodes 过滤废弃实例", len(agg["nodes"]) == 2 and "43.163.4.104" not in agg["nodes"])
    check("出海总额度仅绑定出口落地节点", agg["total"]["total_quota_gb"] == 512.0)
    check("出海月度用量仅绑定出口落地节点", agg["total"]["this_month_gb"] == 291.5)
    check("行动指引剩余量与总额度绝对对齐(SSOT)", agg["total"]["guidance"]["remaining_gb"] == 220.5)
    check("行动指引包含动态偏差比率", "pacing_ratio" in agg["total"]["guidance"])

    # 7c: 周期即将结束（<=2天）时提供安全余量保护文案
    guidance_near_end = T.generate_usage_guidance(
        used_gb=200.0,
        total_gb=500.0,
        start_str="2026-10-23",
        end_str="2026-11-23",
        today_used_gb=1.0,
        now=datetime.datetime(2026, 11, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)
    )
    check("周期临近结束时提示安全余量避免超量计费", "账单周期即将切换" in guidance_near_end["text"] and guidance_near_end["days_remaining"] == 2)

    # 7d: 专线中转跳板木桶短板感知 (Bottleneck Theory)
    mock_bottleneck_usage = {
        "43.153.56.137": {
            "used": 100.0, "total": 512.0, "start": "2026-10-23", "end": "2026-11-23", "region": "硅谷"  # 剩余 412 GB
        },
        "49.233.210.101": {
            "used": 490.0, "total": 500.0, "start": "2026-10-24", "end": "2026-11-24", "region": "北京"  # 剩余仅 10 GB
        },
        "_ts": "2026-11-21T06:00:00Z"
    }
    agg_bottle = T.aggregate_all_traffic_stats(mock_bottleneck_usage, history, now=t3, active_nodes=active_cluster)
    check("识别专线跳板为木桶瓶颈", agg_bottle["total"]["guidance"].get("bottleneck", {}).get("is_relay_bottleneck") is True)
    check("短板场景发出跳板短板预警", agg_bottle["total"]["guidance"]["badge"] == "跳板短板预警" and "北京" in agg_bottle["total"]["guidance"]["text"])

    agg_default_now = T.aggregate_all_traffic_stats(mock_usage, history, active_nodes=active_cluster)
    check("默认时间输出显式 +08:00 时区而非错标 +00:00", agg_default_now["updated_at"].endswith("+08:00"), agg_default_now["updated_at"])

    print(f"\n通过 {passed} 项")


if __name__ == "__main__":
    main()
