const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('local ping ui: script definitions, header pill, and css styling exist', () => {
  assert(html.includes('var LOCAL_DEVICE_PING'), 'LOCAL_DEVICE_PING must exist in client script');
  assert(html.includes('function probeDeviceLocalLatency'), 'probeDeviceLocalLatency must exist');
  assert(html.includes('function updateHeaderLocalPingUI'), 'updateHeaderLocalPingUI must exist');
  assert(html.includes('id="header-local-ping"'), '#header-local-ping element must exist in HTML');
  assert(html.includes('.ping-pill.local-ping'), '.ping-pill.local-ping css class must exist');
  assert(html.includes('.ping-pill.probing'), '.ping-pill.probing css class must exist');
});

test('local ping logic: device probe measures RTT against gateway /api/ping', async () => {
  const mockFetch = (url, opts) => {
    assert(url.includes('/api/ping'), 'must query gateway /api/ping');
    return new Promise((resolve) => {
      setTimeout(resolve, 25);
    });
  };

  const headerPill = { style: { display: 'none' }, className: '', textContent: '', title: '' };
  const sandbox = {
    window: {},
    document: {
      getElementById: (id) => (id === 'header-local-ping' ? headerPill : null)
    },
    fetch: mockFetch,
    performance: { now: () => Date.now() },
    setTimeout,
    clearTimeout,
    AbortController,
    Promise,
    isZh: () => true
  };
  vm.createContext(sandbox);

  const localPingSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/07b-local-ping.js'), 'utf8');
  vm.runInContext(localPingSrc, sandbox);

  assert.equal(typeof sandbox.window.ownlineProbeLocalPing, 'function');
  const ms = await sandbox.window.ownlineProbeLocalPing();
  assert(typeof ms === 'number', 'ms should be numeric RTT');
  assert(ms >= 20, 'ms should reflect elapsed fetch time');
  assert.equal(sandbox.window.LOCAL_DEVICE_PING.status, 'fast');
  assert.equal(headerPill.style.display, 'inline-flex');
  assert.match(headerPill.textContent, /📱 本机 \d+ms/);
});

test('local ping logic: gateway unreachable marks status as bad and updates pill', async () => {
  const failingFetch = () => {
    return Promise.reject(new Error('Network offline'));
  };

  const headerPill = { style: { display: 'none' }, className: '', textContent: '', title: '' };
  const sandbox = {
    window: {},
    document: {
      getElementById: (id) => (id === 'header-local-ping' ? headerPill : null)
    },
    fetch: failingFetch,
    performance: { now: () => Date.now() },
    setTimeout,
    clearTimeout,
    AbortController,
    Promise,
    isZh: () => true
  };
  vm.createContext(sandbox);

  const localPingSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/07b-local-ping.js'), 'utf8');
  vm.runInContext(localPingSrc, sandbox);

  const res = await sandbox.window.ownlineProbeLocalPing();
  assert.equal(res, null);
  assert.equal(sandbox.window.LOCAL_DEVICE_PING.status, 'bad');
  assert.match(headerPill.textContent, /📱 本机网络异常/);
});
