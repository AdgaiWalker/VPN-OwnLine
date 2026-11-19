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
    css_files = sorted(p for p in (SRC_DIR / "css").glob("*.css") if not p.name.startswith('local-'))
    css_content = "\n".join(read_file(f).rstrip() for f in css_files)

    # 2. Gather HTML
    html_files = sorted(p for p in (SRC_DIR / "html").glob("*.html") if not p.name.startswith('local-'))
    html_content = "\n".join(read_file(f).rstrip() for f in html_files)

    # 3. Gather JS
    js_files = sorted(p for p in (SRC_DIR / "js").glob("*.js") if not p.name.startswith('local-'))
    js_content = "\n\n".join(read_file(f).rstrip() for f in js_files)

    out = template
    out = out.replace("/* {{STYLE}} */", css_content)
    out = out.replace("<!-- {{BODY}} -->", html_content)
    out = out.replace("/* {{SCRIPT}} */", js_content)
    return out


def main():
    check_mode = "--check" in sys.argv
    local = read_file(SRC_DIR / 'html/local-setup.html')
    local = local.replace('/* {{STYLE}} */', read_file(SRC_DIR / 'css/local-setup.css'))
    local_scripts = ('00-setup-input.js', 'local-setup.js')
    local = local.replace('/* {{SCRIPT}} */', '\n'.join(read_file(SRC_DIR / 'js' / name) for name in local_scripts))
    outputs = {TARGET: build(), ROOT / 'web/local-setup.html': local}

    if check_mode:
        for target, synthesized in outputs.items():
            if not target.exists() or read_file(target) != synthesized:
                print(f"Error: {target} is out of sync with web/src/.")
                sys.exit(1)
        print("OK: web/index.html is up to date with web/src/.")
        sys.exit(0)

    for target, synthesized in outputs.items():
        target.write_text(synthesized, encoding='utf-8')
        print(f"Synthesized {target}")


if __name__ == "__main__":
    main()
