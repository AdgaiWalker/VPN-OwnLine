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
