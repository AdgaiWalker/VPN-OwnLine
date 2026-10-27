#!/usr/bin/env python3
"""命令行跑自测：python3 verify_cli.py [节点名...]"""
import json
import os
import sys

sys.path.insert(0, "/opt/web")
from nodekit import verify


def main():
    nodes = json.load(open(os.environ.get("LADDER_DATA", "/opt/web-data") + "/nodes.json", encoding="utf-8"))
    want = sys.argv[1:]
    for n in nodes:
        if want and n.get("name") not in want:
            continue
        if n.get("source") == "external":
            print("%-14s unknown  外部节点，不验证" % n["name"])
            continue
        r = verify.run(n)
        print("%-14s %-14s %s" % (n["name"], r["health"], r.get("detail", "")))


if __name__ == "__main__":
    main()
