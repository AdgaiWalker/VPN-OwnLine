const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('ui declutter: obsolete buttons removed and zombie elements cleaned', () => {
  // 1. Obsolete header traffic button (#btn-manage-servers) must be removed
  assert.equal(html.includes('id="btn-manage-servers"'), false, '#btn-manage-servers must be removed');
  assert.equal(html.includes('>Traffic</button>'), false, 'Traffic button text must be removed');

  // 2. Redundant footer refresh button (#btn-refresh-all) must be removed
  assert.equal(html.includes('id="btn-refresh-all"'), false, '#btn-refresh-all must be removed');

  // 3. Status pill default text should not be "Pending Verification"
  assert.equal(html.includes('Pending Verification'), false, '"Pending Verification" should not exist');
});

test('paintStatus: dynamic status pill updates to 运行正常 or N个节点异常', () => {
  function source(name) {
    const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
    assert(match, `missing ${name}`);
    return match[0];
  }

  const mockPill = { className: '', textContent: '' };
  const mockPillText = { textContent: '' };
  const mockPillDot = {};

  const c = vm.createContext({
    document: {
      getElementById: (id) => {
        if (id === 'status-pill') return mockPill;
        if (id === 'status-text') return mockPillText;
        if (id === 'status-dot') return mockPillDot;
        return null;
      }
    },
    NODES: [
      { name: 'Node1', host: '1.1.1.1', port: 443 },
      { name: 'Node2', host: '2.2.2.2', port: 443 }
    ],
    STATUS: {},
    healthText: () => 'ok'
  });

  vm.runInContext(source('paintStatus'), c);

  // Case 1: All nodes healthy
  c.STATUS = {
    'Node1': { ok: true, ms: 50 },
    'Node2': { ok: true, ms: 60 }
  };
  c.paintStatus();
  assert.equal(mockPill.className, 'pill-preview ok');
  assert.equal(mockPillText.textContent, '运行正常');

  // Case 2: One node degraded
  c.STATUS = {
    'Node1': { ok: true, ms: 50 },
    'Node2': { ok: false, ms: 0, reason: 'port' }
  };
  c.paintStatus();
  assert.equal(mockPill.className, 'pill-preview warn');
  assert.equal(mockPillText.textContent, '1 个节点异常');

  // Case 3: Empty nodes
  c.NODES = [];
  c.paintStatus();
  assert.equal(mockPill.className, 'pill-preview');
  assert.equal(mockPillText.textContent, '未连接节点');
});

test('paintStatus: self-probe latency is labelled honestly instead of being disguised', () => {
  const match = html.match(/^  function paintStatus\([^\n]*\)\s*\{[\s\S]*?^  \}/m);
  assert(match, 'missing paintStatus');
  const s0 = { textContent: '', innerHTML: '' };
  const s1 = { textContent: '', innerHTML: '' };
  const c = vm.createContext({
    document: { getElementById: (id) => (id === 's0' ? s0 : id === 's1' ? s1 : null) },
    NODES: [
      { name: 'Local', host: '203.0.113.10', port: 443 },
      { name: 'Remote', host: '203.0.113.20', port: 443 }
    ],
    STATUS: {
      Local: { ok: true, ms: 1, self_probe: true },
      Remote: { ok: true, ms: 142 }
    },
    healthText: () => 'ok',
    esc: (v) => String(v)
  });
  vm.runInContext(match[0], c);
  c.paintStatus();
  assert.match(s0.innerHTML, /1ms \(探针本机\)/);
  assert.match(s1.innerHTML, />142ms</);
  assert.doesNotMatch(s1.innerHTML, /探针本机/);
});
