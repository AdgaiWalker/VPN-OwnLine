"""vless 链接的解析与生成。

所有错误都抛 LinkError，message 是**给用户看的中文**，不是异常堆栈。
"""
import urllib.parse


class LinkError(Exception):
    pass


REQUIRED = ["pbk", "sid", "sni"]
UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def parse(link):
    """vless://uuid@host:port?params#name  ->  dict"""
    import re
    if not link or not link.strip():
        raise LinkError("链接是空的")
    link = link.strip()
    if not link.lower().startswith("vless://"):
        raise LinkError("只支持 vless:// 开头的链接")
    try:
        u = urllib.parse.urlparse(link)
    except Exception:
        raise LinkError("链接格式不对，无法解析")
    if not u.hostname:
        raise LinkError("链接里没有服务器地址")
    try:
        port = int(u.port or 0)
    except Exception:
        port = 0
    if not (0 < port < 65536):
        raise LinkError("端口不合法：%s" % (u.port,))
    uuid = u.username or ""
    if not re.match(UUID_RE, uuid):
        raise LinkError("uuid 格式不对")
    q = dict(urllib.parse.parse_qsl(u.query))
    if q.get("security") != "reality":
        raise LinkError("只支持 security=reality 的节点")
    sid = q.get("sid") or ""
    if sid and not re.fullmatch(r"[0-9a-fA-F]{1,32}", sid):
        raise LinkError("sid 必须是十六进制（0-9a-f），现在填的是 %s" % sid)
    for k in REQUIRED:
        if not q.get(k):
            label = {"pbk": "pbk（Reality 公钥）", "sid": "sid（short id）", "sni": "sni（伪装域名）"}[k]
            raise LinkError("链接缺少 %s" % label)
    return {
        "name": urllib.parse.unquote(u.fragment or "") or u.hostname,
        "host": u.hostname,
        "port": port,
        "uuid": uuid,
        "pbk": q["pbk"],
        "sid": q["sid"],
        "sni": q["sni"],
        "flow": q.get("flow") or "xtls-rprx-vision",
        "type": q.get("type") or "tcp",
    }


def build(node):
    """与 parse 互逆，用于 round-trip 测试与订阅渲染。"""
    q = (
        "encryption=none&flow=%s&security=reality&sni=%s&fp=chrome&pbk=%s&sid=%s&type=%s&headerType=none"
        % (node.get("flow") or "xtls-rprx-vision", node["sni"], node["pbk"], node["sid"], node.get("type") or "tcp")
    )
    return "vless://%s@%s:%s?%s#%s" % (
        node["uuid"], node["host"], node["port"], q, urllib.parse.quote(node.get("name") or node["host"])
    )


def parse_isp_proxy(url):
    """解析 SOCKS5 或 HTTP 代理 URL 为 dict（3x-ui 兼容格式）。
    支持：
      socks5://user:pass@127.0.0.1:1080
      socks5://127.0.0.1:1080
      http://user:pass@127.0.0.1:8080
    """
    if not url or not url.strip():
        raise LinkError("代理链接为空")
    url = url.strip()
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        raise LinkError("代理链接格式不正确")
    scheme = (u.scheme or "").lower()
    if scheme not in ("socks5", "socks", "http", "https"):
        raise LinkError("只支持 socks5:// 或 http:// 格式的代理链接")
    if not u.hostname:
        raise LinkError("代理链接中缺少服务器地址")
    try:
        port = int(u.port or 0)
    except Exception:
        port = 0
    if not (0 < port < 65536):
        raise LinkError("代理端口不合法（必须是 1-65535）")
    res = {
        "type": "socks" if "socks" in scheme else "http",
        "server": u.hostname,
        "server_port": port,
    }
    if u.username:
        res["username"] = urllib.parse.unquote(u.username)
    if u.password:
        res["password"] = urllib.parse.unquote(u.password)
    return res


def build_deep_links(sub_url: str, name: str = "OwnLine") -> dict:
    """生成 iOS Shadowrocket 与 Clash 的一键唤醒 URL Scheme。
    契约遵循 05-interface-contracts.md 第 4.2 节。
    """
    if not sub_url:
        return {"shadowrocket": "", "clash": ""}
    import base64
    b64_url = base64.b64encode(sub_url.encode("utf-8")).decode("ascii")
    sr_link = f"shadowrocket://add/sub://{b64_url}?title={urllib.parse.quote(name)}"

    clash_target_url = sub_url.rstrip("/")
    if not clash_target_url.endswith("/clash"):
        clash_target_url += "/clash"
    clash_link = f"clash://install-config?url={urllib.parse.quote(clash_target_url, safe='')}&name={urllib.parse.quote(name)}"

    return {
        "shadowrocket": sr_link,
        "clash": clash_link,
    }


