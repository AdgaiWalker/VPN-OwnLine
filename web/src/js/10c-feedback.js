(function () {
  var _selectedFeedbackIntent = "bug";
  var _selectedFeedbackType = "bug";
  var _cachedSystemInfo = null;

  function setElementDisplay(id, display) {
    var el = document.getElementById(id);
    if (el) el.style.display = display;
  }

  function setElementText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function selectFeedbackIntent(intent) {
    _selectedFeedbackIntent = intent || "bug";
    _selectedFeedbackType = (_selectedFeedbackIntent === "idea") ? "suggestion" : "bug";

    var bugBtn = document.getElementById("seg-btn-bug");
    var ideaBtn = document.getElementById("seg-btn-idea");
    if (bugBtn && ideaBtn) {
      if (_selectedFeedbackIntent === "bug") {
        bugBtn.classList.add("active");
        ideaBtn.classList.remove("active");
      } else {
        bugBtn.classList.remove("active");
        ideaBtn.classList.add("active");
      }
    }

    var msgEl = document.getElementById("feedback-message");
    if (msgEl) {
      var zh = (typeof isZh === "function") ? isZh() : true;
      if (_selectedFeedbackIntent === "idea") {
        msgEl.placeholder = (typeof t === "function") ? t("feedback_msg_ph_idea") : (zh ? "希望支持什么新平台、新协议或新场景？" : "What new platform, protocol, or scenario would you like to see?");
      } else {
        msgEl.placeholder = (typeof t === "function") ? t("feedback_msg_ph_bug") : (zh ? "在什么时间、哪个节点卡顿或报错？发生了什么？" : "When and on which node did it lag or error? What happened?");
      }
    }
  }

  function selectFeedbackType(type) {
    _selectedFeedbackType = type || "bug";
    if (type === "suggestion") {
      selectFeedbackIntent("idea");
    } else {
      selectFeedbackIntent("bug");
    }
  }

  function toggleFeedbackDiagDetails() {
    var details = document.getElementById("feedback-diag-details");
    var arrow = document.getElementById("feedback-diag-arrow");
    if (!details) return;
    var isExpanded = details.style.display === "block";
    if (isExpanded) {
      details.style.display = "none";
      if (arrow) arrow.style.transform = "rotate(0deg)";
    } else {
      details.style.display = "block";
      if (arrow) arrow.style.transform = "rotate(180deg)";
      var diag = buildDiagnosticSnapshot();
      details.textContent = JSON.stringify(diag, null, 2);
    }
  }

  function updateFeedbackCharCount(val) {
    var count = (val || "").length;
    setElementText("feedback-char-count", count + "/2000");
  }

  function getPlatformSummary() {
    var ua = (typeof navigator !== "undefined" && navigator.userAgent) ? navigator.userAgent : "";
    var platform = "Unknown";
    if (/iPhone|iPad|iPod/i.test(ua)) platform = "iOS";
    else if (/Android/i.test(ua)) platform = "Android";
    else if (/Macintosh|Mac OS X/i.test(ua)) platform = "macOS";
    else if (/Windows/i.test(ua)) platform = "Windows";
    else if (/Linux/i.test(ua)) platform = "Linux";

    var browser = "Browser";
    if (/Chrome/i.test(ua)) browser = "Chrome";
    else if (/Safari/i.test(ua) && !/Chrome/i.test(ua)) browser = "Safari";
    else if (/Firefox/i.test(ua)) browser = "Firefox";
    else if (/Edg/i.test(ua)) browser = "Edge";

    return platform + " · " + browser;
  }

  function buildDiagnosticSnapshot() {
    var ns = (typeof NODES !== "undefined" && Array.isArray(NODES)) ? NODES : [];
    var st = (typeof STATUS !== "undefined" && STATUS) ? STATUS : {};
    var ver = "v0.6.1";
    if (typeof document !== "undefined") {
      var verEl = document.getElementById("footer-version-tag");
      if (verEl && verEl.textContent) ver = verEl.textContent.trim();
    }

    var winW = (typeof window !== "undefined" && window.innerWidth) ? window.innerWidth : 1280;
    var winH = (typeof window !== "undefined" && window.innerHeight) ? window.innerHeight : 800;

    var sys = _cachedSystemInfo || {};

    var summary = {
      version: sys.version || ver,
      commit: sys.commit || "release",
      os: sys.os || "Linux",
      arch: sys.arch || "x86_64",
      singbox: sys.singbox || "1.11+",
      platform: getPlatformSummary(),
      screen: winW + "x" + winH,
      time: new Date().toISOString(),
      node_count: ns.length,
      nodes: ns.map(function (n) {
        var s = st[n.name] || {};
        return {
          name: n.name,
          type: n.type || "vless",
          role: n.role || "exit",
          health: n.health || "-",
          ok: s.ok !== undefined ? s.ok : null,
          ms: s.ms || null,
          cn_ok: s.cn_ok !== undefined ? s.cn_ok : null,
          cn_ms: s.cn_ms || null
        };
      })
    };
    return summary;
  }

  function fetchSystemInfoAsync() {
    if (_cachedSystemInfo) return;
    fetch("/api/system/version", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) {
          _cachedSystemInfo = d;
          var diag = buildDiagnosticSnapshot();
          var zh = (typeof isZh === "function") ? isZh() : true;
          var glanceText = (zh ? "现场指纹已就绪 · " : "Diagnostics Ready · ") + diag.version + " (" + (diag.commit || "release") + ")";
          setElementText("feedback-diag-glance", glanceText);
          var details = document.getElementById("feedback-diag-details");
          if (details && details.style.display === "block") {
            details.textContent = JSON.stringify(diag, null, 2);
          }
        }
      })
      .catch(function () {});
  }

  function openFeedbackDialog() {
    var dlg = document.getElementById("feedback-dialog");
    if (!dlg) return;

    // Reset Form
    var form = document.getElementById("feedback-form");
    if (form) form.reset();
    selectFeedbackIntent("bug");
    updateFeedbackCharCount("");
    setElementDisplay("feedback-status", "none");
    setElementDisplay("feedback-form", "block");
    setElementDisplay("feedback-success-card", "none");

    var details = document.getElementById("feedback-diag-details");
    if (details) details.style.display = "none";
    var arrow = document.getElementById("feedback-diag-arrow");
    if (arrow) arrow.style.transform = "rotate(0deg)";

    var submitBtn = document.getElementById("btn-submit-feedback");
    var submitText = document.getElementById("btn-submit-feedback-text");
    if (submitBtn) submitBtn.disabled = false;
    if (submitText) submitText.textContent = (typeof t === "function") ? t("feedback_btn_submit") : "一键发送给 AI 诊断库";

    // Populate Diagnostic Glance
    var diag = buildDiagnosticSnapshot();
    var zh = (typeof isZh === "function") ? isZh() : true;
    var glanceText = (zh ? "现场指纹已就绪 · " : "Diagnostics Ready · ") + diag.version + " (" + (diag.commit || "release") + ")";
    setElementText("feedback-diag-glance", glanceText);

    fetchSystemInfoAsync();

    if (typeof dlg.showModal === "function") {
      dlg.showModal();
    } else {
      dlg.setAttribute("open", "");
    }
  }

  function insertFeedbackTag(tag) {
    var msgEl = document.getElementById("feedback-message");
    if (!msgEl) return;
    var cur = (msgEl.value || "").trim();
    if (!cur) {
      msgEl.value = tag + "：";
    } else {
      msgEl.value = cur + " [" + tag + "]";
    }
    updateFeedbackCharCount(msgEl.value);
    msgEl.focus();
  }

  function ownlineSubmitFeedback(e) {
    if (e && e.preventDefault) e.preventDefault();

    var msgEl = document.getElementById("feedback-message");
    var contactEl = document.getElementById("feedback-contact");
    var statusEl = document.getElementById("feedback-status");
    var submitBtn = document.getElementById("btn-submit-feedback");
    var submitText = document.getElementById("btn-submit-feedback-text");
    var zh = (typeof isZh === "function") ? isZh() : true;

    var message = (msgEl ? msgEl.value : "").trim();
    var contact = (contactEl ? contactEl.value : "").trim();

    if (!message) {
      message = zh ? "一键现场诊断上报（未填写文字描述）" : "One-click diagnostic report (no user description)";
    }

    if (submitBtn) submitBtn.disabled = true;
    if (submitText) submitText.textContent = (typeof t === "function") ? t("feedback_submitting") : "正在发送...";
    if (statusEl) statusEl.style.display = "none";

    var payload = {
      type: _selectedFeedbackType,
      intent: _selectedFeedbackIntent,
      message: message,
      contact: contact,
      diagnostics: buildDiagnosticSnapshot()
    };

    fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok || !data.ok) throw new Error((data && data.error) || ("HTTP " + r.status));
          return data;
        });
      })
      .then(function () {
        setElementDisplay("feedback-form", "none");
        setElementDisplay("feedback-success-card", "block");
      })
      .catch(function (err) {
        if (submitBtn) submitBtn.disabled = false;
        if (submitText) submitText.textContent = (typeof t === "function") ? t("feedback_btn_submit") : "存入服务器底账";
        if (statusEl) {
          statusEl.textContent = (zh ? "保存失败：" : "Save failed: ") + err.message;
          statusEl.style.color = "var(--bad)";
          statusEl.style.display = "block";
        }
      });
  }

  function formatReport(isMarkdown) {
    var msgEl = document.getElementById("feedback-message");
    var contactEl = document.getElementById("feedback-contact");
    var zh = (typeof isZh === "function") ? isZh() : true;

    var message = (msgEl ? msgEl.value : "").trim() || (zh ? "(未填写描述)" : "(No description provided)");
    var contact = (contactEl ? contactEl.value : "").trim() || (zh ? "(未填写联系方式)" : "(No contact info)");
    var diag = buildDiagnosticSnapshot();

    var intentTitleZh = (_selectedFeedbackIntent === "idea") ? "想要新功能 / 场景建议" : "遇到问题 / 排障求助";
    var intentTitleEn = (_selectedFeedbackIntent === "idea") ? "Feature Request / Scenario Idea" : "Bug & Issue Report";
    var intentTitle = zh ? intentTitleZh : intentTitleEn;

    var report = "";
    if (isMarkdown) {
      report += "### 反馈意图 / Intent\n" + intentTitle + "\n\n";
      report += "### 详细描述 / Description\n" + message + "\n\n";
      if (contact && contact !== "(未填写联系方式)" && contact !== "(No contact info)") {
        report += "### 联系方式 / Contact\n" + contact + "\n\n";
      }
      report += "### 运行环境与版本指纹 / Environment Fingerprint\n";
      report += "- **Evergreen Version**: `" + diag.version + " (" + (diag.commit || "release") + ")`\n";
      report += "- **Host System**: `" + diag.os + " (" + diag.arch + ", sing-box " + diag.singbox + ")`\n";
      report += "- **Client Platform**: `" + diag.platform + " (" + diag.screen + ")`\n";
      report += "- **Timestamp**: `" + diag.time + "`\n\n";

      report += "### 节点状态切片 / Node Status\n```\n";
      if (diag.nodes && diag.nodes.length) {
        diag.nodes.forEach(function (n) {
          var hostProbe = n.ok === true ? (n.ms + "ms") : (n.ok === false ? "异常" : "未测");
          var cnProbe = n.cn_ok === true ? (n.cn_ms + "ms") : (n.cn_ok === false ? "阻断" : "未测");
          report += "- " + n.name + " (" + n.type + "): health=" + n.health + ", 主控探活=" + hostProbe + ", 国内探活=" + cnProbe + "\n";
        });
      } else {
        report += "(当前无节点)\n";
      }
      report += "```\n\n<!-- Generated by Evergreen OwnLine Dogfooding Loop -->\n";
    } else {
      report = "=== Evergreen · OwnLine " + (zh ? "排障反馈报告" : "Feedback Report") + " ===\n";
      report += (zh ? "【意图】: " : "[Intent]: ") + intentTitle + "\n";
      report += (zh ? "【描述】: " : "[Description]: ") + message + "\n";
      report += (zh ? "【联系方式】: " : "[Contact]: ") + contact + "\n";
      report += (zh ? "【版本指纹】: " : "[Version]: ") + diag.version + " (Commit: " + (diag.commit || "release") + ")\n";
      report += (zh ? "【宿主底座】: " : "[Host]: ") + diag.os + " (" + diag.arch + ", sing-box " + diag.singbox + ")\n";
      report += (zh ? "【客户端环境】: " : "[Client]: ") + diag.platform + " (" + diag.screen + ")\n";
      report += (zh ? "【时间】: " : "[Time]: ") + diag.time + "\n\n";

      report += (zh ? "[节点状态现场]:\n" : "[Node Status]:\n");
      if (diag.nodes && diag.nodes.length) {
        diag.nodes.forEach(function (n) {
          var hostProbe = n.ok === true ? (n.ms + "ms") : (n.ok === false ? "异常" : "未测");
          var cnProbe = n.cn_ok === true ? (n.cn_ms + "ms") : (n.cn_ok === false ? "阻断" : "未测");
          report += "  - " + n.name + " (" + n.type + "): health=" + n.health + ", 主控探活=" + hostProbe + ", 国内探活=" + cnProbe + "\n";
        });
      } else {
        report += (zh ? "  (当前无节点)\n" : "  (No nodes connected)\n");
      }
    }
    return report;
  }

  function openMailToAuthor() {
    var msgEl = document.getElementById("feedback-message");
    var zh = (typeof isZh === "function") ? isZh() : true;
    var message = (msgEl ? msgEl.value : "").trim();
    var intentTitle = (_selectedFeedbackIntent === "idea") ? (zh ? "新功能建议" : "Feature Request") : (zh ? "问题排障" : "Bug Report");
    var subject = "[Evergreen] " + intentTitle + (message ? (" - " + (message.length > 25 ? message.slice(0, 25) + "..." : message)) : "");
    var body = formatReport(false);
    var mailto = "mailto:praxiswalker@gmail.com?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
    if (typeof window !== "undefined") {
      window.location.href = mailto;
    }
  }

  function ownlineCopyFeedbackAndDiag(btn) {
    var zh = (typeof isZh === "function") ? isZh() : true;
    var report = formatReport(false);

    function onCopied() {
      if (typeof toast === "function") {
        toast((typeof t === "function") ? t("feedback_copied") : (zh ? "排障报告已复制！可直接发邮件给作者：praxiswalker@gmail.com" : "Report copied! Email to praxiswalker@gmail.com"));
      } else if (btn) {
        var orig = btn.textContent;
        btn.textContent = zh ? "已复制！" : "Copied!";
        setTimeout(function () { btn.textContent = orig; }, 1600);
      }
    }

    if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(report).then(onCopied).catch(function () {
        fallbackCopy(report, onCopied);
      });
    } else {
      fallbackCopy(report, onCopied);
    }
  }

  function openGitHubIssue() {
    var msgEl = document.getElementById("feedback-message");
    var zh = (typeof isZh === "function") ? isZh() : true;
    var message = (msgEl ? msgEl.value : "").trim();

    var prefix = (_selectedFeedbackIntent === "idea") ? "[Feature]: " : "[Bug]: ";
    var summaryTitle = message ? (message.length > 30 ? message.slice(0, 30) + "..." : message) : (_selectedFeedbackIntent === "idea" ? "新功能建议" : "问题反馈");
    var issueTitle = prefix + summaryTitle;
    var body = formatReport(true);

    var repo = "AdgaiWalker/VPN-OwnLine";
    var ghUrl = "https://github.com/" + repo + "/issues/new?title=" + encodeURIComponent(issueTitle) + "&body=" + encodeURIComponent(body);
    if (typeof window !== "undefined") {
      window.open(ghUrl, "_blank", "noopener,noreferrer");
    }
  }

  function fallbackCopy(text, cb) {
    if (typeof document === "undefined") return;
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      if (cb) cb();
    } catch (e) {
      alert("复制失败，请手动选取复制");
    }
    document.body.removeChild(ta);
  }

  // Export functions to window
  if (typeof window !== "undefined") {
    window.openFeedbackDialog = openFeedbackDialog;
    window.insertFeedbackTag = insertFeedbackTag;
    window.selectFeedbackIntent = selectFeedbackIntent;
    window.selectFeedbackType = selectFeedbackType;
    window.toggleFeedbackDiagDetails = toggleFeedbackDiagDetails;
    window.updateFeedbackCharCount = updateFeedbackCharCount;
    window.ownlineSubmitFeedback = ownlineSubmitFeedback;
    window.ownlineCopyFeedbackAndDiag = ownlineCopyFeedbackAndDiag;
    window.openMailToAuthor = openMailToAuthor;
    window.openGitHubIssue = openGitHubIssue;
  }
})();
