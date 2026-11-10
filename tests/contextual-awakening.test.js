const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

function source(name) {
  const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
  assert(match, `missing ${name}`);
  return match[0];
}

test('deriveNodeState: accurately computes health, hy2 capability, and evening congestion flag', () => {
  const c = vm.createContext({
    esc: (s) => String(s == null ? '' : s),
    isZh: () => true,
    Date: { now: () => 1762780000000 },
    window: {}
  });

  vm.runInContext(source('deriveNodeState'), c);

  const nodes = [
    { name: '美西 · 硅谷', host: '43.153.56.137', port: 443, role: 'exit', country: 'US', type: 'vless' },
    { name: '香港 · HK01', host: '203.0.113.10', port: 443, role: 'relay', country: 'CN' }
  ];

  // Case 1: High latency international congestion (245ms >= 220ms) -> isCongested true
  const status1 = {
    '美西 · 硅谷': { ok: true, cn_ok: true, cn_ms: 245 }
  };
  const m1 = c.deriveNodeState(nodes[0], nodes, status1, {}, true);
  assert.equal(m1.hasHy2, true, 'overseas exit should have HY2 support');
  assert.equal(m1.isHy2Active, false, 'HY2 initially inactive');
  assert.equal(m1.isCongested, true, 'evening congestion detected on 245ms');

  // Case 2: Normal low latency (80ms) -> isCongested false
  const status2 = {
    '美西 · 硅谷': { ok: true, cn_ok: true, cn_ms: 80 }
  };
  const m2 = c.deriveNodeState(nodes[0], nodes, status2, {}, true);
  assert.equal(m2.isCongested, false, 'normal latency should not trigger congestion');

  // Case 3: Domestic relay node -> hasHy2 false for relay role
  const m3 = c.deriveNodeState(nodes[1], nodes, status1, {}, true);
  assert.equal(m3.isDomestic, true);
});

test('updateContextualAwakening: surfaces Cupertino capsule on congestion and hides when awakened', () => {
  let innerHTML = '';
  let display = 'none';
  const container = {
    set innerHTML(val) { innerHTML = val; },
    get innerHTML() { return innerHTML; },
    style: {
      set display(val) { display = val; },
      get display() { return display; }
    }
  };

  const c = vm.createContext({
    document: {
      getElementById: (id) => (id === 'contextual-awakening' ? container : null)
    },
    esc: (s) => String(s == null ? '' : s),
    isZh: () => true,
    window: {},
    toggleHy2: () => {}
  });

  vm.runInContext(source('updateContextualAwakening'), c);

  const nodes = [
    { name: '美西 · 硅谷', host: '43.153.56.137', port: 443, role: 'exit', country: 'US', type: 'vless' }
  ];

  // 1. High latency probe triggers awakening capsule
  const highLatencyStatus = {
    '美西 · 硅谷': { ok: true, cn_ok: true, cn_ms: 260 }
  };
  c.updateContextualAwakening(nodes, highLatencyStatus);

  assert.equal(display, 'block', 'container must be visible on congestion');
  assert.match(innerHTML, /awakening-capsule/, 'Cupertino capsule must be rendered');
  assert.match(innerHTML, /美西 · 硅谷/, 'target node name must be present');
  assert.match(innerHTML, /260ms/, 'latency must be present');
  assert.match(innerHTML, /window\.ownlineAwakenHy2/, 'awaken action button must be wired');
  assert.match(innerHTML, /window\.ownlineDismissAwakening/, 'dismiss button must be wired');

  // 2. Once HY2 is activated, capsule disappears
  nodes[0].hy2_enabled = true;
  c.updateContextualAwakening(nodes, highLatencyStatus);
  assert.equal(display, 'none', 'container must be hidden when HY2 is active');
});

test('refreshState: anti-race protection pauses during user operations', () => {
  let calledJsonRequest = false;
  const c = vm.createContext({
    window: { isTogglingHy2: true },
    document: { getElementById: () => null },
    location: { protocol: 'https:' },
    jsonRequest: () => { calledJsonRequest = true; return Promise.resolve(); },
    AbortController: class { abort() {} }
  });

  vm.runInContext(source('refreshState'), c);
  c.refreshState();

  // With isTogglingHy2 = true, refreshState returns immediately without making network calls
  assert.equal(calledJsonRequest, false, 'refreshState should not make network calls when isTogglingHy2 is true');
});
