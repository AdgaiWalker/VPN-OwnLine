const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element() {
  return {hidden:false,open:false,disabled:false,value:'',textContent:'',type:'password',dataset:{},
    children:[],events:{},attributes:{},setAttribute(name,value){this.attributes[name]=value;},
    addEventListener(name,handler){this.events[name]=handler;},focus(){this.focused=true;},
    appendChild(child){this.children.push(child);},replaceChildren(...rows){this.children=rows;}};
}
const running = {state:'running',stage:'dependencies',stage_label:'安装系统依赖和管理网关',elapsed_seconds:83,
  stage_elapsed_seconds:65,stages:[{code:'upload',label:'传输安装程序',elapsed_seconds:18,state:'done'},
    {code:'dependencies',label:'安装系统依赖和管理网关',elapsed_seconds:65,state:'running'}],log:['fixture-private-log']};

async function harness(job = running, responses = {}, copy = async () => {}) {
  const html = fs.readFileSync('web/src/html/local-setup.html','utf8');
  const elements = Object.fromEntries([...html.matchAll(/<[^>]+id="([^"]+)"[^>]*>/g)].map(m=>[
    m[1], {...element(),hidden:/\bhidden\b/.test(m[0]),open:/\bopen\b/.test(m[0]),disabled:/\bdisabled\b/.test(m[0])}
  ]));
  elements['ssh-credential'].value='local-fixture';
  elements['ssh-credential'].required=true;
  elements['ssh-prompt'].textContent=html.match(/<pre id="ssh-prompt" hidden>([\s\S]*?)<\/pre>/)[1];
  elements.connection.elements={
    host:{...element(),value:'198.51.100.2'},username:{...element(),value:'root'},
    ssh_port:{...element(),value:'22'},password:elements['ssh-credential'],passphrase:element(),
  };
  elements['tencent-credentials'].elements={
    secret_id:elements['tencent-secret-id'],secret_key:elements['tencent-secret-key']
  };
  const timers=new Map(), calls=[];let id=0, current=job, fail=false, hang=false, hold=false, release;
  const context={AbortController,URL,FormData:function(form) {
    return Object.entries(form.elements).filter(([,field])=>!field.disabled).map(([k,field])=>[k,field.value]);
  },navigator:{clipboard:{writeText:copy}},
    document:{getElementById:k=>elements[k],body:{appendChild(){}},execCommand:()=>false,
      createElement:()=>({...element(),style:{},select(){},remove(){}})},
    setTimeout(fn,ms){timers.set(++id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
    fetch:async (path,options)=>{
      calls.push({path,options});
      if (hang) return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('timeout'))));
      if (fail) throw new Error('fixture network failure');
      if (hold && path==='/api/status') return new Promise(resolve=>{release=ok=>resolve({ok,json:async()=>current});});
      if (responses[path]) {
        const data=await responses[path](options);
        return {ok:!data.error,json:async()=>data};
      }
      return {ok:true,json:async()=>path==='/api/status'?current:{}};
    }};
  vm.createContext(context);
  for (const file of ['00-setup-input.js','local-setup.js']) vm.runInContext(fs.readFileSync('web/src/js/'+file,'utf8'),context);
  const settle=()=>new Promise(r=>setImmediate(r));await settle();
  return {elements,calls,timers,settle,setJob(value){current=value;fail=hang=false;},setFailure(){fail=true;},setHang(){hang=true;},
    holdNextStatus(){hold=true;},releaseStatus(ok=true){release(ok);},
    async tick(ms){const entry=[...timers].find(([,v])=>v.ms===ms);assert(entry,`timer ${ms}`);timers.delete(entry[0]);entry[1].fn();await settle();}};
}

const checked = {check_token:'fixture-ticket',result:{
  username:'root',address:'198.51.100.2',ssh_port:22,os:'debian',version:'12'
}};
const submit = {preventDefault(){}};

test('a checked server gets one explicit installation action and one POST',async()=>{
  const h=await harness({state:'idle'},{'/api/check':()=>checked});
  assert.equal(h.elements['ssh-options'].open,false);
  h.elements['ssh-options'].events.invalid();
  assert.equal(h.elements['ssh-options'].open,true);
  const checking=h.elements.connection.onsubmit(submit);
  assert.equal(h.elements['connection-fields'].disabled,true);
  assert.equal(h.elements['method-cvm'].disabled,true);
  await checking;
  assert.equal(h.elements['connection-fields'].disabled,false);
  assert.equal(h.elements.connection.hidden,true);
  assert.equal(h.elements['connection-methods'].hidden,true);
  assert.equal(h.elements.confirmation.hidden,false);
  assert.match(h.elements.target.textContent,/root@198\.51\.100\.2:22/);
  assert.equal(h.elements.connection.elements.password.value,'');
  assert.equal(h.elements.install.disabled,false);
  await Promise.all([h.elements.install.onclick(),h.elements.install.onclick()]);
  assert.deepEqual(h.calls.filter(c=>c.path==='/api/install').map(c=>JSON.parse(c.options.body)),[
    {check_token:'fixture-ticket',confirm:true}
  ]);
  assert.equal(h.elements.confirmation.hidden,true);
  assert.equal(h.elements['progress-title'].textContent,'正在创建节点');
});

test('returning to edit removes the old confirmation and preserves the address',async()=>{
  const h=await harness({state:'idle'},{'/api/check':()=>checked});
  await h.elements.connection.onsubmit(submit);
  h.elements['edit-connection'].onclick();
  assert.equal(h.elements.connection.hidden,false);
  assert.equal(h.elements['connection-methods'].hidden,false);
  assert.equal(h.elements.confirmation.hidden,true);
  assert.equal(h.elements.connection.elements.host.value,'198.51.100.2');
  assert.equal(h.elements.connection.elements.host.focused,true);
  await h.elements.install.onclick();
  assert(h.calls.every(c=>c.path!=='/api/install'));
});

test('the fingerprint screen only continues with an explicit match and never starts installation',async()=>{
  const fingerprint='SHA256:'+'A'.repeat(43);
  const h=await harness({state:'idle'},{'/api/check':options=>JSON.parse(options.body).fingerprint===fingerprint
    ? checked
    : {error:true,code:'HOST_KEY_CONFIRMATION',message:'需要核对指纹',fingerprint}});
  let checking=h.elements.connection.onsubmit(submit);
  await h.settle();
  assert.equal(h.elements.fingerprint.hidden,false);
  assert.equal(h.elements['fingerprint-value'].textContent,fingerprint);
  assert.equal(h.elements.connection.hidden,true);
  h.elements['reject-host'].onclick();
  await checking;
  assert.equal(h.elements.fingerprint.hidden,true);
  assert.equal(h.elements['ssh-credential'].focused,true);
  assert.equal(h.calls.filter(c=>c.path==='/api/check').length,1);
  h.elements['ssh-credential'].value='local-fixture';
  checking=h.elements.connection.onsubmit(submit);
  await h.settle();
  h.elements['trust-host'].onclick();
  await checking;
  assert.equal(h.elements.fingerprint.hidden,true);
  assert.equal(h.elements.confirmation.hidden,false);
  assert.equal(h.calls.filter(c=>c.path==='/api/check').length,3);
  assert.equal(h.calls.some(c=>c.path==='/api/install'),false);
});

test('pasting a multiline key uses the one credential field and sends only the key and its passphrase',async()=>{
  const h=await harness({state:'idle'},{'/api/check':()=>checked});
  const credential=h.elements['ssh-credential'];
  const key='-----BEGIN OPENSSH PRIVATE KEY-----\nkey-fixture\n-----END OPENSSH PRIVATE KEY-----';
  let prevented=false;
  credential.events.paste({clipboardData:{getData:()=>key},preventDefault(){prevented=true;}});
  assert.equal(prevented,true);
  assert.equal(credential.value,'');
  assert.equal(credential.required,false);
  assert.equal(h.elements['ssh-key-status'].textContent,'已粘贴 SSH 私钥');
  const fields=h.elements.connection.elements;
  fields.passphrase.value='passphrase-fixture';
  await h.elements.connection.onsubmit(submit);
  const body=JSON.parse(h.calls.find(c=>c.path==='/api/check').options.body);
  assert.equal(body.password,undefined);
  assert.equal(body.private_key,key);
  assert.equal(body.passphrase,'passphrase-fixture');
  assert.equal(fields.passphrase.value,'');
  assert.equal(credential.required,true);
  assert.equal(h.elements['ssh-key-status'].textContent,'');
});

test('typing a password replaces a pasted key and drops its passphrase',async()=>{
  const h=await harness({state:'idle'},{'/api/check':()=>checked});
  const credential=h.elements['ssh-credential'];
  credential.events.paste({clipboardData:{getData:()=>'-----BEGIN OPENSSH PRIVATE KEY-----\nfixture'},preventDefault(){}});
  h.elements.connection.elements.passphrase.value='discarded-phrase';
  credential.value='fixture-password';
  credential.events.input();
  assert.equal(h.elements['ssh-key-status'].textContent,'');
  credential.value='-----BEGIN OPENSSH PRIVATE KEY-----truncated';
  await h.elements.connection.onsubmit(submit);
  assert.equal(h.calls.some(c=>c.path==='/api/check'),false);
  assert.match(h.elements.status.textContent,/粘贴完整的 SSH 私钥/);
  credential.value='fixture-password';
  await h.elements.connection.onsubmit(submit);
  assert.deepEqual(JSON.parse(h.calls.find(c=>c.path==='/api/check').options.body),{
    host:'198.51.100.2',username:'root',ssh_port:22,password:'fixture-password',
  });
});

test('copying the Mac task brief uses only static text and reveals it for manual copy on failure',async()=>{
  let copied='', blockCopy=false;
  const h=await harness({state:'idle'},{},async text=>{
    if (blockCopy) throw new Error('clipboard disabled');
    copied=text;
  });
  assert.equal(h.elements['ssh-help'].open,false);
  await h.elements['copy-ssh-prompt'].onclick();
  assert.match(copied,/启动安装\.command/);
  assert.match(copied,/本人在本地页面输入/);
  assert.doesNotMatch(copied,/local-fixture/);
  assert.equal(h.elements['ssh-prompt'].hidden,true);
  assert.equal(h.elements['ssh-copy-status'].textContent,'已复制');
  blockCopy=true;
  await h.elements['copy-ssh-prompt'].onclick();
  assert.equal(h.elements['ssh-prompt'].hidden,false);
  assert.match(h.elements['ssh-copy-status'].textContent,/手动/);
});

test('partial CVM results require a selection and retain the CVM context and result list',async()=>{
  const h=await harness({state:'idle'},{
    '/api/tencent/instances':()=>({instances:[{name:'<b>fixture</b>',ip:'8.8.8.8',region:'东京',product:'云服务器 CVM'}],
      incomplete_regions:['云服务器 CVM · ap-singapore']}),
    '/api/check':()=>checked,
  });
  assert.equal(h.elements['connection-methods'].hidden,false);
  assert.equal(h.elements.connection.hidden,false);
  h.elements['method-cvm'].onclick();
  assert.equal(h.elements['method-cvm'].attributes['aria-pressed'],'true');
  assert.equal(h.elements['method-ssh'].attributes['aria-pressed'],'false');
  assert.equal(h.elements.connection.elements.password.value,'');
  assert.equal(h.elements.connection.hidden,true);
  assert.equal(h.elements.tencent.hidden,false);
  h.elements['tencent-secret-id'].value='fixture-id';
  h.elements['tencent-secret-key'].value='fixture-key';
  const lookup=h.elements['tencent-credentials'].onsubmit(submit);
  assert.equal(h.elements['method-ssh'].disabled,false);
  await lookup;
  assert.equal(h.elements['method-ssh'].disabled,false);
  assert.equal(h.elements['tencent-secret-id'].value,'');
  assert.equal(h.elements['tencent-secret-key'].value,'');
  assert.equal(h.elements['tencent-credentials'].hidden,true);
  assert.match(h.elements.status.textContent,/列表可能不完整/);
  assert.equal(h.elements['setup-diagnostics'].hidden,false);
  const choice=h.elements['tencent-instances'].children[0].children[0];
  assert.match(choice.textContent,/<b>fixture<\/b>/);
  choice.onclick();
  assert.equal(h.elements['method-ssh'].attributes['aria-pressed'],'false');
  assert.equal(h.elements['method-cvm'].attributes['aria-pressed'],'true');
  assert.equal(h.elements.tencent.hidden,true);
  assert.equal(h.elements.connection.hidden,false);
  assert.equal(h.elements['selected-instance'].hidden,false);
  assert.equal(h.elements['server-address'].hidden,true);
  assert.equal(h.elements.connection.elements.host.value,'8.8.8.8');
  assert.equal(h.elements.connection.elements.password.focused,true);
  assert.deepEqual(h.calls.filter(c=>c.options.method==='POST').map(c=>c.path),['/api/tencent/instances']);
  assert.deepEqual(JSON.parse(h.calls.find(c=>c.path==='/api/tencent/instances').options.body),{
    secret_id:'fixture-id',secret_key:'fixture-key',product:'cvm'
  });
  h.elements.connection.elements.password.value='new-ssh-password';
  await h.elements.connection.onsubmit(submit);
  const body=JSON.parse(h.calls.find(c=>c.path==='/api/check').options.body);
  assert.deepEqual(body,{host:'8.8.8.8',username:'root',ssh_port:22,password:'new-ssh-password'});
  h.elements['edit-connection'].onclick();
  assert.equal(h.elements['selected-instance'].hidden,false);
  h.elements['change-instance'].onclick();
  assert.equal(h.elements['tencent-results'].hidden,false);
  assert.equal(h.elements['tencent-credentials'].hidden,true);
  assert.equal(h.elements['tencent-instances'].children.length,1);
  h.elements['method-ssh'].onclick();
  assert.equal(h.elements['server-address'].hidden,false);
  assert.equal(h.elements.connection.elements.host.value,'198.51.100.2');
});

test('empty Tencent results leave a working manual SSH path',async()=>{
  const h=await harness({state:'idle'},{'/api/tencent/instances':()=>({instances:[],incomplete_regions:[]})});
  h.elements['method-cvm'].onclick();
  await h.elements['tencent-credentials'].onsubmit(submit);
  assert.match(h.elements.status.textContent,/未找到带公网 IPv4/);
  h.elements['method-ssh'].onclick();
  assert.equal(h.elements.connection.hidden,false);
  assert.equal(h.elements.tencent.hidden,true);
  assert.equal(h.elements.connection.elements.host.value,'198.51.100.2');
});

test('a complete single CVM result opens the credential form without checking or installing',async()=>{
  const h=await harness({state:'idle'},{'/api/tencent/instances':()=>({
    instances:[{name:'fixture',ip:'8.8.8.8',region:'东京'}],incomplete_regions:[]
  })});
  h.elements['method-cvm'].onclick();
  await h.elements['tencent-credentials'].onsubmit(submit);
  assert.equal(h.elements['selected-name'].textContent,'fixture');
  assert.equal(h.elements['server-address'].hidden,true);
  assert.equal(h.elements.connection.hidden,false);
  assert.equal(h.elements['ssh-credential'].focused,true);
  assert(h.calls.every(c=>!['/api/check','/api/install'].includes(c.path)));
});

test('switching to SSH during a cloud lookup aborts the browser request and ignores a late result',async()=>{
  let finish;
  const h=await harness({state:'idle'},{'/api/tencent/instances':()=>new Promise(resolve=>{finish=resolve;})});
  h.elements['method-cvm'].onclick();
  const lookup=h.elements['tencent-credentials'].onsubmit(submit);
  await h.settle();
  h.elements['method-ssh'].onclick();
  assert.equal(h.calls.find(c=>c.path==='/api/tencent/instances').options.signal.aborted,true);
  finish({instances:[{name:'fixture',ip:'8.8.8.8',region:'东京'}],incomplete_regions:[]});
  await lookup;
  assert.equal(h.elements['selected-instance'].hidden,true);
  assert.equal(h.elements.tencent.hidden,true);
  assert.equal(h.elements.connection.elements.host.value,'198.51.100.2');
  assert.equal(h.elements.status.textContent,'');
});

test('connection diagnostics exclude credentials, targets and raw failure text',async()=>{
  const h=await harness({state:'idle'},{'/api/check':()=>({result:{message:'fixture-private-error',root:false}})});
  assert.equal(h.elements['setup-diagnostics'].hidden,true);
  await h.elements.connection.onsubmit(submit);
  assert.equal(h.elements['setup-diagnostics'].hidden,false);
  assert.equal(h.elements['setup-events'].children.length,2);
  const rows=JSON.stringify(h.elements['setup-events'].children);
  assert.match(rows,/服务器条件检查未通过/);
  assert.doesNotMatch(rows,/fixture-private-error|local-fixture|198\.51\.100\.2/);
});

test('reload resumes the same actual stage and elapsed time using GET only',async()=>{
  const a=await harness(),b=await harness();
  for(const h of [a,b]) {
    assert.equal(h.elements['progress-title'].textContent,'正在创建节点');
    assert.equal(h.elements['progress-stage'].textContent,running.stage_label);
    assert.match(h.elements['progress-time'].textContent,/1 分 23 秒/);
    assert.match(h.elements['progress-time'].textContent,/1 分 5 秒/);
    assert.equal(h.elements['progress-stages'].children.length,2);
    assert.equal(h.elements['progress-details'].open,false);
    assert.equal(h.elements.quit.disabled,true);
    assert(h.calls.every(c=>c.path==='/api/status'&&!c.options.method));
    assert(!JSON.stringify(h.elements).includes('fixture-private-log'));
  }
});

test('idle keeps requirements collapsed and shows no install history while still polling',async()=>{
  const h=await harness({state:'idle'});
  assert.equal(h.elements['connection-intro'].hidden,false);
  assert.equal(h.elements.progress.hidden,true);
  assert.equal(h.elements['progress-details'].hidden,true);
  assert.equal(h.elements.status.textContent,'');
  h.setJob(running);
  await h.tick(3000);
  assert.equal(h.elements['connection-intro'].hidden,true);
  assert.equal(h.elements['connection-methods'].hidden,true);
  assert.equal(h.elements['progress-details'].hidden,false);
  assert.equal(h.elements['progress-details'].open,false);
  h.elements['progress-details'].open=true;
  await h.tick(3000);
  assert.equal(h.elements['progress-details'].open,true);
});

test('poll failure preserves evidence, retries read-only and shows the failed stage',async()=>{
  const h=await harness();h.setFailure();await h.tick(3000);
  assert.match(h.elements.status.textContent,/无法获取.*3 秒后重试/);
  assert.equal(h.elements.quit.disabled,true);
  assert.equal(h.elements['progress-stage'].textContent,running.stage_label);
  h.setJob({...running,state:'attention',message:'在安装系统依赖阶段未完成：服务器响应超时。不要重复安装。',
    stages:[{label:running.stage_label,elapsed_seconds:65,state:'attention'}]});
  await h.tick(3000);
  assert.equal(h.elements.quit.disabled,false);
  assert.match(h.elements.status.textContent,/服务器响应超时/);
  assert.equal(h.elements['progress-keep-open'].hidden,true);
  assert.equal(h.elements['progress-details'].open,false);
  assert.equal(h.elements['progress-stages'].children[0].dataset.state,'attention');
  assert(h.calls.every(c=>!c.options.method));
});

test('a stalled status request times out and retries without submitting an install',async()=>{
  const h=await harness();h.setHang();await h.tick(3000);await h.tick(15000);
  assert.match(h.elements.status.textContent,/无法获取本地任务状态/);
  h.setJob(running);await h.tick(3000);
  assert.equal(h.elements['progress-stage'].textContent,running.stage_label);
  assert(h.calls.every(c=>c.path==='/api/status'));
});

test('verified completion and quit clear the delivery and progress',async()=>{
  const h=await harness({...running,state:'done',delivery:{dashboard_url:'https://example.test/',temp_password:'test-initial-only'}});
  assert.equal(h.elements['initial-password'].value,'test-initial-only');
  assert.equal(h.elements.quit.disabled,false);
  assert.equal(h.elements.progress.hidden,true);
  assert.equal(h.elements['progress-details'].hidden,false);
  assert.match(h.elements['progress-summary'].textContent,/总耗时/);
  await h.elements.quit.onclick();
  assert.equal(h.elements['initial-password'].value,'');
  assert.equal(h.elements.delivery.hidden,true);
  assert.equal(h.elements.progress.hidden,true);
  assert.equal(h.elements['progress-details'].hidden,true);
  assert.equal(h.calls.at(-1).path,'/api/quit');
  assert.equal(h.timers.size,0);
});

test('a late in-flight status response cannot restore credentials after quitting',async()=>{
  for(const ok of [true,false]) {
    const h=await harness({...running,state:'done',delivery:{dashboard_url:'https://example.test/',temp_password:'fixture-secret'}});
    h.holdNextStatus();await h.tick(3000);
    await h.elements.quit.onclick();
    h.releaseStatus(ok);await h.settle();
    assert.equal(h.elements['initial-password'].value,'');
    assert.equal(h.elements.delivery.hidden,true);
    assert.equal(h.elements.progress.hidden,true);
    assert.match(h.elements.status.textContent,/本地服务已关闭/);
    assert.equal(h.timers.size,0);
  }
});
