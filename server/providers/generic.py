"""通用 provider：任何一台能用 SSH 登上的机器。

它不做任何云 API 操作，只在需要时告诉用户"该去哪儿点哪个按钮"。
有了它，没有云账号的人也能用这套系统——只是少了自动化。
"""
from .base import Provider as Base


class Provider(Base):
    name = "generic"

    def available(self):
        return True

    def open_port(self, ip, port):
        return ("skip", "通用机器：请到服务商控制台 → 防火墙 / 安全组 → 放行 TCP %s" % port)

    def reset_password(self, ip):
        return ("skip", "通用机器：请到服务商控制台 → 重置 root 密码", {})
