const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('apple hig: install error extracts honest diagnostic reason instead of silent failure', async () => {
  const a = html.indexOf('  function initInstallProgress()'), b = html.indexOf('  function detectClient()', a);
  const e = {};
  for (const id of ['install-task','install-task-title','install-task-message','install-task-refresh','install-task-dismiss']) {
    e[id] = { style: {}, textContent: '', disabled: false };
  }
  const storage = { sb_job: 'b'.repeat(12) };
  const c = {
    document: { getElementById: id => e[id] },
    localStorage: { getItem: k => storage[k], removeItem: k => delete storage[k] },
    fetch: async () => ({
      ok: true,
      json: async () => ({ ok: true, state: 'error', error: 'Download timed out connecting to github.com' })
    }),
    setTimeout: () => 1,
    clearTimeout: () => {},
    AbortController,
    encodeURIComponent
  };
  vm.createContext(c);
  vm.runInContext(html.slice(a, b), c);
  c.initInstallProgress();
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(e['install-task-title'].textContent, '安装未完成');
  assert.match(e['install-task-message'].textContent, /下载核心依赖超时/);
  assert.equal(e['install-task-dismiss'].disabled, false);
});

test('apple hig: bonded relay displays clear multi-hop segment pipeline', () => {
  function source(name) {
    const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
    assert(match, `missing ${name}`);
    return match[0];
  }
  let innerHTML = '';
  const box = { set innerHTML(val) { innerHTML = val; }, get innerHTML() { return innerHTML; } };
  const c = vm.createContext({
    document: {
      getElementById: (id) => (id === 'nodes' ? box : null)
    },
    esc: (v) => String(v),
    isZh: () => true,
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: []
  });

  vm.runInContext(source('renderNodes'), c);

  const nodes = [
    {
      name: '上海专线',
      host: '43.153.56.137',
      role: 'relay',
      country: 'CN',
      port: 443,
      landing: { host: '154.21.30.5' }
    },
    {
      name: '香港落地',
      host: '154.21.30.5',
      role: 'exit',
      country: 'HK',
      port: 443
    }
  ];

  c.renderNodes(nodes, {}, null);

  assert(innerHTML.includes('relay-pipeline'), 'relay-pipeline class must exist');
  assert(innerHTML.includes('pipeline-hop'), 'pipeline-hop must exist');
  assert(innerHTML.includes('专线跳板'), 'pipeline must mention transit hop');
  assert(innerHTML.includes('43.153.56.137'), 'entry host must be rendered');
  assert(innerHTML.includes('香港落地'), 'egress name must be rendered');
});

test('apple hig: china-blocked node renders contextual recovery banner with action pills', () => {
  function source(name) {
    const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
    assert(match, `missing ${name}`);
    return match[0];
  }
  let innerHTML = '';
  const box = { set innerHTML(val) { innerHTML = val; }, get innerHTML() { return innerHTML; } };
  const c = vm.createContext({
    document: { getElementById: (id) => (id === 'nodes' ? box : null) },
    esc: (v) => String(v),
    isZh: () => true,
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: []
  });

  vm.runInContext(source('renderNodes'), c);

  const nodes = [
    { name: '国内跳板', host: '43.153.1.1', role: 'standalone', country: 'CN' },
    { name: '东京出口', host: '154.21.2.2', role: 'exit', country: 'JP', port: 443 }
  ];
  const status = {
    '东京出口': { ok: true, cn_ok: false, cn_reason: 'port' }
  };

  c.renderNodes(nodes, status, null);

  assert(innerHTML.includes('adv error warn'), 'adv error warn class must exist for china blocked node');
  assert(innerHTML.includes('国内直连不通 · 疑似被墙'), 'Human friendly alert title must exist');
  assert(innerHTML.includes('ownlineBindDomesticRelayFor'), 'Binding domestic relay action must be available');
  assert(innerHTML.includes('ownlineRecheckNode'), 'Recheck node action must be available');
});

test('apple hig: qr dialog contains real image source, copy url button and url preview', () => {
  assert(html.includes('id="btn-copy-qr-url"'), '#btn-copy-qr-url must exist');
  assert(html.includes('id="qr-sub-url-text"'), '#qr-sub-url-text must exist');
  assert(html.includes('window.ownlineCopyQrSubUrl'), 'ownlineCopyQrSubUrl must be wired');
  assert(html.includes('/api/qr?url='), 'qr modal must query dynamic /api/qr endpoint');
});

test('just-in-time disclosure: node drawer and quota drawer only open upon user interaction', () => {
  assert(html.includes('window.ownlineToggleNodeDrawer'), 'window.ownlineToggleNodeDrawer must be registered');
  assert(html.includes('window.ownlineToggleQuota'), 'window.ownlineToggleQuota must be registered');
  assert(html.includes('class="node-drawer"'), 'node-drawer class must exist');
  assert(html.includes('class="node-main"'), 'node-main class must exist');

  function source(name) {
    const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
    assert(match, `missing ${name}`);
    return match[0];
  }
  let innerHTML = '';
  const box = { set innerHTML(val) { innerHTML = val; }, get innerHTML() { return innerHTML; } };
  const c = vm.createContext({
    document: { getElementById: (id) => (id === 'nodes' ? box : null) },
    esc: (v) => String(v),
    isZh: () => true,
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: []
  });
  vm.runInContext(source('renderNodes'), c);

  const nodes = [
    { name: '日本01', host: '198.51.100.10', role: 'exit', country: 'JP', port: 443 }
  ];
  c.renderNodes(nodes, {}, null);

  assert(innerHTML.includes('id="node-row-0"'), 'node row id must exist');
  assert(innerHTML.includes('window.ownlineToggleNodeDrawer(0)'), 'toggleNodeDrawer(0) must be attached to node-main and more button');
  assert(innerHTML.includes('id="node-drawer-0"'), 'node-drawer-0 must exist');
  assert(innerHTML.includes('id="node-drawer-0" hidden'), 'node drawer must be hidden by default until triggered');
});

test('apple hig: visual hierarchy, responsive topbar, and card interaction affordances', () => {
  // 1. Primary Action First: client-ready-box appears before quota-hero-banner
  const clientReadyIdx = html.indexOf('id="client-ready-box"');
  const quotaBannerIdx = html.indexOf('id="quota-hero-banner"');
  assert(clientReadyIdx > 0 && quotaBannerIdx > 0, 'both elements must exist');
  assert(clientReadyIdx < quotaBannerIdx, 'Primary CTA #client-ready-box must precede #quota-hero-banner for instant connect intent');

  // 2. Topbar actions container and responsive rules
  assert(html.includes('class="topbar-actions"'), 'topbar-actions class must exist');
  assert(html.includes('@media (max-width: 480px)'), 'responsive 480px breakpoint must exist in stylesheet');
  assert(html.includes('.apple-sheet-grabber'), 'apple-sheet-grabber must exist in stylesheet');

  // 3. Node card chevron affordance
  assert(html.includes('class="ico node-chevron"'), 'node-chevron icon must exist in rendered node cards');
});

test('accessibility & theme parity: dark primary contrast, change-password alignment, and quota/i18n guards', () => {
  // 1. Dark-mode primary CTA contrast (#2563eb bg with #ffffff fg >= 4.5:1 AA)
  assert(html.includes('--btn-primary-bg: #2563eb;'), 'dark mode must set --btn-primary-bg to #2563eb');
  assert.match(html, /\.btn\.primary\s*\{[\s\S]*?background:\s*var\(--btn-primary-bg\);[\s\S]*?color:\s*var\(--accent-fg\);/);
  assert.match(html, /\.adv-btn\.primary\s*\{[\s\S]*?background:\s*var\(--btn-primary-bg\);[\s\S]*?color:\s*var\(--accent-fg\);/);
  assert.match(html, /\.sbtn\.ok\s*\{[\s\S]*?background:\s*var\(--btn-primary-bg\);[\s\S]*?color:\s*var\(--accent-fg\);/);
  assert.match(html, /\.apple-client-action-pill\.primary\s*\{[\s\S]*?background:\s*var\(--btn-primary-bg\);[\s\S]*?color:\s*var\(--accent-fg\);/);

  const localSetupCss = fs.readFileSync(path.join(__dirname, '../web/src/css/local-setup.css'), 'utf8');
  assert(localSetupCss.includes('--accent-fill: #2563eb;'), 'local-setup.css dark mode must use --accent-fill: #2563eb');
  assert(localSetupCss.includes('--accent-fg: #ffffff;'), 'local-setup.css must preserve --accent-fg: #ffffff');

  // 2. Quota rules link i18n and non-toggling open behavior
  assert(html.includes('data-i18n="quota_rules_link"'), 'quota rules button must carry data-i18n="quota_rules_link"');
  assert(html.includes('quota_rules_link: "Circuit Breaker & Billing Check"'), 'en i18n must include quota_rules_link');
  assert(html.includes('quota_rules_link: "熔断阈值与账单核对"'), 'zh i18n must include quota_rules_link');

  const toggleQuotaFn = html.match(/  function toggleQuota\(\)\s*\{[\s\S]*?^  \}/m);
  assert(toggleQuotaFn, 'toggleQuota function must exist');
  assert(toggleQuotaFn[0].includes('qs.open = true;'), 'toggleQuota must open #quota-section instead of closing it when already open');
  assert.equal(toggleQuotaFn[0].includes('!qs.open'), false, 'toggleQuota must not flip qs.open closed');

  // 3. change-password.html theme parity and password visibility toggle
  const cpHtml = fs.readFileSync(path.join(__dirname, '../web/change-password.html'), 'utf8');
  assert(cpHtml.includes('color-scheme: light dark'), 'change-password.html must declare color-scheme: light dark');
  assert(cpHtml.includes('prefers-color-scheme: dark'), 'change-password.html must support dark mode');
  assert(cpHtml.includes('--canvas-bg:'), 'change-password.html must use Alpine Mist canvas gradient');
  assert(cpHtml.includes('class="pw-toggle"'), 'change-password.html must include password visibility toggles');
});

test('minimal-ux-motion-guard: motion baseline tokens, reduced motion, compositor progress bars, and skill persistence', () => {
  // 1. Unified physical motion tokens and reduced-motion override
  assert(html.includes('--ease-standard: cubic-bezier(0.22, 1, 0.36, 1);'), 'index.html must define --ease-standard');
  assert(html.includes('--dur-micro: 140ms;'), 'index.html must define --dur-micro');
  assert(html.includes('--dur-panel: 220ms;'), 'index.html must define --dur-panel');
  assert(html.includes('@media (prefers-reduced-motion: reduce)'), 'index.html must include global prefers-reduced-motion rule');

  // 2. Zero transition: all in web/src/css
  for (const name of ['01-variables.css', '02-layout.css', '03-components.css', '04-nodes.css', 'local-setup.css']) {
    const css = fs.readFileSync(path.join(__dirname, '../web/src/css', name), 'utf8');
    assert.equal(/transition:\s*all\b/.test(css), false, `${name} must not use transition: all`);
  }

  // 3. Compositor-only scaleX progress bars
  assert.match(html, /\.quota-strip-bar i\s*\{[\s\S]*?transform:\s*scaleX\(var\(--pct,\s*0\)\);/);
  assert.equal(/\.quota-strip-bar i\s*\{[\s\S]*?transition:\s*width\b/.test(html), false, 'quota-strip-bar must not transition width');

  // 4. Skill file persisted
  const skillPath = path.join(__dirname, '../.agents/skills/minimal-ux-motion-guard/SKILL.md');
  assert(fs.existsSync(skillPath), 'minimal-ux-motion-guard SKILL.md must exist');
  const skillMd = fs.readFileSync(skillPath, 'utf8');
  assert(skillMd.includes('name: minimal-ux-motion-guard'), 'SKILL.md must declare name: minimal-ux-motion-guard');
});

test('deep quota runway UI: 14-day SVG chart, dual ticks, and topology bottleneck view', () => {
  assert(html.includes('id="quota-chart-svg"'), 'quota details panel must include #quota-chart-svg');
  assert(html.includes('id="quota-time-tick"'), 'quota strip bar must include #quota-time-tick');
  assert(html.includes('id="quota-breaker-tick"'), 'quota strip bar must include #quota-breaker-tick');
  assert(html.includes('id="quota-topology-list"'), 'quota details panel must include #quota-topology-list');
  assert(html.includes('quota_trend_14d: "14-Day Daily Usage"'), 'en i18n must include quota_trend_14d');
  assert(html.includes('quota_trend_14d: "近 14 日消耗趋势"'), 'zh i18n must include quota_trend_14d');
  assert(html.includes('quota_safe_rem_lbl: "Safe Runway"'), 'en i18n must include quota_safe_rem_lbl');
  assert(html.includes('quota_safe_rem_lbl: "安全可用"'), 'zh i18n must include quota_safe_rem_lbl');
});

test('ux-motion-guard remediation: setup sibling DOM, honest QR copy, Chinese placeholders, and CSS hygiene', () => {
  // 1. #view-setup must be a sibling of #view-dashboard (never nested inside #view-dashboard)
  const cardServingMatch = html.match(/<section class="panel-card" id="card-serving">([\s\S]*?)<footer class="site-footer">/);
  assert(cardServingMatch, 'card-serving section must exist');
  const setupIdx = cardServingMatch[1].indexOf('<div id="view-setup"');
  assert(setupIdx > 0, '#view-setup must exist inside card-serving');
  const beforeSetup = cardServingMatch[1].slice(0, setupIdx);
  const openDivs = (beforeSetup.match(/<div\b/g) || []).length;
  const closeDivs = (beforeSetup.match(/<\/div\s*>/g) || []).length;
  assert.equal(openDivs, closeDivs, '#view-dashboard and all prior divs must be balanced and closed before #view-setup');

  // 2. #qr-sub-url-text is hidden by default, and copyQrSubUrl reveals it on clipboard failure
  assert.match(html, /<div id="qr-sub-url-text" hidden\b/);
  const copyQrFn = html.match(/  function copyQrSubUrl\([^\n]*\)\s*\{[\s\S]*?^  \}/m);
  assert(copyQrFn, 'copyQrSubUrl must exist');
  assert(copyQrFn[0].includes('urlText.hidden = false'), 'copyQrSubUrl must reveal #qr-sub-url-text when clipboard fails');
  assert(copyQrFn[0].includes('showResult(false)'), 'copyQrSubUrl must not report false success on catch');

  // 3. applyLanguage translates #settings-new-pass and #settings-confirm-pass placeholders
  const applyLangFn = html.match(/  function applyLanguage\(\)\s*\{[\s\S]*?^  \}/m);
  assert(applyLangFn, 'applyLanguage must exist');
  assert(applyLangFn[0].includes('settings-new-pass'), 'applyLanguage must translate #settings-new-pass placeholder');
  assert(applyLangFn[0].includes('settings-confirm-pass'), 'applyLanguage must translate #settings-confirm-pass placeholder');

  // 4. CSS hygiene: no var(--text), var(--blue), or legacy 0.15s ease in web/src/css
  for (const name of ['01-variables.css', '02-layout.css', '03-components.css', '04-nodes.css']) {
    const css = fs.readFileSync(path.join(__dirname, '../web/src/css', name), 'utf8');
    assert.equal(css.includes('var(--text)'), false, `${name} must not reference undefined var(--text)`);
    assert.equal(css.includes('var(--blue'), false, `${name} must not reference undefined var(--blue)`);
    assert.equal(/\b0\.15s\s+ease\b/.test(css), false, `${name} must use --dur-micro --ease-standard instead of 0.15s ease`);
  }
});
