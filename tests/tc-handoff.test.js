const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(server) {
  const html = fs.readFileSync('web/index.html', 'utf8');
  const start = html.indexOf('  function initTencentPanel()');
  const end = html.indexOf('  function renderTcServerList()', start);
  const ids = ['btn-tc-read','tc-sid','tc-skey','tc-read-status','tc-credential-fields','btn-tc-auto-check','btn-tc-connect','tc-report','tc-connection-slot','ssh-connection-fields','other-credential','other-passphrase','other-ip'];
  const e = {};
  for (const id of ids) e[id] = {value:'',style:{},classList:{remove(){}},focus(){this.focused=true},dispatchEvent(){this.changed=true},appendChild(child){this.child=child}};
  e['other-credential'].value = 'old-secret';
  e['other-passphrase'].value = 'old-passphrase';
  let cleared = false;
  const c = {document:{getElementById:id=>e[id]},sessionStorage:{getItem:()=>null},STATE:{tcServers:[server],tcPickedIndex:0},clearOtherSecret(){cleared=true},Event:class{}};
  vm.createContext(c);
  vm.runInContext(html.slice(start,end), c);
  c.initTencentPanel();
  return {e,cleared:()=>cleared};
}

test('selected Tencent server fills the shared SSH form and clears previous secrets', () => {
  const {e,cleared} = setup({ip:'203.0.113.10'});
  e['btn-tc-connect'].onclick();
  assert(cleared());
  assert.equal(e['other-ip'].value, '203.0.113.10');
  assert(e['other-ip'].changed);
  assert.equal(e['other-credential'].value, '');
  assert.equal(e['other-passphrase'].value, '');
  assert.equal(e['tc-connection-slot'].child, e['ssh-connection-fields']);
  assert(e['other-credential'].focused);
});

test('a server without a public IP does not proceed', () => {
  const {e} = setup({ip:''});
  e['btn-tc-connect'].onclick();
  assert.match(e['tc-report'].textContent, /没有可用的公网 IP/);
  assert.equal(e['tc-connection-slot'].child, undefined);
});
