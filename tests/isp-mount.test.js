const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

function source(name) {
  const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
  assert(match, `missing ${name}`);
  return match[0];
}

function context() {
  const box = { innerHTML: '' };
  const c = vm.createContext({
    NODES: [],
    STATUS: {},
    esc: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
    paintStatus: () => {},
    document: {
      getElementById: id => (id === 'nodes' ? box : null)
    },
    window: {}
  });
  vm.runInContext(source('renderNodes'), c);
  return { c, box };
}

test('renderNodes displays residential ISP badge for nodes with isp config', () => {
  const { c, box } = context();
  const nodes = [
    {
      name: '日本 · JP01',
      host: '198.51.100.15',
      port: 443,
      role: 'exit',
      isp: { type: 'socks', server: '198.51.100.88', server_port: 10808 }
    }
  ];
  c.renderNodes(nodes, {});
  assert.match(box.innerHTML, /(住宅 IP · 198\.51\.100\.88:10808|Residential Egress: 198\.51\.100\.88:10808)/);
  assert.match(box.innerHTML, /#i-home/);
  assert.match(box.innerHTML, /window\.ownlineMountIsp\(0\)/);
});

test('renderNodes displays mount button for exit node without isp', () => {
  const { c, box } = context();
  const nodes = [
    {
      name: '美国 · US01',
      host: '198.51.100.30',
      port: 443,
      role: 'exit'
    }
  ];
  c.renderNodes(nodes, {});
  assert.match(box.innerHTML, /(绑定住宅 IP|Mount ISP)/);
  assert.match(box.innerHTML, /#i-plus/);
  assert.match(box.innerHTML, /window\.ownlineMountIsp\(0\)/);
});

test('relay node does not display mount residential ISP button', () => {
  const { c, box } = context();
  const nodes = [
    {
      name: '香港 · HK01',
      host: '203.0.113.10',
      port: 443,
      role: 'relay'
    }
  ];
  c.renderNodes(nodes, {});
  assert.doesNotMatch(box.innerHTML, /(绑定住宅 IP|Mount ISP)/);
  assert.doesNotMatch(box.innerHTML, /(住宅 IP|Residential Egress)/);
  assert.doesNotMatch(box.innerHTML, /#i-home/);
});

test('window.ownlineMountIsp is registered in index.html', () => {
  assert.match(html, /window\.ownlineMountIsp\s*=\s*mountIsp;/);
});

test('mountIsp dialog contains Webshare recommendation link', () => {
  assert.match(html, /https:\/\/www\.webshare\.io/);
  assert.match(html, /选择「Static Residential」/);
});
