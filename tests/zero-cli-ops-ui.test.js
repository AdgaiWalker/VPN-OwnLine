const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const indexHtml = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const localSetupHtml = fs.readFileSync(path.join(__dirname, '../web/local-setup.html'), 'utf8');

function makeNode(tag = 'div') {
  let textVal = '';
  const node = {
    tagName: tag.toUpperCase(),
    style: {},
    children: [],
    dataset: {},
    className: '',
    value: '',
    href: '',
    target: '',
    rel: '',
    disabled: false,
    hidden: false,
    attributes: {},
    focus() { this.focused = true; },
    appendChild(child) { this.children.push(child); },
    replaceChildren(...rows) { this.children = rows; },
    setAttribute(k, v) { this.attributes[k] = v; },
    addEventListener() {},
  };
  Object.defineProperty(node, 'textContent', {
    get() { return textVal; },
    set(v) {
      textVal = String(v == null ? '' : v);
      this.children = [];
    },
    enumerable: true,
    configurable: true,
  });
  return node;
}

test('C1: drift check & one-click align work cleanly in #section-logs without XSS', async () => {
  assert(indexHtml.includes('id="btn-reconcile-check"'));
  assert(indexHtml.includes('id="reconcile-box"'));

  const box = makeNode('div');
  const btn = makeNode('button');
  const calls = [];
  let driftState = 'drifted';

  const context = {
    isZh: () => true,
    safeUrl: p => p,
    document: {
      getElementById: id => (id === 'reconcile-box' ? box : (id === 'btn-reconcile-check' ? btn : null)),
      createElement: tag => makeNode(tag),
    },
    window: {},
    fetch: async (url, opts = {}) => {
      calls.push({ url, opts });
      if (url.includes('/api/reconcile/status')) {
        return {
          ok: true,
          json: async () => ({
            results: [
              { name: '东京-<script>', host: '1.2.3.4', status: driftState, diff_count: 2 },
              { name: '新加坡', host: '5.6.7.8', status: 'in_sync' },
            ],
          }),
        };
      }
      if (url.includes('/api/reconcile/apply')) {
        driftState = 'converged';
        return { ok: true, json: async () => ({ ok: true }) };
      }
      throw new Error('unexpected url: ' + url);
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/10-diagnostics.js'), 'utf8'), context);

  await context.window.ownlineCheckReconcile(btn);

  assert.equal(box.style.display, 'block');
  assert.equal(box.children.length, 2);
  assert.match(box.children[0].children[0].textContent, /存在 2 处偏差/);
  const alignBtn = box.children[0].children[1].children[0];
  assert.equal(alignBtn.textContent, '一键对齐');

  await alignBtn.onclick();

  const applyCall = calls.find(c => c.url.includes('/api/reconcile/apply'));
  assert(applyCall, 'POST /api/reconcile/apply must be called');
  assert.deepEqual(JSON.parse(applyCall.opts.body), { name: '东京-<script>', dry_run: false });
  assert.match(box.children[0].children[0].textContent, /同步一致/);
});

test('C2: billing reconcile form inside #quota-section calls /api/quota/reconcile cleanly', async () => {
  const quotaSec = indexHtml.match(/<details[^>]*id="quota-section"[^>]*>([\s\S]*?)<\/details>/);
  assert(quotaSec && quotaSec[1].includes('id="billing-reconcile-form"'));

  const els = {
    'quota-form': makeNode('form'),
    'billing-reconcile-form': makeNode('form'),
    'billing-official-gb': Object.assign(makeNode('input'), { value: '102.5' }),
    'billing-reset-day': Object.assign(makeNode('input'), { value: '23' }),
    'billing-reconcile-result': makeNode('div'),
    'btn-billing-reconcile': makeNode('button'),
  };
  let bodySent = null;
  const context = {
    isZh: () => true,
    safeUrl: p => p,
    document: { getElementById: id => els[id] || null },
    fetch: async (url, opts) => {
      bodySent = JSON.parse(opts.body);
      return {
        ok: true,
        json: async () => ({
          ok: true,
          status: 'aligned',
          panel_gb: 100.0,
          official_gb: 102.5,
          delta_gb: -2.5,
          delta_pct: 2.44,
          reset_day_match: true,
        }),
      };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/05-state-sync.js'), 'utf8'), context);
  context.initQuotaSettings();
  await els['billing-reconcile-form'].onsubmit({ preventDefault() {} });
  await new Promise(r => setImmediate(r));

  assert.deepEqual(bodySent, { official_gb: 102.5, official_reset_day: 23 });
  assert.match(els['billing-reconcile-result'].textContent, /已对齐/);
  assert.match(els['billing-reconcile-result'].textContent, /重置日一致/);
});

test('C4: custom domain binding form inside #settings-dialog calls /api/domain/change', async () => {
  assert(indexHtml.includes('id="domain-settings-box"'));
  const els = {
    'custom-domain-input': Object.assign(makeNode('input'), { value: 'vpn.example.org' }),
    'custom-domain-skip-dns': Object.assign(makeNode('input'), { checked: false }),
    'btn-save-domain': makeNode('button'),
    'custom-domain-status': makeNode('span'),
    'current-domain-tag': makeNode('span'),
  };
  let reqBody = null;
  const context = {
    isZh: () => true,
    document: {
      getElementById: id => els[id] || null,
      createElement: tag => makeNode(tag),
    },
    window: {},
    setTimeout,
    fetch: async (_url, opts) => {
      reqBody = JSON.parse(opts.body);
      return {
        ok: true,
        json: async () => ({ ok: true, domain: 'vpn.example.org', dashboard_url: 'https://vpn.example.org:8443/' }),
      };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/10b-updater.js'), 'utf8'), context);
  context.window.ownlineChangeDomain({ preventDefault() {} });
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));

  assert.deepEqual(reqBody, { domain: 'vpn.example.org', skip_dns_check: false });
  assert.equal(els['current-domain-tag'].textContent, 'vpn.example.org');
  assert.equal(els['custom-domain-status'].children[0].href, 'https://vpn.example.org:8443/');
});

test('B5: local-setup copy-password copies initial password cleanly', async () => {
  assert(localSetupHtml.includes('id="copy-password"'));
  let copied = '';
  const els = {};
  for (const m of localSetupHtml.matchAll(/<[^>]+id="([^"]+)"/g)) els[m[1]] = makeNode();
  els.connection.elements = { host: makeNode(), username: makeNode(), ssh_port: makeNode(), password: els['ssh-credential'], passphrase: makeNode() };
  els['tencent-credentials'].elements = { secret_id: els['tencent-secret-id'], secret_key: els['tencent-secret-key'] };
  const context = {
    AbortController,
    URL,
    FormData: () => [],
    navigator: { clipboard: { writeText: async t => { copied = t; } } },
    document: { getElementById: id => els[id] || makeNode(), body: makeNode(), execCommand: () => false, createElement: () => makeNode() },
    setTimeout: () => 0,
    clearTimeout: () => {},
    fetch: async () => ({ ok: true, json: async () => ({ state: 'idle' }) }),
  };
  vm.createContext(context);
  for (const f of ['00-setup-input.js', 'local-setup.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/' + f), 'utf8'), context);
  }
  els['initial-password'].value = 'InitPass#2026!';
  await els['copy-password'].onclick();
  assert.equal(copied, 'InitPass#2026!');
  assert.match(els['copy-password-status'].textContent, /已复制/);
});

test('v0.9.1 regressions: auto locale detection, zero /api/setup 404, 80/TCP in prompts, preserve secret on host typo', async () => {
  // P1-1: 01-i18n auto-detects zh-CN when localStorage empty
  const i18nCtx = {
    window: { localStorage: { getItem: () => null } },
    navigator: { language: 'zh-CN' },
  };
  vm.createContext(i18nCtx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/01-i18n.js'), 'utf8'), i18nCtx);
  assert.equal(i18nCtx.window.isZh ? i18nCtx.window.isZh() : i18nCtx.isZh(), true);

  // P2-1: 05-state-sync does not issue dead /api/setup request
  const stateSyncSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/05-state-sync.js'), 'utf8');
  assert.equal(stateSyncSrc.includes('/api/setup'), false);

  // P1-6: 80/TCP included in onboarding agent_brief & panel ssh brief
  const onboarding = JSON.parse(fs.readFileSync(path.join(__dirname, '../web/src/data/onboarding.json'), 'utf8'));
  assert(onboarding.agent_brief.includes('80/TCP'));
  const preMatch = indexHtml.match(/<pre id="ai-ssh-prompt-text"[^>]*>([\s\S]*?)<\/pre>/);
  assert(preMatch && preMatch[1].includes('80'));

  // P2-2: local-setup does not clear #ssh-credential on host syntax typo
  const els = {};
  for (const m of localSetupHtml.matchAll(/<[^>]+id="([^"]+)"/g)) els[m[1]] = makeNode();
  els.connection.elements = {
    host: Object.assign(makeNode(), { value: 'https://43.153.56.137:22' }),
    username: Object.assign(makeNode(), { value: 'root' }),
    ssh_port: Object.assign(makeNode(), { value: '22' }),
    password: els['ssh-credential'],
    passphrase: makeNode(),
  };
  els['ssh-credential'].value = 'KeepMyPass123!';
  els['tencent-credentials'].elements = { secret_id: els['tencent-secret-id'], secret_key: els['tencent-secret-key'] };
  const ctx = {
    AbortController,
    URL,
    FormData: () => [],
    navigator: {},
    document: { getElementById: id => els[id] || makeNode(), body: makeNode(), createElement: () => makeNode() },
    setTimeout: () => 0,
    clearTimeout: () => {},
    fetch: async () => ({ ok: true, json: async () => ({ state: 'idle' }) }),
  };
  vm.createContext(ctx);
  for (const f of ['00-setup-input.js', 'local-setup.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/' + f), 'utf8'), ctx);
  }
  await els.connection.onsubmit({ preventDefault() {} });
  assert.equal(els['ssh-credential'].value, 'KeepMyPass123!');
  assert.match(els['status'].textContent, /纯公网 IPv4/);
});

test('v0.9.2 regressions: refreshState awaits /api/status.json before renderNodes', () => {
  const stateSyncSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/05-state-sync.js'), 'utf8');
  const settledIdx = stateSyncSrc.indexOf('Promise.allSettled([');
  const statusReqIdx = stateSyncSrc.indexOf('jsonRequest("/api/status.json?_t="', settledIdx);
  const renderIdx = stateSyncSrc.indexOf('renderNodes(NODES, STATUS, quota);', settledIdx);
  assert(settledIdx >= 0 && statusReqIdx > settledIdx && statusReqIdx < renderIdx, 'status.json must settle inside Promise.allSettled before renderNodes');
  assert.equal(stateSyncSrc.includes('STATUS = st || {};\n        paintStatus();'), false);
});

test('client setup and vault pages enforce Paper & Ink light/dark tokens, stage cards, secret toggles, ARIA validation, and zero emojis', () => {
  const localVaultHtml = fs.readFileSync(path.join(__dirname, '../web/local-vault.html'), 'utf8');
  for (const [name, docHtml] of [
    ['local-setup.html', localSetupHtml],
    ['local-vault.html', localVaultHtml],
  ]) {
    assert.ok(docHtml.includes('color-scheme: light dark'), `${name} should declare light/dark color-scheme`);
    assert.ok(docHtml.includes('@media (prefers-color-scheme: dark)'), `${name} should support dark mode`);
    assert.ok(docHtml.includes('.stage-card') && docHtml.includes('class="stage-card'), `${name} should render focused .stage-card container`);
    assert.ok(docHtml.includes('initSecretToggles') && docHtml.includes('resetSecretToggles'), `${name} should wire secret toggle lifecycle`);
    assert.ok(docHtml.includes('initAccessibleValidation') && docHtml.includes('aria-invalid'), `${name} should wire accessible ARIA validation`);
    assert.equal(/[\u{1F300}-\u{1FAFF}]/u.test(docHtml), false, `${name} must not contain emoji characters`);
  }

  assert.ok(localSetupHtml.includes('data-toggle-secret="ssh-credential"'));
  assert.match(localSetupHtml, /<details[^>]*id="ssh-help-details"(?![^>]*\sopen\b)/);
  assert.ok(localVaultHtml.includes('data-toggle-secret="vault-ssh-credential"'));
  assert.ok(localVaultHtml.includes('data-toggle-secret="vault-isp-proxy"'));
  assert.ok(localVaultHtml.includes('data-toggle-secret="vault-panel-password"'));
  assert.equal(/[\u{1F300}-\u{1FAFF}]/u.test(indexHtml), false, 'index.html must not contain emoji characters');
});

test('00-setup-input secret toggle and accessible validation helpers handle reveal, reset, and aria-invalid transitions', () => {
  const src = fs.readFileSync(path.join(__dirname, '../web/src/js/00-setup-input.js'), 'utf8');

  function makeDomElement(id, initialType = 'text', selectorMatch = 'input') {
    const attrs = {};
    const listeners = {};
    let userInvalid = false;
    const useEl = {
      attributes: { href: '#i-eye' },
      setAttribute(k, v) { this.attributes[k] = String(v); },
      getAttribute(k) { return this.attributes[k]; },
    };
    return {
      id,
      type: initialType,
      _setUserInvalid(val) { userInvalid = Boolean(val); },
      attributes: attrs,
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
      hasAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k); },
      addEventListener(evt, fn) {
        listeners[evt] = listeners[evt] || [];
        listeners[evt].push(fn);
      },
      dispatch(evt, extra = {}) {
        (listeners[evt] || []).forEach((fn) => fn({ target: this, ...extra }));
      },
      querySelector(sel) { return sel === 'use' ? useEl : null; },
      _useEl: useEl,
      matches(sel) {
        if (sel === ':user-invalid') return userInvalid;
        return sel.split(',').map((s) => s.trim()).includes(selectorMatch);
      },
    };
  }

  const secretInput = makeDomElement('ssh-credential', 'password', 'input');
  const toggleBtn = makeDomElement('toggle-ssh', 'button', 'button');
  toggleBtn.setAttribute('data-toggle-secret', 'ssh-credential');
  toggleBtn.setAttribute('aria-pressed', 'false');

  const rootListeners = {};
  const fakeDoc = {
    getElementById(id) { return id === 'ssh-credential' ? secretInput : null; },
    querySelectorAll(sel) {
      if (sel === '[data-toggle-secret]') return [toggleBtn];
      if (sel === 'input, select, textarea') return [secretInput];
      return [];
    },
    addEventListener(evt, fn) {
      rootListeners[evt] = rootListeners[evt] || [];
      rootListeners[evt].push(fn);
    },
  };

  const ctx = {
    document: fakeDoc,
    WeakSet,
    setTimeout: (fn) => { fn(); return 0; },
  };
  vm.runInNewContext(src, ctx);

  ctx.initSecretToggles(fakeDoc);
  ctx.initAccessibleValidation(fakeDoc);

  assert.equal(secretInput.getAttribute('aria-invalid'), 'false');
  assert.equal(secretInput.type, 'password');

  toggleBtn.dispatch('click');
  assert.equal(secretInput.type, 'text');
  assert.equal(toggleBtn.getAttribute('aria-pressed'), 'true');
  assert.equal(toggleBtn._useEl.getAttribute('href'), '#i-eye-off');

  toggleBtn.dispatch('click');
  assert.equal(secretInput.type, 'password');
  assert.equal(toggleBtn.getAttribute('aria-pressed'), 'false');
  assert.equal(toggleBtn._useEl.getAttribute('href'), '#i-eye');

  toggleBtn.dispatch('click');
  assert.equal(secretInput.type, 'text');
  ctx.resetSecretToggles(fakeDoc);
  assert.equal(secretInput.type, 'password');
  assert.equal(toggleBtn.getAttribute('aria-pressed'), 'false');
  assert.equal(toggleBtn._useEl.getAttribute('href'), '#i-eye');

  secretInput._setUserInvalid(true);
  (rootListeners.blur || []).forEach((fn) => fn({ target: secretInput }));
  assert.equal(secretInput.getAttribute('aria-invalid'), 'true');

  secretInput._setUserInvalid(false);
  (rootListeners.input || []).forEach((fn) => fn({ target: secretInput }));
  assert.equal(secretInput.getAttribute('aria-invalid'), 'false');

  secretInput._setUserInvalid(true);
  (rootListeners.invalid || []).forEach((fn) => fn({ target: secretInput }));
  assert.equal(secretInput.getAttribute('aria-invalid'), 'true');

  secretInput._setUserInvalid(false);
  (rootListeners.reset || []).forEach((fn) => fn({ target: { elements: [secretInput] } }));
  assert.equal(secretInput.getAttribute('aria-invalid'), 'false');
});

test('dashboard, setup, and vault use Alpine Mist canvas theme, forced-colors fallback, 960px spacious container, and valid SVG eye paths', () => {
  const localVaultHtml = fs.readFileSync(path.join(__dirname, '../web/local-vault.html'), 'utf8');
  for (const [name, docHtml] of [
    ['index.html', indexHtml],
    ['local-setup.html', localSetupHtml],
    ['local-vault.html', localVaultHtml],
  ]) {
    assert.ok(docHtml.includes('<meta name="color-scheme" content="light dark">'), `${name} should include early color-scheme meta tag`);
    assert.ok(docHtml.includes('color-scheme: light dark'), `${name} should declare CSS color-scheme: light dark`);
    assert.ok(docHtml.includes('--canvas-bg'), `${name} should define layered canvas background token`);
    assert.ok(docHtml.includes('@media (forced-colors: active)'), `${name} should define forced-colors fallback`);
  }

  assert.match(indexHtml, /\.page\s*\{\s*max-inline-size:\s*960px;/);
  assert.equal(indexHtml.includes('8-11 8-11-8z"'), false, 'broken eye SVG path should be fixed');
});

test('progressive disclosure: quota details and backup drawer stay hidden by default, and collapsed node rows hide raw ISP endpoints and inactive WARP tags', () => {
  assert.match(indexHtml, /<div[^>]*id="quota-details-panel"[^>]*\shidden\b/);
  const nodesSectionMatch = indexHtml.match(/<section[^>]*id="nodes-section"[^>]*>([\s\S]*?)<\/section>/);
  assert.ok(nodesSectionMatch, 'missing #nodes-section');
  assert.match(indexHtml, /<div[^>]*id="backup-drawer"[^>]*\shidden\b/);

  const match = indexHtml.match(/^  function renderNodes\([^\n]*\)\s*\{[\s\S]*?^  \}/m);
  assert.ok(match, 'missing renderNodes in index.html');
  const box = { innerHTML: '' };
  const ctx = vm.createContext({
    document: { getElementById: (id) => (id === 'nodes' ? box : null) },
    esc: (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
    isZh: () => true,
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: [],
    window: {},
  });
  vm.runInContext(match[0], ctx);

  ctx.renderNodes([
    {
      name: 'walker-sv',
      host: '43.153.56.137',
      port: 443,
      role: 'exit',
      warp_enabled: true,
      isp: { type: 'socks', server: '198.51.100.22', server_port: 8080 },
    },
  ], {});

  const drawerIdx = box.innerHTML.indexOf('class="node-drawer"');
  assert.ok(drawerIdx > 0, 'node-drawer must exist');
  const mainHtml = box.innerHTML.slice(0, drawerIdx);
  const drawerHtml = box.innerHTML.slice(drawerIdx);

  assert.ok(mainHtml.includes('住宅 IP'), 'collapsed node row should show compact Residential IP pill');
  assert.equal(mainHtml.includes('198.51.100.22:8080'), false, 'collapsed node row must hide raw ISP endpoint');
  assert.equal(mainHtml.includes('WARP 待命'), false, 'collapsed node row must hide inactive WARP standby badge');
  assert.ok(drawerHtml.includes('住宅 IP · 198.51.100.22:8080'), 'node-drawer should show full ISP endpoint on demand');
  assert.ok(drawerHtml.includes('WARP 待命'), 'node-drawer should keep WARP standby control');
});
