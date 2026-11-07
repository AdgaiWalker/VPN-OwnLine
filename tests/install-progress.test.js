const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function run(response) {
  const html=fs.readFileSync('web/index.html','utf8');
  const a=html.indexOf('  function initInstallProgress()'),b=html.indexOf('  function detectClient()',a);
  const e={};for(const id of ['install-task','install-task-title','install-task-message','install-task-refresh','install-task-dismiss'])e[id]={style:{},textContent:'',disabled:false};
  const calls=[];const storage={sb_job:'a'.repeat(12)};
  const c={document:{getElementById:id=>e[id]},localStorage:{getItem:k=>storage[k],removeItem:k=>delete storage[k]},fetch:async (url,opts)=>{calls.push({url,opts});return response},setTimeout:()=>1,clearTimeout:()=>{},AbortController,encodeURIComponent};
  vm.createContext(c);vm.runInContext(html.slice(a,b),c);c.initInstallProgress();
  await new Promise(resolve=>setImmediate(resolve));
  return {e,calls,storage};
}

test('running task resumes read-only progress without exposing node data',async()=>{
  const {e,calls}=await run({ok:true,json:async()=>({ok:true,state:'running',step:2,log:['fixture-secret']})});
  assert.equal(e['install-task-title'].textContent,'正在安装节点');
  assert.match(e['install-task-message'].textContent,/正在下载并安装/);
  assert.equal(e['install-task-dismiss'].disabled,true);
  assert.equal(calls.length,1);assert.equal(calls[0].opts.method,undefined);
  assert(!JSON.stringify(e).includes('fixture-secret'));
});

test('missing task is unknown and never auto-restarted',async()=>{
  const {e,calls,storage}=await run({ok:false});
  assert.equal(e['install-task-title'].textContent,'安装状态未知');
  assert.match(e['install-task-message'].textContent,/不会停止后台任务/);
  assert.equal(calls.length,1);assert(storage.sb_job);
});

test('completed task does not claim a connection without verification',async()=>{
  const {e}=await run({ok:true,json:async()=>({ok:true,state:'done',health:'unknown'})});
  assert.match(e['install-task-message'].textContent,/尚未确认连通/);
  assert.equal(e['install-task-dismiss'].disabled,false);
});
