  function setStp(id, cls) {
    var el = document.getElementById(id);
    if (!el) return;
    el.className = "stp " + cls;
  }

  // 10. Runtime & diagnostic logs
  function redactLog(value) {
    return String(value || "")
      .replace(/-----BEGIN [^-\r\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\r\n]*PRIVATE KEY-----|$)/g, "[私钥已隐藏]")
      .replace(/\b(?:vless|vmess|ss|ssr|trojan|hysteria2):\/\/[^\s"']+/gi, "[代理链接已隐藏]")
      .replace(/(\/s\/)[^/\s?#"'()]+/gi, "$1[已隐藏]")
      .replace(/\bBearer\s+[^\s,;"']+/gi, "Bearer [已隐藏]")
      .replace(/((?:secret[_-]?(?:id|key)?|access[_-]?(?:key|token)|password|passwd|pwd|passphrase|private[_-]?key|sub[_-]?(?:url|token)|token|authorization|credential)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;()]+)/gi, "$1[已隐藏]");
  }

  function fetchLogs() {
    var box = document.getElementById("log-list");
    if (!box) return;
    if (location.protocol === "file:") { STATE.logStatus = "ready"; renderLogs(); return; }

    STATE.logStatus = "loading";
    renderLogs();

    fetch(safeUrl("/api/logs?limit=50"), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("request failed"); return r.json(); })
      .then(function (d) {
        if (!Array.isArray(d.logs)) throw new Error("invalid log response");
        var logs = d.logs;
        logs = logs.map(function (l) { return { ts: l.ts, level: l.level, source: l.src || l.source, message: redactLog(l.msg || l.message || "") }; });
        STATE.allLogs = logs;
        STATE.logStatus = "ready";
        renderLogs();
      })
      .catch(function () {
        STATE.logStatus = "unavailable";
        renderLogs();
      });
  }

  function appendLog(source, msg, level) {
    var entry = {
      ts: new Date().toISOString(),
      level: level || "INFO",
      source: source || "SYS",
      message: msg
    };
    STATE.allLogs.unshift(entry);
    renderLogs();
  }

  function renderLogs() {
    var box = document.getElementById("log-list");
    if (!box) return;

    if (STATE.logStatus === "loading") { box.innerHTML = "<div class='small muted' style='padding:14px 0'>正在加载日志...</div>"; return; }
    if (STATE.logStatus === "unavailable") { box.innerHTML = "<div class='small muted' style='padding:14px 0'>日志暂不可用</div>"; return; }

    var filter = STATE.logLevel || "ALL";
    var filtered = STATE.allLogs.filter(function (it) {
      if (filter === "ALL") return true;
      if (filter === "BAD") return it.level === "ERROR" || it.level === "WARN" || (it.message && (it.message.toLowerCase().indexOf("fail") >= 0 || it.message.indexOf("err") >= 0 || it.message.indexOf("失败") >= 0 || it.message.indexOf("异常") >= 0));
      if (filter === "SUB") return it.source === "SUB" || (it.message && (it.message.toLowerCase().indexOf("sub") >= 0 || it.message.indexOf("订阅") >= 0));
      if (filter === "PROBE") return it.source === "PROBE" || (it.message && (it.message.toLowerCase().indexOf("probe") >= 0 || it.message.indexOf("探活") >= 0));
      return true;
    });

    if (!filtered.length) {
      box.innerHTML = "<div class='small muted' style='padding:14px 0'>该分类下暂无日志记录</div>";
      return;
    }

    var showAll = document.getElementById("btn-more-logs");
    var isExpanded = showAll && showAll.getAttribute("aria-expanded") === "true";
    if (!isExpanded) filtered = filtered.slice(0, 3);

    box.innerHTML = filtered.map(function (it) {
      var timeStr = "";
      try {
        var d = new Date(it.ts);
        if (isNaN(d.getTime())) throw new Error();
        timeStr = d.getFullYear() + "-" +
          (d.getMonth() + 1).toString().padStart(2, "0") + "-" +
          d.getDate().toString().padStart(2, "0") + " " +
          d.getHours().toString().padStart(2, "0") + ":" +
          d.getMinutes().toString().padStart(2, "0") + ":" +
          d.getSeconds().toString().padStart(2, "0");
      } catch (e) { timeStr = it.ts || ""; }

      var dotCls = "log-dot-ok";
      var tagCls = "log-tag-info";
      var tagText = "信息";
      if (it.level === "ERROR" || it.level === "BAD") {
        dotCls = "log-dot-bad"; tagCls = "log-tag-err"; tagText = "错误";
      } else if (it.level === "WARN" || it.level === "WARNING") {
        dotCls = "log-dot-warn"; tagCls = "log-tag-warn"; tagText = "告警";
      }

      return "<div class='log-row'>" +
        "<span class='log-time'>" + timeStr + "</span> " +
        "<span class='log-msg'><span class='log-dot " + dotCls + "'></span> " + esc(it.message) + "</span>" +
        "<span class='log-tag-col'><span class='log-tag " + tagCls + "'>" + tagText + "</span></span>" +
        "</div>";
    }).join("");
  }

  function initLogFilters() {
    var more = document.getElementById("btn-more-logs");
    if (more) more.onclick = function () {
      var expanded = more.getAttribute("aria-expanded") !== "true";
      more.setAttribute("aria-expanded", String(expanded));
      more.textContent = expanded ? "收起" : "查看全部";
      renderLogs();
    };
    var tabs = document.querySelectorAll(".log-tabs .log-tab-btn, #section-logs .seg .segbtn");
    if (tabs.length) {
      tabs.forEach(function (btn) {
        btn.onclick = function () {
          tabs.forEach(function (b) { b.classList.remove("active"); });
          btn.classList.add("active");
          STATE.logLevel = btn.getAttribute("data-lvl") || "ALL";
          renderLogs();
        };
      });
    }

    var btnRefreshLogs = document.getElementById("btn-refresh-logs");
    if (btnRefreshLogs) {
      btnRefreshLogs.onclick = function () {
        fetchLogs();
      };
    }

    var btnCopyDiag = document.getElementById("btn-copy-diag");
    if (btnCopyDiag) {
      btnCopyDiag.onclick = function () {
        window.ownlineCopyDiag(btnCopyDiag);
      };
    }
  }

