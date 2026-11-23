"""Fixed stage vocabulary; remote output is never a user-facing message."""

STAGES = {
    'recheck': '复核服务器身份和安装条件',
    'connect': '建立安装连接',
    'upload': '传输安装程序',
    'preflight': '检查服务器运行环境',
    'dependencies': '安装系统依赖和管理网关',
    'core': '下载并校验代理核心',
    'deploy': '部署后台程序和连接检查依赖',
    'address': '确认公网地址和域名',
    'config': '生成并校验代理配置',
    'tuning': '配置网络参数',
    'firewall': '配置服务器防火墙',
    'gateway': '配置管理入口',
    'services': '启动服务并申请 HTTPS 证书',
    'selfcheck': '执行服务器安装自检',
    'server_verify': '验收服务器双协议出网',
    'delivery_verify': '从本机校验 HTTPS、登录和订阅',
    'cleanup': '清理临时安装文件',
}
REMOTE_STAGES = tuple(STAGES)[3:14]
PREFIX = b'__OWNLINE_STAGE_V1__:'


class StageReader:
    """Decode only bounded, complete stage markers across SSH chunk boundaries."""
    def __init__(self, report):
        self.report = report
        self.pending = b''
        self.discard = False

    def __call__(self, chunk):
        parts = chunk.split(b'\n')
        for i, part in enumerate(parts):
            if not self.discard:
                self.pending += part
                if len(self.pending) > 128:
                    self.pending = b''
                    self.discard = True
            if i < len(parts) - 1:
                if not self.discard and self.pending.startswith(PREFIX):
                    code = self.pending[len(PREFIX):].decode('ascii', errors='replace')
                    if code in REMOTE_STAGES:
                        self.report(code)
                self.pending = b''
                self.discard = False
