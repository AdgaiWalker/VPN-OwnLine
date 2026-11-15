(function () {
  var _selectedFeedbackType = "connection";

  function setElementDisplay(id, display) {
    var el = document.getElementById(id);
    if (el) el.style.display = display;
  }

  function setElementText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function selectFeedbackType(type) {
    _selectedFeedbackType = type || "connection";
    var pills = ["conn", "client", "suggest", "bug"];
    var typeMap = { connection: "conn", client: "client", suggestion: "suggest", bug: "bug" };
    var activeSuffix = typeMap[_selectedFeedbackType] || "conn";

    pills.forEach(function (p) {
      var wrap = document.getElementById("fb-type-" + p + "-wrap");
      if (wrap) {
        if (p === activeSuffix) {
          wrap.classList.add("active");
          var radio = wrap.querySelector('input[type="radio"]');
          if (radio) radio.checked = true;
        } else {
          wrap.classList.remove("active");
        }
      }
    });
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
    var ver = "v0.6.0";
    if (typeof document !== "undefined") {
      var verEl = document.getElementById("footer-version-tag");
      if (verEl && verEl.textContent) ver = verEl.textContent.trim();
    }

    var winW = (typeof window !== "undefined" && window.innerWidth) ? window.innerWidth : 1280;
    var winH = (typeof window !== "undefined" && window.innerHeight) ? window.innerHeight : 800;

    var summary = {
      version: ver,
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

  function openFeedbackDialog() {
    var dlg = document.getElementById("feedback-dialog");
    if (!dlg) return;

    // Reset Form
    var form = document.getElementById("feedback-form");
    if (form) form.reset();
    selectFeedbackType("connection");
    updateFeedbackCharCount("");
    setElementDisplay("feedback-status", "none");
    setElementDisplay("feedback-form", "block");
    setElementDisplay("feedback-success-card", "none");

    var submitBtn = document.getElementById("btn-submit-feedback");
    var submitText = document.getElementById("btn-submit-feedback-text");
    if (submitBtn) submitBtn.disabled = false;
    if (submitText) submitText.textContent = (typeof t === "function") ? t("feedback_btn_submit") : "Submit";

    // Populate Diagnostic Glance
    var diag = buildDiagnosticSnapshot();
    var zh = (typeof isZh === "function") ? isZh() : true;
    var glanceText = (zh ? "系统 " : "System ") + diag.version + " · " + diag.platform + " · " + diag.node_count + (zh ? " 个节点" : " Nodes");
    setElementText("feedback-diag-glance", glanceText);

    if (typeof dlg.showModal === "function") {
      dlg.showModal();
    } else {
      dlg.setAttribute("open", "");
    }
  }

  function ownlineSubmitFeedback(e) {
    if (e && e.preventDefault) e.preventDefault();

    var msgEl = document.getElementById("feedback-message");
    var contactEl = document.getElementById("feedback-contact");
    var attachDiagEl = document.getElementById("feedback-attach-diag");
    var statusEl = document.getElementById("feedback-status");
    var submitBtn = document.getElementById("btn-submit-feedback");
    var submitText = document.getElementById("btn-submit-feedback-text");
    var zh = (typeof isZh === "function") ? isZh() : true;

    var message = (msgEl ? msgEl.value : "").trim();
    var contact = (contactEl ? contactEl.value : "").trim();
    var attachDiag = attachDiagEl ? attachDiagEl.checked : true;

    if (!message) {
      if (statusEl) {
        statusEl.textContent = zh ? "请填写反馈描述" : "Please enter a description";
        statusEl.style.color = "var(--bad)";
        statusEl.style.display = "block";
      }
      if (msgEl) msgEl.focus();
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    if (submitText) submitText.textContent = (typeof t === "function") ? t("feedback_submitting") : "Submitting...";
    if (statusEl) statusEl.style.display = "none";

    var payload = {
      type: _selectedFeedbackType,
      message: message,
      contact: contact,
      diagnostics: attachDiag ? buildDiagnosticSnapshot() : null
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
        if (submitText) submitText.textContent = (typeof t === "function") ? t("feedback_btn_submit") : "Submit";
        if (statusEl) {
          statusEl.textContent = (zh ? "提交失败：" : "Submit failed: ") + err.message;
          statusEl.style.color = "var(--bad)";
          statusEl.style.display = "block";
        }
      });
  }

  function ownlineCopyFeedbackAndDiag(btn) {
    var msgEl = document.getElementById("feedback-message");
    var contactEl = document.getElementById("feedback-contact");
    var zh = (typeof isZh === "function") ? isZh() : true;

    var message = (msgEl ? msgEl.value : "").trim() || (zh ? "(未填写描述)" : "(No description provided)");
    var contact = (contactEl ? contactEl.value : "").trim() || (zh ? "(未填写联系方式)" : "(No contact info)");
    var diag = buildDiagnosticSnapshot();

    var typeNamesZh = { connection: "⚡️ 连接与测速", client: "📱 客户端与导入", suggestion: "💡 功能建议", bug: "🐞 缺陷与其他" };
    var typeNamesEn = { connection: "⚡️ Speed & Connect", client: "📱 Client & Import", suggestion: "💡 Suggestions", bug: "🐞 Bugs & Other" };
    var typeTitle = zh ? (typeNamesZh[_selectedFeedbackType] || _selectedFeedbackType) : (typeNamesEn[_selectedFeedbackType] || _selectedFeedbackType);

    var report = "=== Evergreen · OwnLine " + (zh ? "快捷反馈报告" : "Feedback Report") + " ===\n";
    report += (zh ? "【类型】: " : "[Category]: ") + typeTitle + "\n";
    report += (zh ? "【描述】: " : "[Description]: ") + message + "\n";
    report += (zh ? "【联系方式】: " : "[Contact]: ") + contact + "\n";
    report += (zh ? "【系统环境】: " : "[Environment]: ") + diag.version + " (" + diag.platform + ")\n";
    report += (zh ? "【生成时间】: " : "[Generated At]: ") + diag.time + "\n\n";

    report += (zh ? "[节点状态]:\n" : "[Node Status]:\n");
    if (diag.nodes && diag.nodes.length) {
      diag.nodes.forEach(function (n) {
        var hostProbe = n.ok === true ? (n.ms + "ms") : (n.ok === false ? "异常" : "未测");
        var cnProbe = n.cn_ok === true ? (n.cn_ms + "ms") : (n.cn_ok === false ? "阻断" : "未测");
        report += "  - " + n.name + " (" + n.type + "): health=" + n.health + ", 主控探活=" + hostProbe + ", 国内探活=" + cnProbe + "\n";
      });
    } else {
      report += (zh ? "  (当前无节点)\n" : "  (No nodes connected)\n");
    }

    function onCopied() {
      if (typeof toast === "function") {
        toast((typeof t === "function") ? t("feedback_copied") : (zh ? "反馈与诊断快照已复制到剪贴板" : "Feedback & diagnostics copied to clipboard"));
      } else if (btn) {
        var orig = btn.textContent;
        btn.textContent = zh ? "已复制!" : "Copied!";
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
    window.selectFeedbackType = selectFeedbackType;
    window.updateFeedbackCharCount = updateFeedbackCharCount;
    window.ownlineSubmitFeedback = ownlineSubmitFeedback;
    window.ownlineCopyFeedbackAndDiag = ownlineCopyFeedbackAndDiag;
  }
})();
