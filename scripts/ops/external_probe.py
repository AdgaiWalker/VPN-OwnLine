#!/usr/bin/env python3
"""External SLA and stealth verification prober + 7-day rolling aggregator."""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import json
import math
from pathlib import Path
import ssl
import subprocess
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CN_TZ = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_HISTORY_PATH = ROOT / ".ops-private" / "external_probe_history.jsonl"


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except Exception:
        return False


def _percentile(sorted_vals: List[float], pct: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 1)
    idx = math.ceil((pct / 100.0) * len(sorted_vals)) - 1
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return round(sorted_vals[idx], 1)


def probe_once(
    url: str,
    *,
    socks5: Optional[str] = None,
    isp_expected_ip: Optional[str] = None,
    timeout: float = 10.0,
    insecure: bool = False,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Run one external HTTPS stealth probe and optional SOCKS5 exit-IP check."""
    now = now or datetime.datetime.now(CN_TZ)
    ctx = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "OwnLine-SLA-Probe/1.0"})

    status = 0
    headers: Dict[str, str] = {}
    error = ""
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = int(resp.status)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            resp.read(256)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
    except Exception as exc:
        error = str(exc)
    rtt_ms = round((time.monotonic() - t0) * 1000.0, 1)

    server_hdr = headers.get("server", "")
    https_ok = 200 <= status < 500
    stealth_ok = bool(https_ok and "caddy" not in server_hdr.lower())

    proxy_ok: Optional[bool] = None
    proxy_ms: Optional[float] = None
    exit_ip = ""
    isp_leak = False

    if socks5:
        proxy_ok = False
        for check_url in ("https://api.ipify.org", "https://ipv4.icanhazip.com"):
            res = subprocess.run(
                [
                    "curl", "-fsS", "--max-time", str(timeout),
                    "--socks5-hostname", socks5,
                    "-w", "\n%{time_starttransfer}",
                    check_url,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            lines = [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]
            if res.returncode == 0 and lines and _is_ip(lines[0]):
                exit_ip = lines[0]
                proxy_ok = True
                if len(lines) >= 2:
                    try:
                        proxy_ms = round(float(lines[-1]) * 1000.0, 1)
                    except ValueError:
                        proxy_ms = None
                break
        if isp_expected_ip and exit_ip and exit_ip != isp_expected_ip.strip():
            isp_leak = True

    overall_ok = https_ok and (proxy_ok if socks5 else True) and not isp_leak
    return {
        "ts": now.isoformat(),
        "url": url,
        "ok": overall_ok,
        "https_ok": https_ok,
        "status": status,
        "rtt_ms": rtt_ms,
        "server_header": server_hdr,
        "stealth_ok": stealth_ok,
        "socks5": socks5 or "",
        "proxy_ok": proxy_ok,
        "proxy_ms": proxy_ms,
        "exit_ip": exit_ip,
        "isp_leak": isp_leak,
        "error": error,
    }


def append_record(record: Dict[str, Any], path: Path = DEFAULT_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_records(path: Path = DEFAULT_HISTORY_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def summarize_history(
    records: List[Dict[str, Any]],
    *,
    days: int = 7,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Compute SLA summary metrics over a rolling day window."""
    now = now or datetime.datetime.now(CN_TZ)
    filtered: List[Dict[str, Any]] = []
    if days and days > 0:
        cutoff = now - datetime.timedelta(days=days)
        for rec in records:
            ts_raw = rec.get("ts")
            if not ts_raw:
                continue
            try:
                ts = datetime.datetime.fromisoformat(str(ts_raw))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=CN_TZ)
                if ts >= cutoff:
                    filtered.append(rec)
            except ValueError:
                continue
    else:
        filtered = list(records)

    total = len(filtered)
    if total == 0:
        return {
            "window_days": days,
            "sample_count": 0,
            "ok_count": 0,
            "fail_count": 0,
            "availability_pct": 0.0,
            "disconnect_rate_pct": 0.0,
            "p50_ms": None,
            "p95_ms": None,
            "stealth_pass_rate_pct": 0.0,
            "isp_leak_count": 0,
        }

    ok_count = sum(1 for r in filtered if r.get("ok") is True)
    fail_count = total - ok_count
    stealth_ok = sum(1 for r in filtered if r.get("stealth_ok") is True)
    isp_leaks = sum(1 for r in filtered if r.get("isp_leak") is True)
    latencies = sorted(
        float(r["rtt_ms"])
        for r in filtered
        if r.get("https_ok") is True and isinstance(r.get("rtt_ms"), (int, float))
    )

    return {
        "window_days": days,
        "sample_count": total,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "availability_pct": round((ok_count / total) * 100.0, 2),
        "disconnect_rate_pct": round((fail_count / total) * 100.0, 2),
        "p50_ms": _percentile(latencies, 50.0),
        "p95_ms": _percentile(latencies, 95.0),
        "stealth_pass_rate_pct": round((stealth_ok / total) * 100.0, 2),
        "isp_leak_count": isp_leaks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run external SLA probe and summarize rolling availability.")
    parser.add_argument("--url", help="Target HTTPS URL (e.g. https://v.goodloop.si:8443/)")
    parser.add_argument("--socks5", help="Optional local proxy host:port for exit IP & leak probing")
    parser.add_argument("--isp-expected-ip", help="Expected residential egress IP when --socks5 is supplied")
    parser.add_argument("--out", default=str(DEFAULT_HISTORY_PATH), help="JSONL history path")
    parser.add_argument("--days", type=int, default=7, help="Rolling report window in days")
    parser.add_argument("--report", action="store_true", help="Print rolling SLA report")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    out_path = Path(args.out)
    last_record = None
    if args.url:
        last_record = probe_once(
            args.url,
            socks5=args.socks5,
            isp_expected_ip=args.isp_expected_ip,
            timeout=args.timeout,
            insecure=args.insecure,
        )
        append_record(last_record, out_path)

    summary = summarize_history(load_records(out_path), days=args.days) if (args.report or not args.url) else None

    if args.json:
        payload: Dict[str, Any] = {}
        if last_record is not None:
            payload["probe"] = last_record
        if summary is not None:
            payload["summary"] = summary
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if last_record is not None:
            print(
                f"PROBE ok={last_record['ok']} status={last_record['status']} "
                f"rtt_ms={last_record['rtt_ms']} stealth_ok={last_record['stealth_ok']} "
                f"server={last_record['server_header'] or '-'}"
            )
        if summary is not None:
            print(
                f"REPORT window={summary['window_days']}d samples={summary['sample_count']} "
                f"avail={summary['availability_pct']}% disconnect={summary['disconnect_rate_pct']}% "
                f"p50={summary['p50_ms']}ms p95={summary['p95_ms']}ms "
                f"stealth={summary['stealth_pass_rate_pct']}% leaks={summary['isp_leak_count']}"
            )

    if last_record is not None and not last_record["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
