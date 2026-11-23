const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

function extractFn(name) {
  const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
  assert(match, `missing ${name}`);
  return match[0];
}

test('reverse_join and frozen windows nodes show honest badges and hide remote-mutation buttons', () => {
  const box = { innerHTML: '' };
  const c = vm.createContext({
    NODES: [],
    STATUS: {},
    esc: (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
    isZh: () => true,
    paintStatus: () => {},
    document: {
      getElementById: (id) => (id === 'nodes' ? box : null),
    },
    window: {},
    Date: { now: () => 1762780000000 },
  });

  vm.runInContext(extractFn('deriveNodeState'), c);
  vm.runInContext(extractFn('renderNodes'), c);

  const rjNode = {
    name: '终端节点',
    host: '198.51.100.51',
    port: 443,
    role: 'exit',
    source: 'reverse_join',
    hy2_enabled: true,
    isp: { type: 'socks', server: '198.51.100.88', server_port: 1080 },
  };
  const winNode = {
    name: '新加坡Win',
    host: '198.51.100.52',
    port: 443,
    role: 'exit',
    os: 'windows',
    source: 'builtin',
  };
  const managedNode = {
    name: '受控硅谷',
    host: '198.51.100.53',
    port: 443,
    role: 'exit',
    source: 'builtin',
  };

  // deriveNodeState should never set isCongested on unmanaged nodes
  const rjState = c.deriveNodeState(rjNode, [rjNode], { '终端节点': { ok: false, cn_ms: 500 } }, {}, true);
  assert.equal(rjState.canRemoteMutate, false);
  assert.equal(rjState.isReverseJoin, true);
  assert.equal(rjState.isCongested, false);

  const winState = c.deriveNodeState(winNode, [winNode], { '新加坡Win': { ok: false, cn_ms: 500 } }, {}, true);
  assert.equal(winState.canRemoteMutate, false);
  assert.equal(winState.isWindowsFrozen, true);
  assert.equal(winState.isCongested, false);

  // Render observe-only nodes alone -> zero clickable remote mutations
  c.renderNodes([rjNode, winNode], {});
  assert.match(box.innerHTML, /免密接入 · 本机运维/);
  assert.match(box.innerHTML, /Windows · 已冻结/);
  assert.doesNotMatch(box.innerHTML, /ownlineToggleHy2ByIndex/);
  assert.doesNotMatch(box.innerHTML, /ownlineMountIsp/);
  assert.doesNotMatch(box.innerHTML, /ownlineToggleWarp/);

  // Managed Linux node retains remote mutation controls
  c.renderNodes([managedNode], {});
  assert.match(box.innerHTML, /ownlineToggleHy2ByIndex/);
  assert.match(box.innerHTML, /ownlineMountIsp/);
  assert.match(box.innerHTML, /ownlineToggleWarp/);
});

test('nodeMenu hides remote-mutation items on reverse_join nodes and keeps them on managed nodes', () => {
  const chosen = [];
  const rjNode = { name: '终端节点', host: '198.51.100.51', port: 443, role: 'exit', source: 'reverse_join' };
  const managedNode = { name: '受控硅谷', host: '198.51.100.53', port: 443, role: 'exit', source: 'builtin' };

  const c = vm.createContext({
    NODES: [rjNode, managedNode],
    STATUS: {},
    isZh: () => true,
    choose: (_title, _sub, items) => {
      chosen.push(items.map((x) => x.id));
      return Promise.resolve(-1);
    },
  });
  vm.runInContext(extractFn('nodeMenu'), c);

  c.nodeMenu(0);
  c.nodeMenu(1);

  assert.deepEqual(Array.from(chosen[0]), ['edit', 'toggle', 'lifecycle', 'del']);
  assert(chosen[1].includes('isp'));
  assert(chosen[1].includes('warp'));
  assert(chosen[1].includes('rotate'));
});
