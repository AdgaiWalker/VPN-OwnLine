"""Read-only, one-shot Tencent Cloud discovery. Credentials stay in memory."""

import ipaddress
import re
import time
from concurrent.futures import ThreadPoolExecutor

if __package__:
    from .providers import tc3
else:
    from providers import tc3

PRODUCTS = {
    "lighthouse": ("轻量应用服务器", "PublicAddresses"),
    "cvm": ("云服务器 CVM", "PublicIpAddresses"),
}

class Problem(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _response(action, payload, secret_id, secret_key, region, **options):
    try:
        response = tc3.call(action, payload, secret_id, secret_key, region, **options)["Response"]
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


def _credentials(secret_id, secret_key):
    if not isinstance(secret_id, str) or not isinstance(secret_key, str):
        raise Problem(
            "TENCENT_CREDENTIALS_REQUIRED", "请输入腾讯云 SecretId 和 SecretKey。"
        )
    secret_id, secret_key = secret_id.strip(), secret_key.strip()
    if not secret_id or not secret_key or len(secret_id) > 256 or len(secret_key) > 256:
        raise Problem(
            "TENCENT_CREDENTIALS_REQUIRED", "请输入有效的腾讯云 SecretId 和 SecretKey。"
        )
    return secret_id, secret_key


def discover(secret_id, secret_key, *, product="lighthouse", deadline=None):
    """The existing two-argument entry point still queries Lighthouse."""
    secret_id, secret_key = _credentials(secret_id, secret_key)
    _, address_field = PRODUCTS[product]

    def query(action, payload, region, service):
        options = {} if service == "lighthouse" and deadline is None else {
            "service": service, "direct": deadline is not None,
        }
        return _response(action, payload, secret_id, secret_key, region, **options)

    if product == "cvm":
        try:
            response = query("DescribeRegions", {"Product": "cvm"}, None, "region")
        except Problem:
            if deadline is not None and time.monotonic() >= deadline:
                raise
            response = query("DescribeRegions", {}, None, "cvm")
    else:
        response = query("DescribeRegions", {}, "ap-singapore", product)
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
                if deadline is not None and time.monotonic() >= deadline:
                    return found, label
                body = query(
                    "DescribeInstances",
                    {"Limit": 50, "Offset": page * 50},
                    region,
                    product,
                )
                instances = body.get("InstanceSet")
                if not isinstance(instances, list):
                    raise ValueError("missing instances")
                for instance in instances:
                    if not isinstance(instance, dict):
                        raise ValueError("invalid instance")
                    ips = instance.get(address_field) or []
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
                    cpu = instance.get("CPU")
                    mem = instance.get("Memory")
                    bw = (instance.get("InternetAccessible") or {}).get("InternetMaxBandwidthOut", 0)
                    bundle_str = f"{cpu}核{mem}G" + (f"-{bw}Mbps" if bw else "") if (cpu and mem) else str(instance.get("BundleId") or "")
                    state_str = str(instance.get("InstanceState") or "未知")[:64]
                    found.append(
                        {
                            "id": str(instance.get("InstanceId") or "")[:128],
                            "name": str(instance.get("InstanceName") or "未命名")[:128],
                            "state": state_str,
                            "status": state_str,
                            "os": str(instance.get("OsName") or "系统未知")[:128],
                            "ip": address,
                            "public_ip": address,
                            "region": label,
                            "region_name": label,
                            "region_id": region,
                            "bundle": bundle_str,
                            "firewall_ready": True,
                        }
                    )
                total = body.get("TotalCount")
                if not instances or (type(total) is int and page * 50 + len(instances) >= total) or len(instances) < 50:
                    return found, None
            return (
                found,
                label,
            )  # A hard limit must never be presented as a complete list.
        except (Problem, TypeError, ValueError):
            return (found if deadline is not None else []), label

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(region_instances, regions))
    servers = [server for group, _ in results for server in group]
    failed = [region for _, region in results if region]
    return {
        "ok": True,
        "regions_scanned": len(regions),
        "instances": servers,
        "incomplete_regions": failed,
    }


def discover_for_local_setup(secret_id, secret_key, *, product=None):
    """Read the requested product or combine both lists, keeping partial results."""
    if product is not None and (not isinstance(product, str) or product not in PRODUCTS):
        raise Problem("TENCENT_PRODUCT_UNSUPPORTED", "请选择支持的腾讯云服务器类型。")
    secret_id, secret_key = _credentials(secret_id, secret_key)
    products = tuple(PRODUCTS) if product is None else (product,)
    deadline = time.monotonic() + 60
    instances, incomplete, errors = [], [], []
    with ThreadPoolExecutor(max_workers=len(products)) as pool:
        jobs = {kind: pool.submit(discover, secret_id, secret_key, product=kind, deadline=deadline)
                for kind in products}
        for kind, job in jobs.items():
            label, _ = PRODUCTS[kind]
            try:
                result = job.result()
            except Problem as error:
                errors.append(error)
                incomplete.append(label)
                continue
            incomplete.extend(f"{label} · {region}" for region in result["incomplete_regions"])
            for item in result["instances"]:
                if item["ip"]:
                    instances.append({key: item[key] for key in ("id", "name", "ip", "region", "os", "state")}
                                     | {"product": label})
    if len(errors) == len(products):
        if all(error.code == "TENCENT_AUTH_FAILED" for error in errors):
            raise errors[0]
        raise Problem("TENCENT_UNAVAILABLE", "无法读取腾讯云实例，请检查网络和只读权限后重试。", 502)
    return {"instances": instances, "incomplete_regions": incomplete}

