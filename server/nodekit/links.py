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


def build(node, name=None):
    """与 parse 互逆，用于 round-trip 测试与订阅渲染。"""
    disp_name = name or node.get("name") or node.get("host") or "vless"
    q = (
        "encryption=none&flow=%s&security=reality&sni=%s&fp=chrome&pbk=%s&sid=%s&type=%s&headerType=none"
        % (node.get("flow") or "xtls-rprx-vision", node.get("sni") or node.get("host") or "", node.get("pbk") or "", node.get("sid") or "", node.get("type") or "tcp")
    )
    return "vless://%s@%s:%s?%s#%s" % (
        node.get("uuid") or "", node["host"], node["port"], q, urllib.parse.quote(disp_name)
    )


def build_hy2(node, name=None):
    """Hysteria2 / QUIC 节点的分享链接。"""
    disp_name = name or node.get("name") or node.get("host") or "hy2"
    q = (
        "insecure=1&sni=%s&alpn=h3&obfs=salamander&obfs-password=%s"
        % (node.get("sni") or node.get("host") or "", node.get("obfs_password") or "")
    )
    return "hysteria2://%s@%s:%s?%s#%s" % (
        node.get("password") or "",
        node["host"],
        node["port"],
        q,
        urllib.parse.quote(disp_name),
    )


def build_link(node, name=None):
    """根据节点协议类型自动生成对应分享链接（vless:// 或 hysteria2://）。"""
    if node.get("type") == "hysteria2":
        return build_hy2(node, name=name)
    return build(node, name=name)


def _valid_proxy_host(host: str) -> bool:
    if not host or not isinstance(host, str):
        return False
    return not any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in host)


def parse_isp_proxy(url):
    """解析 SOCKS5 或 HTTP 代理 URL 为 dict（3x-ui 兼容格式）。
    全面适配 Webshare 常见导出格式：
      1. curl 快速测试命令：
         curl --proxy "http://user:pass@ip:port/" ...
         curl -x "socks5://user:pass@ip:port" ...
      2. 导出列表四段式：
         ip:port:user:pass
      3. 用户凭据串：
         user:pass@ip:port
      4. 简易地址端口：
         ip:port
      5. 标准代理 URL（带或不带双引号）：
         socks5://user:pass@ip:port
         http://user:pass@ip:port
    """
    if not url or not str(url).strip():
        raise LinkError("代理链接为空")
    import re
    text = str(url).strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()

    if "curl " in text or text.startswith("curl"):
        m_curl = re.search(r'(?:--proxy|-x)\s+["\']?([^"\'\s]+)["\']?', text)
        if m_curl:
            text = m_curl.group(1).strip()
        else:
            raise LinkError("无法从 curl 命令中解析出代理参数（--proxy 或 -x）")

    text = text.rstrip("/")

    parts = text.split(":")
    if len(parts) >= 4 and parts[1].isascii() and parts[1].isdigit() and not ("//" in text or "@" in text):
        ip, port_str, user, password = parts[0].strip(), parts[1].strip(), parts[2].strip(), ":".join(parts[3:]).strip()
        if not _valid_proxy_host(ip):
            raise LinkError("代理链接中缺少合法服务器地址")
        port = int(port_str)
        if not (0 < port < 65536):
            raise LinkError("代理端口不合法（必须是 1-65535）")
        return {
            "type": "socks",
            "server": ip,
            "server_port": port,
            "username": user,
            "password": password
        }

    if len(parts) == 2 and parts[1].isascii() and parts[1].isdigit() and not ("//" in text or "@" in text):
        ip, port_str = parts[0].strip(), parts[1].strip()
        if not _valid_proxy_host(ip):
            raise LinkError("代理链接中缺少合法服务器地址")
        port = int(port_str)
        if not (0 < port < 65536):
            raise LinkError("代理端口不合法（必须是 1-65535）")
        return {
            "type": "socks",
            "server": ip,
            "server_port": port
        }

    if "://" not in text:
        target_url = "socks5://" + text
    else:
        target_url = text

    try:
        u = urllib.parse.urlparse(target_url)
    except Exception:
        raise LinkError("代理链接格式不正确")
    scheme = (u.scheme or "").lower()
    if scheme not in ("socks5", "socks", "http", "https"):
        raise LinkError("只支持 socks5:// 或 http:// 格式的代理链接")
    if not _valid_proxy_host(u.hostname or ""):
        raise LinkError("代理链接中缺少合法服务器地址")
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


