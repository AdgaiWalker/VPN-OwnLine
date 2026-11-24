(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const SLOTS = ['ssh', 'tencent_api', 'webshare_isp', 'panel_auth'];
  const TITLES = {
    ssh: '输入服务器 SSH 凭据',
    tencent_api: '输入腾讯云只读 API 密钥',
    webshare_isp: '输入静态住宅代理凭据',
    panel_auth: '输入管理面板登录凭据',
  };
  const sshCred = $('vault-ssh-credential');
  let reqId = '';
  let activeSlot = '';
  let sshPrivateKey = '';
  let busy = false;

  const setStatus = (text, kind = '') => {
    const el = $('vault-status');
    el.textContent = text;
    el.dataset.kind = kind;
  };

  function setSSHKey(key) {
    if (sshPrivateKey && key !== sshPrivateKey) $('vault-ssh-passphrase').value = '';
    sshPrivateKey = key;
    sshCred.required = !key;
    $('vault-ssh-key-status').textContent = key ? '已粘贴 SSH 私钥' : '';
  }

  function clearAllSecrets() {
    for (const id of [
      'vault-ssh-credential',
      'vault-ssh-passphrase',
      'vault-tencent-id',
      'vault-tencent-key',
      'vault-isp-proxy',
      'vault-panel-password',
    ]) {
      const el = $(id);
      if (el) el.value = '';
    }
    if (typeof resetSecretToggles === 'function') resetSecretToggles(document);
    setSSHKey('');
  }

  function formatSummary(slot, summary) {
    if (!summary) return '';
    if (slot === 'ssh') return `${summary.username || 'root'}@${summary.host || ''}:${summary.ssh_port || 22}`;
    if (slot === 'tencent_api') return `SecretId ${summary.secret_id_masked || '****'}`;
    if (slot === 'webshare_isp') return `${summary.protocol || 'socks'}://${summary.host || ''}:${summary.port || ''}`;
    if (slot === 'panel_auth') return `${summary.username || 'admin'}${summary.dashboard_url ? ' · ' + summary.dashboard_url : ''}`;
    return '';
  }

  function showDone(slot, handle, summary) {
    clearAllSecrets();
    $('vault-card').hidden = true;
    $('vault-handle-out').textContent = handle || '';
    $('vault-summary-out').textContent = formatSummary(slot, summary);
    $('vault-done').hidden = false;
    $('vault-done-title').focus();
    setStatus('');
  }

  function showSlot(slot) {
    for (const name of SLOTS) {
      const fs = $(`slot-${name}`);
      const active = name === slot;
      fs.hidden = !active;
      fs.disabled = !active;
    }
  }

  async function api(path, body) {
    const options = body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : { cache: 'no-store' };
    const resp = await fetch(path, options);
    const data = await resp.json();
    if (!resp.ok) {
      const err = new Error(data.message || '操作未完成。');
      err.data = data;
      throw err;
    }
    return data;
  }

  bindSSHKeyPaste(sshCred, key => setSSHKey(key));
  $('vault-ssh-options').addEventListener('invalid', () => { $('vault-ssh-options').open = true; }, true);

  $('vault-form').onsubmit = async event => {
    event.preventDefault();
    if (busy || !reqId || !activeSlot) return;
    let payload = {};
    if (activeSlot === 'ssh') {
      if (!sshPrivateKey && hasSSHPrivateKeyHeader(sshCred.value)) {
        setStatus('请在凭据栏粘贴完整的 SSH 私钥。', 'error');
        sshCred.focus();
        return;
      }
      payload = {
        host: $('vault-ssh-host').value.trim(),
        username: $('vault-ssh-user').value.trim() || 'root',
        ssh_port: Number($('vault-ssh-port').value || 22),
      };
      if (sshPrivateKey) {
        payload.private_key = sshPrivateKey;
        if ($('vault-ssh-passphrase').value) payload.passphrase = $('vault-ssh-passphrase').value;
      } else {
        payload.password = sshCred.value;
      }
    } else if (activeSlot === 'tencent_api') {
      payload = {
        secret_id: $('vault-tencent-id').value.trim(),
        secret_key: $('vault-tencent-key').value.trim(),
      };
    } else if (activeSlot === 'webshare_isp') {
      payload = { proxy_url: $('vault-isp-proxy').value.trim() };
    } else if (activeSlot === 'panel_auth') {
      payload = {
        dashboard_url: $('vault-panel-url').value.trim(),
        username: $('vault-panel-user').value.trim() || 'admin',
        password: $('vault-panel-password').value,
      };
    }

    busy = true;
    $('vault-submit').disabled = $('vault-cancel').disabled = true;
    clearAllSecrets();
    setStatus('正在存入本机内存…');
    try {
      const data = await api('/api/vault/submit', { request_id: reqId, payload });
      showDone(activeSlot, data.handle, data.summary);
    } catch (err) {
      setStatus(err.message || '提交未成功，请核对输入。', 'error');
    } finally {
      payload = {};
      clearAllSecrets();
      busy = false;
      $('vault-submit').disabled = $('vault-cancel').disabled = false;
    }
  };

  $('vault-cancel').onclick = async () => {
    if (busy || !reqId) return;
    busy = true;
    $('vault-submit').disabled = $('vault-cancel').disabled = true;
    clearAllSecrets();
    try {
      await api('/api/vault/cancel', { request_id: reqId });
      $('vault-card').hidden = true;
      setStatus('已取消输入，可关闭此页面。');
    } catch (err) {
      setStatus(err.message || '取消失败。', 'error');
    } finally {
      busy = false;
      $('vault-submit').disabled = $('vault-cancel').disabled = false;
    }
  };

  async function init() {
    $('vault-fallback').hidden = true;
    const params = new URLSearchParams(typeof location !== 'undefined' ? location.search : '');
    reqId = params.get('req') || '';
    if (!reqId) {
      setStatus('缺少凭据请求编号，请回到刚才的界面重新发起授权页。', 'error');
      return;
    }
    try {
      const info = await api(`/api/vault/status?id=${encodeURIComponent(reqId)}`);
      if (info.state === 'submitted') {
        showDone(info.slot, info.handle, info.summary);
        return;
      }
      if (info.state !== 'pending') {
        setStatus(info.state === 'expired' ? '凭据输入请求已超时，请回到刚才的界面重新发起。' : '该凭据输入请求已取消。', 'error');
        return;
      }
      activeSlot = info.slot;
      $('vault-title').textContent = TITLES[activeSlot] || '输入本机凭据';
      const ctxParts = [info.label, info.target_hint].filter(Boolean);
      if (ctxParts.length) {
        $('vault-context').textContent = ctxParts.join(' · ');
        $('vault-context').hidden = false;
      }
      if (activeSlot === 'ssh' && info.target_hint && !$('vault-ssh-host').value) {
        $('vault-ssh-host').value = info.target_hint;
      }
      showSlot(activeSlot);
      $('vault-card').hidden = false;
      const firstFocus = activeSlot === 'ssh'
        ? ($('vault-ssh-host').value ? sshCred : $('vault-ssh-host'))
        : $(`slot-${activeSlot}`).querySelector('input');
      if (firstFocus) firstFocus.focus();
    } catch (err) {
      setStatus(err.message || '无法读取凭据请求状态。', 'error');
    }
  }

  if (typeof initSecretToggles === 'function') initSecretToggles(document);
  if (typeof initAccessibleValidation === 'function') initAccessibleValidation(document);
  init();
})();
