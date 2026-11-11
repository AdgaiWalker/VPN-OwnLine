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

test('node card displays reset_day and removes redundant 剩余 xxx GB in Chinese', () => {
  let innerHtmlContent = '';
  const c = vm.createContext({
    esc: (s) => String(s == null ? '' : s),
    isZh: () => true,
    Date: { now: () => 1762780000000 },
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: [],
    window: {},
    document: {
      getElementById: (id) => {
        if (id === 'nodes' || id === 'nodes-container') {
          return {
            set innerHTML(val) { innerHtmlContent = val; },
            get innerHTML() { return innerHtmlContent; }
          };
        }
        return { style: {}, textContent: '' };
      }
    }
  });

  vm.runInContext(source('deriveNodeState'), c);
  vm.runInContext(source('renderNodes'), c);

  const nodes = [
    { name: '硅谷', host: '43.153.56.137', port: 443, role: 'exit', country: 'US', type: 'vless', reset_day: 23 }
  ];
  const quota = {
    guards: [
      { ip: '43.153.56.137', used_gb: 180.2, total_gb: 512.0, percent: 35, reset_day: 23 }
    ]
  };

  c.renderNodes(nodes, {}, quota);

  assert.match(innerHtmlContent, /<strong>180\.2<\/strong> \/ 512 GB/);
  assert.match(innerHtmlContent, /23日重置/);
  assert.equal(innerHtmlContent.includes('剩余'), false, 'Should not contain redundant 剩余');
});

test('node card displays reset_day in English without 剩余/Remaining', () => {
  let innerHtmlContent = '';
  const c = vm.createContext({
    esc: (s) => String(s == null ? '' : s),
    isZh: () => false,
    Date: { now: () => 1762780000000 },
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: [],
    window: {},
    document: {
      getElementById: (id) => {
        if (id === 'nodes' || id === 'nodes-container') {
          return {
            set innerHTML(val) { innerHtmlContent = val; },
            get innerHTML() { return innerHtmlContent; }
          };
        }
        return { style: {}, textContent: '' };
      }
    }
  });

  vm.runInContext(source('deriveNodeState'), c);
  vm.runInContext(source('renderNodes'), c);

  const nodes = [
    { name: '硅谷', host: '43.153.56.137', port: 443, role: 'exit', country: 'US', type: 'vless', reset_day: 23 }
  ];
  const quota = {
    guards: [
      { ip: '43.153.56.137', used_gb: 180.2, total_gb: 512.0, percent: 35, reset_day: 23 }
    ]
  };

  c.renderNodes(nodes, {}, quota);

  assert.match(innerHtmlContent, /<strong>180\.2<\/strong> \/ 512 GB/);
  assert.match(innerHtmlContent, /Resets on 23/);
  assert.equal(innerHtmlContent.includes('Remaining'), false, 'Should not contain Remaining');
  assert.equal(innerHtmlContent.includes('剩余'), false, 'Should not contain 剩余');
});

test('node card gracefully omits reset day when no reset_day provided', () => {
  let innerHtmlContent = '';
  const c = vm.createContext({
    esc: (s) => String(s == null ? '' : s),
    isZh: () => true,
    Date: { now: () => 1762780000000 },
    paintStatus: () => {},
    STATE: null,
    STATUS: {},
    NODES: [],
    window: {},
    document: {
      getElementById: (id) => {
        if (id === 'nodes' || id === 'nodes-container') {
          return {
            set innerHTML(val) { innerHtmlContent = val; },
            get innerHTML() { return innerHtmlContent; }
          };
        }
        return { style: {}, textContent: '' };
      }
    }
  });

  vm.runInContext(source('deriveNodeState'), c);
  vm.runInContext(source('renderNodes'), c);

  const nodes = [
    { name: '自建节点', host: '198.51.100.99', port: 443, role: 'exit', country: 'US', type: 'vless' }
  ];
  const quota = {
    guards: [
      { ip: '198.51.100.99', used_gb: 50.0, total_gb: 200.0, percent: 25 }
    ]
  };

  c.renderNodes(nodes, {}, quota);

  assert.match(innerHtmlContent, /<strong>50<\/strong> \/ 200 GB/);
  assert.equal(innerHtmlContent.includes('重置'), false);
  assert.equal(innerHtmlContent.includes('剩余'), false);
});
