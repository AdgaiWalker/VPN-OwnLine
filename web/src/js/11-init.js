  // 11. Initialization & refresh
  function init() {
    applyLanguage();
    fetchUserInfo();
    setupInputHighlights();
    initSceneRouter();
    initCloudParallelSwitch();
    setupAiPrompt();
    initInstallCopy();
    initOtherConnection();
    initInstallProgress();
    detectClient();
    initTencentPanel();
    initLogFilters();
    initQuotaSettings();
    initBackup();

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
