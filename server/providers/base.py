"""云厂商适配层的接口定义。

核心代码（admin.py / usage_refresh.py）只认这个接口，不认识任何一家云。
新增一家云 = 在 providers/ 下加一个文件 + 在 __init__._MODULES 里注册一行。
"""


class Provider:
    name = "base"

    def available(self):
        """配置齐全、依赖可用时返回 True。"""
        return False

    def list_instances(self):
        """返回 [{"name","ip","id","region","regionId","expire","state"}]，没有就返回 []。"""
        return []

    def traffic(self):
        """返回 {ip: {"used","total","start","end","overflow","region"}}。"""
        return {}

    def open_port(self, ip, port, dry_run=False):
        """返回 (状态, 说明)。状态取值：opened / already / fail / skip / dry。

        dry_run=True 时只描述"会做什么"，绝不产生副作用。

        skip 表示"这家云不管这台机器"，调用方会继续问下一个 provider。
        """
        return ("skip", "")

    def reset_password(self, ip, dry_run=False):
        """返回 (状态, 说明, 附加数据)，附加数据里可带 {"password": 新密码}。

        dry_run=True 时只描述"会做什么"，绝不产生副作用。
        """
        return ("skip", "", {})
