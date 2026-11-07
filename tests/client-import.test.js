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

function context(ua = '') {
  const ids = ['suburl', 'btn-copy-sub', 'btn-copy-clash', 'btn-sr', 'btn-clash', 'btn-flclash',
    'apple-store-help', 'download-sr', 'download-clash', 'download-flclash',
    'assist-sr', 'assist-clash', 'assist-flclash',
    'clash-ios-help', 'import-note', 'copy-note', 'download-help'];
  const els = Object.fromEntries(ids.map(id => [id, {id, style: {}, disabled: true, href: '#', textContent: '',
    className: '', setAttribute(k, v){this[k]=v;}, getAttribute(k){return this[k];}, removeAttribute(name) {this.removed = name;}}]));
  const c = vm.createContext({BASE_SUB_URL: '', navigator: {userAgent: ua, maxTouchPoints: 0},
    document: {getElementById: id => els[id] || null, querySelectorAll: () => []},
    encodeURIComponent, btoa});
  vm.runInContext([source('wireLinks'), source('detectClient')].join('\n'), c);
  return {c, els};
}

test('without a real subscription the client links and copy actions stay unavailable', () => {
  const {c, els} = context('iPhone');
  c.wireLinks(false);
  assert.equal(els['btn-sr'].href, '#');
  assert.equal(els['btn-clash'].href, '#');
  assert.equal(els['btn-flclash'].href, '#');
  assert.equal(els['suburl'].textContent, '订阅链接暂不可用');
});

test('links use supported app schemes and Clash-format endpoint', () => {
  const {c, els} = context('Android');
  c.BASE_SUB_URL = 'https://example.test/s/abcd1234';
  c.wireLinks(true);
  const brandTitle = encodeURIComponent('Evergreen-OwnLine');
  assert.equal(els['btn-sr'].href, 'shadowrocket://add/sub://' + btoa(c.BASE_SUB_URL) + '?title=' + brandTitle);
  assert.equal(els['btn-clash'].href, 'clash://install-config?url=' + encodeURIComponent(c.BASE_SUB_URL + '/clash') + '&name=' + brandTitle);
  assert.equal(els['btn-flclash'].href, 'flclash://install-config?url=' + encodeURIComponent(c.BASE_SUB_URL + '/clash'));
  assert.equal(html.includes('id="client-item-singbox"'), false, 'Sing-box client entry must be removed per PRD');
  els['btn-sr'].onclick({preventDefault(){}});
  assert.match(els['import-note'].textContent, /正在尝试打开客户端/);
  assert.doesNotMatch(els['import-note'].textContent, /已安装|导入成功/);
});

test('device-specific clients and official download links stay separate', () => {
  for (const [ua, apple, fl, android] of [
    ['iPhone', true, false, false], ['Macintosh', true, true, false],
    ['Android', false, true, true], ['Windows', false, true, false], ['Linux', false, true, false]
  ]) {
    const {c, els} = context(ua);
    c.detectClient();
    assert.equal(els['btn-sr'].style.display !== 'none', apple, ua);
    assert.equal(els['btn-flclash'].style.display !== 'none', fl, ua);
    assert.equal(els['apple-store-help'].style.display !== 'none', apple, ua);
    assert.equal(els['download-flclash'].style.display !== 'none', fl, ua);
    if (android) assert.match(els['download-clash'].href, /^https:\/\/github\.com\/MetaCubeX\/ClashMetaForAndroid\/releases$/);
    else if (fl) assert.match(els['download-clash'].href, /^https:\/\/github\.com\/clash-verge-rev\/clash-verge-rev\/releases$/);
  }
});
