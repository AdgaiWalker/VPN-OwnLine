#!/usr/bin/env python3
"""TypeSafe AI System One (Jev) 集成模块（纯标准库，零外部依赖）。

用于对梯子多节点集群的架构盲区、单点故障、配置漂移、生命周期及封锁风险进行量化预测。
支持三种 System One 原语：
  1. noul   (布尔/真假概率评估)
  2. choice (单选分类与概率分布)
  3. score  (有序等级评分与概率加权)
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"


def get_config():
    """读取 TypeSafe API 配置。优先级：环境变量 > 本地 config/typesafe.json > /opt/web-data/typesafe.json"""
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    endpoint = os.environ.get("TYPESAFE_ENDPOINT", "").strip()
    model = os.environ.get("TYPESAFE_MODEL", "").strip()

    search_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "typesafe.json"),
        os.path.join(os.environ.get("LADDER_DATA", "/opt/web-data"), "typesafe.json"),
        os.path.expanduser("~/.config/typesafe.json"),
    ]

    for p in search_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not api_key:
                        api_key = data.get("api_key", "").strip()
                    if not endpoint:
                        endpoint = data.get("endpoint", "").strip()
                    if not model:
                        model = data.get("model", "").strip()
            except Exception:
                pass
            if api_key:
                break

    return {
        "api_key": api_key,
        "endpoint": endpoint or DEFAULT_ENDPOINT,
        "model": model or DEFAULT_MODEL,
    }


def make_noul(instructions):
    """构造布尔 (noul) 原语问题"""
    return {
        "type": "noul",
        "instructions": str(instructions),
    }


def make_choice(instructions, criteria_dict):
    """构造单选 (choice) 原语问题"""
    if not isinstance(criteria_dict, dict) or not criteria_dict:
        raise ValueError("criteria_dict 必须是非空字典")
    return {
        "type": "choice",
        "instructions": str(instructions),
        "criteria": {str(k): str(v) for k, v in criteria_dict.items()},
    }


def make_score(instructions, criteria_list):
    """构造评分 (score) 原语问题"""
    if not isinstance(criteria_list, (list, tuple)) or not criteria_list:
        raise ValueError("criteria_list 必须是非空列表")
    return {
        "type": "score",
        "instructions": str(instructions),
        "criteria": [str(c) for c in criteria_list],
    }


def call_systemone(state, questions, api_key=None, endpoint=None, model=None, timeout=20):
    """向 TypeSafe AI System One 发送预测请求。
    
    返回字典结构:
      {
        "ok": bool,
        "model": str,
        "answers": dict,
        "usage": dict,
        "error": str (若失败)
      }
    """
    cfg = get_config()
    token = api_key or cfg["api_key"]
    ep = endpoint or cfg["endpoint"]
    mdl = model or cfg["model"]

    if not token:
        return {
            "ok": False,
            "error": "未配置 TYPESAFE_API_KEY。请检查 ~/.zshrc 或 config/typesafe.json",
        }

    payload = {
        "model": mdl,
        "state": state,
        "questions": questions,
    }

    req_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ep,
        data=req_data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Ladder-NodeKit/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            res = json.loads(body)
            return {
                "ok": True,
                "model": res.get("model", mdl),
                "answers": res.get("answers", {}),
                "usage": res.get("usage", {}),
            }
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": e.code,
            "error": f"HTTP {e.code}: {err_msg}",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"请求异常: {str(e)}",
        }
