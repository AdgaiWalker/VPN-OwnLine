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
