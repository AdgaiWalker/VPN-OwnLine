  // 7. Tencent Cloud panel interaction
  function initTencentPanel() {
    var btn = document.getElementById("btn-tc-read");
    var sidInp = document.getElementById("tc-sid");
    var skeyInp = document.getElementById("tc-skey");
    var status = document.getElementById("tc-read-status");
    var credentialFields = document.getElementById("tc-credential-fields");

    try { if (sessionStorage.getItem("ownline-tencent-credentials-collapsed") === "1") credentialFields.open = false; } catch (_) {}

    function keepCredentialsOpen() {
      credentialFields.open = true;
      try { sessionStorage.removeItem("ownline-tencent-credentials-collapsed"); } catch (_) {}
    }

    if (!btn) return;

    btn.onclick = function () {
      var sid = (sidInp ? sidInp.value : "").trim();
      var skey = (skeyInp ? skeyInp.value : "").trim();

      if (!sid || !skey) {
        if (!STATE.tencentConfigured) {
          keepCredentialsOpen();
          if (status) status.innerHTML = "<span style='color:var(--bad)'>请填写 SecretId 与 SecretKey</span>";
          return;
        }
      }


      btn.disabled = true;
      if (status) status.textContent = "正在读取轻量云实例列表...";
      STATE.tcServers = []; STATE.tcPickedIndex = -1;
      document.getElementById("tc-srv-section").style.display = "none";
      document.getElementById("tc-active-panel").style.display = "none";
      if (sidInp) { sidInp.value = ""; sidInp.classList.remove("has-val"); }
      if (skeyInp) { skeyInp.value = ""; skeyInp.classList.remove("has-val"); }

      var tcUrl = typeof safeUrl === "function" ? safeUrl("/api/tencent/instances") : "/api/tencent/instances";
      fetch(tcUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": STATE.csrfToken },
        body: JSON.stringify({ secret_id: sid, secret_key: skey })
      })
      .then(function (r) { if (!r.ok) throw new Error("request failed"); return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        if (d.error) {
          keepCredentialsOpen();
          if (status) status.innerHTML = "<span style='color:var(--bad)'>" + esc(d.error) + "</span>";
          return;
        }

        var srvs = d.instances || d.servers || [];
        if (d.incomplete_regions && d.incomplete_regions.length) {
          keepCredentialsOpen();
        } else {
          credentialFields.open = false;
          try { sessionStorage.setItem("ownline-tencent-credentials-collapsed", "1"); } catch (_) {}
        }
        STATE.tcServers = srvs;
        if (srvs.length) {
          if (status) status.innerHTML = "<span style='color:var(--ok)'>已发现 " + srvs.length + " 台轻量云实例</span>";
          renderTcServerList();
          if (status) status.textContent = "已发现 " + srvs.length + " 台轻量云实例，请选择目标主机。" + (d.incomplete_regions && d.incomplete_regions.length ? " 部分地域读取未完成。" : "");
        } else {
          if (status) status.textContent = d.incomplete_regions && d.incomplete_regions.length ? "部分地域读取未完成，未能确认实例列表。" : "未查询到可用的轻量云实例。";
        }
      })
      .catch(function () {
        keepCredentialsOpen();
        btn.disabled = false;
        STATE.tcServers = [];
        var section = document.getElementById("tc-srv-section");
        var selected = document.getElementById("tc-active-panel");
        if (section) section.style.display = "none";
        if (selected) selected.style.display = "none";
        if (status) status.textContent = "读取实例失败，请检查网络连接与 API 凭据权限。";
      });
    };

    var btnAutoCheck = document.getElementById("btn-tc-auto-check");
    if (btnAutoCheck) {
      btnAutoCheck.onclick = function () {
        var guide = document.getElementById("tc-install-guide");
        if (!guide) return;
        guide.open = true;
        guide.querySelector("summary").focus();
      };
    }
    var btnConnect = document.getElementById("btn-tc-connect");
    if (btnConnect) {
      btnConnect.onclick = function () {
        var server = STATE.tcServers[STATE.tcPickedIndex];
        var report = document.getElementById("tc-report");
        if (!server || !server.ip) {
          report.style.display = "block";
          report.textContent = "该实例没有可用的公网 IP，请检查实例网络详情。";
          return;
        }
        clearOtherSecret();
        ["other-credential", "other-passphrase"].forEach(function (id) { document.getElementById(id).value = ""; });
        var fields = document.getElementById("ssh-connection-fields");
        document.getElementById("tc-connection-slot").appendChild(fields);
        var address = document.getElementById("other-ip");
        address.value = server.ip;
        address.dispatchEvent(new Event("input", {bubbles:true}));
        report.style.display = "none";
        var credential = document.getElementById("other-credential");
        (credential.disabled ? address : credential).focus();
      };
    }

    if (STATE.tencentConfigured && (!STATE.tcServers || !STATE.tcServers.length)) {
      setTimeout(function () {
        if (btn && !btn.disabled && typeof btn.click === "function") {
          btn.click();
        }
      }, 300);
    }
  }

  function renderTcServerList() {
    var box = document.getElementById("tc-srvlist");
    var sec = document.getElementById("tc-srv-section");
    if (!box || !sec) return;

    if (!STATE.tcServers.length) {
      sec.style.display = "none";
      return;
    }

    sec.style.display = "block";
    box.innerHTML = STATE.tcServers.map(function (s, i) {
      var isSel = (STATE.tcPickedIndex === i);
      var badge = s.bundle ? (" · " + esc(s.bundle)) : "";
      var isRunning = (s.state === "RUNNING" || s.status === "RUNNING");
      var statusBadge = isRunning ? " · <span style='color:var(--ok)'>运行中</span>" : (" · <span style='color:var(--warn)'>" + esc(s.state || s.status || "未知") + "</span>");
      var regName = s.region_name || s.region || "未知地域";
      return "<button class='srvrow" + (isSel ? " sel" : "") + "' data-i='" + i + "' type='button'>" +
        "<span><b>" + esc(s.name || s.ip || s.public_ip) + "</b>" +
        "<small>" + esc(s.ip || s.public_ip || "无公网 IP") + " · " + esc(regName) + badge + statusBadge + "</small></span>" +
        "<i class='chk'></i></button>";
    }).join("");

    var rows = box.querySelectorAll(".srvrow");
    rows.forEach(function (r) {
      r.onclick = function () {
        var idx = parseInt(r.getAttribute("data-i"), 10);
        pickTcServer(idx);
      };
    });
  }

  function pickTcServer(idx) {
    var slot = document.getElementById("tc-connection-slot");
    var fields = document.getElementById("ssh-connection-fields");
    if (STATE.tcPickedIndex !== idx && fields && fields.parentElement === slot) {
      clearOtherSecret();
      ["other-credential", "other-passphrase"].forEach(function (id) { document.getElementById(id).value = ""; });
      document.getElementById("other-check-result").style.display = "none";
      var confirmBox = document.getElementById("node-install-confirm-box");
      if (confirmBox) confirmBox.style.display = "none";
      document.getElementById("other-connection-slot").appendChild(fields);
    }
    STATE.tcPickedIndex = idx;
    var rows = document.querySelectorAll("#tc-srvlist .srvrow");
    rows.forEach(function (r) {
      r.classList.toggle("sel", parseInt(r.getAttribute("data-i"), 10) === idx);
    });

    var panel = document.getElementById("tc-active-panel");
    var warnBox = document.getElementById("tc-warn");
    if (panel) panel.style.display = "block";

    var s = STATE.tcServers[idx];
    if (s && warnBox) {
      var isCn = (["北京", "广州", "上海", "南京", "成都", "深圳", "Beijing", "Guangzhou", "Shanghai", "Nanjing", "Chengdu", "Shenzhen"].some(function (c) {
        return (s.region || "").indexOf(c) >= 0;
      }));
      if (isCn) {
        warnBox.style.display = "block";
        warnBox.textContent = "该实例位于中国大陆境内，仅适合作为国内中转入口，无法直接作为出海落地节点。";
      } else {
        warnBox.style.display = "none";
        warnBox.innerHTML = "";
      }
    }

    var btnConnect = document.getElementById("btn-tc-connect");
    if (btnConnect && s && (s.ip || s.public_ip)) {
      if (typeof btnConnect.click === "function") btnConnect.click();
      else if (typeof btnConnect.onclick === "function") btnConnect.onclick();
    }
  }

