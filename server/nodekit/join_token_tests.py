"""join_token 单元测试：纯函数与内存状态机断言。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import join_token as JT

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


JT.clear_all_tokens_for_testing()

# 1. 创建 Token
rec = JT.create_token(name="测试海外机", role="exit", expires_in=300, now_ts=1000.0)
token = rec["token"]
check("Token 是 64 位十六进制", len(token) == 64 and bool(JT.TOKEN_RE.fullmatch(token)))
check("Token 名称一致", rec["name"] == "测试海外机")
check("Token 角色一致", rec["role"] == "exit")
check("Token 过期时间计算正确", rec["expires_at"] == 1300.0)

# 2. 验证 Token (只读，不消耗)
v1 = JT.verify_token(token, now_ts=1100.0)
check("有效时间内验证成功", v1 is not None and v1["token"] == token)
v2 = JT.verify_token(token, now_ts=1100.0)
check("多次验证不消耗 Token", v2 is not None)

# 3. 过期检测
v_exp = JT.verify_token(token, now_ts=1301.0)
check("过期 Token 返回 None", v_exp is None)

# 4. 非法格式与未授权 Token
check("空 Token 返回 None", JT.verify_token("") is None)
check("非法字符 Token 返回 None", JT.verify_token("invalid-token-123") is None)
check("随机伪造 Token 返回 None", JT.verify_token("a" * 64) is None)

# 5. 原子核销 (消费即焚)
JT.clear_all_tokens_for_testing()
rec2 = JT.create_token(name="一次性节点", role="exit", expires_in=300, now_ts=2000.0)
token2 = rec2["token"]
consumed1 = JT.consume_token(token2, now_ts=2100.0)
check("首次消费成功核销", consumed1 is not None and consumed1["name"] == "一次性节点")
consumed2 = JT.consume_token(token2, now_ts=2100.0)
check("二次消费失败（防重放）", consumed2 is None)
v_after = JT.verify_token(token2, now_ts=2100.0)
check("核销后 Token 不再存在", v_after is None)

# 6. 生成安装脚本
script = JT.generate_install_script(token="abcd" * 16, server_url="https://vpn.example.com", role="exit")
check("安装脚本非空且以 #!/usr/bin/env bash 开头", script.startswith("#!/usr/bin/env bash"))
check("安装脚本包含指定 Token", "abcd" * 16 in script)
check("安装脚本包含目标服务器地址", "https://vpn.example.com/join/register" in script)
check("安装脚本包含 sing-box systemd 服务配置", "sing-box.service" in script)

# 7. 中转节点自愈与配对落地
landing_sample = {
    "host": "198.51.100.99",
    "port": 443,
    "uuid": "test-uuid-landing",
    "pbk": "test-pbk-landing",
    "sid": "abcd1234",
    "sni": "www.apple.com",
}
rec_relay = JT.create_token(name="国内中转机", role="relay", landing=landing_sample)
check("中转节点默认端口为 8443", rec_relay["port"] == 8443)
check("中转节点角色一致", rec_relay["role"] == "relay")
check("中转节点挂载落地配置", rec_relay["landing"] == landing_sample)

script_relay = JT.generate_install_script(
    token=rec_relay["token"],
    server_url="https://vpn.example.com",
    role="relay",
    landing=landing_sample,
    port=rec_relay["port"],
)
check("中转安装脚本监听 8443", '"listen_port": 8443' in script_relay)
check("中转安装脚本包含落地 outbound", '"server": "198.51.100.99"' in script_relay)
check("中转安装脚本包含落地 route", '"rules": [{"outbound": "landing"}]' in script_relay)
check("中转安装脚本不含 Hysteria2 入站", "hysteria2" not in script_relay)
check("安装脚本不含任何 emoji 表情", not any(ord(ch) > 0x1F000 for ch in script_relay))

print("通过 %d 项" % ok)
