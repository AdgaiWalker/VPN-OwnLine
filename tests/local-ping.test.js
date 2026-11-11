const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('local ping ui: script definitions and css styling exist', () => {
  assert(html.includes('var LOCAL_PING_STATE'), 'LOCAL_PING_STATE must exist in client script');
  assert(html.includes('function ownlineProbeLocalPing'), 'ownlineProbeLocalPing must exist');
  assert(html.includes('function probeHostLatency'), 'probeHostLatency must exist');
  assert(html.includes('function initLocalPing'), 'initLocalPing must exist');
  assert(html.includes('.ping-pill.local-ping'), '.ping-pill.local-ping css class must exist');
  assert(html.includes('.ping-pill.probing'), '.ping-pill.probing css class must exist');
});

test('local ping logic: single probe resolves fast RTT on network response or reject', async () => {
  // Create sandbox
  let fetchCallCount = 0;
  const mockFetch = (url, opts) => {
    fetchCallCount++;
    return new Promise((resolve, reject) => {
      // Simulate fast network response (e.g. 25ms)
      setTimeout(() => {
        reject(new TypeError('Failed to fetch')); // Common in no-cors TLS reject
      }, 25);
    });
  };

  const sandbox = {
    window: {},
    fetch: mockFetch,
    performance: { now: () => Date.now() },
    setTimeout,
    clearTimeout,
    AbortController,
    Promise
  };
  vm.createContext(sandbox);

  const localPingSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/07b-local-ping.js'), 'utf8');
  vm.runInContext(localPingSrc, sandbox);

  assert.equal(typeof sandbox.window.probeTargetSingleAttempt, 'function');
  const res = await sandbox.window.probeTargetSingleAttempt('1.2.3.4', 443, 1000);
  assert.equal(res.ok, true, 'network response should register as reachable');
  assert(res.ms >= 20, 'ms should reflect elapsed time');
  assert.equal(res.timeout, false);
});

test('local ping logic: probe times out when connection hangs', async () => {
  const hangingFetch = (url, opts) => {
    return new Promise((resolve, reject) => {
      if (opts && opts.signal) {
        opts.signal.addEventListener('abort', () => {
          const err = new Error('The operation was aborted');
          err.name = 'AbortError';
          reject(err);
        });
      }
    });
  };

  const sandbox = {
    window: {},
    fetch: hangingFetch,
    performance: { now: () => Date.now() },
    setTimeout,
    clearTimeout,
    AbortController,
    Promise
  };
  vm.createContext(sandbox);

  const localPingSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/07b-local-ping.js'), 'utf8');
  vm.runInContext(localPingSrc, sandbox);

  const res = await sandbox.window.probeTargetSingleAttempt('1.2.3.4', 443, 100);
  assert.equal(res.ok, false);
  assert.equal(res.ms, null);
  assert.equal(res.timeout, true);
});

test('local ping logic: ownlineProbeLocalPing aggregates all unique nodes and populates LOCAL_PING_STATE', async () => {
  const mockFetch = (url) => {
    return new Promise((resolve) => {
      setTimeout(resolve, 15);
    });
  };

  const sandbox = {
    window: {
      NODES: [
        { name: 'Node-1', host: '10.0.0.1', port: 443 },
        { name: 'Node-2', host: '10.0.0.2', port: 8443 },
        { name: 'Node-1-Alt', host: '10.0.0.1', port: 443 } // Duplicate host
      ],
      paintStatus: () => {}
    },
    fetch: mockFetch,
    performance: { now: () => Date.now() },
    setTimeout,
    clearTimeout,
    AbortController,
    Promise
  };
  vm.createContext(sandbox);

  const localPingSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/07b-local-ping.js'), 'utf8');
  vm.runInContext(localPingSrc, sandbox);

  const results = await sandbox.window.ownlineProbeLocalPing(true);
  assert(results['10.0.0.1'], '10.0.0.1 must have probe result');
  assert(results['10.0.0.2'], '10.0.0.2 must have probe result');
  assert.equal(results['10.0.0.1'].ok, true);
  assert.equal(results['10.0.0.1'].probing, false);
  assert(typeof results['10.0.0.1'].ms === 'number');
});
