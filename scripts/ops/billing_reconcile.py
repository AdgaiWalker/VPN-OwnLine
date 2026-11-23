#!/usr/bin/env python3
"""Reconcile OwnLine panel traffic totals against official cloud billing exports."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from nodekit import quota_guard  # noqa: E402


def extract_panel_metrics(data: Dict[str, Any], host: Optional[str] = None) -> Dict[str, Any]:
    """Extract panel monthly GB and reset day from usage.json or /api/traffic/stats."""
    if not isinstance(data, dict):
        raise ValueError("Invalid panel JSON payload")

    # Case 1: /api/traffic/stats output
    if isinstance(data.get("total"), dict) and "this_month_gb" in data["total"]:
        panel_gb = float(data["total"]["this_month_gb"])
        reset_day = None
        nodes_map = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        if host and isinstance(nodes_map.get(host), dict):
            panel_gb = float(nodes_map[host].get("used_gb", panel_gb))
            reset_day = quota_guard.parse_reset_day(nodes_map[host].get("end"))
        elif nodes_map:
            for item in nodes_map.values():
                if isinstance(item, dict) and item.get("end"):
                    reset_day = quota_guard.parse_reset_day(item.get("end"))
                    break
        return {"panel_gb": round(panel_gb, 3), "panel_reset_day": reset_day}

    # Case 2: raw usage.json keyed by IP
    candidates = []
    for k, v in data.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if host and k != host:
            continue
        candidates.append((k, v))
    if not candidates:
        raise ValueError(f"No matching host entry found in panel JSON (host={host})")
    used = sum(float(v.get("used") or 0.0) for _, v in candidates)
    reset_day = quota_guard.parse_reset_day(candidates[0][1].get("reset_day") or candidates[0][1].get("end"))
    return {"panel_gb": round(used, 3), "panel_reset_day": reset_day}


def parse_official_file(path: Path) -> Dict[str, Any]:
    """Parse official cloud traffic statement from JSON or CSV."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError("Official JSON must be an object")
        gb = obj.get("used_gb")
        if gb is None:
            gb = obj.get("used")
        if gb is None:
            gb = obj.get("traffic_gb")
        if gb is None:
            raise ValueError("Official JSON missing used_gb/used/traffic_gb")
        rday = quota_guard.parse_reset_day(obj.get("reset_day") or obj.get("end"))
        return {"official_gb": float(gb), "official_reset_day": rday}

    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    if not rows:
        raise ValueError("Official CSV contains no data rows")
    row = rows[-1]
    gb_val = None
    for key in ("used_gb", "UsedGB", "traffic_gb", "used", "已用流量(GB)", "流量(GB)", "Consumption"):
        if key in row and str(row[key]).strip():
            gb_val = float(str(row[key]).strip())
            break
    if gb_val is None:
        raise ValueError("Official CSV missing recognizable GB column")
    rday = None
    for key in ("reset_day", "ResetDay", "end", "PeriodEnd", "重置日"):
        if key in row and str(row[key]).strip():
            rday = quota_guard.parse_reset_day(row[key])
            break
    return {"official_gb": gb_val, "official_reset_day": rday}


def reconcile_billing(
    panel_gb: float,
    official_gb: float,
    *,
    panel_reset_day: Optional[int] = None,
    official_reset_day: Optional[int] = None,
) -> Dict[str, Any]:
    panel_r = round(float(panel_gb), 3)
    official_r = round(float(official_gb), 3)
    delta_gb = round(panel_r - official_r, 3)
    if official_r > 0:
        delta_pct = round((abs(delta_gb) / official_r) * 100.0, 2)
    else:
        delta_pct = 0.0 if panel_r == 0 else 100.0

    reset_match: Optional[bool] = None
    if panel_reset_day is not None and official_reset_day is not None:
        reset_match = int(panel_reset_day) == int(official_reset_day)

    if delta_pct <= 5.0 and reset_match is not False:
        status = "aligned"
    elif delta_pct <= 15.0:
        status = "minor_drift"
    else:
        status = "discrepancy"

    return {
        "panel_gb": panel_r,
        "official_gb": official_r,
        "delta_gb": delta_gb,
        "delta_pct": delta_pct,
        "panel_reset_day": panel_reset_day,
        "official_reset_day": official_reset_day,
        "reset_day_match": reset_match,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile panel traffic numbers with cloud provider billing.")
    parser.add_argument("--panel-file", help="Path to usage.json or /api/traffic/stats JSON output")
    parser.add_argument("--panel-gb", type=float, help="Panel used GB value")
    parser.add_argument("--panel-reset-day", type=int)
    parser.add_argument("--host", help="Optional node IP to select from usage.json or stats JSON")
    parser.add_argument("--official-file", help="Path to official cloud billing CSV or JSON")
    parser.add_argument("--official-gb", type=float, help="Official cloud console used GB")
    parser.add_argument("--official-reset-day", type=int)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on minor_drift as well as discrepancy")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.panel_file:
        pdata = json.loads(Path(args.panel_file).read_text(encoding="utf-8"))
        pmetrics = extract_panel_metrics(pdata, host=args.host)
        panel_gb = pmetrics["panel_gb"]
        panel_reset = args.panel_reset_day if args.panel_reset_day is not None else pmetrics["panel_reset_day"]
    elif args.panel_gb is not None:
        panel_gb = args.panel_gb
        panel_reset = args.panel_reset_day
    else:
        parser.error("Provide --panel-file or --panel-gb")

    if args.official_file:
        ometrics = parse_official_file(Path(args.official_file))
        official_gb = ometrics["official_gb"]
        official_reset = args.official_reset_day if args.official_reset_day is not None else ometrics["official_reset_day"]
    elif args.official_gb is not None:
        official_gb = args.official_gb
        official_reset = args.official_reset_day
    else:
        parser.error("Provide --official-file or --official-gb")

    result = reconcile_billing(
        panel_gb,
        official_gb,
        panel_reset_day=panel_reset,
        official_reset_day=official_reset,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"status={result['status']} panel={result['panel_gb']}GB "
            f"official={result['official_gb']}GB delta={result['delta_gb']:+.3f}GB ({result['delta_pct']}%) "
            f"reset_match={result['reset_day_match']}"
        )

    if result["status"] == "discrepancy":
        return 1
    if args.strict and result["status"] == "minor_drift":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
