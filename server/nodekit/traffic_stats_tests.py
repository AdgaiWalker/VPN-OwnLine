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
          {"id": 0, "date": {"year": 2026, "month": 11, "day": 21}, "rx": 1073741824, "tx": 2147483648},
          {"id": 1, "date": {"year": 2026, "month": 11, "day": 20}, "rx": 2147483648, "tx": 4294967296},
          {"id": 2, "date": {"year": 2026, "month": 11, "day": 19}, "rx": 1073741824, "tx": 1073741824}
        ],
        "month": [
          {"id": 0, "date": {"year": 2026, "month": 11}, "rx": 10737418240, "tx": 21474836480}
        ],
        "year": [
          {"id": 0, "date": {"year": 2026}, "rx": 53687091200, "tx": 53687091200}
        ]
      }
    }
  ]
}"""

MOCK_VNSTAT_V1_JSON = """{
  "vnstatversion": "1.18",
  "jsonversion": "1",
  "interfaces": [
    {
      "id": "eth0",
      "traffic": {
        "days": [
          {"id": 0, "date": {"year": 2026, "month": 11, "day": 21}, "rx": 1048576, "tx": 2097152},
          {"id": 1, "date": {"year": 2026, "month": 11, "day": 20}, "rx": 2097152, "tx": 4194304},
          {"id": 2, "date": {"year": 2026, "month": 11, "day": 19}, "rx": 1048576, "tx": 1048576}
        ],
        "months": [
          {"id": 0, "date": {"year": 2026, "month": 11}, "rx": 10485760, "tx": 20971520}
        ],
        "years": [
          {"id": 0, "date": {"year": 2026}, "rx": 52428800, "tx": 52428800}
        ]
      }
    }
  ]
}"""


def main():
    # 1. 测试 vnStat 2.x (bytes) 与 vnStat 1.x (KiB) JSON 解析
    vn_parsed = T.parse_vnstat_json(MOCK_VNSTAT_JSON)
    check("vnStat 2.x 识别为 bytes 单位", vn_parsed.get("unit") == "bytes", str(vn_parsed))
    check("正确解析 vnStat 2.x 今日流量", vn_parsed.get("today_gb") == 3.0, str(vn_parsed))
    check("正确解析 vnStat 2.x 昨日流量", vn_parsed.get("yesterday_gb") == 6.0, str(vn_parsed))
    check("正确统计 vnStat 2.x 本周流量", vn_parsed.get("this_week_gb") == 11.0, str(vn_parsed))
    check("正确解析 vnStat 2.x 本月流量", vn_parsed.get("this_month_gb") == 30.0, str(vn_parsed))
    check("正确解析 vnStat 2.x 年度流量", vn_parsed.get("this_year_gb") == 100.0, str(vn_parsed))

    vn_v1 = T.parse_vnstat_json(MOCK_VNSTAT_V1_JSON)
    check("vnStat 1.x 识别为 KiB 单位并准确换算", vn_v1.get("unit") == "kib" and vn_v1.get("today_gb") == 3.0 and vn_v1.get("this_month_gb") == 30.0, str(vn_v1))

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

    # 8. 深度决策模型不变量校验 (14 日序列 + 熔断前安全余量 + 周期刻度 + 冷启动/无上限降级)
    deep_usage = {
        "43.153.56.137": {"used": 309.49, "total": 512.0, "start": "2026-10-27", "end": "2026-11-26"},
        "198.51.100.88": {"used": 164.0, "total": 200.0, "start": "2026-10-27", "end": "2026-11-26"},
    }
    deep_nodes = [
        {"name": "walker-sv", "host": "43.153.56.137", "role": "exit"},
        {"name": "relay-hk", "host": "198.51.100.88", "role": "relay"},
    ]
    now_deep = datetime.datetime(2026, 11, 25, 19, 0, 0, tzinfo=T.CN_TZ)
    deep_hist = {
        "nodes": {
            "43.153.56.137": {
                "daily_totals": {
                    (now_deep - datetime.timedelta(days=k)).strftime("%Y-%m-%d"): float(k + 1)
                    for k in range(10)
                }
            }
        }
    }
    agg_deep = T.aggregate_all_traffic_stats(
        deep_usage, deep_hist, now=now_deep, active_nodes=deep_nodes, breaker_threshold_pct=85
    )
    tot_deep = agg_deep["total"]
    series = tot_deep["daily_series"]
    runway = tot_deep["runway"]
    cycle = tot_deep["cycle"]
    check("daily_series 严格返回 14 天升序且诚实标注 missing", len(series) == 14 and series[0]["missing"] is True and series[-1]["missing"] is False, str(len(series)))
    check("周期归一化刻度准确计算剩余天数与百分比", cycle["days_remaining"] == 1 and 90.0 <= cycle["elapsed_pct"] <= 100.0, str(cycle))
    check("熔断前安全余量严格等于跳板距 85% 熔断线距离 (6.0 GB) 且不大于账单剩余", runway["safe_before_breaker_gb"] == 6.0 and runway["safe_before_breaker_gb"] <= runway["effective_remaining_gb"], str(runway))
    check("拓扑排序首个元素为瓶颈中转节点 relay-hk", runway["bottleneck_node"] is not None and runway["bottleneck_node"]["name"] == "relay-hk" and len(runway["topology"]) == 2, str(runway["topology"]))

    # 冷启动与无套餐上限边界
    cold_agg = T.aggregate_all_traffic_stats(
        {"1.1.1.1": {"used": 12.3, "total": 0}},
        {"nodes": {"1.1.1.1": {"daily_totals": {now_deep.strftime("%Y-%m-%d"): 1.5}}}},
        now=now_deep,
        active_nodes=[{"name": "host-only", "host": "1.1.1.1", "role": "exit"}],
    )
    check("冷启动仅 1 天采样且无上限套餐安全降级", cold_agg["total"]["data_meta"]["history_days"] == 1 and cold_agg["total"]["data_meta"]["has_quota"] is False and cold_agg["total"]["runway"]["topology"] == [], str(cold_agg["total"]["data_meta"]))

    print(f"\n通过 {passed} 项")


if __name__ == "__main__":
    main()
