"""Read-only, one-shot Lighthouse discovery; credentials are never persisted."""

import ipaddress
import re
from concurrent.futures import ThreadPoolExecutor

from providers import tc3

class Problem(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _response(action, payload, secret_id, secret_key, region):
    try:
        response = tc3.call(action, payload, secret_id, secret_key, region)["Response"]
        if not isinstance(response, dict):
            raise ValueError("invalid response")
        if "Error" in response:
            code = str(response["Error"].get("Code", ""))
            if code.startswith(("AuthFailure", "UnauthorizedOperation")):
                raise Problem(
                    "TENCENT_AUTH_FAILED",
                    "腾讯云密钥无效或权限不足，请检查只读权限。",
                    403,
                )
            raise Problem("TENCENT_API_FAILED", "腾讯云查询未完成，请稍后重试。", 502)
        return response
    except Problem:
        raise
    except Exception:
        # Do not surface upstream exceptions: request headers can contain credentials.
        raise Problem(
            "TENCENT_UNAVAILABLE", "无法连接腾讯云，请检查网络后重试。", 502
        ) from None


def discover(secret_id, secret_key):
    if not isinstance(secret_id, str) or not isinstance(secret_key, str):
        raise Problem(
            "TENCENT_CREDENTIALS_REQUIRED", "请输入腾讯云 SecretId 和 SecretKey。"
        )
    secret_id, secret_key = secret_id.strip(), secret_key.strip()
    if not secret_id or not secret_key or len(secret_id) > 256 or len(secret_key) > 256:
        raise Problem(
            "TENCENT_CREDENTIALS_REQUIRED", "请输入有效的腾讯云 SecretId 和 SecretKey。"
        )
    response = _response("DescribeRegions", {}, secret_id, secret_key, "ap-singapore")
    entries = response.get("RegionSet")
    if not isinstance(entries, list) or len(entries) > 64:
        raise Problem(
            "TENCENT_RESPONSE_INVALID", "腾讯云地域列表无法识别，请稍后重试。", 502
        )
    regions = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise Problem(
                "TENCENT_RESPONSE_INVALID", "腾讯云地域列表无法识别，请稍后重试。", 502
            )
        code = entry.get("Region")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9-]{1,48}", code):
            raise Problem(
                "TENCENT_RESPONSE_INVALID", "腾讯云地域列表无法识别，请稍后重试。", 502
            )
        regions.append((code, str(entry.get("RegionName") or code)[:80]))

    def region_instances(item):
        region, label = item
        found = []
        try:
            for page in range(20):
                body = _response(
                    "DescribeInstances",
                    {"Limit": 50, "Offset": page * 50},
                    secret_id,
                    secret_key,
                    region,
                )
                instances = body.get("InstanceSet")
                if not isinstance(instances, list):
                    raise ValueError("missing instances")
                for instance in instances:
                    if not isinstance(instance, dict):
                        raise ValueError("invalid instance")
                    ips = instance.get("PublicAddresses") or []
                    if not isinstance(ips, list):
                        raise ValueError("invalid addresses")
                    address = ""
                    for candidate in ips:
                        try:
                            parsed = ipaddress.ip_address(candidate)
                            if parsed.version == 4 and parsed.is_global:
                                address = str(parsed)
                                break
                        except ValueError:
                            continue
                    found.append(
                        {
                            "id": str(instance.get("InstanceId") or "")[:128],
                            "name": str(instance.get("InstanceName") or "未命名")[:128],
                            "state": str(instance.get("InstanceState") or "未知")[:64],
                            "os": str(instance.get("OsName") or "系统未知")[:128],
                            "ip": address,
                            "region": label,
                            "region_id": region,
                        }
                    )
                if len(instances) < 50:
                    return found, None
            return (
                found,
                label,
            )  # A hard limit must never be presented as a complete list.
        except (Problem, TypeError, ValueError):
            return [], label

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(region_instances, regions))
    servers = [server for group, _ in results for server in group]
    failed = [region for _, region in results if region]
    return {"instances": servers, "incomplete_regions": failed}

