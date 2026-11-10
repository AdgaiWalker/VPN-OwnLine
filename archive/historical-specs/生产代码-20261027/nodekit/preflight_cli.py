#!/usr/bin/env python3
"""预检 CLI：读 PROBE 输出文件，打印 ARCH=xxx 或失败原因（退出码 1）。"""
import sys

sys.path.insert(0, "/opt/web")
from nodekit import preflight


def main():
    if len(sys.argv) < 2:
        print("缺少探测结果文件")
        return 2
    text = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
    info = preflight.parse_probe_output(text)
    ok, reason, hints = preflight.decide(info)
    if not ok:
        print("预检未通过：%s" % (hints[0] if hints else reason))
        print("REASON=%s" % reason)
        return 1
    arch = preflight.map_arch(info["arch"])
    print("ARCH=%s" % arch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
