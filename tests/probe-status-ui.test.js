const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function paint(nodes,status){
  const elements={};
  const source=fs.readFileSync('web/src/js/07-nodes.js','utf8');
  const context={NODES:nodes,STATUS:status,isZh:()=>true,esc:String,
    document:{getElementById(id){return elements[id]??=( {textContent:'',className:''} );}}};
  vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('  function deriveNodeState')),context);
  context.paintStatus();return elements;
}

test('missing snapshot ends in explicit unverified state instead of endless checking',()=>{
  const e=paint([{name:'test',health:'unknown'}],{});
  assert.equal(e['status-text'].textContent,'1 个节点待验证');
  assert.equal(e.s0.textContent,'未验证');
});

test('snapshot failure does not advertise historical healthy nodes as operational',()=>{
  const e=paint([{name:'test',health:'ok'}],{_unavailable:true});
  assert.match(e['status-text'].textContent,/探活数据不可用/);
  assert.equal(e.d0.className,'dot');
  assert.equal(e.s0.textContent,'未验证');
});

test('partial verification never says all nodes are operational',()=>{
  const e=paint([{name:'one'},{name:'two'}],{one:{ok:true,ms:18}});
  assert.equal(e['status-text'].textContent,'1 个节点待验证');
});

test('successful reload paints actual snapshot and manual recovery replaces the failure state',()=>{
  const nodes=[{name:'test'}],snapshot={test:{ok:true,ms:35}};
  assert.equal(paint(nodes,snapshot)['status-text'].textContent,'运行正常');
  assert.equal(paint(nodes,snapshot)['status-text'].textContent,'运行正常');
  assert.match(paint(nodes,snapshot).s0.innerHTML,/35ms/);
});
