  // Backups read node configuration from management backend and encrypt in-browser before download.
  function backupPassword(confirmPassword) {
    return new Promise(function (resolve) {
      var dialog = document.getElementById("backup-dialog"), form = document.getElementById("backup-password-form");
      var first = document.getElementById("backup-password"), second = document.getElementById("backup-confirm");
      var error = document.getElementById("backup-error"), cancel = document.getElementById("backup-cancel");
      document.getElementById("backup-dialog-title").textContent = confirmPassword ? "设置备份口令" : "输入备份口令";
      document.getElementById("backup-confirm-wrap").style.display = confirmPassword ? "" : "none";
      second.required = confirmPassword; error.textContent = ""; first.value = ""; second.value = "";
      function done(value) { first.value = ""; second.value = ""; if (dialog.open) dialog.close(); resolve(value); }
      form.onsubmit = function (event) {
        event.preventDefault();
        if (first.value.length < 10 || (confirmPassword && first.value !== second.value)) {
          error.textContent = "口令长度至少 10 位，且两次输入必须一致。"; return;
        }
        done(first.value);
      };
      cancel.onclick = function () { done(null); };
      dialog.oncancel = function (event) { event.preventDefault(); done(null); };
      if (typeof dialog.showModal !== "function") { resolve(null); return; }
      dialog.showModal(); first.focus();
    });
  }

  function encodeBytes(bytes) {
    var text = ""; for (var i = 0; i < bytes.length; i += 8192) text += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
    return btoa(text);
  }
  function decodeBytes(value) {
    if (typeof value !== "string" || value.length > 2000000) throw new Error("Invalid backup");
    var str = atob(value), bytes = new Uint8Array(str.length);
    for (var i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i);
    return bytes;
  }
  async function backupKey(password, salt) {
    var encoder = new TextEncoder();
    var material = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({name:"PBKDF2", hash:"SHA-256", salt:salt, iterations:310000}, material, {name:"AES-GCM", length:256}, false, ["encrypt", "decrypt"]);
  }
  async function encryptBackup(data, password) {
    var salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
    var key = await backupKey(password, salt);
    var cipher = await crypto.subtle.encrypt({name:"AES-GCM", iv:iv}, key, new TextEncoder().encode(JSON.stringify(data)));
    return {format:"ownline-node-backup", version:1, kdf:"PBKDF2-SHA256", iterations:310000, cipher:"AES-256-GCM", salt:encodeBytes(salt), iv:encodeBytes(iv), ciphertext:encodeBytes(new Uint8Array(cipher))};
  }
  async function decryptBackup(data, password) {
    if (!data || data.format !== "ownline-node-backup" || data.version !== 1 || data.kdf !== "PBKDF2-SHA256" || data.iterations !== 310000 || data.cipher !== "AES-256-GCM") throw new Error("Unsupported backup format");
    var salt = decodeBytes(data.salt), iv = decodeBytes(data.iv), cipher = decodeBytes(data.ciphertext);
    if (salt.length !== 16 || iv.length !== 12 || cipher.length < 16) throw new Error("Invalid backup file");
    var key = await backupKey(password, salt);
    var plain = await crypto.subtle.decrypt({name:"AES-GCM", iv:iv}, key, cipher);
    return JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(plain));
  }
  function initBackup() {
    var note = document.getElementById("backup-note"), file = document.getElementById("backup-file");
    document.getElementById("backup-export").onclick = async function () {
      if (!window.isSecureContext || !window.crypto || !crypto.subtle) { note.textContent = "请通过受保护的 HTTPS 连接访问，以便在本地创建加密备份。"; return; }
      var password = await backupPassword(true);
      if (!password) return;
      try {
        var source = await jsonRequest("/api/backup");
        if (!source.ok || !Array.isArray(source.nodes)) throw new Error("invalid backup response");
        var encrypted = await encryptBackup(source, password);
        var url = URL.createObjectURL(new Blob([JSON.stringify(encrypted)], {type:"application/json"}));
        var a = document.createElement("a"); a.href = url; a.download = "ownline-node-backup.json";
        document.body.appendChild(a); a.click(); a.remove(); setTimeout(function(){URL.revokeObjectURL(url);}, 60000);
        note.textContent = "已生成加密备份文件，请妥善保存备份文件与口令。";
      } catch (_) { note.textContent = "导出备份失败，请检查网络连接后重试。"; }
      finally { password = ""; }
    };
    document.getElementById("backup-restore").onclick = function () { file.click(); };
    file.onchange = async function () {
      var selected = file.files[0]; file.value = "";
      if (!selected) return;
      if (!window.isSecureContext || !window.crypto || !crypto.subtle) { note.textContent = "请通过受保护的 HTTPS 连接访问，以便解密恢复备份。"; return; }
      if (selected.size > 2000000) { note.textContent = "备份文件超出大小上限。"; return; }
      var data;
      try { data = JSON.parse(await selected.text()); } catch (_) { note.textContent = "请选择有效的加密备份 JSON 文件。"; return; }
      var password = await backupPassword(false);
      if (!password) return;
      try { data = await decryptBackup(data, password); }
      catch (_) { note.textContent = "解密失败：备份口令错误或文件已损坏。"; return; }
      finally { password = ""; }
      if (!data || !Array.isArray(data.nodes) || !data.nodes.length) { note.textContent = "该文件不是有效的节点备份数据。"; return; }
      var date = typeof data.exported_at === "string" ? data.exported_at : "未知";
      var message = "备份时间：" + date + "\n包含节点：" + data.nodes.length + " 个\n恢复将覆盖当前节点列表与订阅令牌，不会恢复远端主机软件、管理员密码或流量阈值设置，客户端可能需要重新拉取订阅。";
      if (!window.confirm(message + "\n\n确认立即恢复？")) return;
      try {
        var response = await jsonRequest("/api/restore", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
        if (!response.ok) throw new Error("restore failed");
        note.textContent = "节点配置已恢复，请核对各服务器连通状态与流量保护设置。";
        refreshState(); fetchLogs();
      } catch (_) { note.textContent = "恢复未完成，部分变更可能已写入，请检查服务器状态。"; }
    };
  }

