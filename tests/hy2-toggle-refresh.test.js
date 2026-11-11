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

function setup(fetchResult) {
  const state = { refreshingWhileLocked: null, refreshCount: 0, alerts: [] };
  const context = vm.createContext({
    window: {},
    document: { body: { style: {} } },
    isZh: () => true,
    jsonRequest: () => fetchResult(),
    refreshState: () => {
      state.refreshCount += 1;
      state.refreshingWhileLocked = context.window.isTogglingHy2;
    },
    alert: (message) => state.alerts.push(message)
  });
  vm.runInContext('var isTogglingHy2 = false;' + String.fromCharCode(10) + source('toggleHy2'), context);
  return { context, state };
}

async function settle() {
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

test('HY2 fetch failure refreshes actual state after releasing mutation lock', async () => {
  let fail;
  const { context, state } = setup(() => new Promise((_resolve, reject) => { fail = reject; }));

  context.toggleHy2('硅谷', '43.153.56.137', true);
  fail(new Error('Failed to fetch'));
  await settle();

  assert.equal(state.refreshCount, 1);
  assert.equal(state.refreshingWhileLocked, false);
  assert.equal(context.window.isTogglingHy2, false);
  assert.equal(state.alerts.length, 1);
});

test('HY2 server rejection refreshes state after reporting the rejection', async () => {
  const { context, state } = setup(() => Promise.resolve({ ok: false, error: '验真失败' }));

  context.toggleHy2('硅谷', '43.153.56.137', false);
  await settle();

  assert.equal(state.refreshCount, 1);
  assert.equal(state.refreshingWhileLocked, false);
  assert.match(state.alerts[0], /验真失败/);
});
