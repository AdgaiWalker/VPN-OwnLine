  function healthText(h) {
    var m = {
      port: "端口关闭",
      tls: "服务停止",
      proxy: "代理未就绪",
      role_mismatch: "机房不符",
      landing: "落地不可达",
      blocked: "疑似被墙阻断",
      timeout: "检测超时",
      unknown: "未验证"
    };
    return m[h] || "状态未知";
  }

  function paintStatus() {
    var total = NODES.length;
    var badCount = 0;
    var okCount = 0;
    var zh = (typeof isZh === 'function') ? isZh() : true;

    NODES.forEach(function (n, i) {
      var d = document.getElementById("d" + i), s = document.getElementById("s" + i);
      var st = STATUS[n.name];
      if (st && st.ok === false) {
        badCount++;
        if (d) d.className = "dot bad";
        if (s) s.textContent = st.reason === "port" ? (zh ? "端口关闭 · 阻断" : "Port Blocked") : (st.reason === "tls" ? (zh ? "服务未响应" : "No Response") : (zh ? "连接失败" : "Connection Failed"));
        return;
      }
      if (st && st.cn_ok === false) {
        badCount++;
        if (d) d.className = "dot bad";
        if (s) s.textContent = zh ? "国内直连不通 · 疑似被墙" : "Blocked in China";
        return;
      }
      var isHealthy = (st && st.ok === true) || n.health === "ok";
      if (isHealthy) {
        okCount++;
        if (d) d.className = "dot ok";
        var ms = (st && st.cn_ms != null) ? st.cn_ms : ((st && st.ms != null) ? st.ms : ((st && st.cn_latency != null) ? st.cn_latency : ((st && st.latency != null) ? st.latency : null)));
        var pingHtml = "";
        if (ms != null) {
          var cls = ms <= 200 ? "fast" : (ms <= 350 ? "medium" : "slow");
          var msNum = Math.round(Number(ms)) || 0;
          var isSelf = (st && st.self_probe) || false;
          var pingLabel = isSelf ? (msNum + (zh ? "ms (探针本机)" : "ms (local probe)")) : (msNum + "ms");
          var tip = isSelf
            ? (zh ? "当前节点为系统国内探测基准锚点（点击右侧 ⋯ 或卡片可更换）" : "Active domestic vantage anchor for latency measurement")
            : (st && st.vantage ? (zh ? ("经 [" + st.vantage + "] 观测基准机房测得") : ("Probed via [" + st.vantage + "]")) : "");
          var tipAttr = tip ? (' title="' + esc(tip) + '"') : '';
          pingHtml = '<span class="ping-pill ' + cls + '"' + tipAttr + '>' + pingLabel + '</span>';
        } else {
          pingHtml = '<span class="ping-pill fast">' + (zh ? "正常" : "OK") + '</span>';
        }
        var exitNotice = "";
        if (n.role !== "relay" && n.exit_ip && n.exit_ip !== n.host && n.exit_ip !== n.ip) {
          exitNotice = (zh ? ' · 出口 ' : ' · Egress ') + esc(n.exit_ip);
        }
        if (s) s.innerHTML = pingHtml + exitNotice;
        return;
      }
      var h = n.health;
      if (h && h !== "unknown") {
        badCount++;
        if (d) d.className = "dot bad";
        if (s) s.textContent = healthText(h);
        return;
      }
      if (d) d.className = "dot";
      if (s) s.textContent = n.source === "external" ? (zh ? "外部节点（未验证）" : "External Node (Unverified)") : (zh ? "未验证" : "Unverified");
    });

    var pill = document.getElementById("status-pill"), pillText = document.getElementById("status-text");
    if (pill && pillText) {
      if (total === 0) {
        pill.className = "pill-preview";
        pillText.textContent = zh ? "未连接节点" : "No Nodes Connected";
      } else if (badCount > 0) {
        pill.className = "pill-preview warn";
        pillText.textContent = zh ? (badCount + " 个节点异常") : (badCount + (badCount > 1 ? " Nodes Degraded" : " Node Degraded"));
      } else if (okCount > 0) {
        pill.className = "pill-preview ok";
        pillText.textContent = zh ? "运行正常" : "All Nodes Operational";
      } else {
        pill.className = "pill-preview";
        pillText.textContent = zh ? "检测中..." : "Checking…";
      }
    }
  }

  function renderNodes(nodes, status, quota) {
    var box = document.getElementById("nodes");
    if (!box) return;
    var zh = (typeof isZh === 'function') ? isZh() : true;
    if (!nodes || !nodes.length) {
      box.innerHTML = '<div class="small muted" style="padding:12px 0">' + (zh ? '暂未连接任何节点。' : 'No nodes connected yet.') + '<button type="button" class="tiny" style="margin-left:8px" onclick="switchScene(\'setup\')">' + (zh ? '+ 添加节点' : '+ Add Node') + '</button></div>';
      return;
    }
    var qData = quota || (typeof STATE !== "undefined" && STATE ? STATE.quota : null);
    var qMap = {};
    if (qData && Array.isArray(qData.guards)) {
      qData.guards.forEach(function (g) {
        if (g.ip) qMap[g.ip] = g;
      });
    }

    function deriveNodeState(n) {
      var host = n.host || n.ip;
      var st = (status && status[n.name]) || {};
      var isBad = (n.health && n.health !== "ok" && n.health !== "unknown") || (st && (st.ok === false || st.cn_ok === false));

      var lc = n.lifecycle || {};
      var expBadge = "";
      if (lc.state === "draining") {
        expBadge = '<span class="tag warn">' + esc(lc.badge_text || (zh ? "下线中" : "Draining")) + "</span>";
      } else if (lc.state === "expired") {
        expBadge = '<span class="tag bad">' + (zh ? "已过期" : "Expired") + '</span>';
      } else if (lc.state === "disabled" || n.enabled === false) {
        expBadge = '<span class="tag">' + (zh ? "已暂停" : "Paused") + '</span>';
      } else if (lc.days_left !== undefined && lc.days_left !== null && lc.days_left <= 15) {
        expBadge = '<span class="tag warn">' + lc.days_left + (zh ? "天到期" : "d left") + "</span>";
      } else if (n.expire_at) {
        var days = Math.ceil((new Date(n.expire_at).getTime() - Date.now()) / (86400 * 1000));
        if (days <= 0) expBadge = '<span class="tag bad">' + (zh ? "已过期" : "Expired") + '</span>';
        else if (days <= 15) expBadge = '<span class="tag warn">' + days + (zh ? "天到期" : "d left") + "</span>";
      }

      var hy2Node = (nodes || []).find(function(x) {
        return (x.host === host || x.ip === host) && (x.type === "hysteria2" || (x.name && x.name.indexOf("HY2") >= 0));
      });
      var isDomestic = (n.role === "relay" || n.role === "standalone" || n.country === "CN");
      var isOverseasExit = !isDomestic && n.source !== "external";
      var isMultiProtoHost = (host && (nodes || []).filter(function(x){ return (x.host || x.ip) === host; }).length > 1);
      var hasHy2 = isOverseasExit || isMultiProtoHost || n.type === "hysteria2" || (n.name && n.name.indexOf("HY2") >= 0) || typeof n.hy2_enabled === "boolean";
      var isHy2Active = hy2Node ? (hy2Node.enabled !== false) : (n.type === "hysteria2" ? (n.enabled !== false) : (n.hy2_enabled === true));

      var isBondedRelay = isDomestic && (n.role === "relay" && n.landing && n.landing.host);
      var targetText = "";
      if (isBondedRelay) {
        var targetHost = n.landing.host;
        var targetNode = (nodes || []).find(function (x) {
          return (x.host === targetHost || x.ip === targetHost) && x.type !== "hysteria2";
        });
        targetText = (targetNode && targetNode.name) || targetHost;
      }

      var qInfo = qMap[host] || null;
      if (!qInfo && (n.used_gb != null || n.total_gb != null)) {
        qInfo = { used_gb: n.used_gb, total_gb: n.total_gb, percent: n.percent, status: n.quota_status || "normal", control_supported: n.quota_control_managed === true };
      }

      return {
        host: host,
        st: st,
        isBad: isBad,
        expBadge: expBadge,
        hasHy2: hasHy2,
        isHy2Active: isHy2Active,
        isDomestic: isDomestic,
        isBondedRelay: isBondedRelay,
        targetText: targetText,
        qInfo: qInfo
      };
    }

    var hostCount = {};
    nodes.forEach(function (n) {
      var h = n.host || n.ip;
      if (h) hostCount[h] = (hostCount[h] || 0) + 1;
    });

    var renderedHosts = {};
    var htmlParts = [];

    nodes.forEach(function (n, i) {
      var m = deriveNodeState(n);
      var host = m.host;
      if (host && hostCount[host] > 1 && renderedHosts[host]) {
        htmlParts.push('<span id="d' + i + '" style="display:none"></span><span id="s' + i + '" style="display:none"></span>');
        return;
      }
      if (host && hostCount[host] > 1) {
        renderedHosts[host] = true;
      }

      var st = m.st;
      var isBad = m.isBad;
      var expBadge = m.expBadge;
      var hasHy2 = m.hasHy2;
      var isHy2Active = m.isHy2Active;
      var isDomestic = m.isDomestic;
      var isBondedRelay = m.isBondedRelay;
      var targetText = m.targetText;

      var protoBadges = "";
      if (hasHy2) {
        protoBadges = '<span class="tag ' + (isHy2Active ? 'ok' : 'muted') + '" style="cursor:pointer" onclick="window.ownlineToggleHy2ByIndex(' + i + ',' + (!isHy2Active) + ')" title="' + (zh ? ('点击' + (isHy2Active ? '关闭' : '开启') + '该服务器的 HY2 极速通道') : ('Click to ' + (isHy2Active ? 'disable' : 'enable') + ' HY2 turbo for this server')) + '">' + (isHy2Active ? (zh ? 'HY2 极速: 开启' : 'HY2 Turbo: On') : (zh ? 'HY2 极速: 关闭' : 'HY2 Turbo: Off')) + '</span><span class="tag" title="' + (zh ? 'VLESS Reality 稳定通道' : 'VLESS Reality Stable Channel') + '">' + (zh ? 'Reality 稳定' : 'Reality Stable') + '</span>';
      } else if (!isDomestic && n.source !== "external") {
        protoBadges = '<span class="tag" title="' + (zh ? 'VLESS Reality 稳定通道' : 'VLESS Reality Stable Channel') + '">' + (zh ? 'Reality 稳定' : 'Reality Stable') + '</span>';
      }

      var relayPill = "";
      var displayName = n.name;
      var detailLine = "";

      if (isBondedRelay) {
        displayName = (zh ? n.name + "专线 ➔ " : n.name + " Relay ➔ ") + targetText;
        relayPill = '<span class="tag ok" style="cursor:pointer" onclick="window.ownlineOpenRelayDialogByIndex(' + i + ')" title="' + (zh ? "点击更换中转落地目标" : "Click to change relay egress target") + '">' + (zh ? '极速防卡顿 · 落地 ' : 'Low-latency Relay · Egress ') + esc(targetText) + '</span>' +
          '<button class="btn tiny" style="margin-left:6px;font-size:11px;padding:1px 6px;height:24px" type="button" onclick="window.ownlineUnbindRelayByIndex(' + i + ')" title="' + (zh ? "解除中转加速，恢复为独立服务器" : "Unbind relay acceleration, restore as standalone") + '">' + (zh ? '解除中转' : 'Unbind') + '</button>';
        detailLine = '<div class="relay-pipeline">' +
          '<span class="pipeline-hop">' + (zh ? '入口 ' : 'Entry ') + '<b>' + esc(n.host || n.ip) + '</b></span>' +
          '<span class="pipeline-arrow"><svg class="ico" width="10" height="10" style="vertical-align:-1px"><use href="#i-arrow-right"/></svg> ' + (zh ? '专线跳板' : 'Relay Hop') + '</span>' +
          '<span class="pipeline-hop">' + (zh ? '落地 ' : 'Egress ') + '<b>' + esc(targetText) + '</b></span>' +
          ' · ' + (n.port || 443) + ' · <span id="s' + i + '">' + (zh ? "检测中..." : "Checking…") + '</span>' +
        '</div>';
      } else if (isDomestic) {
        displayName = n.name;
        var isVantage = (st && st.self_probe);
        var vantageBtn = isVantage
          ? ('<span class="tag ok" style="cursor:pointer;margin-left:6px" onclick="window.ownlineSetProbeVantageByIndex(' + i + ')" title="' + (zh ? '当前为系统出海可用性探测基准机房' : 'Active probe vantage') + '">' + (zh ? '探测基准' : 'Probe Vantage') + '</span>')
          : ('<button class="btn tiny" style="margin-left:6px;font-size:11px;padding:2px 7px;height:24px" type="button" onclick="window.ownlineSetProbeVantageByIndex(' + i + ')" title="' + (zh ? '将该机房设为国内可用性探测基准' : 'Set as domestic probe vantage') + '">' + (zh ? '设为探测基准' : 'Set as Vantage') + '</button>');
        relayPill = '<span class="tag">' + (zh ? '国内独立服务器' : 'Domestic Standalone') + '</span>' +
          '<button class="btn tiny primary" style="margin-left:6px;font-size:11.5px;padding:2px 8px;height:24px" type="button" onclick="window.ownlineOpenRelayDialogByIndex(' + i + ')">' + (zh ? '＋ 设为中转加速' : '+ Enable Relay') + '</button>' + vantageBtn;
        detailLine = (zh ? "国内入口: " : "Entry: ") + esc(n.host || n.ip) + " · " + (n.port || 443) + ' · <span id="s' + i + '">' + (zh ? "检测中..." : "Checking…") + '</span> · ' + (zh ? '尚未绑定海外落地' : 'Not bound to egress');
      } else {
        detailLine = esc(n.host || n.ip) + " · " + (n.port || 443) + ' · <span id="s' + i + '">' + (zh ? "检测中..." : "Checking…") + '</span>';
      }

      var ispPill = "";
      if (n.isp) {
        var ispHost = esc(n.isp.server) + ":" + (n.isp.server_port || "");
        ispPill = '<span class="tag ok" style="cursor:pointer" onclick="window.ownlineMountIsp(' + i + ')" title="' + (zh ? '已挂载静态住宅 IP 出口（点击修改或解绑）' : 'Mounted static residential IP egress (click to edit/unmount)') + '"><svg class="ico" width="13" height="13" style="vertical-align:-2px;margin-right:4px"><use href="#i-home"/></svg>' + (zh ? ('住宅 IP · ' + ispHost) : ('Residential Egress: ' + ispHost)) + '</span>';
      } else if (n.role !== "relay") {
        ispPill = '<span class="tag isp-add" style="cursor:pointer" onclick="window.ownlineMountIsp(' + i + ')" title="' + (zh ? '点击绑定静态住宅 IP 出口' : 'Click to mount static residential IP egress') + '"><svg class="ico" width="12" height="12" style="vertical-align:-1px;margin-right:3px"><use href="#i-plus"/></svg>' + (zh ? '绑定住宅 IP' : 'Mount ISP') + '</span>';
      }

      var qInfo = m.qInfo;
      var quotaRow = "";
      if (qInfo && qInfo.total_gb != null && Number(qInfo.total_gb) > 0) {
        var usedNum = Number(qInfo.used_gb || 0);
        var totalNum = Number(qInfo.total_gb || 0);
        var pctNum = qInfo.percent != null ? Number(qInfo.percent) : Math.round((usedNum / totalNum) * 100);
        var remNum = Math.max(0, totalNum - usedNum);
        var isWarnQ = pctNum >= 75 && pctNum < 85;
        var isTrippedQ = pctNum >= 85 || qInfo.status === "tripped";
        var barColor = isTrippedQ ? "var(--apple-red)" : (isWarnQ ? "var(--apple-amber)" : "var(--apple-blue)");
        var barW = Math.max(0, Math.min(100, pctNum));
        var noteBadge = isTrippedQ ? ('<span class="tag bad" style="margin-left:4px">' + (zh ? '已触发保护' : 'Protection Tripped') + '</span>') : (qInfo.control_supported === false ? ('<span class="tag" style="margin-left:4px">' + (zh ? '仅告警' : 'Alert Only') + '</span>') : "");
        var quotaRoleTip = n.role === "relay" ? (' <span class="muted" style="font-size:11px">' + (zh ? '(专线跳板)' : '(Relay Hop)') + '</span>') : '';

        quotaRow = '<div class="node-quota-row">' +
          '<div class="node-quota-bar">' +
            '<i style="width:' + barW + '%;background:' + barColor + '"></i>' +
          '</div>' +
          '<span class="node-quota-text">' +
            '<strong>' + (Math.round(usedNum * 10) / 10) + '</strong> / ' + Math.round(totalNum) + ' GB <span class="muted">(' + Math.round(pctNum) + '%)</span> · ' + (zh ? '剩余 <strong>' : 'Remaining <strong>') + Math.round(remNum) + ' GB</strong>' +
          '</span>' + noteBadge + quotaRoleTip +
        '</div>';
      } else if (qInfo && qInfo.used_gb != null) {
        quotaRow = '<div class="node-quota-row">' +
          '<span class="node-quota-text">' + (zh ? '本月已统计：<strong>' : 'Monthly Usage: <strong>') + (Math.round(Number(qInfo.used_gb) * 10) / 10) + ' GB</strong> <span class="muted">' + (zh ? '（未配置流量包上限）' : '(No traffic limit set)') + '</span></span>' +
        '</div>';
      }
      var quotaRow = "";
      if (qInfo && qInfo.total_gb != null && Number(qInfo.total_gb) > 0) {
        var usedNum = Number(qInfo.used_gb || 0);
        var totalNum = Number(qInfo.total_gb || 0);
        var pctNum = qInfo.percent != null ? Number(qInfo.percent) : Math.round((usedNum / totalNum) * 100);
        var remNum = Math.max(0, totalNum - usedNum);
        var isWarnQ = pctNum >= 75 && pctNum < 85;
        var isTrippedQ = pctNum >= 85 || qInfo.status === "tripped";
        var barColor = isTrippedQ ? "var(--apple-red)" : (isWarnQ ? "var(--apple-amber)" : "var(--apple-blue)");
        var barW = Math.max(0, Math.min(100, pctNum));
        var noteBadge = isTrippedQ ? ('<span class="tag bad" style="margin-left:4px">' + (zh ? '已触发保护' : 'Protection Tripped') + '</span>') : (qInfo.control_supported === false ? ('<span class="tag" style="margin-left:4px">' + (zh ? '仅告警' : 'Alert Only') + '</span>') : "");
        var quotaRoleTip = n.role === "relay" ? (' <span class="muted" style="font-size:11px">' + (zh ? '(专线跳板)' : '(Relay Hop)') + '</span>') : '';

        quotaRow = '<div class="node-quota-row">' +
          '<div class="node-quota-bar">' +
            '<i style="width:' + barW + '%;background:' + barColor + '"></i>' +
          '</div>' +
          '<span class="node-quota-text">' +
            '<strong>' + (Math.round(usedNum * 10) / 10) + '</strong> / ' + Math.round(totalNum) + ' GB <span class="muted">(' + Math.round(pctNum) + '%)</span> · ' + (zh ? '剩余 <strong>' : 'Remaining <strong>') + Math.round(remNum) + ' GB</strong>' +
          '</span>' + noteBadge + quotaRoleTip +
        '</div>';
      } else if (qInfo && qInfo.used_gb != null) {
        quotaRow = '<div class="node-quota-row">' +
          '<span class="node-quota-text">' + (zh ? '本月已统计：<strong>' : 'Monthly Usage: <strong>') + (Math.round(Number(qInfo.used_gb) * 10) / 10) + ' GB</strong> <span class="muted">' + (zh ? '（未配置流量包上限）' : '(No traffic limit set)') + '</span></span>' +
        '</div>';
      }

      var advHtml = "";
      if (isBad) {
        var advTitle = "";
        var advReason = "";
        var advCls = "adv error";
        var advBtns = [];

        var hasDomesticRelay = (nodes || []).some(function (x) {
          var isDom = (x.role === "relay" || x.role === "standalone" || x.country === "CN");
          return isDom && !(x.landing && x.landing.host);
        });

        if (st && st.cn_ok === false) {
          advCls = "adv error warn";
          advTitle = zh ? "国内直连不通 · 疑似被墙" : "Blocked in China";
          advReason = zh ? "国内网络握手被阻断。建议绑定国内专线中转跳板，或切换为 HY2 极速通道。" : "Handshake from China blocked. Recommend binding to a domestic relay or enabling HY2.";
          if (!isDomestic && hasDomesticRelay) {
            advBtns.push('<button type="button" class="adv-btn primary" onclick="window.ownlineBindDomesticRelayFor(\'' + esc(n.host || n.ip) + '\')"><svg class="ico" width="11" height="11"><use href="#i-plus"/></svg>' + (zh ? "绑定专线跳板" : "Bind Relay") + '</button>');
          }
          if (hasHy2 && !isHy2Active) {
            advBtns.push('<button type="button" class="adv-btn" onclick="window.ownlineToggleHy2ByIndex(' + i + ', true)">' + (zh ? "开启 HY2 极速" : "Enable HY2") + '</button>');
          }
        } else if (st && st.reason === "port") {
          advTitle = zh ? "服务未响应 · 端口阻断" : "Port Blocked";
          advReason = zh ? "无法连接节点 " + (n.port || 443) + " 端口。请确认服务器开机并在云安全组放行该端口。" : "Cannot reach port " + (n.port || 443) + ". Please check cloud firewall security group.";
          advBtns.push('<button type="button" class="adv-btn" onclick="window.ownlineEditNodeByIndex(' + i + ')">' + (zh ? "修改端口" : "Edit Port") + '</button>');
        } else if (st && st.reason === "tls") {
          advTitle = zh ? "安全握手失败 · 证书异常" : "TLS Handshake Failed";
          advReason = zh ? "TCP 端口已通但 TLS 握手失败。建议重置 Reality 密钥或同步服务器时钟。" : "TCP port reachable but TLS handshake failed. Resetting keys or syncing clock is recommended.";
          if (n.source !== "external") {
            advBtns.push('<button type="button" class="adv-btn" onclick="window.ownlineRotateKeyByIndex(' + i + ')">' + (zh ? "重置密钥" : "Reset Key") + '</button>');
          }
        } else {
          advTitle = (n.advice && n.advice.text) || (zh ? "连接异常" : "Connection Error");
          advReason = (n.advice && n.advice.reason) || (st && st.reason) || (zh ? "请检查防火墙端口或节点运行状态" : "Please check firewall port or node status");
        }

        if (n.source !== "external") {
          advBtns.push('<button type="button" class="adv-btn" onclick="window.ownlineRecheckNode(\'' + esc(n.name) + '\')"><svg class="ico" width="11" height="11"><use href="#i-refresh"/></svg>' + (zh ? "重新检测" : "Recheck") + '</button>');
        }

        advHtml = '<div class="' + advCls + '">' +
          '<div class="adv-text">' +
            '<div class="adv-title"><svg class="ico" width="13" height="13" style="vertical-align:-2px"><use href="#i-alert"/></svg> ' + esc(advTitle) + '</div>' +
            '<span>' + esc(advReason) + '</span>' +
          '</div>' +
          (advBtns.length ? ('<div class="adv-actions">' + advBtns.join("") + '</div>') : '') +
        '</div>';
      }

      var statusBadges = (n.isp ? ispPill : "") + (isBondedRelay ? ('<span class="tag ok">' + (zh ? '专线加速' : 'Relay') + '</span>') : "") + (hasHy2 && isHy2Active ? ('<span class="tag ok" style="font-size:11px" title="' + (zh ? 'HY2 极速通道已启用' : 'HY2 Turbo Active') + '">HY2</span>') : "");
      var drawerActions = protoBadges + relayPill + (!n.isp ? ispPill : ('<button class="btn tiny" type="button" onclick="event.stopPropagation();window.ownlineMountIsp(' + i + ')">' + (zh ? '住宅 IP 详情' : 'ISP Config') + '</button>'));

      htmlParts.push('<div class="node" id="node-row-' + i + '">' +
        '<div class="node-main" onclick="window.ownlineToggleNodeDrawer(' + i + ')">' +
          '<span class="dot" id="d' + i + '"></span>' +
          '<div class="nmeta"><b>' + esc(displayName) + (n.source === "external" ? '<span class="tag">' + (zh ? '外部' : 'External') + '</span>' : "") + expBadge + statusBadges + "</b>" +
          "<small>" + detailLine + "</small>" +
          quotaRow +
          advHtml + "</div>" +
          '<button class="more" type="button" aria-label="' + (zh ? '更多操作' : 'More options') + '" onclick="event.stopPropagation();window.ownlineToggleNodeDrawer(' + i + ')"><svg class="ico" width="16" height="16"><use href="#i-more"/></svg></button>' +
        '</div>' +
        '<div class="node-drawer" id="node-drawer-' + i + '" style="display:none">' +
          '<div class="drawer-group">' + drawerActions + '</div>' +
          '<button class="btn tiny" type="button" onclick="event.stopPropagation();window.ownlineNodeMenu(' + i + ')">' + (zh ? '更多选项…' : 'More…') + '</button>' +
        '</div>' +
      '</div>');
    });

    box.innerHTML = htmlParts.join("");
    paintStatus();
  }

  function nodeMenu(i) {
    var n = NODES[i], st = STATUS[n.name];
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var items = [];

    items.push({label: zh ? "修改名称与端口" : "Edit Name & Port", id: "edit"});

    var toggleLabel = (n.enabled === false)
      ? (zh ? "恢复使用" : "Enable Node")
      : (zh ? "暂停使用" : "Pause Node");
    items.push({label: toggleLabel, id: "toggle"});

    var isDom = (n.role === "relay" || n.role === "standalone" || n.country === "CN");
    var isBonded = (isDom && n.role === "relay" && n.landing && n.landing.host);
    if (isBonded) {
      items.push({label: zh ? "解除中转加速（恢复独立）" : "Unbind Relay (Restore Standalone)", id: "unbind_relay"});
      items.push({label: zh ? "更换中转落地目标" : "Change Egress Target", id: "bind_relay"});
      items.push({label: zh ? "设为国内探测基准锚点" : "Set as Domestic Probe Vantage", id: "set_vantage"});
    } else if (isDom) {
      items.push({label: zh ? "设为中转加速专线" : "Configure as Relay Node", id: "bind_relay"});
      items.push({label: zh ? "设为国内探测基准锚点" : "Set as Domestic Probe Vantage", id: "set_vantage"});
    } else {
      var ispLabel = n.isp
        ? (zh ? "解绑住宅 IP" : "Unmount Residential IP")
        : (zh ? "绑定住宅 IP" : "Mount Residential IP");
      items.push({label: ispLabel, id: "isp"});
    }

    items.push({label: zh ? "设置到期提醒" : "Set Expiration Notice", id: "lifecycle"});

    if (n.source !== "external") {
      items.push({label: zh ? "重置密钥（断开所有设备）" : "Reset Key (Disconnect All Devices)", id: "rotate"});
    }

    items.push({label: zh ? "删除节点" : "Delete Node", id: "del", danger: true});

    var ms = (st && st.cn_ms != null) ? st.cn_ms : ((st && st.ms != null) ? st.ms : null);
    var statusSummary = "";
    if (n.source === "external") {
      statusSummary = zh ? "外部订阅节点" : "External Subscription Node";
    } else if (st && st.ok === false) {
      statusSummary = zh ? "服务异常 · 端口阻断" : "Offline · Port Blocked";
    } else if (st && st.cn_ok === false) {
      statusSummary = zh ? "国内直连不通" : "Unreachable from China";
    } else if (st && st.ok) {
      statusSummary = ms != null ? (zh ? ("在线 · 延迟 " + ms + "ms") : ("Online · " + ms + "ms")) : (zh ? "在线" : "Online");
    } else {
      statusSummary = zh ? "未验证" : "Unverified";
    }
    var subtext = (n.host || n.ip) + (zh ? " · 端口 " : " · Port ") + (n.port || 443) + "\n" + statusSummary;

    choose(n.name, subtext, items).then(function (k) {
      var item = items[k];
      if (!item) return;
      var act = item.id;
      if (act === "edit") editNode(i);
      else if (act === "toggle") toggleNode(i);
      else if (act === "drill") drillRelaySwitch(i);
      else if (act === "bind_relay") openRelayDialog(n.name, n.host || n.ip);
      else if (act === "unbind_relay") unbindRelay(n.name);
      else if (act === "set_vantage") setProbeVantage(n.name);
      else if (act === "toggle_hy2") {
        var host = n.host || n.ip;
        var hy2Node = (NODES || []).find(function(x) {
          return (x.host === host || x.ip === host) && (x.type === "hysteria2" || (x.name && x.name.indexOf("HY2") >= 0));
        });
        var isHy2Active = hy2Node ? (hy2Node.enabled !== false) : (n.type === "hysteria2" ? (n.enabled !== false) : (n.hy2_enabled === true));
        toggleHy2(n.name, n.host || n.ip, !isHy2Active);
      }
      else if (act === "isp") mountIsp(i);
      else if (act === "lifecycle") setNodeLifecycle(i);
      else if (act === "rotate") rotateKey(i);
      else if (act === "del") delNode(i);
    });
  }

  function drillRelaySwitch(i) {
    var n = NODES[i];
    if (!n || n.role !== "relay") return;
    var lp = n.landing_policy || {};
    var curTarget = lp.active_target || (n.landing && n.landing.host) || "";
    var candidates = (NODES || []).filter(function (x) {
      var host = x.host || x.ip;
      return host && host !== curTarget && x.role !== "relay" && x.role !== "standalone" && x.type !== "hysteria2";
    });
    if (!candidates.length) {
      dialog({title: "暂无备选落地节点", message: "请先添加至少两台海外出口服务器后再切换中转落地。", cancelText: null, confirmText: "确定"});
      return;
    }
    var nextNode = candidates[0];
    var nextTarget = nextNode.host || nextNode.ip;
    var nextName = (nextNode.name || nextTarget) + " (" + nextTarget + ")";

    dialog({
      title: "切换中继落地出口",
      message: '将节点 "' + n.name + '" 的出口落地切换至：' + nextName + '？\n\n切换时将同步更新远端转发配置并验证真实出网。',
      confirmText: "切换出口",
      cancelText: "取消"
    }).then(function (y) {
      if (!y) return;
      jsonRequest("/api/relay/switch", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: n.name, target: nextTarget})
      }).then(function (d) {
        if (!d.ok) { dialog({title: "切换失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
        dialog({title: "切换成功", message: "中继出口已切换至 " + nextName + "。", cancelText: null, confirmText: "确定"}).then(function () { refreshState(); });
      }).catch(function (e) { dialog({title: "切换失败", message: String(e), cancelText: null, confirmText: "确定"}); });
    });
  }

  function setNodeLifecycle(i) {
    var n = NODES[i];
    var curExp = (n.lifecycle && n.lifecycle.expire_at) || n.expire_at || "";
    formSheet('设置到期提醒 · "' + n.name + '"', [
      {label: "到期日期（如 2026-12-31）", value: curExp, ph: "年-月-日（留空为长期有效）"},
      {label: "节点状态（active 正常 / draining 下线排空）", value: (n.lifecycle && n.lifecycle.state) || "active", ph: "draining 会将节点移出订阅"}
    ], "保存").then(function (vals) {
      if (!vals) return;
      var exp = vals[0].trim();
      var st = vals[1].trim();
      jsonRequest("/api/editnode", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: n.name, expire_at: exp, lifecycle: {expire_at: exp, state: st}})
      }).then(function (d) {
        if (!d.ok) { dialog({title: "更新失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
        dialog({title: "到期设置已更新", message: "节点状态已同步，客户端刷新订阅后生效。", cancelText: null, confirmText: "确定"}).then(function () { refreshState(); });
      }).catch(function (e) { dialog({title: "更新失败", message: String(e), cancelText: null, confirmText: "确定"}); });
    });
  }

  function toggleNode(i) {
    var n = NODES[i];
    var willEnable = (n.enabled === false);
    jsonRequest("/api/editnode", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: n.name, enabled: willEnable})
    }).then(function (d) {
      if (!d.ok) { dialog({title: "操作失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
      dialog({
        title: willEnable ? "节点已恢复" : "节点已暂停",
        message: willEnable ? "已重新加入客户端订阅。" : "已从客户端订阅中隐藏，客户端刷新后将不再连接该节点。",
        cancelText: null,
        confirmText: "确定"
      }).then(function () { refreshState(); });
    }).catch(function (e) { dialog({title: "操作失败", message: String(e), cancelText: null, confirmText: "确定"}); });
  }

  function mountIsp(i) {
    var n = NODES[i];
    if (!n) return;
    var currentIsp = n.isp || null;
    var currentDesc = "";
    if (currentIsp) {
      currentDesc = '<div style="background:var(--accent-soft);border:1px solid var(--accent);border-radius:6px;padding:8px 10px;margin-bottom:12px;font-size:12.5px">' +
        '<b>当前住宅出口：</b><br>' +
        '<code style="font-size:12px;color:var(--accent);word-break:break-all">' +
        esc((currentIsp.type || 'socks') + '://' + (currentIsp.username ? (currentIsp.username + '@') : '') + currentIsp.server + ':' + currentIsp.server_port) +
        '</code></div>';
    }

    var content = '<h2>住宅 IP 出口 · "' + esc(n.name) + '"</h2>' +
      '<p class="small muted" style="margin-bottom:12px;line-height:1.5">' +
      '所有经由此节点的流量将通过静态住宅代理出网，降低 ChatGPT 与流媒体平台的风控拦截概率。' +
      '</p>' +
      currentDesc +
      '<div style="margin-bottom:12px">' +
        '<label for="isp-input-url" style="display:block;font-size:13px;font-weight:600;margin-bottom:4px">代理连接串</label>' +
        '<input id="isp-input-url" type="text" placeholder="例如 socks5://user:pass@198.51.100.99:1080 或 http://..." style="width:100%;padding:8px 10px;border:1px solid var(--line);background:var(--surface-card);border-radius:4px;font-size:13px">' +
        '<div class="small muted" style="margin-top:6px;line-height:1.4">需要静态住宅 IP？可前往 <a href="https://www.webshare.io" target="_blank" rel="noopener noreferrer" style="color:var(--apple-blue);text-decoration:underline">Webshare</a>（选择「Static Residential」静态住宅）。</div>' +
      '</div>' +
      '<details style="margin-bottom:14px;font-size:12.5px;color:var(--muted)">' +
        '<summary style="cursor:pointer;margin-bottom:8px">手动填写服务器与端口</summary>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">' +
          '<div><label style="display:block;font-size:11px;margin-bottom:2px">服务器地址 / IP</label><input id="isp-manual-host" type="text" value="' + esc((currentIsp && currentIsp.server) || "") + '" placeholder="例如 198.51.100.99" style="width:100%;padding:6px 8px;border:1px solid var(--line);background:var(--surface-card)"></div>' +
          '<div><label style="display:block;font-size:11px;margin-bottom:2px">端口</label><input id="isp-manual-port" type="number" value="' + esc((currentIsp && currentIsp.server_port) || "") + '" placeholder="例如 10808" style="width:100%;padding:6px 8px;border:1px solid var(--line);background:var(--surface-card)"></div>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">' +
          '<div><label style="display:block;font-size:11px;margin-bottom:2px">账号</label><input id="isp-manual-user" type="text" value="' + esc((currentIsp && currentIsp.username) || "") + '" placeholder="选填" style="width:100%;padding:6px 8px;border:1px solid var(--line);background:var(--surface-card)"></div>' +
          '<div><label style="display:block;font-size:11px;margin-bottom:2px">密码</label><input id="isp-manual-pass" type="password" value="' + esc((currentIsp && currentIsp.password) || "") + '" placeholder="选填" style="width:100%;padding:6px 8px;border:1px solid var(--line);background:var(--surface-card)"></div>' +
        '</div>' +
      '</details>' +
      '<div id="isp-err" class="small" style="color:var(--bad);display:none;margin-bottom:8px"></div>' +
      '<div class="sheetbtns" style="margin-top:14px">' +
        '<button type="button" class="sbtn cancel">取消</button>' +
        (currentIsp ? '<button type="button" class="sbtn danger" id="isp-unbind-btn">解绑（恢复机房直连）</button>' : '') +
        '<button type="button" class="sbtn ok" id="isp-save-btn">保存</button>' +
      '</div>';

    new Promise(function (resolve) {
      var close = mountSheet(content, resolve, "#isp-input-url");
      var active = document.querySelector("dialog.sheet[open]");
      if (!active) return;
      var cancelBtn = active.querySelector(".sbtn.cancel");
      if (cancelBtn) cancelBtn.addEventListener("click", function () { close(null); });

      var unbindBtn = active.querySelector("#isp-unbind-btn");
      if (unbindBtn) {
        unbindBtn.addEventListener("click", function () {
          close("unbind");
        });
      }

      var saveBtn = active.querySelector("#isp-save-btn");
      var errDiv = active.querySelector("#isp-err");
      function showErr(msg) {
        if (!errDiv) return;
        errDiv.textContent = msg;
        errDiv.style.display = "";
      }

      if (saveBtn) {
        saveBtn.addEventListener("click", function () {
          var url = (active.querySelector("#isp-input-url").value || "").trim();
          var host = (active.querySelector("#isp-manual-host").value || "").trim();
          var port = (active.querySelector("#isp-manual-port").value || "").trim();
          var user = (active.querySelector("#isp-manual-user").value || "").trim();
          var pass = (active.querySelector("#isp-manual-pass").value || "").trim();

          if (url) {
            close({url: url});
            return;
          }
          if (host && port) {
            var pNum = parseInt(port, 10);
            if (isNaN(pNum) || pNum < 1 || pNum > 65535) {
              showErr("端口必须是 1 到 65535 之间的整数");
              return;
            }
            var ispObj = {
              type: "socks",
              server: host,
              server_port: pNum
            };
            if (user) ispObj.username = user;
            if (pass) ispObj.password = pass;
            close({isp: ispObj});
            return;
          }
          showErr("请粘贴代理连接串，或在下方填写服务器地址与端口");
        });
      }
    }).then(function (result) {
      if (!result) return;
      if (location.protocol === "file:") {
        if (result === "unbind") {
          delete n.isp;
          renderNodes(NODES, STATUS);
          dialog({title: "解绑成功", message: "已恢复为机房原生直连出网（本地演示模拟）。", cancelText: null, confirmText: "确定"});
          return;
        }
        var mockIsp = result.isp;
        if (result.url) {
          try {
            var m = result.url.match(/^(?:(socks5?|https?):\/\/)?(?:([^:@]+)(?::([^@]+))?@)?([^:\/]+):(\d+)/i);
            if (m) {
              mockIsp = {
                type: m[1] && m[1].toLowerCase().indexOf("http") >= 0 ? "http" : "socks",
                server: m[4],
                server_port: parseInt(m[5], 10)
              };
              if (m[2]) mockIsp.username = decodeURIComponent(m[2]);
              if (m[3]) mockIsp.password = decodeURIComponent(m[3]);
            } else {
              mockIsp = {type: "socks", server: "198.51.100.88", server_port: 10808};
            }
          } catch (e) {
            mockIsp = {type: "socks", server: "198.51.100.88", server_port: 10808};
          }
        }
        n.isp = mockIsp;
        renderNodes(NODES, STATUS);
        dialog({title: "挂载成功", message: "静态住宅 IP 出口已生效（本地演示模拟）。\n经由此节点的流量将通过住宅代理出网。", cancelText: null, confirmText: "确定"});
        return;
      }

      if (result === "unbind") {
        dialog({
          title: "确认解绑住宅 IP？",
          message: "解绑后将恢复为服务器机房直连出网。",
          confirmText: "确认解绑",
          danger: true
        }).then(function (yes) {
          if (!yes) return;
          jsonRequest("/api/editnode", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name: n.name, isp: null})
          }).then(function (d) {
            if (!d.ok) {
              dialog({title: "解绑失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"});
              return;
            }
            dialog({title: "解绑成功", message: "已恢复为服务器机房直连出网。", cancelText: null, confirmText: "确定"}).then(function () {
              refreshState();
            });
          }).catch(function (e) {
            dialog({title: "解绑失败", message: String(e), cancelText: null, confirmText: "确定"});
          });
        });
        return;
      }

      var payload = {name: n.name};
      if (result.url) {
        payload.isp = result.url;
      } else if (result.isp) {
        payload.isp = result.isp;
      }

      jsonRequest("/api/editnode", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      }).then(function (d) {
        if (!d.ok) {
          dialog({title: "挂载失败", message: d.error || "请检查代理连接串格式或住宅代理连通性。", cancelText: null, confirmText: "确定"});
          return;
        }
        dialog({
          title: "挂载成功",
          message: "静态住宅 IP 出口已写入远端并验证生效。\n链式转发已启用，出站流量将经由住宅代理转发。",
          cancelText: null,
          confirmText: "确定"
        }).then(function () {
          refreshState();
        });
      }).catch(function (e) {
        dialog({title: "挂载失败", message: String(e), cancelText: null, confirmText: "确定"});
      });
    });
  }

  function editNode(i) {
    var n = NODES[i];
    formSheet('修改 "' + n.name + '"', [{label: "节点名称", value: n.name}, {label: "服务端口", value: n.port, type: "number"}], "保存").then(function (v) {
      if (!v) return;
      var body = {name: n.name};
      if (v[0] && v[0] !== n.name) body.newname = v[0];
      if (v[1] && String(v[1]) !== String(n.port)) body.port = v[1];
      if (!body.newname && !body.port) return;
      jsonRequest("/api/editnode", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      }).then(function (d) {
        if (!d.ok) { dialog({title: "修改失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
        var msg = "订阅已自动更新。" + (body.port ? ("\n\n端口已变更为 " + body.port + "，服务已平滑重启。") : "");
        dialog({title: "修改成功", message: msg, cancelText: null, confirmText: "确定"}).then(function () { refreshState(); });
      }).catch(function (e) { dialog({title: "修改失败", message: String(e), cancelText: null, confirmText: "确定"}); });
    });
  }

  function rotateKey(i) {
    var n = NODES[i];
    dialog({title: '重置 "' + n.name + '" 连接密钥？', message: "所有已连接设备将立刻断开，客户端必须重新拉取订阅后才能连接。", confirmText: "重置密钥", danger: true})
      .then(function (y) {
        if (!y) return;
        jsonRequest("/api/editnode", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({name: n.name, newkey: true})
        }).then(function (d) {
          if (!d.ok) { dialog({title: "重置失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
          dialog({title: "密钥已重置", message: "旧密钥已作废。请在手机/电脑客户端刷新订阅以恢复连接。", cancelText: null, confirmText: "确定"}).then(function () { refreshState(); });
        }).catch(function (e) { dialog({title: "重置失败", message: String(e), cancelText: null, confirmText: "确定"}); });
      });
  }

  function delNode(i) {
    var n = NODES[i];
    dialog({title: '删除节点 "' + n.name + '"？', message: "该节点将从订阅中彻底移除，并停止服务器上的节点服务。", confirmText: "确认删除", danger: true})
      .then(function (yes) {
        if (!yes) return;
        jsonRequest("/api/removenode", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({name: n.name})
        }).then(function (d) {
          if (!d.ok) { dialog({title: "删除失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
          var m = d.stopped === true ? "已删除节点并停止对应服务。"
                : d.stopped === false ? "已从订阅中移除，但远程服务器服务未停止。"
                : "已从订阅中移除。";
          dialog({title: "删除完成", message: m, cancelText: null, confirmText: "确定"}).then(function () { refreshState(); });
        }).catch(function (e) { dialog({title: "删除失败", message: String(e), cancelText: null, confirmText: "确定"}); });
      });
  }

  function rotate() {
    dialog({title: "确认撤销旧订阅链接？", message: "撤销后原订阅立即失效，所有手机与电脑客户端必须重新导入新订阅。", confirmText: "撤销并生成新链接", danger: true})
      .then(function (yes) {
        if (!yes) return;
        jsonRequest("/api/rotate", {method: "POST"}).then(function (d) {
          if (!d.ok) { dialog({title: "操作失败", message: d.error || "未知错误", cancelText: null, confirmText: "确定"}); return; }
          dialog({title: "订阅链接已更新", message: "新的订阅地址：\n" + d.url, cancelText: null, confirmText: "确定"}).then(function () { refreshState(); });
        }).catch(function (e) { dialog({title: "操作失败", message: String(e), cancelText: null, confirmText: "确定"}); });
      });
  }

  function health() {
    var box = document.getElementById("health");
    if (!box) return;
    var secLogs = document.getElementById("section-logs");
    if (secLogs && !secLogs.open) secLogs.open = true;
    box.innerHTML = '<div class="small muted" style="padding:8px 0">正在诊断系统与节点健康状态...</div>';
    var rows = [];
    function add(ok, txt, adv) { rows.push({ok: ok, txt: txt, adv: adv || ""}); }
    var tasks = [];
    tasks.push(jsonRequest("/api/nodes").then(function (j) {
      add(true, "管理接口正常（已加载 " + (Array.isArray(j) ? j.length : 0) + " 个节点）");
    }).catch(function () {
      add(false, "管理接口不可达", "后端进程未响应或网络中断");
    }));
    var sub = document.getElementById("suburl").textContent.trim();
    if (sub && sub !== "订阅链接暂不可用") {
      tasks.push(fetch(safeUrl(sub), {cache: "no-store"}).then(function (r) {
        add(r.ok, "订阅分发正常（HTTP " + r.status + "）");
      }).catch(function () {
        add(false, "订阅拉取失败", "订阅令牌已撤销或管理端离线");
      }));
    }
    tasks.push(jsonRequest("/status.json").then(function (s) {
      NODES.forEach(function (n) {
        var st = s[n.name];
        var isHealthy = !!(st && st.ok && st.cn_ok !== false && (n.health === "ok" || !n.health));
        var msNote = (st && st.ms != null) ? (st.ms + "ms" + (st.self_probe ? " · 探针本机" : "")) : "";
        var text = n.name + (isHealthy ? (" 在线 " + msNote) : (st && st.cn_ok === false ? " 国内直连阻断（疑似被封锁）" : " 无法连接"));
        var adv = isHealthy ? "" : (st && st.cn_ok === false ? "海外可达但国内直连受阻，建议绑定中转专线或更换端口" : (n.health_detail || "服务器进程未运行或防火墙阻断，请登录服务器排查"));
        add(isHealthy, text, adv);
      });
    }).catch(function () {
      add(false, "探活数据不可用", "后台定时探活任务尚未生成数据");
    }));
    tasks.push(jsonRequest("/usage.json").then(function (u) {
      var bad = null, n = 0;
      for (var k in u) {
        if (k.charAt(0) === "_") continue;
        n++;
        if (u[k] && u[k].error) bad = k;
      }
      add(!bad, (n ? ("腾讯云流量采集（" + n + " 台实例）") : "未关联腾讯云实例"), (bad ? (bad + " 采集失败") : "未配置云 API 凭据（使用网卡流量统计）"));
    }).catch(function () {
      add(false, "腾讯云流量快照不可用", "未配置腾讯云 API 凭据或尚未同步");
    }));

    Promise.all(tasks).then(function () {
      var bad = rows.filter(function (r) { return !r.ok; }).length;
      box.innerHTML = '<p class="small" style="margin:10px 0 6px;font-weight:600;color:' + (bad ? "var(--bad)" : "var(--ok)") + '">' + (bad ? ("检测到 " + bad + " 项异常") : "全部服务运行正常") + "</p>" +
        rows.map(function (r) {
          return '<div class="hitem ' + (r.ok ? "ok" : "bad") + '"><b><svg class="ico" width="14" height="14" style="vertical-align:-2px;margin-right:6px"><use href="' + (r.ok ? "#i-check" : "#i-x") + '"/></svg>' + esc(r.txt) + "</b>" + (r.ok ? "" : "<i>" + esc(r.adv) + "</i>") + "</div>";
        }).join("");
    });
  }

  function loadSyslog(srv, btn) {
    var box = document.getElementById("syslog-box");
    if (!box) return;
    box.style.display = "block";
    box.textContent = "正在读取 " + srv + " 日志...";
    jsonRequest("/api/syslogs?service=" + encodeURIComponent(srv) + "&lines=60")
      .then(function (d) {
        if (!d.ok) { box.textContent = "读取失败：" + (d.error || "未知错误"); return; }
        var lines = d.lines || [];
        box.textContent = lines.length ? lines.join("\n") : "（暂无日志输出）";
        box.scrollTop = box.scrollHeight;
      }).catch(function (e) {
        box.textContent = "请求失败：" + String(e);
      });
  }

  function copyDiagInfo(btn) {
    var orig = btn ? btn.textContent : "";
    if (btn) { btn.textContent = "正在生成..."; btn.disabled = true; }
    Promise.all([
      jsonRequest("/api/nodes").catch(function () { return []; }),
      jsonRequest("/status.json").catch(function () { return {}; }),
      jsonRequest("/api/logs?limit=30").catch(function () { return {logs: []}; })
    ]).then(function (res) {
      var ns = res[0] || [], st = res[1] || {}, lg = (res[2] && res[2].logs) || [];
      var text = "=== Evergreen · OwnLine 诊断快照 (" + new Date().toISOString() + ") ===\n";
      text += "[节点状态]:\n";
      ns.forEach(function (n) {
        var s = st[n.name] || {};
        var probeText = "";
        if (n.type === "hysteria2") {
          var parentNode = ns.find(function (x) {
            return (x.host === n.host || x.ip === n.host) && x.type !== "hysteria2";
          });
          var parentStatus = parentNode ? st[parentNode.name] : null;
          probeText = parentStatus && parentStatus.ok ? (parentStatus.ms + "ms(宿主同端口)") : "免探活(UDP通道)";
        } else if (s.ok) {
          probeText = s.ms + "ms" + (s.self_probe ? "(本机)" : "");
        } else if (s.ok === false) {
          probeText = "异常:" + (s.reason || "连接失败");
        } else {
          probeText = "未测";
        }
        var cnProbeText = "";
        if (n.type === "hysteria2") {
          cnProbeText = "客户端实测";
        } else if (s.cn_ok) {
          cnProbeText = s.cn_ms + "ms";
        } else if (s.cn_ok === false) {
          cnProbeText = "阻断";
        } else {
          cnProbeText = "未测";
        }
        text += "  - " + n.name + " (" + (n.type || "vless") + "): health=" + (n.health || "-") + ", exit_ip=" + (n.exit_ip || "-") +
                ", 主控探活=" + probeText +
                ", 国内探活=" + cnProbeText + "\n";
      });
      text += "\n[近期日志]:\n";
      lg.forEach(function (l) {
        text += "  [" + l.ts + "] [" + l.level + "] [" + (l.src || l.source) + "] " + redactLog(l.msg || l.message) + "\n";
      });
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function () {
          if (btn) { btn.textContent = "已复制诊断"; btn.disabled = false; setTimeout(function () { btn.textContent = orig; }, 1600); }
        });
      } else {
        if (btn) { btn.textContent = orig; btn.disabled = false; }
        prompt("请按 Ctrl+C / Cmd+C 复制诊断摘要：", text);
      }
    }).catch(function () {
      if (btn) { btn.textContent = orig; btn.disabled = false; }
    });
  }

  function openRelayDialog(name, host) {
    var dialog = document.getElementById("relay-dialog");
    var list = document.getElementById("relay-targets-list");
    var title = document.getElementById("relay-dialog-title");
    if (!dialog || !list) return;
    if (title) title.textContent = "将【" + name + "】设为加速中转";

    var exits = (NODES || []).filter(function (x) {
      var xHost = x.host || x.ip;
      var isDom = (x.role === "relay" || x.role === "standalone" || x.country === "CN" || xHost === host);
      return !isDom && x.type !== "hysteria2";
    });
    var seen = {};
    exits = exits.filter(function (x) {
      var xHost = x.host || x.ip;
      if (!xHost || seen[xHost]) return false;
      seen[xHost] = true; return true;
    });

    if (!exits.length) {
      list.innerHTML = '<div class="small muted" style="padding:10px 0">当前暂无可用的海外出口服务器</div>';
    } else {
      list.innerHTML = exits.map(function (ex) {
        var exHost = ex.host || ex.ip;
        var st = STATUS[ex.name];
        var ping = (st && st.ms != null) ? ("延迟 " + st.ms + "ms") : "待测速";
        return '<button type="button" class="btn relay-target-btn" data-relay-name="' + esc(name) + '" data-target-host="' + esc(exHost) + '" style="text-align:left;display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-radius:12px;border:1px solid var(--apple-line);background:var(--apple-card);cursor:pointer;width:100%">' +
          '<div>' +
            '<div style="font-weight:600;font-size:13.5px">' + esc(ex.name) + '</div>' +
            '<div class="small muted" style="font-size:11.5px">' + esc(exHost) + ' · ' + esc(ping) + '</div>' +
          '</div>' +
          '<span class="tag ok" style="font-size:11.5px">建立专线</span>' +
        '</button>';
      }).join("");
      list.querySelectorAll(".relay-target-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var rName = btn.getAttribute("data-relay-name") || "";
          var tHost = btn.getAttribute("data-target-host") || "";
          submitRelayBind(rName, tHost);
        });
      });
    }
    dialog.showModal();
  }

  function submitRelayBind(name, targetHost) {
    var dialog = document.getElementById("relay-dialog");
    if (dialog) dialog.close();
    jsonRequest("/api/relay/bind", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, target: targetHost })
    }).then(function (res) {
      if (res && res.ok) {
        refreshState();
      } else {
        alert("绑定中转失败：" + ((res && res.error) || "未知错误"));
      }
    }).catch(function (err) {
      alert("绑定请求失败：" + err.message);
    });
  }

  function unbindRelay(name) {
    if (!confirm("确定要解除【" + name + "】的中转关系，将其恢复为独立服务器吗？")) return;
    jsonRequest("/api/relay/unbind", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    }).then(function (res) {
      if (res && res.ok) {
        refreshState();
      } else {
        alert("解除中转失败：" + ((res && res.error) || "未知错误"));
      }
    }).catch(function (err) {
      alert("请求失败：" + err.message);
    });
  }

  var isTogglingHy2 = false;
  function toggleHy2(name, host, enable) {
    if (isTogglingHy2) {
      return;
    }
    isTogglingHy2 = true;
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var actText = enable ? (zh ? "开启" : "Enable") : (zh ? "关闭" : "Disable");
    if (document.body) document.body.style.cursor = "wait";

    jsonRequest("/api/hy2/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, host: host, enabled: enable })
    }).then(function (res) {
      if (res && res.ok) {
        refreshState();
      } else {
        alert(actText + (zh ? " HY2 失败：" : " HY2 failed: ") + ((res && res.error) || "未知错误"));
      }
    }).catch(function (err) {
      alert((zh ? "请求失败：" : "Request failed: ") + err.message);
    }).finally(function () {
      isTogglingHy2 = false;
      if (document.body) document.body.style.cursor = "default";
    });
  }

  function setProbeVantage(name) {
    var zh = (typeof isZh === 'function') ? isZh() : true;
    jsonRequest("/api/probe/vantage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    }).then(function (res) {
      if (res && res.ok) {
        if (typeof toast === "function") {
          toast(zh ? ("已将【" + name + "】设为国内探测基准锚点") : ("Set " + name + " as domestic probe vantage"));
        } else {
          alert(zh ? ("已将【" + name + "】设为国内探测基准锚点") : ("Set " + name + " as domestic probe vantage"));
        }
        refreshState();
        refreshPing();
      } else {
        alert("设置基准失败：" + ((res && res.error) || "未知错误"));
      }
    }).catch(function (err) {
      alert("请求失败：" + err.message);
    });
  }

  window.ownlineSetProbeVantage = setProbeVantage;
  window.ownlineSetProbeVantageByIndex = function (idx) {
    var n = NODES[idx];
    if (n) setProbeVantage(n.name);
  };
  window.ownlineNodeMenu = nodeMenu;
  window.ownlineMountIsp = mountIsp;
  window.ownlineRelaySwitch = drillRelaySwitch;
  window.ownlineHealth = health;
  window.ownlineRotate = rotate;
  window.ownlineCopyDiag = copyDiagInfo;
  window.ownlineLoadSyslog = loadSyslog;
  window.ownlineOpenRelayDialog = openRelayDialog;
  window.ownlineOpenRelayDialogByIndex = function (idx) {
    var n = NODES[idx];
    if (n) openRelayDialog(n.name, n.host || n.ip);
  };
  window.ownlineSubmitRelayBind = submitRelayBind;
  window.ownlineUnbindRelay = unbindRelay;
  window.ownlineUnbindRelayByIndex = function (idx) {
    var n = NODES[idx];
    if (n) unbindRelay(n.name);
  };
  window.ownlineToggleHy2 = toggleHy2;
  window.ownlineToggleHy2ByIndex = function (idx, enable) {
    var n = NODES[idx];
    if (n) toggleHy2(n.name, n.host || n.ip, enable);
  };
  window.ownlineEditNodeByIndex = function (idx) {
    if (typeof editNode === "function") editNode(idx);
  };
  window.ownlineRotateKeyByIndex = function (idx) {
    if (typeof rotateKey === "function") rotateKey(idx);
  };
  window.ownlineBindDomesticRelayFor = function (targetHost) {
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var dom = (NODES || []).find(function (x) {
      var isDom = (x.role === "relay" || x.role === "standalone" || x.country === "CN");
      return isDom && !(x.landing && x.landing.host);
    });
    if (!dom) {
      dom = (NODES || []).find(function (x) {
        return (x.role === "relay" || x.role === "standalone" || x.country === "CN");
      });
    }
    if (dom) {
      openRelayDialog(dom.name, dom.host || dom.ip);
    } else {
      dialog({
        title: zh ? "暂无可用国内中转跳板" : "No Domestic Relay Available",
        message: zh ? "当前尚未接入国内独立服务器。请先接入一台国内机器（如腾讯云国内轻量），即可秒级开启专线加速。" : "No domestic server connected yet. Connect a domestic VPS first to enable relay acceleration.",
        confirmText: zh ? "确定" : "OK",
        cancelText: null
      });
    }
  };
  window.ownlineRecheckNode = function (name) {
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var node = (NODES || []).find(function (x) { return x.name === name; });
    if (!node) return;
    dialog({
      title: zh ? "正在验真节点连通性..." : "Verifying Node Connectivity...",
      message: (zh ? "正在对节点【" : "Testing node [") + name + (zh ? "】进行端口、TLS 握手及真实出口校验..." : "] for port, TLS handshake, and egress..."),
      confirmText: zh ? "后台检测" : "Check in Background",
      cancelText: null
    });
    jsonRequest("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    }).then(function (d) {
      if (document.querySelector("dialog.sheet[open]")) {
        var active = document.querySelector("dialog.sheet[open]");
        if (active && active.close) active.close();
      }
      var res = d.result || {};
      if (res.health === "ok") {
        dialog({
          title: zh ? "验真通过 · 节点恢复正常" : "Verification Passed",
          message: (zh ? "节点【" : "Node [") + name + (zh ? "】已确认连通！\n\n出口 IP: " : "] is operational!\n\nEgress IP: ") + (res.exit_ip || "-") + " (" + (res.exit_country || "") + ")\n" + (res.detail || ""),
          confirmText: zh ? "好" : "OK",
          cancelText: null
        });
      } else {
        dialog({
          title: zh ? "连通性受限" : "Connectivity Degraded",
          message: (zh ? "节点【" : "Node [") + name + (zh ? "】验真未通过：\n\n原因: " : "] verification failed:\n\nReason: ") + (res.detail || (zh ? "服务未响应" : "No response")),
          confirmText: zh ? "知道了" : "Dismiss",
          cancelText: null
        });
      }
      if (typeof refreshState === "function") refreshState();
    }).catch(function (e) {
      dialog({
        title: zh ? "请求异常" : "Request Error",
        message: String(e),
        confirmText: zh ? "确定" : "OK",
        cancelText: null
      });
    });
  };

  function refreshPing(btn) {
    if (btn) btn.classList.add("refreshing");
    if (location.protocol === "file:") {
      setTimeout(function () {
        if (STATUS["香港 · HK01"]) STATUS["香港 · HK01"].cn_ms = Math.floor(20 + Math.random() * 12);
        if (STATUS["日本 · JP01"]) STATUS["日本 · JP01"].cn_ms = Math.floor(55 + Math.random() * 15);
        if (STATUS["新加坡 · SG01"]) STATUS["新加坡 · SG01"].cn_ms = Math.floor(70 + Math.random() * 20);
        if (STATUS["美西 · US01"]) STATUS["美西 · US01"].cn_ms = Math.floor(135 + Math.random() * 25);
        paintStatus();
        if (btn) btn.classList.remove("refreshing");
      }, 500);
      return;
    }
    // 视觉即时反馈：将所有节点的测速胶囊标为「测速中...」
    (NODES || []).forEach(function (n, i) {
      var s = document.getElementById("s" + i);
      if (s) {
        var existing = s.querySelector(".ping-pill");
        if (existing) existing.textContent = "测速中...";
      }
    });
    jsonRequest("/api/ping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts: Date.now() })
    }).then(function (res) {
      if (res && res.status) {
        STATUS = res.status;
      }
      paintStatus();
      if (btn) btn.classList.remove("refreshing");
    }).catch(function () {
      jsonRequest("/status.json?_t=" + Date.now()).then(function (st) {
        STATUS = st || {};
        paintStatus();
        if (btn) btn.classList.remove("refreshing");
      }).catch(function () {
        if (btn) btn.classList.remove("refreshing");
      });
    });
  }
  window.ownlineRefreshPing = refreshPing;

  function toggleNodeDrawer(i) {
    var drawer = document.getElementById("node-drawer-" + i);
    var row = document.getElementById("node-row-" + i);
    if (!drawer) return;
    var isOpen = (drawer.style.display !== "none");
    var allDrawers = document.querySelectorAll(".node-drawer");
    allDrawers.forEach(function (d) { d.style.display = "none"; });
    var allRows = document.querySelectorAll(".node");
    allRows.forEach(function (r) { r.classList.remove("active"); });
    if (!isOpen) {
      drawer.style.display = "flex";
      if (row) row.classList.add("active");
    }
  }
  window.ownlineToggleNodeDrawer = toggleNodeDrawer;

  function toggleQuota() {
    var qs = document.getElementById("quota-section");
    if (!qs) return;
    qs.open = !qs.open;
    var settings = document.getElementById("quota-settings");
    if (settings) settings.style.display = qs.open ? "block" : "none";
    if (qs.open) {
      qs.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
  window.ownlineToggleQuota = toggleQuota;

  function openQrModal() {
    var dlg = document.getElementById("qr-dialog");
    var qrImg = document.getElementById("qr-code-img");
    var sub = BASE_SUB_URL;
    var urlText = document.getElementById("qr-sub-url-text");
    if (urlText) {
      urlText.textContent = sub || "";
    }
    if (qrImg) {
      var ts = Date.now();
      if (sub && location.protocol !== "file:") {
        qrImg.src = "/api/qr?url=" + encodeURIComponent(sub) + "&t=" + ts;
        qrImg.onerror = function () {
          qrImg.src = "/qr?url=" + encodeURIComponent(sub) + "&t=" + ts;
          qrImg.onerror = function () {
            qrImg.src = "qr-sub.png?t=" + ts;
          };
        };
      } else {
        qrImg.src = "qr-sub.png?t=" + ts;
      }
    }
    if (dlg) {
      if (typeof dlg.showModal === "function") {
        if (!dlg.open) dlg.showModal();
      } else {
        dlg.setAttribute("open", "");
      }
    }
  }
  window.ownlineOpenQrModal = openQrModal;

  function copyQrSubUrl(btn) {
    var sub = BASE_SUB_URL;
    if (!sub) return;
    function done() {
      var lbl = document.getElementById("copy-qr-label");
      if (lbl) {
        var orig = lbl.textContent;
        lbl.textContent = (typeof isZh === 'function' && !isZh()) ? "Copied! ✓" : "已复制订阅链接 ✓";
        setTimeout(function () { lbl.textContent = orig; }, 1800);
      }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(sub).then(done).catch(done);
    } else {
      done();
    }
  }
  window.ownlineCopyQrSubUrl = copyQrSubUrl;

  function autoFixOffer(host) {
    var resultBox = document.getElementById("other-check-result");
    if (!resultBox) return;
    resultBox.style.display = "block";
    resultBox.innerHTML = "<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>" +
      "<span>忘记密码？可通过腾讯云 API 重置实例 root 密码：</span>" +
      "<button class='tiny' type='button' id='btn-auto-fix' style='color:var(--accent);font-weight:600'>通过 API 重置密码</button>" +
      "</div>";
    var btn = document.getElementById("btn-auto-fix");
    if (btn) {
      btn.onclick = function () {
        autoFixPrompt(host);
      };
    }
  }

  function autoFixPrompt(host) {
    if (!host) return;
    choose("重置服务器 root 密码？", '将通过云厂商 API 把 "' + host + '" 的 root 密码重置为高强度随机密码并重启实例（约需 60–90 秒）。\n\n重启后新密码会自动填入上方凭据框。', [
      {label: "确认重置并重启", danger: true}
    ]).then(function (k) {
      if (k === 0) autoFix(host);
    });
  }

  function autoFix(host) {
    if (!host) return;
    var note = document.getElementById("other-connect-status");
    if (note) note.textContent = '正在调用云厂商 API 重置 "' + host + '" 密码并重启实例...';
    jsonRequest("/api/resetpw", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ip: host})
    }).then(function (d) {
      if (!d.ok) {
        dialog({title: "重置密码失败", message: d.error || "请确认已配置有效的腾讯云 API 凭据，或前往云控制台手动重置。", cancelText: null, confirmText: "确定"});
        if (note) note.textContent = "自动重置失败：" + (d.error || "未知原因");
        return;
      }
      var newPw = d.password || "";
      if (newPw) {
        var input = document.getElementById("other-credential");
        if (input) input.value = newPw;
      }
      dialog({
        title: "已触发密码重置",
        message: '已为 "' + host + '" 生成新的 root 密码，实例正在重启（约需 60–90 秒）。\n\n新密码已自动填入凭据框，请等待实例重启完成后再次点击测试连接。',
        cancelText: null,
        confirmText: "确定"
      });
      if (note) note.textContent = "密码已重置，请等待实例重启完成后再测试连接。";
    }).catch(function (e) {
      dialog({title: "网络请求失败", message: String(e), cancelText: null, confirmText: "确定"});
    });
  }

