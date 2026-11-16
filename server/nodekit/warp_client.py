"""Cloudflare WARP 客户端注册与密钥对管理模块。

为海外出口节点全自动注册 Cloudflare WARP 免费清洁出网凭据（WireGuard 协议）。
生成 x25519 密钥对并调用 Cloudflare 官方注册接口完成终端设备绑定，
获取专有内网 IP 与对端公钥，用于 sing-box 智能 AI 分流。
"""
from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

WARP_REG_URL = "https://api.cloudflareclient.com/v0a2158/reg"
WARP_PEER_PUBKEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
WARP_ENDPOINT_HOST = "engage.cloudflareclient.com"
WARP_ENDPOINT_PORT = 2408


def _x25519_clamp(k: bytearray) -> bytearray:
    """RFC 7748 X25519 私钥安全截断。"""
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return k


def _rfc7748_scalarmult(scalar_bytes: bytes, u_bytes: bytes) -> bytes:
    """RFC 7748 纯 Python 标量乘法（零第三方依赖回退实现）。"""
    p = (1 << 255) - 19
    a24 = 121665

    def cswap(swap: int, x_2: int, x_3: int) -> Tuple[int, int]:
        dummy = swap * ((x_2 ^ x_3) % p)
        return (x_2 ^ dummy) % p, (x_3 ^ dummy) % p

    k = bytearray(scalar_bytes)
    _x25519_clamp(k)

    u = int.from_bytes(u_bytes, "little") % p
    x_1 = u
    x_2 = 1
    z_2 = 0
    x_3 = u
    z_3 = 1
    swap = 0

    for t in reversed(range(255)):
        k_t = (k[t // 8] >> (t % 8)) & 1
        swap ^= k_t
        x_2, x_3 = cswap(swap, x_2, x_3)
        z_2, z_3 = cswap(swap, z_2, z_3)
        swap = k_t

        a = (x_2 + z_2) % p
        aa = (a * a) % p
        b = (x_2 - z_2) % p
        bb = (b * b) % p
        e = (aa - bb) % p
        c = (x_3 + z_3) % p
        d = (x_3 - z_3) % p
        da = (d * a) % p
        cb = (c * b) % p
        x_3 = ((da + cb) * (da + cb)) % p
        z_3 = (x_1 * ((da - cb) * (da - cb))) % p
        x_2 = (aa * bb) % p
        z_2 = (e * (aa + (a24 * e) % p)) % p

    x_2, x_3 = cswap(swap, x_2, x_3)
    z_2, z_3 = cswap(swap, z_2, z_3)

    return (x_2 * pow(z_2, p - 2, p) % p).to_bytes(32, "little")


def generate_keypair() -> Tuple[str, str]:
    """生成 x25519 Curve25519 密钥对，返回 (private_key_b64, public_key_b64)。"""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import x25519

        priv = x25519.X25519PrivateKey.generate()
        priv_bytes = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return (
            base64.b64encode(priv_bytes).decode("ascii"),
            base64.b64encode(pub_bytes).decode("ascii"),
        )
    except Exception:
        # 纯 Python RFC 7748 回退实现
        import secrets

        priv_raw = bytearray(secrets.token_bytes(32))
        _x25519_clamp(priv_raw)
        base_point = (9).to_bytes(32, "little")
        pub_raw = _rfc7748_scalarmult(bytes(priv_raw), base_point)
        return (
            base64.b64encode(bytes(priv_raw)).decode("ascii"),
            base64.b64encode(pub_raw).decode("ascii"),
        )


def register_warp(
    timeout: float = 10.0,
    keypair: Optional[Tuple[str, str]] = None,
    reg_url: str = WARP_REG_URL,
) -> Dict[str, Any]:
    """向 Cloudflare API 注册 WARP 客户端，获取 WireGuard 配置。"""
    priv_b64, pub_b64 = keypair if keypair else generate_keypair()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    payload = {
        "key": pub_b64,
        "install_id": "",
        "fcm_token": "",
        "tos": now_iso,
        "model": "PC",
        "type": "Android",
        "locale": "en_US",
    }
    req_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        reg_url,
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "okhttp/3.12.1",
        },
        method="POST",
    )

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"WARP 注册网络请求失败: {exc}",
        }

    cfg = data.get("config") or {}
    peers = cfg.get("peers") or []
    peer_pub = peers[0].get("public_key") if peers else WARP_PEER_PUBKEY
    peer_endpoint = (peers[0].get("endpoint") or {}) if peers else {}
    peer_host = peer_endpoint.get("host") or WARP_ENDPOINT_HOST
    if ":" in peer_host:
        peer_host = peer_host.split(":", 1)[0]

    addresses = (cfg.get("interface") or {}).get("addresses") or {}
    v4 = addresses.get("v4") or "172.16.0.2"
    v6 = addresses.get("v6")

    local_address = [f"{v4}/32" if "/" not in v4 else v4]
    if v6:
        local_address.append(f"{v6}/128" if "/" not in v6 else v6)

    return {
        "ok": True,
        "type": "wireguard",
        "private_key": priv_b64,
        "public_key": pub_b64,
        "peer_public_key": peer_pub or WARP_PEER_PUBKEY,
        "server": peer_host or WARP_ENDPOINT_HOST,
        "server_port": WARP_ENDPOINT_PORT,
        "local_address": local_address,
        "mtu": 1280,
        "client_id": data.get("id"),
        "account_id": (data.get("account") or {}).get("id"),
    }
