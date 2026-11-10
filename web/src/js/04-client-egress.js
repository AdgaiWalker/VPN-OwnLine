  function detectClient() {
    var ua = navigator.userAgent || "", os = "other";
    var isWx = /MicroMessenger|QQ\//i.test(ua);
    var wxTip = document.getElementById("wx-tip");
    if (wxTip) wxTip.style.display = isWx ? "block" : "none";
    if (/iPhone|iPod|iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) os = "ios";
    else if (/Android/.test(ua)) os = "android";
    else if (/Macintosh|Mac OS X/.test(ua)) os = "mac";
    else if (/Windows/.test(ua)) os = "win";
    else if (/Linux/.test(ua)) os = "linux";
    var apple = os === "ios" || os === "mac";
    var flSupported = os === "mac" || os === "android" || os === "win" || os === "linux";
    var sr = document.getElementById("btn-sr"), cl = document.getElementById("btn-clash");
    sr.style.display = apple ? "" : "none";
    sr.className = apple ? "btn action-btn apple-client-row primary" : "btn action-btn apple-client-row";
    cl.className = apple ? "btn action-btn apple-client-row" : "btn action-btn apple-client-row primary";
    document.getElementById("btn-flclash").style.display = flSupported ? "" : "none";
    document.getElementById("apple-store-help").style.display = apple ? "" : "none";
    document.getElementById("download-sr").style.display = apple ? "" : "none";
    document.getElementById("download-flclash").style.display = flSupported ? "" : "none";
    var dc = document.getElementById("download-clash");
    dc.style.display = flSupported ? "" : "none";
    dc.href = os === "android" ? "https://github.com/MetaCubeX/ClashMetaForAndroid/releases" : "https://github.com/clash-verge-rev/clash-verge-rev/releases";
    document.getElementById("clash-ios-help").style.display = os === "ios" ? "" : "none";
    var itemSr = document.getElementById("client-item-sr");
    if (itemSr) itemSr.style.display = apple ? "" : "none";
    var itemFl = document.getElementById("client-item-flclash");
    if (itemFl) itemFl.style.display = flSupported ? "" : "none";
    var devBadge = document.getElementById("client-device-badge");
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var devName = os === "ios" ? "iPhone / iPad" : (os === "mac" ? "macOS" : (os === "android" ? "Android" : (os === "win" ? "Windows" : (os === "linux" ? "Linux" : (zh ? "当前设备" : "This Device")))));
    if (devBadge) {
      devBadge.textContent = devName;
    }
    var hubTitle = document.getElementById("hub-device-title");
    if (hubTitle) {
      hubTitle.textContent = zh ? ("在 " + devName + " 上连接") : ("Connect on " + devName);
    }
  }

  function openClientHub() {
    detectClient();
    ["sr", "clash", "flclash"].forEach(function (k) {
      var el = document.getElementById("assist-" + k);
      if (el) el.style.display = "none";
    });
    var dlg = document.getElementById("client-hub-dialog");
    if (dlg) {
      if (typeof dlg.showModal === "function") {
        if (!dlg.open) dlg.showModal();
      } else {
        dlg.setAttribute("open", "");
      }
    }
  }
  window.ownlineOpenClientHub = openClientHub;

  function toggleAppleId() {
    var box = document.getElementById("apple-store-help");
    if (!box) return;
    box.style.display = (box.style.display === "none") ? "block" : "none";
  }
  window.ownlineToggleAppleId = toggleAppleId;

  function copyText(value) {
    var note = document.getElementById("copy-note");
    if (!value) return;
    function showManualCopy(message) {
      var code = document.getElementById("suburl");
      code.textContent = value;
      code.onclick = function () { copyText(value); };
      document.getElementById("download-help").open = true;
      note.style.display = "block";
      note.textContent = message;
    }
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      showManualCopy("无法自动复制，请在下方手动选择复制。");
      return;
    }
    navigator.clipboard.writeText(value).then(function () {
      note.style.display = "block"; note.textContent = "已复制";
    }).catch(function () {
      showManualCopy("复制失败，请在下方手动选择复制。");
    });
  }

  function wireLinks(importAvailable) {
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var sub = BASE_SUB_URL, code = document.getElementById("suburl");
    if (!sub) { code.textContent = zh ? "订阅链接暂不可用" : "Subscription link unavailable"; return; }
    code.textContent = sub;
    var title = encodeURIComponent("Evergreen-OwnLine");
    var sr = document.getElementById("btn-sr"), cl = document.getElementById("btn-clash"), fl = document.getElementById("btn-flclash");
    try { sr.href = "shadowrocket://add/sub://" + btoa(sub) + "?title=" + title; }
    catch (e) { sr.removeAttribute("href"); }
    cl.href = "clash://install-config?url=" + encodeURIComponent(sub + "/clash") + "&name=" + title;
    fl.href = "flclash://install-config?url=" + encodeURIComponent(sub + "/clash");

    function activateAssist(clientKey) {
      ["sr", "clash", "flclash"].forEach(function (k) {
        var el = document.getElementById("assist-" + k);
        if (el) el.style.display = (k === clientKey) ? "block" : "none";
      });
    }

    [
      {btn: sr, key: "sr"},
      {btn: cl, key: "clash"},
      {btn: fl, key: "flclash"}
    ].forEach(function (pair) {
      var button = pair.btn;
      if (!button) return;
      button.setAttribute("aria-disabled", String(!importAvailable));
      button.onclick = function (event) {
        if (!importAvailable) { event.preventDefault(); return; }
        var note = document.getElementById("import-note");
        if (note) note.textContent = zh
          ? "正在尝试打开客户端。若未自动拉起，请先下载客户端或手动复制链接导入。"
          : "Attempting to launch client. If it doesn't open automatically, please download the client or copy the link manually.";
        activateAssist(pair.key);
      };
    });
    document.getElementById("import-note").textContent = importAvailable ? "" : (zh ? "当前暂无已确认可用的在线节点，您可以先复制订阅链接备用。" : "No verified online nodes available yet. You may copy the subscription link for future use.");
    var btnCopySub = document.getElementById("btn-copy-sub");
    if (btnCopySub) btnCopySub.onclick = function () { copyText(sub); };
    var btnCopySubManual = document.getElementById("btn-copy-sub-manual");
    if (btnCopySubManual) btnCopySubManual.onclick = function () { copyText(sub); };
    var btnCopyClash = document.getElementById("btn-copy-clash");
    if (btnCopyClash) btnCopyClash.onclick = function () { copyText(sub + "/clash"); };
    code.onclick = function () { copyText(sub); };
  }

