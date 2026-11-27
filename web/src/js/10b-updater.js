(function () {
  var _latestUpdateData = null;
  var _isUpgrading = false;

  function setElementText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setElementDisplay(id, display) {
    var el = document.getElementById(id);
    if (el) el.style.display = display;
  }

  function allowUpgradeRetry() {
    _isUpgrading = false;
    setElementDisplay("update-action-box", "block");
    var btn = document.getElementById("btn-check-update");
    if (btn) btn.disabled = false;
  }

  function updateVersionBadges(version) {
    if (!version) return;
    setElementText("current-version-tag", version);
    setElementText("footer-version-tag", version);
  }

  function ownlineCheckUpdate(isManual) {
    var btn = document.getElementById("btn-check-update");
    var btnText = document.getElementById("btn-check-update-text");
    var zh = isZh();

    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = t("btn_checking");

    var url = "/api/system/check_update" + (isManual ? "?force=1" : "");
    fetch(url, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (btn) btn.disabled = false;
        if (btnText) btnText.textContent = t("btn_check_update");

        if (!data || !data.ok) {
          if (isManual) {
            setElementText("update-status-title", zh ? "检查更新失败" : "Check Failed");
            setElementText("update-status-desc", (data && data.error) || (zh ? "网络超时" : "Network timeout"));
          }
          return;
        }

        _latestUpdateData = data;
        updateVersionBadges(data.current_version);

        if (data.has_update) {
          // Show blue dot on header settings gear
          setElementDisplay("settings-update-dot", "inline-block");
          setElementText("update-status-title", (zh ? "发现新版本 " : "Update Available: ") + data.latest_version);
          setElementText("update-status-desc", zh ? "点击下方查看更新详情" : "Click below to review and upgrade");

          // Show action box
          setElementDisplay("update-action-box", "block");
          setElementText("update-target-version", data.latest_version);
          var changelogEl = document.getElementById("update-changelog");
          if (changelogEl) {
            changelogEl.textContent = data.changelog || (zh ? "包含性能优化与稳健性改进。" : "Contains bug fixes and performance improvements.");
          }
        } else {
          setElementDisplay("settings-update-dot", "none");
          setElementText("update-status-title", t("update_status_latest"));
          setElementText("update-status-desc", "");
          setElementDisplay("update-action-box", "none");
        }
      })
      .catch(function (err) {
        if (btn) btn.disabled = false;
        if (btnText) btnText.textContent = t("btn_check_update");
        if (isManual) {
          setElementText("update-status-title", zh ? "检查更新失败" : "Check Failed");
          setElementText("update-status-desc", err.message || (zh ? "网络超时" : "Network timeout"));
        }
      });
  }

  async function ownlinePerformUpgrade() {
    if (_isUpgrading) return;
    var target = (_latestUpdateData && _latestUpdateData.latest_version) || "latest";
    var zh = isZh();
    var confirmMsg = (t("confirm_upgrade_desc") || "").replace("{version}", target);

    var confirmed = false;
    if (typeof dialog === "function") {
      confirmed = await dialog({ title: t("confirm_upgrade_title"), message: confirmMsg, confirmText: t("btn_upgrade_now"), danger: true });
    } else if (typeof window !== "undefined" && typeof window.confirm === "function") {
      confirmed = window.confirm(confirmMsg);
    } else {
      confirmed = true;
    }
    if (!confirmed) {
      return;
    }

    _isUpgrading = true;
    setElementDisplay("update-action-box", "none");
    setElementDisplay("update-progress-box", "block");
    var btnCheck = document.getElementById("btn-check-update");
    if (btnCheck) btnCheck.disabled = true;

    fetch("/api/system/upgrade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_version: target })
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (res) {
        if (!res || !res.ok) {
          allowUpgradeRetry();
          setElementDisplay("update-progress-box", "none");
          setElementDisplay("update-action-box", "block");
          if (btnCheck) btnCheck.disabled = false;
          setElementText("update-status-title", zh ? "启动升级失败" : "Upgrade Failed to Start");
          setElementText("update-status-desc", (res && res.error) || (zh ? "请稍后重试" : "Please retry later"));
          return;
        }

        // Service is restarting in background. Begin polling for health check.
        if (!res.job_id) {
          allowUpgradeRetry();
          setElementText("update-progress-title", zh ? "无法确认升级状态" : "Upgrade status unavailable");
          return;
        }
        pollForRecovery(0, res.job_id);
      })
      .catch(function () {
        // Without a job ID the outcome cannot be determined.
        allowUpgradeRetry();
        setElementText("update-progress-title", zh ? "无法确认升级状态" : "Upgrade status unavailable");
      });
  }

  function pollForRecovery(attempt, jobId) {
    var zh = isZh();
    if (attempt > 320) {
      allowUpgradeRetry();
      setElementText("update-progress-title", zh ? "升级耗时较长" : "Taking longer than usual");
      setElementText("update-progress-desc", zh ? "请手动刷新页面确认服务是否恢复。" : "Please refresh the page to check service status.");
      return;
    }
    if (attempt >= 10) {
      var elapsed = Math.round(attempt * 1.5);
      setElementText("update-progress-desc", zh ? ("服务热重启中（已等待 " + elapsed + " 秒），也可手动刷新确认。") : ("Restarting service (" + elapsed + "s elapsed); you may also refresh manually."));
    }

    setTimeout(function () {
      fetch("/api/system/upgrade-status?id=" + encodeURIComponent(jobId), { cache: "no-store" })
        .then(function (r) {
          if (!r.ok) throw new Error("not ready");
          return r.json();
        })
        .then(function (data) {
          if (data && data.ok && data.status === "succeeded") {
            setElementText("update-progress-title", zh ? "升级完成！" : "Upgrade Complete!");
            setElementText("update-progress-desc", zh ? "服务已就绪，正在刷新界面..." : "Service reloaded. Refreshing page…");
            setTimeout(function () {
              if (typeof window !== "undefined" && window.location && window.location.reload) {
                window.location.reload();
              }
            }, 1200);
          } else if (data && data.ok && data.status === "failed") {
            allowUpgradeRetry();
            setElementText("update-progress-title", zh ? "升级失败" : "Upgrade failed");
            setElementText("update-progress-desc", zh ? "请检查服务器状态后重试。" : "Check the server and retry.");
          } else {
            pollForRecovery(attempt + 1, jobId);
          }
        })
        .catch(function () {
          pollForRecovery(attempt + 1, jobId);
        });
    }, 1500);
  }

  function ownlineChangeDomain(event) {
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    var input = document.getElementById("custom-domain-input");
    var skipEl = document.getElementById("custom-domain-skip-dns");
    var btn = document.getElementById("btn-save-domain");
    var statusEl = document.getElementById("custom-domain-status");
    var zh = (typeof isZh === "function") ? isZh() : true;
    var domain = input ? String(input.value || "").trim().toLowerCase() : "";
    if (!domain) {
      if (statusEl) {
        if (statusEl.style) statusEl.style.color = "var(--bad, #dc2626)";
        statusEl.textContent = zh ? "请输入域名（例如 vpn.example.com）。" : "Please enter a domain.";
      }
      return;
    }
    if (btn) btn.disabled = true;
    if (statusEl) {
      if (statusEl.style) statusEl.style.color = "";
      statusEl.textContent = zh ? "正在校验解析并切换管理域名..." : "Validating DNS & binding domain...";
    }
    fetch("/api/domain/change", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain: domain, skip_dns_check: !!(skipEl && skipEl.checked) })
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res || !res.ok) {
          if (statusEl) {
            if (statusEl.style) statusEl.style.color = "var(--bad, #dc2626)";
            statusEl.textContent = (res && res.error) || (zh ? "域名绑定未完成。" : "Failed to bind domain.");
          }
          return;
        }
        setElementText("current-domain-tag", res.domain);
        if (statusEl) {
          if (statusEl.style) statusEl.style.color = "var(--ok, #16a34a)";
          statusEl.textContent = zh ? "已切换至新地址：" : "Switched to: ";
          if (res.dashboard_url && /^https:\/\//.test(res.dashboard_url)) {
            var a = document.createElement("a");
            a.href = res.dashboard_url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = res.dashboard_url;
            statusEl.appendChild(a);
          }
        }
      })
      .catch(function () {
        if (statusEl) {
          if (statusEl.style) statusEl.style.color = "var(--bad, #dc2626)";
          statusEl.textContent = zh ? "域名切换未完成或连接已断开，请尝试打开新域名访问。" : "Request interrupted; check your new domain URL.";
        }
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  function initUpdater() {
    window.ownlineCheckUpdate = ownlineCheckUpdate;
    window.ownlinePerformUpgrade = ownlinePerformUpgrade;
    window.ownlineUpdateVersionBadges = updateVersionBadges;
    window.ownlineChangeDomain = ownlineChangeDomain;

    // Quiet background update check (deferred when tab is hidden)
    function scheduleCheck() {
      setTimeout(function () {
        ownlineCheckUpdate(false);
      }, 2500);
    }
    if (typeof document !== "undefined" && document.visibilityState === "hidden" && typeof document.addEventListener === "function") {
      var onVis = function () {
        if (document.visibilityState === "visible") {
          document.removeEventListener("visibilitychange", onVis);
          scheduleCheck();
        }
      };
      document.addEventListener("visibilitychange", onVis);
    } else {
      scheduleCheck();
    }
  }

  if (typeof window !== "undefined") {
    window.initUpdater = initUpdater;
    window.ownlineCheckUpdate = ownlineCheckUpdate;
    window.ownlinePerformUpgrade = ownlinePerformUpgrade;
    window.ownlineUpdateVersionBadges = updateVersionBadges;
    window.ownlineChangeDomain = ownlineChangeDomain;
  }
})();
