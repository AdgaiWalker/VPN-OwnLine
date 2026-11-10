#!/usr/bin/env python3
"""
scripts/build_web.py - Synthesizes web/index.html from modular source files in web/src/.

Usage:
    python3 scripts/build_web.py          # Synthesize web/index.html
    python3 scripts/build_web.py --check  # Verify web/index.html is up to date
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "web" / "src"
TARGET = ROOT / "web" / "index.html"


def read_file(p: Path) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def build() -> str:
    template = read_file(SRC_DIR / "template.html")

    # 1. Gather CSS
    css_files = sorted((SRC_DIR / "css").glob("*.css"))
    css_content = "\n".join(read_file(f).rstrip() for f in css_files)

    # 2. Gather HTML
    html_files = sorted((SRC_DIR / "html").glob("*.html"))
    html_content = "\n".join(read_file(f).rstrip() for f in html_files)

    # 3. Gather JS
    js_files = sorted((SRC_DIR / "js").glob("*.js"))
    js_content = "\n\n".join(read_file(f).rstrip() for f in js_files)

    out = template
    out = out.replace("/* {{STYLE}} */", css_content)
    out = out.replace("<!-- {{BODY}} -->", html_content)
    out = out.replace("/* {{SCRIPT}} */", js_content)
    return out


def main():
    check_mode = "--check" in sys.argv
    synthesized = build()

    if check_mode:
        if not TARGET.exists():
            print(f"Error: {TARGET} does not exist.")
            sys.exit(1)
        current = read_file(TARGET)
        if current != synthesized:
            print(f"Error: {TARGET} is out of sync with web/src/. Run 'python3 scripts/build_web.py' to rebuild.")
            sys.exit(1)
        print("OK: web/index.html is up to date with web/src/.")
        sys.exit(0)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(synthesized)
    print(f"Synthesized {TARGET} ({len(synthesized.splitlines())} lines, {len(synthesized)} bytes)")


if __name__ == "__main__":
    main()
