  function initDialogLightDismiss() {
    if (typeof HTMLDialogElement === "undefined" || ("closedBy" in HTMLDialogElement.prototype)) return;
    var outside = function (e, dlg) {
      var r = dlg.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    document.querySelectorAll('dialog[closedby="any"]').forEach(function (dlg) {
      var pressedOutside = false;
      dlg.addEventListener("pointerdown", function (e) { pressedOutside = outside(e, dlg); });
      dlg.addEventListener("pointerup", function (e) { if (pressedOutside && outside(e, dlg)) dlg.close(); });
    });
  }

  function installClientErrorBuffer() {
    if (typeof window === "undefined") return;
    window.__ownlineClientErrors = window.__ownlineClientErrors || [];
    function pushErr(kind, msg) {
      var text = typeof redactLog === "function" ? redactLog(msg) : String(msg || "");
      window.__ownlineClientErrors.push({ ts: new Date().toISOString(), kind: kind, msg: text.slice(0, 240) });
      if (window.__ownlineClientErrors.length > 20) window.__ownlineClientErrors.shift();
    }
    window.addEventListener("error", function (e) {
      pushErr("error", (e && (e.message || (e.error && e.error.message))) || "Script error");
    });
    window.addEventListener("unhandledrejection", function (e) {
      var r = e && e.reason;
      pushErr("rejection", (r && r.message) ? r.message : String(r || "Unhandled rejection"));
    });
  }

  function initNonSecretDrafts() {
    if (typeof sessionStorage === "undefined") return;
    [["other-ip", "ownline_draft_other_ip"], ["custom-domain-input", "ownline_draft_domain"]].forEach(function (pair) {
      var el = document.getElementById(pair[0]);
      if (!el) return;
      try {
        var saved = sessionStorage.getItem(pair[1]);
        if (saved && !el.value) el.value = saved;
        el.addEventListener("input", function () {
          try { sessionStorage.setItem(pair[1], el.value); } catch (_) {}
        });
      } catch (_) {}
    });
  }

  // 11. Initialization & refresh
  function init() {
    installClientErrorBuffer();
    initDialogLightDismiss();
    applyLanguage();
    initNonSecretDrafts();
    fetchUserInfo();
    setupInputHighlights();
    initSceneRouter();
    initCloudParallelSwitch();
    initReverseJoin();
    setupAiPrompt();
    initInstallCopy();
    initOtherConnection();
    initInstallProgress();
    detectClient();
    initTencentPanel();
    initLogFilters();
    initQuotaSettings();
    initBackup();
    if (typeof window.initUpdater === "function") window.initUpdater();
    if (typeof window.initLocalPing === "function") window.initLocalPing();

    refreshState();
    fetchLogs();

    var btnRefreshAll = document.getElementById("btn-refresh-all");
    if (btnRefreshAll) {
      btnRefreshAll.onclick = function () {
        refreshState();
        fetchLogs();
      };
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
