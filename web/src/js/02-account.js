  function updateUserInfo(user) {
    if (!user) return;
    STATE.currentUsername = user;
    var initial = (user.charAt(0) || 'U').toUpperCase();
    var elTopName = document.getElementById('topbar-user-name');
    var elTopAvatar = document.getElementById('topbar-user-avatar');
    var elModalUser = document.getElementById('settings-display-username');
    var elModalAvatar = document.getElementById('account-modal-avatar');
    var elNewUser = document.getElementById('settings-username');
    var zh = isZh();

    if (elTopName) elTopName.textContent = user;
    if (elTopAvatar) elTopAvatar.textContent = initial;
    if (elModalUser) elModalUser.textContent = user;
    if (elModalAvatar) elModalAvatar.textContent = initial;
    if (elNewUser) elNewUser.placeholder = zh ? ('保持当前用户名 (' + user + ')') : ('Keep current (' + user + ')');
  }

  function fetchUserInfo() {
    fetch('/api/user', { cache: 'no-store' })
      .then(function(r) { return r.json(); })
      .then(function(res) {
        if (res && res.username) {
          updateUserInfo(res.username);
        }
      })
      .catch(function() {});
  }
  window.fetchUserInfo = fetchUserInfo;

  function openSettingsDialog() {
    var dlg = document.getElementById('settings-dialog');
    if (!dlg) return;
    var zh = isZh();
    var optEn = document.getElementById('opt-lang-en'), optZh = document.getElementById('opt-lang-zh');
    if (optEn) optEn.checked = !zh;
    if (optZh) optZh.checked = zh;
    if (typeof dlg.showModal === 'function') {
      dlg.showModal();
    } else {
      dlg.setAttribute('open', '');
    }
  }
  window.openSettingsDialog = openSettingsDialog;

  function openAccountDialog() {
    var dlg = document.getElementById('account-dialog');
    if (!dlg) return;
    var zh = isZh();
    var cur = document.getElementById('settings-curr-pass'),
        p1 = document.getElementById('settings-new-pass'),
        p2 = document.getElementById('settings-confirm-pass'),
        u = document.getElementById('settings-username');
    if (cur) cur.value = '';
    if (p1) p1.value = '';
    if (p2) p2.value = '';
    if (u) {
      u.value = '';
      u.setAttribute('readonly', 'readonly');
      u.placeholder = zh ? (STATE.currentUsername ? ('保持当前用户名 (' + STATE.currentUsername + ')') : '如不修改请留空') : (STATE.currentUsername ? ('Keep current (' + STATE.currentUsername + ')') : 'Leave empty to keep current');
    }
    var st = document.getElementById('settings-status');
    if (st) { st.textContent = ''; st.style.color = ''; }
    var strWrap = document.getElementById('pwd-strength-wrap');
    if (strWrap) strWrap.style.display = 'none';
    var matchText = document.getElementById('pwd-match-text');
    if (matchText) matchText.style.display = 'none';
    var formCard = document.getElementById('settings-cred-form');
    if (formCard) formCard.style.display = '';
    var succCard = document.getElementById('account-success-card');
    if (succCard) succCard.style.display = 'none';
    var btnEl = document.getElementById('settings-btn-save');
    if (btnEl) btnEl.disabled = false;
    var userDetails = document.getElementById('account-user-details');
    if (userDetails) userDetails.removeAttribute('open');

    // Anti-autofill clearing pass
    setTimeout(function() {
      if (cur && !cur.matches(':focus')) cur.value = '';
      if (p1 && !p1.matches(':focus')) p1.value = '';
      if (p2 && !p2.matches(':focus')) p2.value = '';
      if (u && !u.matches(':focus')) u.value = '';
    }, 60);

    fetchUserInfo();

    if (typeof dlg.showModal === 'function') {
      dlg.showModal();
    } else {
      dlg.setAttribute('open', '');
    }
  }
  window.openAccountDialog = openAccountDialog;

  function togglePasswordVisibility(id, btn) {
    var input = document.getElementById(id);
    if (!input) return;
    var isPass = input.type === 'password';
    input.type = isPass ? 'text' : 'password';
    if (btn) {
      var openIco = btn.querySelector('.eye-open');
      var closedIco = btn.querySelector('.eye-closed');
      if (openIco) openIco.style.display = isPass ? 'none' : '';
      if (closedIco) closedIco.style.display = isPass ? '' : 'none';
    }
  }
  window.togglePasswordVisibility = togglePasswordVisibility;

  function updatePasswordStrength(val) {
    var wrap = document.getElementById('pwd-strength-wrap');
    if (!wrap) return;
    if (!val) {
      wrap.style.display = 'none';
      return;
    }
    wrap.style.display = '';
    var zh = isZh();
    var score = 0;
    if (val.length >= 12) score++;
    if (val.length >= 16) score++;
    if (/[a-z]/.test(val) && /[A-Z]/.test(val)) score++;
    if (/\d/.test(val)) score++;
    if (/[^a-zA-Z0-9]/.test(val)) score++;

    var level = 1;
    if (score <= 1) level = 1;
    else if (score === 2) level = 2;
    else if (score <= 4) level = 3;
    else level = 4;

    var colors = ['var(--red)', 'var(--amber)', '#3b82f6', 'var(--green)'];
    var labelsZh = ['密码强度：弱', '密码强度：一般', '密码强度：良好', '密码强度：极佳'];
    var labelsEn = ['Strength: Weak', 'Strength: Fair', 'Strength: Good', 'Strength: Strong'];
    var color = colors[level - 1];

    for (var i = 1; i <= 4; i++) {
      var seg = document.getElementById('pwd-seg-' + i);
      if (seg) seg.style.backgroundColor = (i <= level) ? color : 'var(--line)';
    }

    var txt = document.getElementById('pwd-strength-text');
    if (txt) {
      txt.textContent = zh ? labelsZh[level - 1] : labelsEn[level - 1];
      txt.style.color = color;
    }
    window.checkPasswordMatch();
  }
  window.updatePasswordStrength = updatePasswordStrength;

  function checkPasswordMatch() {
    var p1El = document.getElementById('settings-new-pass');
    var p2El = document.getElementById('settings-confirm-pass');
    var matchEl = document.getElementById('pwd-match-text');
    if (!p1El || !p2El || !matchEl) return;
    var p1 = p1El.value;
    var p2 = p2El.value;
    if (!p2) {
      matchEl.style.display = 'none';
      return;
    }
    matchEl.style.display = '';
    var zh = isZh();
    if (p1 === p2) {
      matchEl.style.color = 'var(--green)';
      matchEl.textContent = zh ? '✓ 两次输入的密码一致' : '✓ Passwords match';
    } else {
      matchEl.style.color = 'var(--red)';
      matchEl.textContent = zh ? '✕ 两次输入的密码不一致' : '✕ Passwords do not match';
    }
  }
  window.checkPasswordMatch = checkPasswordMatch;

  window.ownlineSaveCredentials = async function(event) {
    if (event && event.preventDefault) event.preventDefault();
    var zh = isZh();
    var curEl = document.getElementById('settings-curr-pass');
    var userEl = document.getElementById('settings-username');
    var newEl = document.getElementById('settings-new-pass');
    var confEl = document.getElementById('settings-confirm-pass');
    var stEl = document.getElementById('settings-status');
    var btnEl = document.getElementById('settings-btn-save');

    var cur = curEl ? curEl.value : '';
    var user = userEl ? userEl.value.trim() : '';
    var p1 = newEl ? newEl.value : '';
    var p2 = confEl ? confEl.value : '';
    var currentUsername = STATE.currentUsername || 'admin';

    if (!cur) {
      if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '请输入当前密码' : 'Please enter current password'; }
      return;
    }

    var isChangingUser = !!user && user !== currentUsername;
    var isChangingPass = !!p1;

    if (!isChangingUser && !isChangingPass) {
      if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '未做任何修改（如需修改请提供新密码或新用户名）' : 'No changes detected. Please provide a new username or new password.'; }
      return;
    }

    if (isChangingUser) {
      if (!/^[A-Za-z0-9_.-]{1,64}$/.test(user)) {
        if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '用户名仅支持字母、数字、点、减号或下划线（1-64位）' : 'Username only supports letters, numbers, dot, hyphen, underscore (1-64 chars)'; }
        return;
      }
    }

    if (isChangingPass) {
      if (p1 !== p2) {
        if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '两次输入的新密码不一致' : 'New passwords do not match'; }
        return;
      }
      if (p1.length < 12) {
        if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '新密码长度至少需要 12 个字符' : 'New password must be at least 12 characters'; }
        return;
      }
      if (p1 === cur && !isChangingUser) {
        if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '新密码不能与原密码相同' : 'New password cannot be identical to current password'; }
        return;
      }
    }

    if (btnEl) btnEl.disabled = true;
    if (stEl) { stEl.style.color = 'var(--ink-muted)'; stEl.textContent = zh ? '正在保存更改…' : 'Saving changes…'; }

    try {
      var payload = { current: cur };
      if (isChangingUser) payload.username = user;
      if (isChangingPass) { payload.new = p1; payload.confirm = p2; }
      var res = await fetch('/api/password/change', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        cache: 'no-store'
      });
      var data = await res.json();
      if (!res.ok || !data.ok) {
        if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = data.error || (zh ? '保存失败，请检查输入' : 'Failed to update credentials'); }
        return;
      }

      var updatedUser = data.username || (isChangingUser ? user : currentUsername);
      updateUserInfo(updatedUser);

      // Show Apple-style post-save transition card
      var formCard = document.getElementById('settings-cred-form');
      var succCard = document.getElementById('account-success-card');
      var succUser = document.getElementById('account-success-user');
      if (succUser) succUser.textContent = updatedUser;
      if (formCard) formCard.style.display = 'none';
      if (succCard) succCard.style.display = '';

      setTimeout(function() {
        window.location.reload();
      }, 2200);
    } catch (err) {
      if (stEl) { stEl.style.color = 'var(--red)'; stEl.textContent = zh ? '网络错误或无法确认结果，请尝试使用新凭据登录' : 'Error updating credentials. Please try logging in with new credentials.'; }
    } finally {
      if (btnEl) btnEl.disabled = false;
    }
  };

  var STATE = {
    cloudMode: "other",
    otherAuthMode: "password",
    tcServers: [],
    tcPickedIndex: -1,
    csrfToken: "",
    token: null,
    logLevel: "ALL",
    allLogs: [],
    logStatus: "loading"
  };

  var NODES = [];
  var STATUS = {};
  var BASE_SUB_URL = "";
  // Private key remains in memory only, never in local/session storage or logs.
  var otherPrivateKey = "";
  var otherCheckController = null;
  var pendingNodeInstall = null;

