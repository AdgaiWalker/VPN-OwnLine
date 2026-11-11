  function jsonRequest(path, options) {
    return fetch(safeUrl(path), options || {cache: "no-store"}).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function setQuotaMessage(box, message) {
    box.innerHTML = '<h2 class="quota-heading">服务器流量</h2><div class="small muted">' + esc(message) + '</div>';
  }

  function renderQuotaList(nodes, quota) {
    var box = document.getElementById("quota-list-container");
    if (!box) return;
    var groups = quota && Array.isArray(quota.guards) ? quota.guards : null;
    if (!groups) {
      var seen = {};
      groups = (nodes || []).filter(function (n) {
        var host = n.host || n.ip;
        if (!host || seen[host]) return false;
        seen[host] = true; return true;
      }).map(function (n) {
        return {
          ip: n.host || n.ip,
          name: n.name,
          used_gb: n.used_gb != null ? n.used_gb : null,
          total_gb: n.total_gb != null ? n.total_gb : null,
          percent: n.percent != null ? n.percent : null,
          status: n.quota_status || "unknown",
          control_supported: n.quota_control_managed === true,
          reset_day: n.reset_day != null ? n.reset_day : null
        };
      });
    }
    if (!groups.length) { setQuotaMessage(box, nodes && nodes.length ? "暂无流量统计" : "暂无服务器流量数据"); return; }

    var totalUsed = 0, totalCap = 0;
    var egressUsed = 0, egressCap = 0;
    groups.forEach(function (g) {
      var isRelay = false;
      if (nodes && nodes.length) {
        var matchNode = nodes.find(function (n) { return (n.host === g.ip || n.ip === g.ip); });
        if (matchNode && (matchNode.role === "relay" || matchNode.role === "standalone")) isRelay = true;
      }

      var u = (g.used_gb != null) ? Number(g.used_gb) : 0;
      var t = (g.total_gb != null) ? Number(g.total_gb) : 0;
      totalUsed += u;
      totalCap += t;
      if (!isRelay) {
        egressUsed += u;
        egressCap += t;
      }
    });

    if (egressCap <= 0) {
      egressUsed = totalUsed;
      egressCap = totalCap;
    }

    var glanceBox = document.getElementById("quota-glance");
    var glanceText = document.getElementById("quota-glance-text");
    var glanceFill = document.getElementById("quota-glance-fill");
    if (glanceBox && glanceText && glanceFill) {
      if (egressCap > 0) {
        var overallPct = Math.min(100, Math.round((egressUsed / egressCap) * 100));
        glanceText.textContent = Math.round(egressUsed) + " / " + Math.round(egressCap) + " GB";
        glanceFill.style.width = overallPct + "%";
        glanceFill.style.background = overallPct >= 80 ? "var(--apple-amber)" : "var(--apple-blue)";
        glanceBox.style.display = "inline-flex";
      } else {
        glanceBox.style.display = "none";
      }
    }

    var heroBanner = document.getElementById("quota-hero-banner");
    if (heroBanner) {
      if (egressCap > 0) {
        var overallPct = Math.min(100, Math.round((egressUsed / egressCap) * 100));
        var remGb = Math.max(0, Math.round((egressCap - egressUsed) * 10) / 10);
        var usedFmt = (Math.round(egressUsed * 10) / 10).toString();
        var totalFmt = Math.round(egressCap).toString() + " GB";
        var elUsed = document.getElementById("quota-hero-used");
        var elTotal = document.getElementById("quota-hero-total");
        var elPct = document.getElementById("quota-hero-percent");
        var elRem = document.getElementById("quota-hero-rem");
        var elFill = document.getElementById("quota-hero-fill");
        var elStatus = document.getElementById("quota-hero-status");
        if (elUsed) elUsed.textContent = usedFmt;
        if (elTotal) elTotal.textContent = totalFmt;
        if (elPct) elPct.textContent = "(" + overallPct + "%)";
        if (elRem) elRem.textContent = remGb + " GB";
        if (elFill) {
          elFill.style.width = overallPct + "%";
          elFill.style.background = overallPct >= 85 ? "var(--apple-red)" : (overallPct >= 75 ? "var(--apple-amber)" : "var(--apple-blue)");
        }
        if (elStatus) {
          elStatus.textContent = overallPct >= 85 ? "已熔断" : (overallPct >= 75 ? "预警" : "充足");
          elStatus.className = "tag " + (overallPct >= 85 ? "bad" : (overallPct >= 75 ? "warn" : "ok"));
        }
        var anyTripped = groups.some(function(g){ return g.status === "tripped" || (g.percent && g.percent >= 85); });
        var elSafe = document.getElementById("quota-hero-nodes-safe");
        if (elSafe) {
          elSafe.textContent = anyTripped ? "部分节点已触发保护熔断" : "所有出口服务器均在安全配额内 · 国内专线为防卡顿跳板";
          elSafe.style.color = anyTripped ? "var(--apple-red)" : "var(--apple-muted)";
        }
        heroBanner.style.display = "block";
      } else {
        heroBanner.style.display = "none";
      }
    }

    var headerHtml = '<div style="display:flex;justify-content:space-between;align-items:baseline;margin:24px 0 10px">' +
      '<h2 class="quota-heading" style="margin:0">服务器流量</h2>' +
    '</div>' +
    '<div class="quota-table-head">' +
      '<span>服务器</span>' +
      '<span>配额进度</span>' +
      '<span style="text-align:right">已用 / 总额</span>' +
    '</div>';

    var hostNodes = nodes || [];
    var rowsHtml = groups.map(function (g) {
      var related = hostNodes.filter(function (n) { return (n.host || n.ip) === g.ip; });
      var valid = g.used_gb != null && g.total_gb != null && Number.isFinite(Number(g.used_gb)) && Number.isFinite(Number(g.total_gb)) && Number(g.total_gb) > 0;
      var usage = valid
        ? (Math.round(Number(g.used_gb)) + " / " + Math.round(Number(g.total_gb)) + " GB")
        : (g.used_gb != null ? ("已统计 " + (Math.round(Number(g.used_gb) * 10) / 10) + " GB（未设上限）") : "暂无流量统计");
      var pct = Number.isFinite(Number(g.percent)) ? Math.max(0, Math.min(100, Number(g.percent))) : (valid ? Math.round((Number(g.used_gb)/Number(g.total_gb))*100) : null);
      var name = (g.name && g.name !== g.ip) ? g.name : (related[0] && related[0].name) || g.ip || "服务器";
      var isTripped = g.status === "tripped";
      var isWarn = pct != null && pct >= 80;
      var ctrlNote = (g.control_supported === false) ? ' <span class="tag" style="font-size:11px;margin-left:4px">仅告警</span>' : '';

      var barWidth = pct != null ? pct : 0;
      var pctText = pct != null ? Math.round(pct) + "%" : "--";
      var dotCls = isTripped ? "q-dot tripped" : (isWarn ? "q-dot warn" : "q-dot");
      var barCls = isTripped ? "bar tripped" : (isWarn ? "bar warn" : "bar");

      return '<div class="quota-table-row">' +
        '<div class="quota-col-name"><span class="' + dotCls + '"></span><b>' + esc(name) + '</b>' + ctrlNote + '</div>' +
        '<div class="quota-col-progress">' +
          '<div class="' + barCls + '" role="progressbar" aria-label="' + esc(name) + ' 流量使用进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + barWidth + '"><i style="width:' + barWidth + '%"></i></div>' +
        '</div>' +
        '<div class="quota-col-stat">' + esc(usage) + (pct != null ? ' <span class="small muted">(' + pctText + ')</span>' : '') + '</div>' +
      '</div>';
    }).join("");

    box.innerHTML = headerHtml + '<div class="quota-table-body">' + rowsHtml + '</div>';
  }

  function setAvailability(text, detail) {
    document.getElementById("unready-title").textContent = text;
    document.getElementById("unready-note").textContent = detail;
  }

  var refreshStateAbortController = null;
  function refreshState() {
    if (typeof window !== "undefined" && (window.isTogglingHy2 || window.isRelayMutating)) {
      return;
    }
    if (refreshStateAbortController) {
      try { refreshStateAbortController.abort(); } catch (_) {}
    }
    refreshStateAbortController = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var signal = refreshStateAbortController ? refreshStateAbortController.signal : undefined;

    var pill = document.getElementById("status-pill"), pillText = document.getElementById("status-text");
    var readyBox = document.getElementById("client-ready-box"), unready = document.getElementById("client-unready-box");
    var quotaSettings = document.getElementById("quota-settings"), quotaBox = document.getElementById("quota-list-container");
    var btn = document.getElementById("btn-enter-setup");
    if (location.protocol === "file:") {
      pillText.textContent = "本地预览";
      var pDot = document.getElementById("status-dot");
      if (pDot) pDot.textContent = "";
      document.getElementById("serving-node-ip").textContent = "离线演示环境";
      setAvailability("连接就绪 · 演示模式", "运行于离线预览环境，展示模拟连接数据。");
      readyBox.style.display = "block";
      document.getElementById("client-unready-box").style.display = "none";
      quotaSettings.style.display = "none";

      BASE_SUB_URL = "https://vpn.example.com/s/demotoken123";
      wireLinks(true);

      NODES = [
        { name: "香港 · HK01", host: "203.0.113.10", port: 443, role: "relay", enabled: true, exit_ip: "203.0.113.10", exit_country: "HK", health: "ok", used_gb: 20, total_gb: 500, percent: 4 },
        { name: "日本 · JP01", host: "198.51.100.15", port: 443, role: "exit", enabled: true, exit_ip: "198.51.100.15", exit_country: "JP", health: "ok", used_gb: 120, total_gb: 500, percent: 24, isp: { type: "socks", server: "198.51.100.88", server_port: 10808, username: "res_user" } },
        { name: "新加坡 · SG01", host: "203.0.113.20", port: 8443, role: "exit", enabled: true, exit_ip: "203.0.113.20", exit_country: "SG", health: "ok", used_gb: 60, total_gb: 500, percent: 12 },
        { name: "美西 · US01", host: "198.51.100.30", port: 443, role: "exit", enabled: true, exit_ip: "198.51.100.30", exit_country: "US", health: "ok", used_gb: 200, total_gb: 500, percent: 40 }
      ];
      STATUS = {
        "香港 · HK01": { ok: true, cn_ok: true, latency: 28, cn_latency: 24 },
        "日本 · JP01": { ok: true, cn_ok: true, latency: 65, cn_latency: 58 },
        "新加坡 · SG01": { ok: true, cn_ok: true, latency: 85, cn_latency: 72 },
        "美西 · US01": { ok: true, cn_ok: true, latency: 145, cn_latency: 160 }
      };
      var mockQuota = {
        guards: [
          { ip: "203.0.113.10", name: "香港 · HK01", used_gb: 20, total_gb: 500, percent: 4, status: "normal", control_supported: true },
          { ip: "198.51.100.15", name: "日本 · JP01", used_gb: 120, total_gb: 500, percent: 24, status: "normal", control_supported: true },
          { ip: "203.0.113.20", name: "新加坡 · SG01", used_gb: 60, total_gb: 500, percent: 12, status: "normal", control_supported: true },
          { ip: "198.51.100.30", name: "美西 · US01", used_gb: 200, total_gb: 500, percent: 40, status: "normal", control_supported: true }
        ]
      };
      STATE.quota = mockQuota;
      renderNodes(NODES, STATUS, mockQuota);
      renderQuotaList(NODES, mockQuota);
      STATE.allLogs = [
        { ts: "2026-11-02 10:24:11", level: "INFO", source: "SUB", message: "订阅配置已同步更新（共 4 个节点）。" },
        { ts: "2026-11-02 09:17:36", level: "INFO", source: "SYS", message: "服务器 HK01 流量统计已更新：20 / 500 GB (4%)。" },
        { ts: "2026-11-02 08:03:22", level: "WARN", source: "SYS", message: "本地预览模式未连接管理后端。" }
      ];
      STATE.logStatus = "ready";
      renderLogs();
      return;
    }
    Promise.allSettled([
      jsonRequest("/api/settings", { signal: signal }),
      jsonRequest("/api/nodes", { signal: signal }),
      jsonRequest("/api/quota/guard", { signal: signal }),
      jsonRequest("/api/setup", { signal: signal })
    ]).then(function (res) {
      if (signal && signal.aborted) return;
      if (typeof window !== "undefined" && (window.isTogglingHy2 || window.isRelayMutating)) return;
      var settings = res[0].status === "fulfilled" ? res[0].value : null;
      var nodes = res[1].status === "fulfilled" && Array.isArray(res[1].value) ? res[1].value : null;
      var quota = res[2].status === "fulfilled" && res[2].value && res[2].value.ok === true ? res[2].value : null;
      var setup = res[3].status === "fulfilled" ? res[3].value : null;
      var mh = document.getElementById("management-help");
      if (mh) mh.style.display = settings && settings.ok === true ? "" : "none";
      var modernBackend = !!(settings && Number.isInteger(settings.quota_threshold));
      var canRestore = !!(settings && settings.backup_restore_supported === true);
      var restoreBtn = document.getElementById("backup-restore");
      if (restoreBtn) restoreBtn.disabled = !canRestore;
      var backupNote = document.getElementById("backup-note");
      var zh = (typeof isZh === 'function') ? isZh() : true;
      if (backupNote && settings && settings.ok === true && !canRestore) backupNote.textContent = zh ? "当前服务器后端不支持备份恢复。" : "Backup restore is not supported by current server backend.";
      if (settings && settings.ok === true) {
        if (settings.version && typeof window.ownlineUpdateVersionBadges === "function") {
          window.ownlineUpdateVersionBadges(settings.version);
        }
        jsonRequest("/api/password/state", { signal: signal }).then(function (result) {
          if (signal && signal.aborted) return;
          document.getElementById("change-password-link").style.display = result.ok === true ? "" : "none";
        }).catch(function () { document.getElementById("change-password-link").style.display = "none"; });
      }
      jsonRequest("/status.json?_t=" + Date.now(), { signal: signal }).then(function (st) {
        if (signal && signal.aborted) return;
        if (typeof window !== "undefined" && (window.isTogglingHy2 || window.isRelayMutating)) return;
        STATUS = st || {};
        paintStatus();
      }).catch(function () {});
      STATE.csrfToken = setup && typeof setup.csrf_token === "string" ? setup.csrf_token : "";
      STATE.tencentConfigured = !!(settings && settings.tencent_configured === true);
      var canDiscover = !!STATE.csrfToken || !!(settings && settings.tencent_discovery === true) || STATE.tencentConfigured;
      STATE.nodeCheckAvailable = location.protocol === "https:" && !!(settings && settings.node_check_supported === true);
      setOtherCheckBusy(!!otherCheckController);
      document.getElementById("other-connect-status").textContent = STATE.nodeCheckAvailable
        ? (zh ? "仅测试连接，尚未安装节点。" : "Testing connection only, node not installed yet.")
        : (zh ? "网页连接检测不可用。" : "Web connection check unavailable.");
      ["tc-sid", "tc-skey", "btn-tc-read"].forEach(function(id){ document.getElementById(id).disabled = !canDiscover; });
      document.getElementById("tc-credential-fields").style.display = "";
      if (STATE.tencentConfigured) {
        document.getElementById("tc-credential-fields").open = false;
        document.getElementById("tc-read-status").innerHTML = zh ? "<span style='color:var(--ok)'>✓ 已绑定服务器默认腾讯云账号</span>" : "<span style='color:var(--ok)'>✓ Server default credentials linked</span>";
      } else {
        document.getElementById("tc-read-status").textContent = canDiscover ? "" : (zh ? "当前后端未开启腾讯云 API 自动发现。" : "Tencent Cloud API auto-discovery is disabled.");
      }
      NODES = nodes || [];
      if (typeof window !== "undefined") window.NODES = NODES;
      if (nodes) {
        document.getElementById("serving-node-title").textContent = zh ? "连接配置" : "Connection Profiles";
        document.getElementById("serving-node-ip").textContent = nodes.length ? (zh ? nodes.length + " 个节点已加载" : nodes.length + " nodes loaded") : (zh ? "暂无节点连接" : "No nodes connected");
        if (btn) {
          var aText = zh ? "添加节点" : "Add Node";
          btn.title = aText;
          btn.setAttribute("aria-label", aText);
        }
        var bManage = document.getElementById("btn-manage-servers");
        if (bManage) bManage.style.display = "none";
      } else {
        document.getElementById("serving-node-ip").textContent = zh ? "无法获取服务器状态" : "Unable to reach server";
        if (btn) {
          var aText2 = zh ? "添加节点" : "Add Node";
          btn.title = aText2;
          btn.setAttribute("aria-label", aText2);
        }
        var bManage2 = document.getElementById("btn-manage-servers");
        if (bManage2) bManage2.style.display = "none";
      }
      if (location.protocol === "file:") {
        pillText.textContent = zh ? "本地预览" : "Local Preview";
        pill.className = "pill-preview";
      } else {
        pill.className = "pill-preview";
        pillText.textContent = nodes && nodes.length ? (zh ? "检测中..." : "Checking…") : (zh ? "未连接节点" : "No Nodes Connected");
      }
      var url = settings && typeof settings.sub_url === "string" ? settings.sub_url : "";
      try { var parsed = new URL(url); if ((parsed.protocol !== "https:" && parsed.protocol !== "http:") || !parsed.host) url = ""; }
      catch (_) { url = ""; }
      BASE_SUB_URL = url.replace(/\/$/, "");
      if (BASE_SUB_URL) {
        var eligible = !!nodes && nodes.some(function (n) {
          var lifecycle = n.lifecycle || {};
          var health = n.health || "unknown";
          return n.enabled !== false && !n.cleanup_pending && lifecycle.state !== "disabled" && lifecycle.state !== "expired" && (health === "ok" || health === "unknown");
        });
        wireLinks(eligible); unready.style.display = "none"; readyBox.style.display = "block";
      } else {
        readyBox.style.display = "none"; unready.style.display = "block";
        if (nodes && !nodes.length) setAvailability(zh ? "尚未连接服务器" : "No Servers Connected", zh ? "请点击「+ 添加节点」选择连接方式开始部署。" : "Please click \"+ Add Node\" to begin setup.");
        else if (settings && settings.ok) setAvailability(zh ? "订阅链接暂不可用" : "Subscription link unavailable", zh ? "请检查服务器管理端配置。" : "Please check server management settings.");
        else setAvailability(zh ? "未连接到管理后端" : "Not connected to management backend", zh ? "请通过受保护的管理后台地址访问，当前无法校验服务器状态。" : "Please access via protected admin portal.");
      }
      if (quota) {
        STATE.quota = quota;
        var threshold = quota.watermarks && quota.watermarks.tripped;
        quotaSettings.style.display = modernBackend && Number.isInteger(threshold) && threshold >= 1 && threshold <= 100 ? "" : "none";
        var input = document.getElementById("quota-threshold");
        if (document.activeElement !== input && quotaSettings.style.display !== "none") input.value = threshold;
        renderQuotaList(NODES, quota);
      } else {
        STATE.quota = null;
        quotaSettings.style.display = "none";
        if (nodes && nodes.length) renderQuotaList(nodes, null); else setQuotaMessage(quotaBox, "暂无流量统计");
      }
      renderNodes(NODES, STATUS, quota);
      if (NODES && NODES.length) {
        if (typeof ownlineProbeLocalPing === "function") {
          setTimeout(function () { ownlineProbeLocalPing(); }, 150);
        } else if (typeof window !== "undefined" && typeof window.ownlineProbeLocalPing === "function") {
          setTimeout(function () { window.ownlineProbeLocalPing(); }, 150);
        }
      }
      var distinctHosts = {};
      (nodes || []).forEach(function (n) {
        var h = n.host || n.ip;
        if (h) distinctHosts[h] = true;
      });
      var serverCount = Object.keys(distinctHosts).length || (nodes ? nodes.length : 0);
      var badge = document.getElementById("nodes-count-badge");
      if (badge) badge.textContent = serverCount ? (zh ? serverCount + " 台服务器" : serverCount + (serverCount > 1 ? " servers" : " server")) : "";
      var servingIp = document.getElementById("serving-node-ip");
      if (servingIp) servingIp.textContent = serverCount ? (zh ? serverCount + " 台服务器已就绪" : serverCount + (serverCount > 1 ? " servers ready" : " server ready")) : (zh ? "已加载" : "Ready");
    });
  }

  function initQuotaSettings() {
    document.getElementById("quota-form").onsubmit = function (event) {
      event.preventDefault();
      var input = document.getElementById("quota-threshold"), note = document.getElementById("quota-note");
      var value = Number(input.value);
      if (!Number.isInteger(value) || value < 1 || value > 100) { note.textContent = "请输入 1 至 100 之间的整数"; return; }
      note.textContent = "正在保存...";
      jsonRequest("/api/quota/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({threshold:value})})
        .then(function(result){ if (!result.ok) throw new Error("Save failed"); note.textContent = "阈值已保存，节点保护状态已刷新。"; refreshState(); })
        .catch(function(){note.textContent = "保存失败，请稍后重试";});
    };
  }


