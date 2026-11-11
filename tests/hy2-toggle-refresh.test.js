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

function setup(fetchResult, nodesResult) {
  const state = { refreshingWhileLocked: null, refreshCount: 0, alerts: [] };
  const context = vm.createContext({
    window: {},
    document: { body: { style: {} } },
    isZh: () => true,
    jsonRequest: (path, opts) => {
      if (path === '/api/nodes') {
        if (nodesResult !== undefined) {
          return typeof nodesResult === 'function' ? nodesResult() : Promise.resolve(nodesResult);
        }
        return Promise.resolve([]);
      }
      return fetchResult(path, opts);
    },
    refreshState: () => {
      state.refreshCount += 1;
      state.refreshingWhileLocked = context.window.isTogglingHy2;
    },
    alert: (message) => state.alerts.push(message),
    setTimeout: (fn) => setImmediate(fn)
  });
  vm.runInContext('var isTogglingHy2 = false;' + String.fromCharCode(10) + source('toggleHy2'), context);
  return { context, state };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test('HY2 success clears mutation lock before refreshing visible state', async () => {
  let complete;
  const { context, state } = setup(() => new Promise((resolve) => { complete = resolve; }));

  context.toggleHy2('硅谷', '43.153.56.137', true);
  assert.equal(context.window.isTogglingHy2, true);

  complete({ ok: true });
  await settle();

  assert.equal(state.refreshCount, 1);
  assert.equal(state.refreshingWhileLocked, false);
  assert.equal(context.window.isTogglingHy2, false);
});

test('HY2 network break succeeds cleanly when backend state confirmed', async () => {
  let fail;
  const nodes = [
    { name: '硅谷', host: '43.153.56.137', hy2_enabled: true },
    { name: '硅谷-HY2', host: '43.153.56.137', type: 'hysteria2', enabled: true }
  ];
  const { context, state } = setup(
    () => new Promise((_resolve, reject) => { fail = reject; }),
    nodes
  );

  context.toggleHy2('硅谷', '43.153.56.137', true);
  fail(new Error('Failed to fetch'));
  await settle();

  assert.equal(state.refreshCount, 1);
  assert.equal(state.refreshingWhileLocked, false);
  assert.equal(context.window.isTogglingHy2, false);
  // Confirmed success suppresses confusing error alert
  assert.equal(state.alerts.length, 0);
});

test('HY2 network break reports unconfirmed state when backend state does not match', async () => {
  let fail;
  const nodes = [
    { name: '硅谷', host: '43.153.56.137', hy2_enabled: false }
  ];
  const { context, state } = setup(
    () => new Promise((_resolve, reject) => { fail = reject; }),
    nodes
  );

  context.toggleHy2('硅谷', '43.153.56.137', true);
  fail(new Error('Failed to fetch'));
  await settle();

  assert.equal(state.refreshCount, 1);
  assert.equal(state.refreshingWhileLocked, false);
  assert.equal(context.window.isTogglingHy2, false);
  assert.equal(state.alerts.length, 1);
  assert.match(state.alerts[0], /网络连接瞬断且未确认生效/);
});

test('HY2 server rejection refreshes state after reporting the rejection', async () => {
  const { context, state } = setup(() => Promise.resolve({ ok: false, error: '验真失败' }));

  context.toggleHy2('硅谷', '43.153.56.137', false);
  await settle();

  assert.equal(state.refreshCount, 1);
  assert.equal(state.refreshingWhileLocked, false);
  assert.match(state.alerts[0], /验真失败/);
});
