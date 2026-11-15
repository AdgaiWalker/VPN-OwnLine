const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('ui refinement: status-pill is clickable button with scrollToIssue', () => {
  assert.match(html, /<button class="pill-preview" id="status-pill"[^>]*onclick="window\.ownlineScrollToIssue\(\)"/);
  assert(html.includes('window.ownlineScrollToIssue = scrollToIssue;'));
});

test('ui refinement: duplicate quota glance removed from subheader', () => {
  assert.equal(html.includes('id="quota-glance"'), false, '#quota-glance must be removed to avoid duplication with hero banner');
});

test('ui refinement: setup entry relocated to nodes summary and footer cleaned up', () => {
  assert.match(html, /<summary id="nodes-summary"[\s\S]*?id="btn-enter-setup"[\s\S]*?id="btn-ping-action"/);
  assert(html.includes('class="site-footer-links"'));
  assert(html.includes('class="footer-sep">·</span>'));
});

test('node deletion: delNode sends cleanup_confirmed for pending nodes or chains two-phase commit', async () => {
  const match = html.match(/^  function delNode\([^\n]*\)\s*\{[\s\S]*?^  \}/m);
  assert(match, 'missing delNode function');

  const requests = [];
  let dialogShown = [];
  const c = vm.createContext({
    NODES: [
      { name: 'NormalNode', cleanup_pending: false },
      { name: 'PendingNode', cleanup_pending: true }
    ],
    dialog: (opts) => {
      dialogShown.push(opts);
      return Promise.resolve(true); // user confirms
    },
    jsonRequest: (url, opts) => {
      requests.push({ url, body: JSON.parse(opts.body) });
      if (url === '/api/removenode') {
        const body = JSON.parse(opts.body);
        if (body.name === 'NormalNode' && !body.cleanup_confirmed) {
          return Promise.resolve({ ok: true, cleanup_pending: true });
        }
        return Promise.resolve({ ok: true, stopped: true });
      }
      return Promise.resolve({ ok: true });
    },
    refreshState: () => {}
  });

  vm.runInContext(match[0], c);

  // Case 1: Pending node (like Guangzhou VPS) -> directly sends cleanup_confirmed: true
  await c.delNode(1);
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0], {
    url: '/api/removenode',
    body: { name: 'PendingNode', cleanup_confirmed: true }
  });

  // Case 2: Normal node -> step 1 returns cleanup_pending: true -> chains step 2 automatically
  requests.length = 0;
  await c.delNode(0);
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[0], {
    url: '/api/removenode',
    body: { name: 'NormalNode' }
  });
  assert.deepEqual(requests[1], {
    url: '/api/removenode',
    body: { name: 'NormalNode', cleanup_confirmed: true }
  });
});
