#!/usr/bin/env python3
"""jev.py 的离线单测。全离网，通过 mock urllib 验证原语构造与响应解析。"""
import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import jev  # noqa: E402


class MockHTTPResponse:
    def __init__(self, data, status=200):
        self.data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_get_config():
    cfg = jev.get_config()
    assert "api_key" in cfg
    assert "endpoint" in cfg
    assert "model" in cfg
    assert cfg["endpoint"] == jev.DEFAULT_ENDPOINT
    assert cfg["model"] == jev.DEFAULT_MODEL
    print("  OK get_config 正确读取默认或文件配置")


def test_make_primitives():
    # noul
    q_noul = jev.make_noul("是否存在单点故障？")
    assert q_noul["type"] == "noul"
    assert q_noul["instructions"] == "是否存在单点故障？"

    # choice
    q_choice = jev.make_choice("评估风险等级", {"high": "严重", "low": "轻微"})
    assert q_choice["type"] == "choice"
    assert q_choice["instructions"] == "评估风险等级"
    assert q_choice["criteria"]["high"] == "严重"

    # score
    q_score = jev.make_score("评分", ["极低", "中等", "极高"])
    assert q_score["type"] == "score"
    assert q_score["criteria"] == ["极低", "中等", "极高"]

    # validation errors
    try:
        jev.make_choice("test", {})
        assert False, "空字典应抛出异常"
    except ValueError:
        pass

    try:
        jev.make_score("test", [])
        assert False, "空列表应抛出异常"
    except ValueError:
        pass

    print("  OK make_noul, make_choice, make_score 原语构造与校验正确")


def test_call_systemone_mock_success(monkeypatch=None):
    mock_payload = {
        "model": "jev-1.14.0",
        "answers": {
            "spof": {"type": "noul", "noul": 0.95},
            "risk": {
                "type": "choice",
                "choice": "high",
                "confidence": 0.88,
                "probabilities": {"high": 0.9, "low": 0.1},
            },
        },
        "usage": {"input_tokens": 150, "output_tokens": 20},
    }

    orig_urlopen = urllib.request.urlopen

    def mock_urlopen(req, timeout=None):
        return MockHTTPResponse(mock_payload)

    urllib.request.urlopen = mock_urlopen
    try:
        res = jev.call_systemone(
            state="System state",
            questions={"spof": jev.make_noul("test")},
            api_key="mock_key",
        )
        assert res["ok"] is True
        assert res["model"] == "jev-1.14.0"
        assert res["answers"]["spof"]["noul"] == 0.95
        assert res["answers"]["risk"]["choice"] == "high"
        print("  OK call_systemone 成功解析 Mock API 响应")
    finally:
        urllib.request.urlopen = orig_urlopen


def test_call_systemone_no_key():
    orig_cfg = jev.get_config
    jev.get_config = lambda: {"api_key": "", "endpoint": "http://x", "model": "m"}
    try:
        res = jev.call_systemone(
            state="test",
            questions={},
            api_key="",
        )
        assert res["ok"] is False
        assert "未配置 TYPESAFE_API_KEY" in res["error"]
        print("  OK 缺少 API Key 时安全返回清晰错误提示")
    finally:
        jev.get_config = orig_cfg


def test_call_systemone_http_error():
    orig_urlopen = urllib.request.urlopen

    def mock_urlopen(req, timeout=None):
        fp = io.BytesIO(b'{"detail":"Invalid request"}')
        raise urllib.error.HTTPError("http://api", 400, "Bad Request", {}, fp)

    urllib.request.urlopen = mock_urlopen
    try:
        res = jev.call_systemone(
            state="test",
            questions={},
            api_key="valid_key",
        )
        assert res["ok"] is False
        assert res["status_code"] == 400
        assert "Invalid request" in res["error"]
        print("  OK HTTP 错误能够被捕获并保留状态码与原因")
    finally:
        urllib.request.urlopen = orig_urlopen


def run_all():
    test_get_config()
    test_make_primitives()
    test_call_systemone_mock_success()
    test_call_systemone_no_key()
    test_call_systemone_http_error()
    print("通过 5 项")


if __name__ == "__main__":
    run_all()
