#!/usr/bin/env python3
"""中转节点双落地高可用自愈守护进程（纯标准库，零外部依赖）。

职责：
  1. 周期性（默认 5 秒）对主落地（硅谷）与备用落地（新加坡）执行健康探测。
  2. 状态机防抖：连续 fail_threshold 次探测失败才触发主备倒换；连续 recover_threshold 次探测成功才回切主链路。
  3. 支持通过 sing-box 配置切换或原子路由置换，保证客户端出网不断流。
  4. 产出结构化状态文件 /opt/web-data/relay_state.json 供主控 API 实时呈现。
"""
import json
import os
import socket
import sys
import time

STATE_FILE = os.environ.get("RELAY_STATE_FILE", "/opt/web-data/relay_state.json")
DEFAULT_PROBE_TIMEOUT = 3.0
DEFAULT_FAIL_THRESHOLD = 2
DEFAULT_RECOVER_THRESHOLD = 3


def check_tcp_port(host, port, timeout=DEFAULT_PROBE_TIMEOUT):
    """纯标准库 TCP SYN 握手探活。返回 (ok: bool, latency_ms: int or None)"""
    t0 = time.time()
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        ms = int((time.time() - t0) * 1000)
        return True, ms
    except Exception:
        return False, None


class RelayFailoverEngine:
    """双落地自愈状态机引擎（纯逻辑，解耦 I/O 方便离网单测）"""

    def __init__(self, primary_host, primary_port, fallback_host, fallback_port,
                 fail_threshold=DEFAULT_FAIL_THRESHOLD,
                 recover_threshold=DEFAULT_RECOVER_THRESHOLD):
        self.primary_host = primary_host
        self.primary_port = int(primary_port)
        self.fallback_host = fallback_host
        self.fallback_port = int(fallback_port)
        self.fail_threshold = fail_threshold
        self.recover_threshold = recover_threshold

        self.active_target = primary_host
        self.consecutive_primary_fails = 0
        self.consecutive_primary_successes = 0
        self.last_switch_time = None
        self.switch_history = []

    def evaluate_step(self, primary_ok, fallback_ok, now_ts=None):
        """输入当前探测结果，计算下一个状态并返回是否发生切换事件。
        返回 (did_switch: bool, new_target: str, reason: str)
        """
        now_ts = now_ts or time.time()
        did_switch = False
        reason = ""

        # 1. 追踪主落地连续成功/失败计数
        if primary_ok:
            self.consecutive_primary_successes += 1
            self.consecutive_primary_fails = 0
        else:
            self.consecutive_primary_fails += 1
            self.consecutive_primary_successes = 0

        # 2. 判断是否触发倒换 (Primary -> Fallback)
        if self.active_target == self.primary_host:
            if self.consecutive_primary_fails >= self.fail_threshold:
                if fallback_ok:
                    self.active_target = self.fallback_host
                    self.last_switch_time = now_ts
                    did_switch = True
                    reason = f"主落地连续 {self.consecutive_primary_fails} 次探测失败，自动故障倒换至备用落地"
                    self.switch_history.append({"time": now_ts, "to": self.fallback_host, "reason": reason})
                else:
                    reason = "主落地与备用落地均不可达，保持当前路由不颠簸"
        # 3. 判断是否触发回切 (Fallback -> Primary)
        elif self.active_target == self.fallback_host:
            if self.consecutive_primary_successes >= self.recover_threshold:
                self.active_target = self.primary_host
                self.last_switch_time = now_ts
                did_switch = True
                reason = f"主落地已连续 {self.consecutive_primary_successes} 次探活正常，自动回切至主落地"
                self.switch_history.append({"time": now_ts, "to": self.primary_host, "reason": reason})

        return did_switch, self.active_target, reason

    def get_state(self):
        return {
            "active_target": self.active_target,
            "primary": {"host": self.primary_host, "port": self.primary_port},
            "fallback": {"host": self.fallback_host, "port": self.fallback_port},
            "consecutive_primary_fails": self.consecutive_primary_fails,
            "consecutive_primary_successes": self.consecutive_primary_successes,
            "last_switch_time": self.last_switch_time,
            "history": self.switch_history[-10:],
        }


def save_relay_state(state, path=STATE_FILE):
    """保存中转健康状态至 JSON"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False
