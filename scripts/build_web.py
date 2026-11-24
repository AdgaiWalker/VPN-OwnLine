#!/usr/bin/env python3
"""
scripts/build_web.py - Synthesizes web/index.html from modular source files in web/src/.

Usage:
    python3 scripts/build_web.py          # Synthesize web/index.html
    python3 scripts/build_web.py --check  # Verify web/index.html is up to date
"""
import html
import json
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "web" / "src"
TARGET = ROOT / "web" / "index.html"
ONBOARDING_PATH = SRC_DIR / "data" / "onboarding.json"


def read_file(p: Path) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _official_href(url: object) -> str:
    raw = str(url or "").strip()
    if not raw.startswith("https://"):
        raise ValueError(f"onboarding resource url must use https://: {raw!r}")
    return _e(raw)


def onboarding_fragments() -> dict[str, str]:
    data = json.loads(read_file(ONBOARDING_PATH))
    checked = _e(data["checked_at"])
    price_note = _e(data["price_note"])

    vps_items = "".join(
        f'<li><a href="{_official_href(item["url"])}" target="_blank" rel="noopener noreferrer">{_e(item["name"])}</a>'
        f'：{_e(item["cost_range"])}；{_e(item["note"])}</li>'
        for item in data["vps_options"]
    )
    req = data["server_requirements"]
    ports_text = _e("、".join(req["ports"]))
    topo = data["topology_advice"]
    isp = data["webshare_isp"]
    isp_formats = " ".join(f"<code>{_e(fmt)}</code>" for fmt in isp["paste_formats"])
    dom = data["custom_domain"]

    local_no_server = (
        '<details id="no-server-guide" class="guide-disclosure">'
        '<summary>还没有服务器？查看 0~99 元/年选型与必开端口</summary>'
        '<div class="guide-body">'
        f'<ul class="guide-list">{vps_items}</ul>'
        f'<p><strong>系统与端口：</strong>{_e(req["os"])}；在云防火墙放行 {ports_text}。</p>'
        f'<p><strong>单机 vs 中转：</strong>{_e(topo["single_node"])}<br>{_e(topo["relay_pair"])}</p>'
        f'<p><strong>家宽与自定义域名：</strong>防 AI 封控可选 <a href="{_official_href(isp["url"])}" target="_blank" rel="noopener noreferrer">{_e(isp["name"])}</a>（{_e(isp["cost_range"])}）；{_e(dom["default_behavior"])} 如需自有域名可选 <a href="{_official_href(dom["url"])}" target="_blank" rel="noopener noreferrer">{_e(dom["registrar"])}</a>（{_e(dom["cost_range"])}，{_e(dom["note"])}）。</p>'
        f'<p class="field-note">核实日期：{checked} · {price_note}</p>'
        '</div></details>'
    )

    vault_webshare = (
        '<details id="vault-webshare-guide" class="guide-disclosure">'
        '<summary>如何获取 Webshare 静态住宅代理？</summary>'
        '<div class="guide-body">'
        f'<p><a href="{_official_href(isp["url"])}" target="_blank" rel="noopener noreferrer">打开 Webshare 官网</a>（{_e(isp["cost_range"])}）：{_e(isp["select_hint"])}</p>'
        f'<p><strong>可直接粘贴的格式：</strong>{isp_formats}</p>'
        f'<p class="field-note">核实日期：{checked} · {price_note}</p>'
        '</div></details>'
    )

    panel_onboarding = (
        '<details class="inner" id="panel-onboarding-guide" style="margin-top:10px">'
        '<summary>还没有服务器或想看选型与可选域名？</summary>'
        '<div class="small muted" style="margin-top:8px;line-height:1.6">'
        f'<ul style="margin:0 0 8px;padding-left:18px">{vps_items}</ul>'
        f'<p style="margin:4px 0"><b>系统与端口：</b>{_e(req["os"])}；放行 {ports_text}。</p>'
        f'<p style="margin:4px 0"><b>方案参考：</b>{_e(topo["single_node"])} {_e(topo["relay_pair"])}</p>'
        f'<p style="margin:4px 0"><b>自定义域名（可选）：</b>{_e(dom["default_behavior"])} 可选 <a href="{_official_href(dom["url"])}" target="_blank" rel="noopener noreferrer">{_e(dom["registrar"])}</a>（{_e(dom["cost_range"])}，{_e(dom["note"])}）。</p>'
        f'<p style="margin:6px 0 0">核实日期：{checked} · {price_note}</p>'
        '</div></details>'
    )

    panel_tc_cam = (
        '<p class="small"><a href="https://console.cloud.tencent.com/lighthouse/" target="_blank" rel="noopener noreferrer">腾讯云轻量控制台</a>'
        ' · <a href="https://console.cloud.tencent.com/cam/user/userList" target="_blank" rel="noopener noreferrer">CAM 只读子账号管理</a>'
        f' · <span class="muted">{_e(data["tencent_cam_note"])}</span></p>'
    )

    local_tc_cam = (
        '<p class="field-note"><a href="https://console.cloud.tencent.com/lighthouse/" target="_blank" rel="noopener noreferrer">腾讯云控制台</a>'
        ' · <a href="https://console.cloud.tencent.com/cam/user/userList" target="_blank" rel="noopener noreferrer">新建只读 CAM 密钥</a>'
        f'：{_e(data["tencent_cam_note"])}</p>'
    )

    return {
        "<!-- {{LOCAL_NO_SERVER_GUIDE}} -->": local_no_server,
        "{{AGENT_BRIEF}}": _e(data["agent_brief"]),
        "<!-- {{VAULT_WEBSHARE_GUIDE}} -->": vault_webshare,
        "<!-- {{PANEL_ONBOARDING_GUIDE}} -->": panel_onboarding,
        "<!-- {{PANEL_TC_CAM_GUIDE}} -->": panel_tc_cam,
        "<!-- {{LOCAL_TC_CAM_GUIDE}} -->": local_tc_cam,
    }


def apply_fragments(content: str, fragments: dict[str, str]) -> str:
    for placeholder, rendered in fragments.items():
        content = content.replace(placeholder, rendered)
    return content


def build(fragments: dict[str, str] | None = None) -> str:
    template = read_file(SRC_DIR / "template.html")
    frags = fragments if fragments is not None else onboarding_fragments()

    # 1. Gather CSS
    css_files = sorted(p for p in (SRC_DIR / "css").glob("*.css") if not p.name.startswith('local-'))
    css_content = "\n".join(read_file(f).rstrip() for f in css_files)

    # 2. Gather HTML
    html_files = sorted(p for p in (SRC_DIR / "html").glob("*.html") if not p.name.startswith('local-'))
    html_content = "\n".join(read_file(f).rstrip() for f in html_files)
    html_content = apply_fragments(html_content, frags)

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
    frags = onboarding_fragments()
    local_css = read_file(SRC_DIR / 'css/local-setup.css')
    local = read_file(SRC_DIR / 'html/local-setup.html')
    local = apply_fragments(local, frags)
    local = local.replace('/* {{STYLE}} */', local_css)
    local_scripts = ('00-setup-input.js', 'local-setup.js')
    local = local.replace('/* {{SCRIPT}} */', '\n'.join(read_file(SRC_DIR / 'js' / name) for name in local_scripts))
    vault = read_file(SRC_DIR / 'html/local-vault.html')
    vault = apply_fragments(vault, frags)
    vault = vault.replace('/* {{STYLE}} */', local_css)
    vault_scripts = ('00-setup-input.js', 'local-vault.js')
    vault = vault.replace('/* {{SCRIPT}} */', '\n'.join(read_file(SRC_DIR / 'js' / name) for name in vault_scripts))
    outputs = {
        TARGET: build(frags),
        ROOT / 'web/local-setup.html': local,
        ROOT / 'web/local-vault.html': vault,
    }

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
