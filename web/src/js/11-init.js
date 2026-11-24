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

  // 11. Initialization & refresh
  function init() {
    initDialogLightDismiss();
    applyLanguage();
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
