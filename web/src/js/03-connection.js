  function setOtherCheckBusy(busy) {
    ["other-ip", "other-user", "other-ssh-port"].forEach(function(id) {
      document.getElementById(id).disabled = busy;
    });
    ["other-credential", "other-passphrase", "other-connect"].forEach(function(id) {
      document.getElementById(id).disabled = busy || !STATE.nodeCheckAvailable;
    });
  }

  function safeUrl(path) {
    if (!path || typeof path !== "string") return path;
    if (path.indexOf("http://") === 0 || path.indexOf("https://") === 0) return path;
    if (typeof window !== "undefined" && window.location && window.location.origin && window.location.origin !== "null") {
      return (path.charAt(0) === "/" ? window.location.origin : window.location.origin + "/") + path;
    }
    return path;
  }

  function clearOtherSecret() {
    otherPrivateKey = "";
    if (otherCheckController) {
      otherCheckController.abort();
      document.getElementById("other-connect-status").textContent = "已取消连接检查。";
    }
    otherCheckController = null;
    setOtherCheckBusy(false);
    var status = document.getElementById("other-key-status");
    if (status) status.textContent = "";
    var confirmBox = document.getElementById("node-install-confirm-box");
    if (confirmBox) confirmBox.style.display = "none";
    pendingNodeInstall = null;
  }

  function esc(s) {
    if (!s) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // 1. Input focus highlight
  function setupInputHighlights() {
    var inputs = document.querySelectorAll("input, textarea");
    inputs.forEach(function (inp) {
      function checkVal() {
        if (inp.value && inp.value.trim().length > 0) {
          inp.classList.add("has-val");
        } else {
          inp.classList.remove("has-val");
        }
      }
      inp.addEventListener("input", checkVal);
      inp.addEventListener("change", checkVal);
      checkVal();
    });
  }

  // 2. Scene routing (Dashboard vs Setup)
  var dashboardScrollY = 0;

  function switchScene(sceneName) {
    var vDash = document.getElementById("view-dashboard");
    var vSetup = document.getElementById("view-setup");
    if (!vDash || !vSetup) return;
    var btnRefresh = document.getElementById("btn-refresh-all");

    if (sceneName === "setup") {
      dashboardScrollY = window.scrollY || 0;
      vDash.style.display = "none";
      vSetup.style.display = "block";
      document.getElementById("section-logs").style.display = "none";
      if (btnRefresh) btnRefresh.style.display = "none";
      window.scrollTo({ top: 0, behavior: "auto" });
      document.getElementById("setup-title").focus({preventScroll:true});
    } else {
      // Clear unsaved credentials when leaving form without interrupting background operations.
      clearOtherSecret();
      ["tc-sid", "tc-skey", "other-credential", "other-passphrase"].forEach(function (id) {
        var input = document.getElementById(id);
        if (input) { input.value = ""; input.classList.remove("has-val"); }
      });
      vSetup.style.display = "none";
      vDash.style.display = "block";
      document.getElementById("section-logs").style.display = "";
      if (btnRefresh) btnRefresh.style.display = "";
      refreshState();
      fetchLogs();
      document.getElementById("btn-enter-setup").focus({preventScroll:true});
      window.scrollTo({ top: dashboardScrollY, behavior: "auto" });
    }
  }

  function initSceneRouter() {
    var btnEnter = document.getElementById("btn-enter-setup");
    var btnCancel = document.getElementById("btn-cancel-setup");

    if (btnEnter) {
      btnEnter.onclick = function () {
        switchScene("setup");
      };
    }

    if (btnCancel) {
      btnCancel.onclick = function () {
        switchScene("dashboard");
      };
    }
    var btnManage = document.getElementById("btn-manage-servers");
    if (btnManage) {
      btnManage.onclick = function () {
        var sec = document.getElementById("quota-section");
        if (sec) sec.open = true;
        var ql = document.getElementById("quota-list-container");
        if (ql) ql.scrollIntoView({behavior:"smooth", block:"start"});
      };
    }
  }

  // 3. Connection mode switch (Direct server vs Tencent Cloud)
  function initCloudParallelSwitch() {
    var tabTc = document.getElementById("tab-tc");
    var tabOther = document.getElementById("tab-other");
    var panelTc = document.getElementById("panel-tc");
    var panelOther = document.getElementById("panel-other");

    if (!tabTc || !tabOther) return;

    tabTc.onclick = function () {
      STATE.cloudMode = "tc";
      tabTc.classList.add("active");
      tabOther.classList.remove("active");
      tabTc.setAttribute("aria-pressed", "true");
      tabOther.setAttribute("aria-pressed", "false");
      if (panelTc) panelTc.style.display = "block";
      if (panelOther) panelOther.style.display = "none";
    };

    tabOther.onclick = function () {
      var fields = document.getElementById("ssh-connection-fields");
      var slot = document.getElementById("other-connection-slot");
      if (fields.parentElement !== slot) {
        clearOtherSecret();
        ["other-credential", "other-passphrase"].forEach(function (id) { document.getElementById(id).value = ""; });
        slot.appendChild(fields);
      }
      STATE.cloudMode = "other";
      tabOther.classList.add("active");
      tabTc.classList.remove("active");
      tabOther.setAttribute("aria-pressed", "true");
      tabTc.setAttribute("aria-pressed", "false");
      if (panelTc) panelTc.style.display = "none";
      if (panelOther) panelOther.style.display = "block";

    };
  }

  // 4. Copy AI agent prompt
  function setupAiPrompt() {
    var btn = document.getElementById("btn-copy-ai-prompt");
    var pre = document.getElementById("ai-prompt-text");
    if (!btn || !pre) return;

    btn.onclick = function () {
      var text = pre.textContent || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          var orig = btn.textContent;
          btn.textContent = "已复制";
          setTimeout(function () { btn.textContent = orig; }, 2500);
        });
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        document.body.removeChild(ta);
        var orig = btn.textContent;
        btn.textContent = "已复制";
        setTimeout(function () { btn.textContent = orig; }, 2500);
      }
    };
  }

  function initInstallCopy() {
    document.querySelectorAll(".install-guide").forEach(function (guide) {
      var btn = guide.querySelector(".copy-install-command");
      var status = guide.querySelector(".copy-install-status");
      var code = guide.querySelector("code");
      btn.onclick = function () {
        if (!navigator.clipboard || !navigator.clipboard.writeText) {
          status.textContent = "无法自动复制，请手动选择复制。";
          return;
        }
        navigator.clipboard.writeText(code.textContent).then(function () {
          status.textContent = "已复制";
        }).catch(function () {
          status.textContent = "复制失败，请手动选择复制。";
        });
      };
    });
  }

  function initOtherConnection() {
    var input = document.getElementById("other-credential");
    var button = document.getElementById("other-connect");
    var keyStatus = document.getElementById("other-key-status");
    var note = document.getElementById("other-connect-status");
    var resultBox = document.getElementById("other-check-result");
    var confirmBox = document.getElementById("node-install-confirm-box");
    var btnSubmit = document.getElementById("btn-submit-addnode");
    var submitStatus = document.getElementById("addnode-submit-status");

    function invalidateCheck() {
      resultBox.style.display = "none";
      if (confirmBox) confirmBox.style.display = "none";
      pendingNodeInstall = null;
      if (!otherCheckController && STATE.nodeCheckAvailable) note.textContent = "仅测试连接，尚未安装节点。";
    }
    ["other-ip", "other-user", "other-ssh-port", "other-passphrase"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", invalidateCheck);
    });
    input.addEventListener("paste", function (event) {
      var pasted = event.clipboardData && event.clipboardData.getData("text/plain");
      if (pasted && /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/.test(pasted)) {
        event.preventDefault();
        otherPrivateKey = pasted;
        input.value = "";
        keyStatus.textContent = "已粘贴 SSH 私钥";
        invalidateCheck();
      }
    });
    input.addEventListener("input", function () {
      otherPrivateKey = "";
      keyStatus.textContent = "";
      invalidateCheck();
    });
    button.onclick = async function () {
      var host = document.getElementById("other-ip").value.trim();
      var username = document.getElementById("other-user").value.trim();
      var port = document.getElementById("other-ssh-port").value.trim();
      var passphrase = document.getElementById("other-passphrase").value;
      var password = input.value;
      if (!otherPrivateKey && /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/.test(password)) {
        note.textContent = "请粘贴完整的 SSH 私钥。";
        return;
      }
      if (!host || !username || !/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535 || (!password && !otherPrivateKey)) {
        note.textContent = "请填写公网 IP 与登录凭据，并核对高级设置。";
        return;
      }
      var body = {host:host, username:username, ssh_port:Number(port), password:password, private_key:otherPrivateKey, passphrase:otherPrivateKey ? passphrase : ""};
      var pendingAuth = {
        ip: host,
        user: username,
        ssh_port: Number(port),
        pass: password,
        private_key: otherPrivateKey,
        auth_type: otherPrivateKey ? "key" : "password"
      };
      otherCheckController = new AbortController();
      var controller = otherCheckController;
      setOtherCheckBusy(true);
      resultBox.style.display = "none";
      note.textContent = "正在只读检测服务器连接...";
      async function requestCheck() {
        var checkUrl = typeof safeUrl === "function" ? safeUrl("/api/node/check") : "/api/node/check";
        var response = await fetch(checkUrl, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), signal:controller.signal});
        return response.json();
      }
      try {
        var data = await requestCheck();
        if (controller.signal.aborted) return;
        if (data.code === "HOST_KEY_CONFIRMATION" && /^SHA256:[A-Za-z0-9+/]{43}$/.test(data.fingerprint || "")) {
          if (document.getElementById("view-setup").style.display !== "block") return;
          if (!window.confirm("请通过云控制台或可信渠道核对服务器 SSH 指纹：\n\n" + data.fingerprint + "\n\n确认无误后继续连接？")) {
            note.textContent = "未确认服务器指纹，已停止连接。";
            return;
          }
          body.fingerprint = data.fingerprint;
          data = await requestCheck();
          if (controller.signal.aborted) return;
        }
        if (!data.ok || !data.result) {
          var msg = data.message || "连接检测未完成，请稍后重试。";
          if (/permission denied|auth|password/i.test(msg)) {
            msg = "认证失败：SSH 密码或密钥不正确。";
            if (typeof autoFixOffer === "function") autoFixOffer(host);
          } else if (/timed out|connection timed out|timeout/i.test(msg) || /port 22/i.test(msg)) {
            msg = "连接超时：SSH 端口不可达，请检查云防火墙或安全组。";
          } else if (/no route to host|network unreachable/i.test(msg)) {
            msg = "网络不可达：请检查公网 IP 或确认实例已开机。";
          }
          note.textContent = msg;
          return;
        }
        var item = data.result;
        var serviceNote = item.existing_singbox ? "检测到已有 sing-box 服务，未作改动。" : (!item.root || item.singbox_service === "unknown") ? "未能确认服务状态，尚未安装。" : "未检测到已有 sing-box，尚未安装。";
        resultBox.textContent = "连接检测通过 · " + (item.os || "未知系统") + " " + (item.version || "") + " · " + (item.architecture || "未知架构") + " · " + (item.root ? "root" : "非 root") + "。" + serviceNote + " " + (item.message || "");
        resultBox.style.display = "block";
        note.textContent = "只读检测已完成。";

        if (confirmBox && item.root && !item.existing_singbox && item.os !== "windows") {
          pendingNodeInstall = pendingAuth;
          var nameInput = document.getElementById("node-name-input");
          if (nameInput) nameInput.value = "节点-" + host;
          confirmBox.style.display = "block";
        }
      } catch (error) {
        if (error.name !== "AbortError") note.textContent = "连接检测未完成，请检查网络后重试。";
      } finally {
        body.password = ""; body.private_key = ""; body.passphrase = "";
        if (otherCheckController === controller) {
          input.value = ""; document.getElementById("other-passphrase").value = "";
          otherCheckController = null; otherPrivateKey = ""; keyStatus.textContent = "";
          setOtherCheckBusy(false);
        }
      }
    };

    if (btnSubmit) {
      btnSubmit.onclick = async function () {
        if (!pendingNodeInstall) {
          if (submitStatus) submitStatus.textContent = "请先通过服务器连接检测。";
          return;
        }
        var nameInput = document.getElementById("node-name-input");
        var roleSelect = document.getElementById("node-role-select");
        var nodeName = (nameInput && nameInput.value.trim()) || ("节点-" + pendingNodeInstall.ip);
        var nodeRole = (roleSelect && roleSelect.value) || "auto";

        btnSubmit.disabled = true;
        if (submitStatus) submitStatus.textContent = "正在启动安装任务...";

        try {
          var addUrl = typeof safeUrl === "function" ? safeUrl("/api/addnode") : "/api/addnode";
          var res = await fetch(addUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ip: pendingNodeInstall.ip,
              user: pendingNodeInstall.user,
              pass: pendingNodeInstall.pass,
              private_key: pendingNodeInstall.private_key,
              auth_type: pendingNodeInstall.auth_type,
              ssh_port: pendingNodeInstall.ssh_port || 22,
              port: 443,
              name: nodeName,
              role: nodeRole
            })
          });
          var resData = await res.json();
          if (!resData.ok || !resData.job) {
            if (submitStatus) submitStatus.textContent = "安装任务被拒绝：" + (resData.error || "未知错误");
            btnSubmit.disabled = false;
            return;
          }
          pendingNodeInstall = null;
          try { localStorage.setItem("sb_job", resData.job); } catch (_) {}
          if (confirmBox) confirmBox.style.display = "none";
          resultBox.style.display = "none";
          btnSubmit.disabled = false;
          if (submitStatus) submitStatus.textContent = "";
          switchScene("dashboard");
          initInstallProgress();
        } catch (e) {
          if (submitStatus) submitStatus.textContent = "启动安装时发生网络错误。";
          btnSubmit.disabled = false;
        }
      };
    }
  }

  // Legacy job identifiers contain no credentials. Never auto-restart an unknown job.
  function initInstallProgress() {
    var id = "";
    try { id = localStorage.getItem("sb_job") || ""; } catch (_) {}
    if (!/^[a-f0-9]{12}$/.test(id)) return;
    var box = document.getElementById("install-task");
    var title = document.getElementById("install-task-title");
    var message = document.getElementById("install-task-message");
    var refresh = document.getElementById("install-task-refresh");
    var dismiss = document.getElementById("install-task-dismiss");
    var timer = null, stopped = false, loading = false;
    box.style.display = "block";
    async function update() {
      if (stopped || loading) return;
      loading = true; refresh.disabled = true; dismiss.disabled = true;
      var controller = new AbortController();
      var requestTimeout = setTimeout(function () { controller.abort(); }, 12000);
      try {
        var jobUrl = typeof safeUrl === "function" ? safeUrl("/api/node/job?id=" + encodeURIComponent(id)) : "/api/node/job?id=" + encodeURIComponent(id);
        var response = await fetch(jobUrl, {cache:"no-store", signal:controller.signal});
        if (!response.ok) throw new Error("unknown");
        var job = await response.json();
        if (!job.ok) throw new Error("unknown");
        if (job.state === "queued" || job.state === "running") {
          var labels = ["准备环境", "连接目标服务器", "正在下载并安装", "启动节点服务", "校验端口连通性"];
          var step = Number.isInteger(job.step) && job.step >= 0 && job.step <= 4 ? job.step : 0;
          title.textContent = "正在安装节点"; message.textContent = labels[step] + "。离开此页面不会中断后台任务。";
          timer = setTimeout(update, 5000);
        } else if (job.state === "done") {
          title.textContent = job.delivery ? "安装就绪 · 私人专属资产已就绪" : "安装任务已结束";
          var baseMsg = job.health === "ok" ? "节点已通过连通性校验，可在主面板导入订阅。" : "节点尚未确认连通，请检查服务器防火墙与运行状态。";
          if (job.delivery && job.delivery.dashboard_url) {
            var d = job.delivery;
            message.textContent = baseMsg + " (专属后台: " + d.dashboard_url + ")";
            var srLink = (d.deep_links && d.deep_links.shadowrocket) ? '<a href="' + d.deep_links.shadowrocket + '" class="btn primary" style="font-size:12px;padding:4px 10px;text-decoration:none;">一键导入小火箭</a>' : '';
            var clashLink = (d.deep_links && d.deep_links.clash) ? '<a href="' + d.deep_links.clash + '" class="btn primary" style="font-size:12px;padding:4px 10px;text-decoration:none;">一键导入 Clash</a>' : '';
            message.innerHTML = baseMsg + '<div style="margin-top:10px;padding:10px;background:rgba(0,0,0,0.05);border-radius:6px;font-size:13px;line-height:1.6;">' +
              '<div><strong>专属后台：</strong><a href="' + d.dashboard_url + '" target="_blank" rel="noopener">' + d.dashboard_url + '</a></div>' +
              '<div><strong>初始账号：</strong><code>' + (d.username || 'admin') + '</code> ｜ <strong>初始密码：</strong><code>' + (d.temp_password || '已预设') + '</code></div>' +
              ((srLink || clashLink) ? ('<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">' + srLink + clashLink + '</div>') : '') +
              '</div>';
          } else {
            message.textContent = baseMsg;
          }
          dismiss.disabled = false;
          if (typeof refreshState === "function") refreshState();
        } else if (job.state === "error") {
          title.textContent = "安装未完成";
          var errDetail = job.error || "";
          var reasonText = "请先检查目标服务器状态后再重试。";
          if (/timeout|timed out|fetch|curl|download/i.test(errDetail)) {
            reasonText = "下载核心依赖超时，请检查目标服务器外网网络连通性。";
          } else if (/lock|dpkg|apt/i.test(errDetail)) {
            reasonText = "目标服务器软件包管理器被后台占用，请稍后再试。";
          } else if (/port|443|bind/i.test(errDetail)) {
            reasonText = "端口冲突：目标服务器 443 端口可能已被占用。";
          } else if (errDetail) {
            reasonText = "安装未完成：" + errDetail;
          }
          message.textContent = reasonText;
          dismiss.disabled = false;
        } else throw new Error("unknown");
      } catch (_) {
        title.textContent = "安装状态未知";
        message.textContent = "后台任务可能仍在运行，关闭提示不会停止后台任务。";
        dismiss.disabled = false;
      } finally { clearTimeout(requestTimeout); loading = false; refresh.disabled = false; }
    }
    refresh.onclick = function () { if (timer) clearTimeout(timer); update(); };
    dismiss.onclick = function () {
      stopped = true; if (timer) clearTimeout(timer);
      try { if (localStorage.getItem("sb_job") === id) localStorage.removeItem("sb_job"); } catch (_) {}
      box.style.display = "none";
    };
    update();
  }

  // 5. Client adaptation and links
