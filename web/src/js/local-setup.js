'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let ticket = '', busy = false, timer = null, stopped = false;
  let readingStatus = false, jobStarted = false;
  const statusUnavailable = '无法获取本地任务状态，页面将在 3 秒后重试。请检查启动窗口，安装可能仍在运行，不要重复安装。';
  const status = text => {
    const element = $('status');
    if (element.textContent !== text) element.textContent = text;
  };
  async function request(path, body) {
    const options = body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {cache:'no-store'};
    const controller = new AbortController();
    options.signal = controller.signal;
    const timeout = setTimeout(() => controller.abort(), path === '/api/check' ? 90000 : 15000);
    try {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) { const error = new Error(data.message || '操作未完成。'); error.data = data; throw error; }
      return data;
    } finally { clearTimeout(timeout); }
  }
  function duration(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return value >= 60 ? `${Math.floor(value / 60)} 分 ${value % 60} 秒` : `${value} 秒`;
  }
  function renderProgress(job) {
    const running = job.state === 'running';
    const done = job.state === 'done';
    $('progress').hidden = done;
    $('progress-keep-open').hidden = !running;
    const title = running ? job.stage_label || '正在安装' : '安装需要检查';
    if ($('progress-title').textContent !== title) $('progress-title').textContent = title;
    $('progress-time').textContent = job.stage
      ? `总耗时 ${duration(job.elapsed_seconds)} · ${running ? '当前阶段' : '失败阶段'} ${duration(job.stage_elapsed_seconds)}`
      : '';
    $('progress-summary').textContent = done ? `查看安装记录 · 总耗时 ${duration(job.elapsed_seconds)}` : '查看安装记录';
    const rows = (job.stages || []).map(step => {
      const row = document.createElement('li');
      row.dataset.state = step.state;
      const state = step.state === 'done' ? '已完成' : (step.state === 'attention' ? '未完成' : '进行中');
      row.textContent = `${step.label} · ${state} · ${duration(step.elapsed_seconds)}`;
      return row;
    });
    $('progress-details').hidden = rows.length === 0;
    $('progress-stages').replaceChildren(...rows);
  }
  function clearSecrets() {
    for (const name of ['password', 'private_key', 'passphrase']) $('connection').elements[name].value = '';
  }
  function invalidate() {
    ticket = '';
    $('confirmation').hidden = true;
    $('install').disabled = true;
  }
  $('connection').addEventListener('input', invalidate);
  $('ssh-options').addEventListener('invalid', () => { $('ssh-options').open = true; }, true);
  $('auth').onchange = () => {
    clearSecrets();
    invalidate();
    const useKey = $('auth').value === 'private_key';
    const fields = $('connection').elements;
    $('password-label').hidden = useKey;
    $('key-label').hidden = $('phrase-label').hidden = !useKey;
    fields.password.disabled = fields.private_key.required = useKey;
    fields.password.required = fields.private_key.disabled = fields.passphrase.disabled = !useKey;
    (useKey ? fields.private_key : fields.password).focus();
  };
  $('connection').onsubmit = async event => {
    event.preventDefault();
    if (busy || jobStarted || stopped) return;
    const values = Object.fromEntries(new FormData($('connection')));
    values.ssh_port = Number(values.ssh_port);
    busy = true;
    invalidate();
    $('connection-fields').disabled = true;
    $('quit').disabled = true;
    clearSecrets();
    status('正在检查连接和服务器条件…');
    try {
      let data;
      try { data = await request('/api/check', values); }
      catch (error) {
        const fingerprint = error.data && error.data.fingerprint;
        if (!error.data || error.data.code !== 'HOST_KEY_CONFIRMATION' || !/^SHA256:[A-Za-z0-9+/]{43}$/.test(fingerprint || '')) throw error;
        if (jobStarted || stopped) return;
        if (!window.confirm('请通过云控制台等可信渠道核对 SSH 指纹。\n\n' + fingerprint + '\n\n确认一致后继续？')) { status('请核对服务器指纹后重新检查连接。'); return; }
        values.fingerprint = fingerprint; data = await request('/api/check', values);
      }
      if (jobStarted || stopped) return;
      if (!data.check_token) { status(data.result.message + (data.result.root === false ? '\n当前账号没有 root 权限，请使用 root 账号。' : '')); return; }
      ticket = data.check_token;
      $('target').textContent = `${data.result.username}@${data.result.address}:${data.result.ssh_port} · ${data.result.os} ${data.result.version}`;
      $('connection-intro').hidden = $('connection').hidden = true;
      $('confirmation').hidden = $('install').disabled = false;
      status('');
      $('confirmation-title').focus();
    } catch (error) {
      if (!jobStarted && !stopped) status(error.message);
    } finally {
      values.password = values.private_key = values.passphrase = '';
      busy = false;
      $('connection-fields').disabled = false;
      if (!jobStarted && !stopped) $('quit').disabled = false;
    }
  };
  $('edit-connection').onclick = () => {
    if (busy || jobStarted || stopped) return;
    invalidate();
    $('connection-intro').hidden = $('connection').hidden = false;
    status('');
    $('connection').elements.host.focus();
  };
  $('install').onclick = async () => {
    if (busy || !ticket || jobStarted || stopped) return;
    busy = true;
    const checkToken = ticket;
    ticket = '';
    $('install').disabled = $('edit-connection').disabled = $('quit').disabled = true;
    status('正在提交安装请求…');
    try {
      await request('/api/install', {check_token:checkToken, confirm:true});
      if (!jobStarted && !stopped) renderJob({state:'running'});
    } catch (error) {
      if (!jobStarted && !stopped) {
        status(error.data
          ? error.message + '\n请查看任务状态，或修改连接后重新检查。'
          : '暂时无法确认安装请求是否送达。页面会继续读取任务状态，请勿重复提交。');
      }
    } finally {
      busy = false;
      if (!jobStarted && !stopped) $('edit-connection').disabled = $('quit').disabled = false;
      poll();
    }
  };
  function renderJob(job) {
    jobStarted = true;
    $('connection-intro').hidden = $('connection').hidden = $('confirmation').hidden = true;
    renderProgress(job);
    $('quit').disabled = job.state === 'running' || busy;
    if (job.state === 'done') {
      const url = new URL(job.delivery.dashboard_url);
      if (url.protocol !== 'https:') throw new Error('交付地址无效');
      $('dashboard').href = url.href;
      $('initial-password').value = job.delivery.temp_password;
      $('delivery').hidden = false;
    }
    status(job.state === 'attention' ? job.message : '');
  }
  async function poll() {
    if (stopped || readingStatus) return;
    readingStatus = true;
    if (timer) clearTimeout(timer);
    try {
      const job = await request('/api/status');
      if (stopped) return;
      if (job.state === 'idle') {
        if ($('status').textContent === statusUnavailable) status('');
        return;
      }
      renderJob(job);
    } catch (_) {
      if (!stopped && !busy) status(statusUnavailable);
    } finally {
      readingStatus = false;
      if (!stopped) timer = setTimeout(poll, 3000);
    }
  }
  $('reveal').onclick = () => { $('initial-password').type = $('initial-password').type === 'password' ? 'text' : 'password'; };
  $('quit').onclick = async () => {
    try {
      await request('/api/quit', {});
      stopped = true;
      clearTimeout(timer);
      clearSecrets();
      $('initial-password').value = '';
      for (const id of ['connection-intro', 'connection', 'confirmation', 'delivery', 'progress', 'progress-details', 'quit']) {
        $(id).hidden = true;
      }
      status('本地服务已关闭，可以关闭此页面和启动窗口。');
    } catch (error) { status(error.message); }
  };
  $('startup-fallback').hidden = true;
  $('connection').hidden = $('quit').hidden = false;
  poll();
})();
