'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let ticket = '', busy = false, timer = null, stopped = false;
  const status = text => { $('status').textContent = text; };
  async function request(path, body) {
    const options = body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {cache:'no-store'};
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.message || '操作未完成。'); error.data = data; throw error; }
    return data;
  }
  function clearSecrets() { for (const name of ['password','private_key','passphrase']) $('connection').elements[name].value = ''; }
  function invalidate() { ticket = ''; $('confirmation').hidden = true; $('consent').checked = false; $('install').disabled = true; }
  $('connection').addEventListener('input', invalidate);
  $('auth').onchange = () => { clearSecrets(); invalidate(); $('password-label').hidden = $('auth').value !== 'password'; $('key-label').hidden = $('phrase-label').hidden = $('auth').value !== 'private_key'; };
  $('connection').onsubmit = async event => {
    event.preventDefault(); if (busy) return; busy = true; invalidate(); $('check').disabled = true;
    const values = Object.fromEntries(new FormData($('connection'))); values.ssh_port = Number(values.ssh_port);
    if ($('auth').value === 'password') { values.private_key = ''; values.passphrase = ''; } else values.password = '';
    clearSecrets(); status('正在只读检查连接和服务器条件…');
    try {
      let data;
      try { data = await request('/api/check', values); }
      catch (error) {
        const fingerprint = error.data && error.data.fingerprint;
        if (!error.data || error.data.code !== 'HOST_KEY_CONFIRMATION' || !/^SHA256:[A-Za-z0-9+/]{43}$/.test(fingerprint || '')) throw error;
        if (!window.confirm('请通过云控制台等可信渠道核对 SSH 指纹：\n\n' + fingerprint + '\n\n确认一致后继续？')) { status('未确认服务器指纹，已停止。'); return; }
        values.fingerprint = fingerprint; data = await request('/api/check', values);
      }
      if (!data.check_token) { status(data.result.message + (data.result.root === false ? '\n当前账号没有 root 权限，请使用 root 账号。' : '')); return; }
      ticket = data.check_token; $('target').textContent = `${data.result.username}@${data.result.address}:${data.result.ssh_port} · ${data.result.os} ${data.result.version}`;
      $('confirmation').hidden = false; status('连接检查通过；尚未安装。');
    } catch (error) { status(error.message); }
    finally { values.password = values.private_key = values.passphrase = ''; busy = false; $('check').disabled = false; }
  };
  $('consent').onchange = () => { $('install').disabled = !$('consent').checked || !ticket; };
  $('install').onclick = async () => {
    if (busy || !ticket || !$('consent').checked) return;
    busy = true; $('install').disabled = true; $('check').disabled = true;
    try { await request('/api/install', {check_token:ticket,confirm:true}); ticket = ''; }
    catch (error) { status(error.message + '\n请刷新状态确认原任务，勿重复提交。'); }
    finally { busy = false; poll(); }
  };
  async function poll() {
    if (stopped) return;
    if (timer) clearTimeout(timer);
    try {
      const job = await request('/api/status');
      if (job.state === 'running') { $('connection').hidden = $('confirmation').hidden = true; $('quit').disabled = true; status('正在安装和验收，可能需要数分钟。请保持 Mac 和启动窗口运行。'); }
      if (job.state === 'done') { $('connection').hidden = $('confirmation').hidden = true; $('quit').disabled = false; $('delivery').hidden = false; const url = new URL(job.delivery.dashboard_url); if (url.protocol !== 'https:') throw new Error('交付地址无效'); $('dashboard').href = url.href; $('initial-password').value = job.delivery.temp_password; status('安装与服务端验收通过。'); }
      if (job.state === 'attention') { $('connection').hidden = $('confirmation').hidden = true; $('quit').disabled = false; status(job.message); }
    } catch (_) { status('无法获取本地任务状态。请检查启动窗口，安装可能仍在运行，不要重复安装。'); }
    if (!stopped) timer = setTimeout(poll, 3000);
  }
  $('reveal').onclick = () => { $('initial-password').type = $('initial-password').type === 'password' ? 'text' : 'password'; };
  $('quit').onclick = async () => { try { await request('/api/quit', {}); stopped = true; clearTimeout(timer); clearSecrets(); $('initial-password').value = ''; $('delivery').hidden = true; status('本地服务已关闭，可以关闭此页面和启动窗口。'); } catch (error) { status(error.message); } };
  poll();
})();
