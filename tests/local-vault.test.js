const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function makeElement(tagAttrs = '') {
  const hidden = /\bhidden\b/.test(tagAttrs);
  const disabled = /\bdisabled\b/.test(tagAttrs);
  const open = /\bopen\b/.test(tagAttrs);
  return {
    hidden,
    disabled,
    open,
    value: '',
    textContent: '',
    dataset: {},
    required: /\brequired\b/.test(tagAttrs),
    events: {},
    attributes: {},
    addEventListener(name, handler) { this.events[name] = handler; },
    focus() { this.focused = true; },
    querySelector(sel) {
      if (sel === 'input' && this._firstInput) return this._firstInput;
      return null;
    },
  };
}

async function runVaultHarness(search = '?req=vr_fixture', responses = {}) {
  const html = fs.readFileSync('web/src/html/local-vault.html', 'utf8');
  const elements = {};
  for (const m of html.matchAll(/<[^>]+id="([^"]+)"([^>]*)>/g)) {
    elements[m[1]] = makeElement(m[0]);
  }
  elements['slot-tencent_api']._firstInput = elements['vault-tencent-id'];
  elements['slot-webshare_isp']._firstInput = elements['vault-isp-proxy'];
  elements['slot-panel_auth']._firstInput = elements['vault-panel-password'];

  const calls = [];
  const context = {
    URLSearchParams,
    location: { search },
    document: { getElementById: id => elements[id] || null },
    fetch: async (path, options = {}) => {
      calls.push({ path, options });
      if (responses[path]) {
        const res = await responses[path](options);
        const status = res._status || 200;
        const body = { ...res };
        delete body._status;
        return { ok: status >= 200 && status < 300, json: async () => body };
      }
      return { ok: true, json: async () => ({}) };
    },
  };
  vm.createContext(context);
  for (const file of ['00-setup-input.js', 'local-vault.js']) {
    vm.runInContext(fs.readFileSync('web/src/js/' + file, 'utf8'), context);
  }
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));
  return { elements, calls };
}

test('local-vault: shows error cleanly when req query param is missing', async () => {
  const h = await runVaultHarness('');
  assert.equal(h.elements['vault-fallback'].hidden, true);
  assert.equal(h.elements['vault-card'].hidden, true);
  assert.match(h.elements['vault-status'].textContent, /缺少凭据请求编号/);
  assert.equal(h.calls.length, 0);
});

test('local-vault: renders only requested ssh slot, supports PEM paste, and clears secrets on submit', async () => {
  const pem = '-----BEGIN OPENSSH PRIVATE KEY-----\nfixture-key-body\n-----END OPENSSH PRIVATE KEY-----';
  const h = await runVaultHarness('?req=vr_ssh1', {
    '/api/vault/status?id=vr_ssh1': () => ({
      request_id: 'vr_ssh1',
      slot: 'ssh',
      label: '首次安装',
      target_hint: '198.51.100.12',
      state: 'pending',
    }),
    '/api/vault/submit': () => ({
      handle: 'vh_opaque_ssh',
      slot: 'ssh',
      summary: { host: '198.51.100.12', username: 'root', ssh_port: 22, auth_type: 'private_key' },
    }),
  });

  assert.equal(h.elements['slot-ssh'].hidden, false);
  assert.equal(h.elements['slot-ssh'].disabled, false);
  assert.equal(h.elements['slot-tencent_api'].hidden, true);
  assert.equal(h.elements['slot-tencent_api'].disabled, true);
  assert.equal(h.elements['slot-webshare_isp'].hidden, true);
  assert.equal(h.elements['vault-ssh-host'].value, '198.51.100.12');
  assert.equal(h.elements['vault-ssh-user'].value = 'root', 'root');
  assert.equal(h.elements['vault-ssh-port'].value = '22', '22');

  let prevented = false;
  h.elements['vault-ssh-credential'].events.paste({
    clipboardData: { getData: () => pem },
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(h.elements['vault-ssh-key-status'].textContent, '已粘贴 SSH 私钥');
  h.elements['vault-ssh-passphrase'].value = 'key-phrase-123';

  await h.elements['vault-form'].onsubmit({ preventDefault() {} });
  const subCall = h.calls.find(c => c.path === '/api/vault/submit');
  assert(subCall, 'must POST /api/vault/submit');
  const sent = JSON.parse(subCall.options.body);
  assert.equal(sent.request_id, 'vr_ssh1');
  assert.equal(sent.payload.private_key, pem);
  assert.equal(sent.payload.passphrase, 'key-phrase-123');

  assert.equal(h.elements['vault-ssh-credential'].value, '');
  assert.equal(h.elements['vault-ssh-passphrase'].value, '');
  assert.equal(h.elements['vault-ssh-key-status'].textContent, '');
  assert.equal(h.elements['vault-card'].hidden, true);
  assert.equal(h.elements['vault-done'].hidden, false);
  assert.equal(h.elements['vault-handle-out'].textContent, 'vh_opaque_ssh');
});

test('local-vault: webshare_isp slot shows only isp input and cancel clears fields', async () => {
  const h = await runVaultHarness('?req=vr_isp1', {
    '/api/vault/status?id=vr_isp1': () => ({
      request_id: 'vr_isp1',
      slot: 'webshare_isp',
      label: '绑定住宅出口',
      target_hint: '',
      state: 'pending',
    }),
    '/api/vault/cancel': () => ({ state: 'cancelled' }),
  });

  assert.equal(h.elements['slot-webshare_isp'].hidden, false);
  assert.equal(h.elements['slot-ssh'].hidden, true);
  h.elements['vault-isp-proxy'].value = '1.2.3.4:8080:u:p';
  await h.elements['vault-cancel'].onclick();
  assert.equal(h.elements['vault-isp-proxy'].value, '');
  assert.equal(h.elements['vault-card'].hidden, true);
  assert.match(h.elements['vault-status'].textContent, /已取消/);
});

test('local setup & vault HTML templates contain zero emojis', () => {
  const emojiRe = /\p{Extended_Pictographic}/u;
  for (const file of ['web/src/html/local-setup.html', 'web/src/html/local-vault.html']) {
    const content = fs.readFileSync(file, 'utf8');
    assert.equal(emojiRe.test(content), false, `${file} must not contain emojis`);
  }
});
