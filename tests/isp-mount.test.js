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

test('mountIsp dialog contains Webshare smart input and structured parameter fields', () => {
  assert.match(html, /id="isp-smart-input"/);
  assert.match(html, /id="isp-manual-host"/);
  assert.match(html, /id="isp-manual-port"/);
  assert.match(html, /id="isp-manual-user"/);
  assert.match(html, /id="isp-manual-pass"/);
  assert.match(html, /name="isp-proto"/);
  assert.match(html, /已深度适配 Webshare/);
});

test('parseWebshareProxy parses curl command, 4-colon list, and credentials correctly', () => {
  const match = html.match(/function parseWebshareProxy\(raw\)\s*\{[\s\S]*?^\s*return null;\s*\}/m);
  assert(match, 'parseWebshareProxy function must be present');
  const fnStr = match[0];
  const parseWebshareProxy = new Function('raw', `${fnStr}; return parseWebshareProxy(raw);`);

  // 1. Webshare curl quickstart
  const curlRes = parseWebshareProxy('curl --proxy "http://dora2026:secretpass@168.158.185.30:6297/" https://ipv4.webshare.io/');
  assert.deepEqual(curlRes, {
    type: 'http',
    server: '168.158.185.30',
    server_port: 6297,
    username: 'dora2026',
    password: 'secretpass'
  });

  // 2. Webshare 4-colon download format
  const colonRes = parseWebshareProxy('168.158.185.30:6297:dora2026:secretpass');
  assert.deepEqual(colonRes, {
    type: 'socks',
    server: '168.158.185.30',
    server_port: 6297,
    username: 'dora2026',
    password: 'secretpass'
  });

  // 3. socks5 URL
  const socksRes = parseWebshareProxy('socks5://dora2026:secretpass@168.158.185.30:6297');
  assert.deepEqual(socksRes, {
    type: 'socks',
    server: '168.158.185.30',
    server_port: 6297,
    username: 'dora2026',
    password: 'secretpass'
  });

  // 4. bare IP:Port
  const bareRes = parseWebshareProxy('168.158.185.30:6297');
  assert.deepEqual(bareRes, {
    type: 'socks',
    server: '168.158.185.30',
    server_port: 6297,
    username: '',
    password: ''
  });

  // 5. user:pass@ip:port
  const authRes = parseWebshareProxy('dora2026:secretpass@168.158.185.30:6297');
  assert.deepEqual(authRes, {
    type: 'socks',
    server: '168.158.185.30',
    server_port: 6297,
    username: 'dora2026',
    password: 'secretpass'
  });

  // 6. curl --proxy + --proxy-user / -U
  const curlProxyUser = parseWebshareProxy('curl --proxy http://198.51.100.22:8080 --proxy-user wsuser:wspass123 https://ipv4.webshare.io/');
  assert.deepEqual(curlProxyUser, {
    type: 'http',
    server: '198.51.100.22',
    server_port: 8080,
    username: 'wsuser',
    password: 'wspass123'
  });

  const curlShortU = parseWebshareProxy('curl -x socks5://198.51.100.22:8080 -U "u:p:1" https://ipv4.webshare.io/');
  assert.deepEqual(curlShortU, {
    type: 'socks',
    server: '198.51.100.22',
    server_port: 8080,
    username: 'u',
    password: 'p:1'
  });

  assert.equal(parseWebshareProxy('hello world'), null);
});

test('renderNodes displays muted WARP standby instead of active ok WARP badge when ISP is mounted', () => {
  const { c, box } = context();
  const nodes = [
    {
      name: '硅谷',
      host: '198.51.100.15',
      port: 443,
      role: 'exit',
      warp_enabled: true,
      isp: { type: 'socks', server: '198.51.100.88', server_port: 10808 }
    }
  ];
  c.renderNodes(nodes, {});
  assert.match(box.innerHTML, /WARP 待命/);
  assert.doesNotMatch(box.innerHTML, /<span class="tag ok"[^>]*>WARP<\/span>/);
});

test('mountIsp modal provides rule-mode zero-DNS-leak guidance', () => {
  assert.match(html, /防泄漏与分流建议/);
  assert.match(html, /保持<b>「规则模式」<\/b>/);
});
