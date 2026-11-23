(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const sshForm = $('connection');
  const sshCredential = $('ssh-credential');
  let ticket = '', busy = false, timer = null, stopped = false;
  let readingStatus = false, jobStarted = false;
  let privateKey = '';
  let cvmActive = false, selectedInstance = null, manualHost = '', cloudLookup = null;
  let answerFingerprint = null;
  const diagnostics = [];
  let lastDiagnostic = '';
  const statusUnavailable = '无法获取本地任务状态，页面将在 3 秒后重试。请检查启动窗口，安装可能仍在运行，不要重复安装。';
  const status = (text, kind = '') => {
    const element = $('status');
    if (element.textContent !== text) element.textContent = text;
    element.dataset.kind = kind;
  };
  function setStep(activeStep) {
    if (!$('step-rail')) return;
    $('step-rail').hidden = activeStep <= 0;
    for (let i = 1; i <= 3; i += 1) {
      const node = $(`step-${i}`);
      if (!node) continue;
      node.dataset.state = activeStep > i ? 'done' : (activeStep === i ? 'active' : 'pending');
    }
  }
  function record(label, attention = false) {
    if (label !== lastDiagnostic) {
      const row = document.createElement('li');
      row.textContent = `${new Date().toLocaleTimeString('zh-CN', {hour12:false})} · ${label}`;
      diagnostics.unshift(row);
      if (diagnostics.length > 12) diagnostics.pop();
      $('setup-events').replaceChildren(...diagnostics);
      lastDiagnostic = label;
    }
    if (attention) $('setup-diagnostics').hidden = false;
  }
  async function request(path, body, controller = new AbortController()) {
    const options = body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {cache:'no-store'};
    options.signal = controller.signal;
    const timeout = setTimeout(() => controller.abort(),
      path === '/api/check' || path === '/api/tencent/instances' ? 90000 : 15000);
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
    const title = running ? '正在创建节点' : '创建未完成';
    if ($('progress-title').textContent !== title) $('progress-title').textContent = title;
    const stage = job.stage_label || '';
    if ($('progress-stage').textContent !== stage) $('progress-stage').textContent = stage;
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
    sshCredential.value = sshForm.elements.passphrase.value = '';
    setSSHKey('');
  }
  function invalidate() {
    ticket = '';
    $('confirmation').hidden = true;
    $('install').disabled = true;
  }
  sshForm.addEventListener('input', invalidate);
  $('ssh-options').addEventListener('invalid', () => { $('ssh-options').open = true; }, true);
  function setSSHKey(key) {
    if (privateKey && key !== privateKey) sshForm.elements.passphrase.value = '';
    privateKey = key;
    sshCredential.required = !key;
    $('ssh-key-status').textContent = key ? '已粘贴 SSH 私钥' : '';
  }
  bindSSHKeyPaste(sshCredential, key => {
    setSSHKey(key);
    invalidate();
  });
  $('copy-ssh-prompt').onclick = async () => {
    const prompt = $('ssh-prompt');
    const copied = await copySetupText(prompt.textContent);
    $('ssh-copy-status').textContent = copied ? '已复制' : '请手动选择任务书文字复制。';
    if (!copied && $('ssh-help-details')) $('ssh-help-details').open = true;
  };
  function clearTencentKeys() {
    $('tencent-secret-id').value = $('tencent-secret-key').value = '';
  }
  function resetTencentResults() {
    $('tencent-credentials').hidden = false;
    $('tencent-results').hidden = $('tencent-retry').hidden = true;
    $('tencent-instances').replaceChildren();
  }
  function leaveTencent() {
    if (cloudLookup) cloudLookup.abort();
    cloudLookup = null;
    selectedInstance = null;
    $('tencent-fields').disabled = false;
    clearTencentKeys();
    resetTencentResults();
    $('tencent').hidden = true;
  }
  function showConnectionMethod(cvm) {
    cvmActive = cvm;
    const selected = cvm && Boolean(selectedInstance);
    $('method-ssh').setAttribute('aria-pressed', String(!cvm));
    $('method-cvm').setAttribute('aria-pressed', String(cvm));
    sshForm.hidden = cvm && !selected;
    $('tencent').hidden = !cvm || selected;
    $('server-address').hidden = selected;
    $('selected-instance').hidden = !selected;
  }
  function lockConnectionMethods(locked) {
    $('method-ssh').disabled = $('method-cvm').disabled = locked;
  }
  $('method-cvm').onclick = () => {
    if (busy || jobStarted || stopped || cvmActive) return;
    manualHost = sshForm.elements.host.value;
    clearSecrets();
    invalidate();
    showConnectionMethod(true);
    status('');
  };
  $('method-ssh').onclick = () => {
    if (busy || jobStarted || stopped || !cvmActive) return;
    clearSecrets();
    leaveTencent();
    sshForm.elements.host.value = manualHost;
    showConnectionMethod(false);
    status('');
  };
  $('change-instance').onclick = () => {
    if (busy || jobStarted || stopped || !selectedInstance) return;
    selectedInstance = null;
    clearSecrets();
    invalidate();
    showConnectionMethod(true);
    status('');
    $('tencent-results-title').focus();
  };
  $('tencent-retry').onclick = () => {
    resetTencentResults();
    status('');
    $('tencent-secret-id').focus();
  };
  $('tencent-credentials').onsubmit = async event => {
    event.preventDefault();
    if (busy || cloudLookup || jobStarted || stopped || !cvmActive) return;
    const credentials = Object.fromEntries(new FormData($('tencent-credentials')));
    const controller = new AbortController();
    cloudLookup = controller;
    clearTencentKeys();
    $('tencent-fields').disabled = true;
    status('正在读取腾讯云实例…');
    record('开始读取腾讯云实例');
    try {
      const data = await request('/api/tencent/instances', credentials, controller);
      if (cloudLookup !== controller || jobStarted || stopped) return;
      const instances = data.instances || [];
      const incomplete = data.incomplete_regions && data.incomplete_regions.length > 0;
      if (!instances.length) {
        record(incomplete ? '部分腾讯云实例未读取' : '没有可连接的腾讯云实例', true);
        status(incomplete
          ? '部分实例未能读取。请检查腾讯云只读权限，或改用 SSH 直连。'
          : '未找到带公网 IPv4 的实例。可检查实例网络，或改用 SSH 直连。', 'error');
        return;
      }
      const rows = instances.map(instance => {
        const row = document.createElement('li');
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = instance.product
          ? `${instance.name}（${instance.product}）· ${instance.ip} · ${instance.region}`
          : `${instance.name} · ${instance.ip} · ${instance.region}`;
        button.onclick = () => selectTencentInstance(instance);
        row.appendChild(button);
        return row;
      });
      $('tencent-instances').replaceChildren(...rows);
      $('tencent-credentials').hidden = true;
      $('tencent-results').hidden = $('tencent-retry').hidden = false;
      record(incomplete ? '部分腾讯云实例未读取' : '腾讯云实例读取完成', incomplete);
      if (!incomplete && instances.length === 1) {
        selectTencentInstance(instances[0]);
      } else {
        status(incomplete ? '列表可能不完整。可选择已读取的实例，或检查权限后重新读取。' : '', incomplete ? 'error' : '');
        $('tencent-results-title').focus();
      }
    } catch (error) {
      if (cloudLookup === controller && !jobStarted && !stopped) {
        record('腾讯云实例读取失败', true);
        status(error.data ? error.message : '读取实例超时或连接中断。可重试，或改用 SSH 直连。', 'error');
      }
    } finally {
      credentials.secret_id = credentials.secret_key = '';
      if (cloudLookup === controller) {
        cloudLookup = null;
        $('tencent-fields').disabled = false;
      }
    }
  };
  function selectTencentInstance(instance) {
    if (!instance.ip || !cvmActive || busy || jobStarted || stopped) return;
    clearSecrets();
    selectedInstance = instance;
    $('selected-name').textContent = instance.name;
    $('selected-address').textContent = `${instance.ip} · ${instance.region}`;
    sshForm.elements.host.value = instance.ip;
    showConnectionMethod(true);
    invalidate();
    status('');
    sshCredential.focus();
  }
  function showConnectionStep(show) {
    if (show) setStep(1);
    $('connection-intro').hidden = $('connection-methods').hidden = $('ssh-help').hidden = !show;
    if (show) showConnectionMethod(cvmActive);
    else sshForm.hidden = $('tencent').hidden = true;
  }
  function confirmFingerprint(fingerprint) {
    showConnectionStep(false);
    $('fingerprint-value').textContent = fingerprint;
    $('fingerprint').hidden = false;
    $('fingerprint-title').focus();
    status('');
    return new Promise(resolve => {
      answerFingerprint = accepted => {
        answerFingerprint = null;
        $('fingerprint').hidden = true;
        $('fingerprint-value').textContent = '';
        resolve(accepted);
      };
    });
  }
  $('trust-host').onclick = () => answerFingerprint?.(true);
  $('reject-host').onclick = () => answerFingerprint?.(false);
  sshForm.onsubmit = async event => {
    event.preventDefault();
    if (busy || jobStarted || stopped) return;
    if (!privateKey && hasSSHPrivateKeyHeader(sshCredential.value)) {
      status('请在凭据栏粘贴完整的 SSH 私钥。', 'error');
      sshCredential.focus();
      return;
    }
    const values = Object.fromEntries(new FormData(sshForm));
    if (privateKey) {
      values.private_key = privateKey;
      delete values.password;
    } else {
      delete values.passphrase;
    }
    values.ssh_port = Number(values.ssh_port);
    busy = true;
    invalidate();
    lockConnectionMethods(true);
    $('connection-fields').disabled = true;
    $('quit').disabled = true;
    clearSecrets();
    status('正在检查连接和服务器条件…');
    record('开始测试 SSH 连接');
    let focusCredential = false;
    try {
      let data;
      try { data = await request('/api/check', values); }
      catch (error) {
        const fingerprint = error.data && error.data.fingerprint;
        if (!error.data || error.data.code !== 'HOST_KEY_CONFIRMATION' || !/^SHA256:[A-Za-z0-9+/]{43}$/.test(fingerprint || '')) throw error;
        if (jobStarted || stopped) return;
        const accepted = await confirmFingerprint(fingerprint);
        if (jobStarted || stopped) return;
        showConnectionStep(true);
        focusCredential = true;
        if (!accepted) {
          record('取消 SSH 指纹确认', true);
          status('请核对服务器指纹后重新测试连接。', 'error');
          return;
        }
        status('正在检查连接和服务器条件…');
        values.fingerprint = fingerprint; data = await request('/api/check', values);
      }
      if (jobStarted || stopped) return;
      if (!data.check_token) {
        record('服务器条件检查未通过', true);
        status(data.result.message + (data.result.root === false ? '\n当前账号没有 root 权限，请使用 root 账号。' : ''), 'error');
        return;
      }
      record('SSH 连接检查通过');
      ticket = data.check_token;
      $('target').textContent = `${data.result.username}@${data.result.address}:${data.result.ssh_port} · ${data.result.os} ${data.result.version}`;
      showConnectionStep(false);
      setStep(2);
      $('setup-diagnostics').hidden = true;
      $('confirmation').hidden = $('install').disabled = false;
      status('');
      $('confirmation-title').focus();
    } catch (error) {
      if (!jobStarted && !stopped) {
        record('SSH 连接检查失败', true);
        status(error.data ? error.message : '连接检查超时或中断。请检查服务器地址和 SSH 端口后重试。', 'error');
      }
    } finally {
      values.password = values.private_key = values.passphrase = '';
      busy = false;
      lockConnectionMethods(false);
      $('connection-fields').disabled = false;
      if (!jobStarted && !stopped) $('quit').disabled = false;
      if (focusCredential && !$('connection').hidden) sshCredential.focus();
    }
  };
  $('edit-connection').onclick = () => {
    if (busy || jobStarted || stopped) return;
    invalidate();
    showConnectionStep(true);
    status('');
    (selectedInstance ? sshCredential : sshForm.elements.host).focus();
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
        record('创建请求未确认', true);
        status(error.data
          ? error.message + '\n请查看任务状态，或修改连接后重新检查。'
          : '暂时无法确认安装请求是否送达。页面会继续读取任务状态，请勿重复提交。', 'error');
      }
    } finally {
      busy = false;
      if (!jobStarted && !stopped) $('edit-connection').disabled = $('quit').disabled = false;
      poll();
    }
  };
  function renderJob(job) {
    const firstRender = !jobStarted;
    jobStarted = true;
    answerFingerprint?.(false);
    if (cvmActive && firstRender) leaveTencent();
    clearSecrets();
    showConnectionStep(false);
    setStep(job.state === 'done' ? 4 : 3);
    $('confirmation').hidden = true;
    $('setup-diagnostics').hidden = true;
    renderProgress(job);
    $('quit').disabled = job.state === 'running' || busy;
    if (job.state === 'done') {
      const url = new URL(job.delivery.dashboard_url);
      if (url.protocol !== 'https:') throw new Error('交付地址无效');
      $('dashboard').href = url.href;
      $('initial-password').value = job.delivery.temp_password;
      if ($('delivery').hidden) {
        $('delivery').hidden = false;
        $('delivery-title').focus();
      }
    } else if (firstRender) {
      $('progress-title').focus();
    }
    status(job.state === 'attention' ? job.message : '', job.state === 'attention' ? 'error' : '');
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
      if (!stopped && !busy && !cloudLookup) {
        record('任务状态读取异常', true);
        status(statusUnavailable, 'error');
      }
    } finally {
      readingStatus = false;
      if (!stopped) timer = setTimeout(poll, 3000);
    }
  }
  $('reveal').onclick = () => {
    const field = $('initial-password');
    const show = field.type === 'password';
    field.type = show ? 'text' : 'password';
    $('reveal').textContent = show ? '隐藏密码' : '显示密码';
    $('reveal').setAttribute('aria-pressed', String(show));
  };
  if ($('check-update')) {
    $('check-update').onclick = async () => {
      const btn = $('check-update');
      const note = $('update-status');
      btn.disabled = true;
      note.hidden = false;
      note.textContent = '正在检查更新…';
      try {
        const info = await request('/api/update');
        if (!info.ok) {
          note.textContent = info.error || '当前处于离线或受限网络，无法检查更新。';
        } else if (info.has_update) {
          note.textContent = `发现新版本 ${info.latest_version}（当前 ${info.current_version}），请到发布页或更新仓库。`;
        } else {
          note.textContent = `当前已是最新版本 ${info.current_version || ''}`.trim();
        }
      } catch (err) {
        note.textContent = (err && err.message) || '无法检查更新。';
      } finally {
        btn.disabled = false;
      }
    };
  }
  $('quit').onclick = async () => {
    try {
      await request('/api/quit', {});
      stopped = true;
      clearTimeout(timer);
      answerFingerprint?.(false);
      clearSecrets();
      leaveTencent();
      $('initial-password').value = '';
      diagnostics.length = 0;
      $('setup-events').replaceChildren();
      for (const id of ['step-rail', 'connection-intro', 'connection-methods', 'connection', 'confirmation', 'delivery', 'progress', 'progress-details', 'setup-diagnostics', 'ssh-help', 'quit', 'check-update', 'update-status']) {
        if ($(id)) $(id).hidden = true;
      }
      status('本地服务已关闭，可以关闭此页面和启动窗口。');
    } catch (error) { status(error.message); }
  };
  $('startup-fallback').hidden = true;
  showConnectionStep(true);
  $('quit').hidden = false;
  if ($('check-update')) $('check-update').hidden = false;
  poll();
})();
