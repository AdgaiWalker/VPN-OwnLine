const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function createUI(fetchImpl, confirm = () => true) {
  const html = fs.readFileSync('web/index.html', 'utf8');
  const ids = [
    'other-credential', 'other-connect', 'other-key-status', 'other-connect-status',
    'other-check-result', 'other-ip', 'other-user', 'other-ssh-port', 'other-passphrase',
    'view-setup', 'node-install-confirm-box', 'node-name-input', 'node-role-select',
    'btn-submit-addnode', 'addnode-submit-status', 'install-task', 'install-task-title',
    'install-task-message', 'install-task-refresh', 'install-task-dismiss',
    'ssh-advanced-settings', 'node-install-options'
  ];
  const elements = {};
  for (const id of ids) elements[id] = {
    value:'', disabled:false, open:false, style:{display:''}, textContent:'', listeners:{}, attributes:{},
    addEventListener(k,v){const previous=this.listeners[k];this.listeners[k]=(...args)=>{if(previous) previous(...args);v(...args);};},
    setAttribute(k,v){this.attributes[k]=v;}, removeAttribute(k){delete this.attributes[k];},
    focus(){this.focused=true;}
  };
  elements['node-role-select'].value = 'auto';
  elements['other-ip'].value = '8.8.8.8';
  elements['other-user'].value = 'root';
  elements['other-ssh-port'].value = '22';
  elements['view-setup'].style.display = 'block';
  const storage = {};
  const context = {
    document: { getElementById: id => elements[id] },
    window: { confirm },
    localStorage: {
      getItem: k => storage[k],
      setItem: (k, v) => { storage[k] = String(v); },
      removeItem: k => { delete storage[k]; }
    },
    STATE: { nodeCheckAvailable: true },
    otherPrivateKey: '',
    otherCheckController: null,
    AbortController,
    fetch: fetchImpl,
    switchScene: () => {},
    initInstallProgress: () => {},
    setTimeout,
    clearTimeout
  };
  vm.createContext(context);
  const a = html.indexOf('  function setOtherCheckBusy('), b = html.indexOf('  function esc(', a);
  const c = html.indexOf('  function initOtherConnection()'), d = html.indexOf('  function detectClient()', c);
  vm.runInContext(html.slice(a,b) + html.slice(c,d), context);
  context.initOtherConnection();
  return {elements, context, storage};
}

test('password is sent to the pinned host only after fingerprint confirmation and is cleared', async () => {
  const requests = [];
  const {elements} = createUI(async (_url, opts) => {
    requests.push(JSON.parse(opts.body));
    const data = requests.length === 1 ? {ok:false,code:'HOST_KEY_CONFIRMATION',fingerprint:'SHA256:'+'A'.repeat(43)} : {ok:true,result:{os:'ubuntu',version:'22.04',architecture:'x86_64',root:true,existing_singbox:false,singbox_service:'inactive'}};
    return {json:async()=>data};
  });
  elements['other-credential'].value = 'fixture-password';
  await elements['other-connect'].onclick();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].fingerprint, 'SHA256:'+'A'.repeat(43));
  assert.equal(elements['other-credential'].value, '');
  assert.match(elements['other-check-result'].textContent, /尚未安装/);
  elements['other-ip'].listeners.input();
  assert.equal(elements['other-check-result'].style.display, 'none');
});

test('canceling the fingerprint challenge never sends a second request', async () => {
  let count = 0;
  const {elements} = createUI(async () => {count++;return {json:async()=>({ok:false,code:'HOST_KEY_CONFIRMATION',fingerprint:'SHA256:'+'A'.repeat(43)})}}, () => false);
  elements['other-credential'].value = 'fixture-password';
  await elements['other-connect'].onclick();
  assert.equal(count, 1);
  assert.equal(elements['other-credential'].value, '');
  assert.match(elements['other-connect-status'].textContent, /已停止连接/);
});

test('pasted multiline key stays out of the visible password field and is cleared', async () => {
  let body;
  const {elements, context} = createUI(async (_url, opts) => {body=JSON.parse(opts.body);return {json:async()=>({ok:false,message:'fixture'})}});
  const key = '-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n-----END OPENSSH PRIVATE KEY-----';
  let prevented = false;
  elements['other-credential'].listeners.paste({clipboardData:{getData:()=>key},preventDefault(){prevented=true}});
  assert(prevented);
  assert.equal(elements['other-credential'].value, '');
  await elements['other-connect'].onclick();
  assert.equal(body.private_key, key);
  assert.equal(context.otherPrivateKey, '');
  assert.equal(elements['other-key-status'].textContent, '');
});

test('a key inserted without multiline clipboard support is not sent as a password', async () => {
  let calls = 0;
  const {elements} = createUI(async () => {calls++; throw new Error('must not run')});
  elements['other-credential'].value = '-----BEGIN OPENSSH PRIVATE KEY-----truncated';
  await elements['other-connect'].onclick();
  assert.equal(calls, 0);
  assert.match(elements['other-connect-status'].textContent, /完整的 SSH 私钥/);
});

test('returning to the dashboard aborts the check and discards late responses', async () => {
  let finish;
  const {elements, context} = createUI(() => new Promise(resolve => {finish=resolve}));
  elements['other-credential'].value = 'fixture-password';
  const pending = elements['other-connect'].onclick();
  context.clearOtherSecret();
  finish({json:async()=>({ok:true,result:{os:'ubuntu'}})});
  await pending;
  assert.equal(elements['other-check-result'].style.display, 'none');
  assert.equal(elements['other-connect-status'].textContent, '已取消连接检查。');
});

test('successful connection check reveals install confirmation and clicking install dispatches addnode', async () => {
  const requests = [];
  const {elements, storage} = createUI(async (url, opts) => {
    requests.push({url, body: JSON.parse(opts.body)});
    if (url.includes('/api/node/check')) {
      return {
        json: async () => ({
          ok: true,
          result: {
            os: 'ubuntu',
            version: '22.04',
            architecture: 'x86_64',
            root: true,
            existing_singbox: false,
            singbox_service: 'inactive'
          }
        })
      };
    }
    if (url.includes('/api/addnode')) {
      return {
        json: async () => ({
          ok: true,
          job: 'feedbeef1234'
        })
      };
    }
    throw new Error('unexpected url: ' + url);
  });

  elements['other-ssh-port'].value = '2222';
  elements['other-credential'].value = 'valid-root-pass';
  await elements['other-connect'].onclick();

  // Confirmation box is revealed with prefilled name
  assert.equal(elements['node-install-confirm-box'].style.display, 'block');
  assert.equal(elements['node-name-input'].value, '节点-8.8.8.8');

  // Submit node installation
  elements['node-name-input'].value = 'Tokyo-Edge';
  elements['node-role-select'].value = 'exit';
  await elements['btn-submit-addnode'].onclick();

  // Assert /api/addnode was called with proper payload including custom ssh_port
  assert.equal(requests.length, 2);
  const addnodeCall = requests[1];
  assert.match(addnodeCall.url, /\/api\/addnode/);
  assert.equal(addnodeCall.body.ip, '8.8.8.8');
  assert.equal(addnodeCall.body.user, 'root');
  assert.equal(addnodeCall.body.pass, 'valid-root-pass');
  assert.equal(addnodeCall.body.ssh_port, 2222);
  assert.equal(addnodeCall.body.port, 443);
  assert.equal(addnodeCall.body.name, 'Tokyo-Edge');
  assert.equal(addnodeCall.body.role, 'exit');

  // Job ID stored for progress tracking
  assert.equal(storage.sb_job, 'feedbeef1234');
  assert.equal(elements['node-install-confirm-box'].style.display, 'none');
});


test('two-field setup uses default account, port, name and automatic role without installing during check', async () => {
  const requests = [];
  const {elements, context} = createUI(async (url, opts) => {
    requests.push({url, body:JSON.parse(opts.body)});
    return {json:async()=> url.includes('/check')
      ? {ok:true,result:{os:'ubuntu',root:true,existing_singbox:false,singbox_service:'inactive'}}
      : {ok:true,job:'feedbeef1234'}};
  });
  context.initInstallProgress = () => {};
  elements['other-credential'].value = 'fixture-password';
  await elements['other-connect'].onclick();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].body.username, 'root');
  assert.equal(requests[0].body.ssh_port, 22);
  assert.equal(elements['node-install-options'].open, false);
  await elements['btn-submit-addnode'].onclick();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.name, '节点-8.8.8.8');
  assert.equal(requests[1].body.role, 'auto');
});

test('invalid hidden SSH port opens settings, focuses the field and clears its error after editing', async () => {
  let requests = 0;
  const {elements} = createUI(async () => { requests++; throw new Error('unexpected request'); });
  elements['other-credential'].value = 'fixture-password';
  elements['other-ssh-port'].value = '65536';
  await elements['other-connect'].onclick();
  assert.equal(requests, 0);
  assert.equal(elements['ssh-advanced-settings'].open, true);
  assert.equal(elements['other-ssh-port'].focused, true);
  assert.equal(elements['other-ssh-port'].attributes['aria-invalid'], 'true');
  assert.match(elements['other-connect-status'].textContent, /1–65535/);
  elements['other-ssh-port'].value = '22';
  elements['other-ssh-port'].listeners.input();
  assert.equal(elements['other-ssh-port'].attributes['aria-invalid'], undefined);
});

test('missing visible credentials are identified without opening advanced settings', async () => {
  const {elements, context} = createUI(async () => { throw new Error('unexpected request'); });
  context.isZh = () => false;
  elements['other-ip'].value = '';
  await elements['other-connect'].onclick();
  assert.equal(elements['other-ip'].focused, true);
  assert.equal(elements['other-connect-status'].textContent, 'Enter the server public IP.');
  elements['other-ip'].value = '203.0.113.10';
  elements['other-ip'].listeners.input();
  await elements['other-connect'].onclick();
  assert.equal(elements['other-credential'].focused, true);
  assert.match(elements['other-connect-status'].textContent, /password/);
  assert.equal(elements['ssh-advanced-settings'].open, false);
});

test('previous manual role stays visible in installation options after checking another server', async () => {
  const {elements} = createUI(async () => ({json:async()=>({ok:true,result:{os:'ubuntu',root:true,existing_singbox:false}})}));
  elements['other-credential'].value = 'fixture-password';
  elements['node-role-select'].value = 'relay';
  await elements['other-connect'].onclick();
  assert.equal(elements['node-role-select'].value, 'relay');
  assert.equal(elements['node-install-options'].open, true);
});
