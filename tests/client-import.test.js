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

function context(ua = '', opts = {}) {
  const ids = ['suburl', 'btn-copy-sub', 'btn-copy-clash', 'btn-sr', 'btn-clash', 'btn-flclash',
    'pill-sr', 'pill-clash', 'pill-flclash', 'client-item-sr', 'client-item-clash', 'client-item-flclash',
    'apple-store-help', 'download-sr', 'download-clash', 'download-flclash',
    'hub-dl-clash', 'hub-dl-flclash', 'hub-dl-sr',
    'assist-sr', 'assist-clash', 'assist-flclash',
    'clash-ios-help', 'import-note', 'copy-note', 'download-help'];
  const els = Object.fromEntries(ids.map(id => [id, {id, style: {}, disabled: true, href: '#', textContent: '',
    className: '', setAttribute(k, v){this[k]=v;}, getAttribute(k){return this[k];}, removeAttribute(name) {this.removed = name;}}]));
  const appendedFrames = [];
  const doc = {
    getElementById: id => els[id] || null,
    querySelectorAll: () => [],
  };
  if (opts.withBody) {
    doc.body = {
      appendChild(el) { appendedFrames.push(el); el.parentNode = this; },
      removeChild(el) { el.removedFromBody = true; }
    };
    doc.createElement = tag => ({
      tagName: tag.toUpperCase(),
      style: {},
      setAttribute() {},
      href: '',
      target: '',
      rel: '',
      clicked: false,
      click() { this.clicked = true; },
    });
  }
  const c = vm.createContext({BASE_SUB_URL: '', navigator: {userAgent: ua, maxTouchPoints: 0},
    document: doc,
    encodeURIComponent, btoa, setTimeout: () => 0});
  vm.runInContext([source('wireLinks'), source('detectClient')].join('\n'), c);
  return {c, els, appendedFrames};
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

test('client clicks prevent navigation, launch synthetic blank anchor without tab lock, prioritize Clash on macOS and hide desktop downloads on iOS', () => {
  const mac = context('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)');
  mac.c.detectClient();
  assert.doesNotMatch(mac.els['btn-sr'].className, /\bprimary\b/);
  assert.match(mac.els['btn-clash'].className, /\bprimary\b/);
  assert.equal(mac.els['hub-dl-clash'].style.display, '');

  const ios = context('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', { withBody: true });
  ios.c.BASE_SUB_URL = 'https://example.test/s/abcd1234';
  ios.c.detectClient();
  ios.c.wireLinks(true);
  assert.match(ios.els['btn-sr'].className, /\bprimary\b/);
  assert.equal(ios.els['hub-dl-clash'].style.display, 'none');
  assert.equal(ios.els['hub-dl-flclash'].style.display, 'none');
  assert.equal(ios.els['hub-dl-sr'].style.display, '');

  let prevented = false;
  ios.els['btn-sr'].onclick({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(ios.appendedFrames.length, 1);
  assert.equal(ios.appendedFrames[0].tagName, 'A');
  assert.equal(ios.appendedFrames[0].target, '_blank');
  assert.equal(ios.appendedFrames[0].rel, 'noopener noreferrer');
  assert.equal(ios.appendedFrames[0].clicked, true);
  assert.equal(ios.appendedFrames[0].removedFromBody, true);
  assert.match(ios.appendedFrames[0].href, /^shadowrocket:\/\/add\/sub:\/\//);
  assert.equal(ios.els['assist-sr'].style.display, 'block');
});

(require('node:test'))('client hub and QR dialogs use native accessible top-layer semantics, light-dismiss fallback, collapsed download disclosure, and discrete animations', () => {
  const localFs = require('node:fs');
  const localPath = require('node:path');
  const localAssert = require('node:assert/strict');
  const builtIndex = localFs.readFileSync(localPath.join(__dirname, '../web/index.html'), 'utf8');

  localAssert.match(builtIndex, /<dialog[^>]*id="client-hub-dialog"[^>]*aria-labelledby="hub-device-title"[^>]*closedby="any"/);
  localAssert.match(builtIndex, /<dialog[^>]*id="qr-dialog"[^>]*aria-labelledby="qr-dialog-title"[^>]*closedby="any"/);
  localAssert.match(builtIndex, /<h2[^>]*id="qr-dialog-title"/);
  localAssert.equal(builtIndex.includes('data-i18n="scan_qr_desc"'), false, 'duplicate scan_qr_desc helper should be removed');
  localAssert.match(builtIndex, /<details[^>]*id="hub-download-disclosure"(?![^>]*\sopen\b)/);

  localAssert.ok(builtIndex.includes('@starting-style'), 'top-layer dialog entry should use @starting-style');
  localAssert.ok(builtIndex.includes('transition-behavior: allow-discrete'), 'discrete dialog transition should be declared outside shorthand');
  localAssert.ok(builtIndex.includes('initDialogLightDismiss'), 'init script should register progressive light-dismiss fallback');
  localAssert.ok(builtIndex.includes('getBoundingClientRect') && builtIndex.includes('closedBy'), 'fallback should feature-detect native closedBy and check backdrop bounds');
});
