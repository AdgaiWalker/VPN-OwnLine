#!/bin/bash
# A previously enabled timer may still call this script after an upgrade.
# Never choose a host automatically or send an unencrypted archive. An opt-in,
# encrypted offsite backup feature requires its own explicit configuration.
set -euo pipefail
echo "异地自动备份未启用。请在管理网页手动导出加密的节点备份。"
