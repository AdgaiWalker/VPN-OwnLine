  function jsonRequest(path, options) {
    options = options || {cache: "no-store"};
    if (!options.credentials) options.credentials = "same-origin";
    return fetch(safeUrl(path), options).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function syncHeroQuotaSummary() {
    var zh = (typeof isZh === "function") ? isZh() : true;
    var overallPct = (typeof STATE !== "undefined" && STATE && typeof STATE.heroOverallPct === "number") ? STATE.heroOverallPct : 0;
    var anyTripped = !!(typeof STATE !== "undefined" && STATE && STATE.heroAnyTripped);
    var bottleneck = (typeof STATE !== "undefined" && STATE) ? STATE.relayBottleneck : null;
    var report = (typeof STATE !== "undefined" && STATE) ? STATE.trafficReport : null;
    var tot = (report && report.total) ? report.total : null;
    var runway = (tot && tot.runway) ? tot.runway : null;
    var cycle = (tot && tot.cycle) ? tot.cycle : null;
    var elStatus = document.getElementById("quota-hero-status");
    var elSafe = document.getElementById("quota-hero-nodes-safe");
    var bNode = (runway && runway.bottleneck_node) ? runway.bottleneck_node : null;
    var isRelayBottle = !!(bottleneck && bottleneck.is_relay_bottleneck) || !!(bNode && bNode.role === "relay" && runway.topology && runway.topology.length > 1);
    var breakerPct = runway && runway.breaker_pct != null ? Math.round(runway.breaker_pct) : 85;

    if (elStatus) {
      if (anyTripped || (runway && runway.safe_before_breaker_gb <= 0) || overallPct >= breakerPct) {
        elStatus.textContent = zh ? "已熔断" : "Tripped";
        elStatus.className = "tag bad";
      } else if (isRelayBottle) {
        elStatus.textContent = zh ? "跳板受限" : "Relay Bottleneck";
        elStatus.className = "tag warn";
      } else if (overallPct >= Math.max(50, breakerPct - 10)) {
        elStatus.textContent = zh ? "预警" : "Warning";
        elStatus.className = "tag warn";
      } else {
        elStatus.textContent = zh ? "充足" : "Healthy";
        elStatus.className = "tag ok";
      }
    }
    if (elSafe) {
      var daysRem = (cycle && cycle.days_remaining != null) ? cycle.days_remaining : null;
      if (anyTripped || (runway && runway.safe_before_breaker_gb <= 0)) {
        elSafe.textContent = zh ? "节点流量已达保护熔断线" : "Traffic reached protection circuit breaker";
        if (elSafe.style) {
          elSafe.style.display = "block";
          elSafe.style.color = "var(--apple-red)";
        }
      } else if (isRelayBottle) {
        var rName = (bottleneck && bottleneck.relay_name) || (bNode && bNode.name) || "relay";
        var safeRem = (runway && runway.safe_before_breaker_gb != null) ? runway.safe_before_breaker_gb : (bottleneck ? bottleneck.relay_remaining_gb : 0);
        var resetSuffix = daysRem != null ? (zh ? (" · " + daysRem + " 天后重置") : (" · resets in " + daysRem + "d")) : "";
        elSafe.textContent = zh
          ? ("短板 " + rName + " · 距 " + breakerPct + "% 熔断余 " + safeRem + " GB" + resetSuffix)
          : ("Bottleneck " + rName + " · " + safeRem + " GB to " + breakerPct + "% cap" + resetSuffix);
        if (elSafe.style) {
          elSafe.style.display = "block";
          elSafe.style.color = "var(--apple-amber, #b45309)";
        }
      } else if (runway && runway.will_hit_breaker && runway.projected_days_to_breaker != null) {
        elSafe.textContent = zh
          ? ("按近 7 日消耗速度，预计 " + runway.projected_days_to_breaker + " 天后触达 " + breakerPct + "% 熔断线")
          : ("At 7d pace, estimated " + runway.projected_days_to_breaker + "d until " + breakerPct + "% cap");
        if (elSafe.style) {
          elSafe.style.display = "block";
          elSafe.style.color = "var(--apple-amber, #b45309)";
        }
      } else {
        elSafe.textContent = "";
        if (elSafe.style) {
          elSafe.style.display = "none";
          elSafe.style.color = "";
        }
      }
    }
  }

  function renderTrafficBreakdown(report) {
    if (!report) return;
    if (typeof STATE !== "undefined" && STATE) STATE.trafficReport = report;
    var zh = (typeof isZh === "function") ? isZh() : true;
    var tot = report.total || {};
    var guide = tot.guidance || {};
    var runway = tot.runway || null;
    var cycle = tot.cycle || null;
    var meta = tot.data_meta || {};
    var series = Array.isArray(tot.daily_series) ? tot.daily_series : [];
    if (typeof STATE !== "undefined" && STATE) {
      STATE.relayBottleneck = (guide.bottleneck && guide.bottleneck.is_relay_bottleneck) ? guide.bottleneck : null;
    }

    var timeTick = document.getElementById("quota-time-tick");
    var breakerTick = document.getElementById("quota-breaker-tick");
    if (timeTick) {
      if (cycle && typeof cycle.elapsed_pct === "number" && cycle.elapsed_pct > 0 && cycle.elapsed_pct <= 100) {
        timeTick.hidden = false;
        timeTick.style.left = Math.max(2, Math.min(98, cycle.elapsed_pct)) + "%";
        timeTick.title = zh ? ("周期时间已过 " + cycle.elapsed_pct + "%") : ("Billing cycle " + cycle.elapsed_pct + "% elapsed");
      } else {
        timeTick.hidden = true;
      }
    }
    if (breakerTick) {
      var bPct = runway && typeof runway.breaker_pct === "number" ? runway.breaker_pct : null;
      if (bPct && bPct > 0 && bPct < 100) {
        breakerTick.hidden = false;
        breakerTick.style.left = Math.max(4, Math.min(98, bPct)) + "%";
        breakerTick.title = zh ? ("保护熔断阈值 " + bPct + "%") : ("Circuit breaker threshold " + bPct + "%");
      } else {
        breakerTick.hidden = true;
      }
    }

    var elRem = document.getElementById("quota-hero-rem");
    var elRemSub = document.getElementById("quota-runway-sub");
    var elAvg7 = document.getElementById("quota-avg-7d");
    var elCycleRem = document.getElementById("quota-cycle-rem");
    var elCyclePct = document.getElementById("quota-cycle-pct");
    var breakerPctLbl = runway && runway.breaker_pct != null ? Math.round(runway.breaker_pct) : 85;

    if (elRem) {
      var safeVal = (runway && runway.safe_before_breaker_gb != null) ? runway.safe_before_breaker_gb : guide.remaining_gb;
      elRem.textContent = (safeVal != null ? safeVal : "--") + " GB";
    }
    if (elRemSub) {
      if (runway && runway.safe_before_breaker_gb <= 0) {
        elRemSub.textContent = zh ? "已触发熔断" : "Breaker tripped";
      } else if (runway && runway.effective_remaining_gb != null) {
        elRemSub.textContent = zh
          ? ("(距 " + breakerPctLbl + "% 熔断 · 账单余 " + runway.effective_remaining_gb + "G)")
          : ("(to " + breakerPctLbl + "% cap · " + runway.effective_remaining_gb + "G bill)");
      } else {
        elRemSub.textContent = "";
      }
    }
    if (elAvg7) {
      var avg7 = (runway && runway.avg_7d_gb != null) ? runway.avg_7d_gb : tot.today_gb;
      elAvg7.textContent = avg7 != null ? (avg7 + (zh ? " GB/天" : " GB/d")) : "--";
    }
    if (elCycleRem) {
      var dRem = (cycle && cycle.days_remaining != null) ? cycle.days_remaining : guide.days_remaining;
      elCycleRem.textContent = dRem != null ? (zh ? (dRem + " 天后重置") : ("Resets in " + dRem + "d")) : "--";
    }
    if (elCyclePct) {
      elCyclePct.textContent = (cycle && cycle.elapsed_pct != null)
        ? (zh ? ("周期已过 " + cycle.elapsed_pct + "%") : (cycle.elapsed_pct + "% elapsed"))
        : "";
    }

    var chartWrap = document.getElementById("quota-chart-wrap");
    var chartSvg = document.getElementById("quota-chart-svg");
    var chartCold = document.getElementById("quota-chart-cold");
    var chartAxis = document.getElementById("quota-chart-axis");
    var readout = document.getElementById("quota-chart-readout");
    var todayVal = tot.today_gb != null ? tot.today_gb : 0;
    var yestVal = tot.yesterday_gb != null ? tot.yesterday_gb : 0;
    var defaultReadout = zh
      ? ("今日 " + todayVal + " · 昨日 " + yestVal + " GB")
      : ("Today " + todayVal + " · Yest " + yestVal + " GB");
    if (readout) readout.textContent = defaultReadout;

    var histDays = (typeof meta.history_days === "number") ? meta.history_days : series.filter(function (s) { return !s.missing; }).length;
    if (series.length && histDays > 1 && chartSvg && chartWrap) {
      chartWrap.hidden = false;
      if (chartCold) chartCold.hidden = true;
      if (chartAxis) chartAxis.hidden = false;

      var dailyBudget = (runway && runway.daily_budget_gb > 0) ? runway.daily_budget_gb : 0;
      var maxGb = 0.5;
      series.forEach(function (item) {
        if (!item.missing && item.gb > maxGb) maxGb = item.gb;
      });
      if (dailyBudget > 0 && dailyBudget <= maxGb * 1.4 && dailyBudget > maxGb) {
        maxGb = dailyBudget * 1.1;
      }

      var svgW = 560, svgH = 56, padTop = 6, padBottom = 4, plotH = svgH - padTop - padBottom;
      var stepW = svgW / series.length;
      var barW = Math.max(12, Math.floor(stepW * 0.56));
      var svgParts = [];

      if (dailyBudget > 0 && dailyBudget <= maxGb) {
        var budY = Math.round((padTop + plotH - (dailyBudget / maxGb) * plotH) * 10) / 10;
        svgParts.push('<line class="qbar-budget-line" x1="0" y1="' + budY + '" x2="' + svgW + '" y2="' + budY + '"></line>');
      }

      series.forEach(function (item, idx) {
        var colX = Math.round(idx * stepW * 10) / 10;
        var rectX = Math.round((colX + (stepW - barW) / 2) * 10) / 10;
        var isToday = idx === series.length - 1;
        var h = item.missing ? 3 : Math.max(3, Math.round((item.gb / maxGb) * plotH * 10) / 10);
        var y = Math.round((svgH - padBottom - h) * 10) / 10;
        var cls = item.missing ? "qbar qbar-missing" : (isToday ? "qbar qbar-today" : (dailyBudget > 0 && item.gb > dailyBudget ? "qbar qbar-over" : "qbar"));
        var ariaLbl = item.label + ": " + (item.missing ? (zh ? "无采样" : "no sample") : (item.gb + " GB"));
        svgParts.push(
          '<g class="qbar-col" tabindex="0" role="listitem" aria-label="' + esc(ariaLbl) + '" data-label="' + esc(item.label) + '" data-gb="' + esc(String(item.gb)) + '" data-missing="' + (item.missing ? "1" : "0") + '">' +
            '<rect x="' + colX + '" y="0" width="' + stepW + '" height="' + svgH + '" fill="transparent"></rect>' +
            '<rect class="' + cls + '" x="' + rectX + '" y="' + y + '" width="' + barW + '" height="' + h + '" rx="2"></rect>' +
          '</g>'
        );
      });
      chartSvg.innerHTML = svgParts.join("");

      if (!chartSvg.dataset.boundReadout) {
        chartSvg.dataset.boundReadout = "1";
        var showCol = function (ev) {
          var col = ev.target && ev.target.closest ? ev.target.closest(".qbar-col") : null;
          var rEl = document.getElementById("quota-chart-readout");
          if (!col || !rEl) return;
          var lbl = col.getAttribute("data-label") || "";
          var isMiss = col.getAttribute("data-missing") === "1";
          var gbVal = col.getAttribute("data-gb") || "0";
          var curZh = (typeof isZh === "function") ? isZh() : true;
          rEl.textContent = lbl + " · " + (isMiss ? (curZh ? "无采样" : "No sample") : (gbVal + " GB"));
        };
        var resetCol = function () {
          var rEl = document.getElementById("quota-chart-readout");
          if (rEl && chartSvg.dataset.defaultReadout) rEl.textContent = chartSvg.dataset.defaultReadout;
        };
        chartSvg.addEventListener("mouseover", showCol);
        chartSvg.addEventListener("focusin", showCol);
        chartSvg.addEventListener("click", showCol);
        chartSvg.addEventListener("mouseleave", resetCol);
        chartSvg.addEventListener("focusout", resetCol);
      }
      chartSvg.dataset.defaultReadout = defaultReadout;

      var axStart = document.getElementById("quota-axis-start");
      var axMid = document.getElementById("quota-axis-mid");
      var axEnd = document.getElementById("quota-axis-end");
      if (axStart) axStart.textContent = series[0].label;
      if (axMid) axMid.textContent = dailyBudget > 0 ? ((zh ? "日均预算 " : "Budget ") + dailyBudget + "G") : series[Math.floor(series.length / 2)].label;
      if (axEnd) axEnd.textContent = zh ? "今天" : "Today";
    } else if (chartWrap && chartCold) {
      chartWrap.hidden = true;
      if (chartAxis) chartAxis.hidden = true;
      chartCold.hidden = false;
      chartCold.textContent = zh
        ? ("今日已用 " + todayVal + " GB · 采样积累中，连续运行后自动呈现 14 日趋势")
        : ("Today " + todayVal + " GB · Collecting samples for 14-day trend");
    }

    var topoEl = document.getElementById("quota-topology-list");
    var topo = (runway && Array.isArray(runway.topology)) ? runway.topology : [];
    if (topoEl) {
      if (topo.length > 1) {
        topoEl.hidden = false;
        var topoHead = '<div class="quota-topo-title">' + (zh ? "链路木桶分布" : "Path Bottleneck") + '</div>';
        var topoRows = topo.map(function (item, idx) {
          var isBottleneck = idx === 0 && runway && runway.bottleneck_node && runway.bottleneck_node.host === item.host;
          var roleTxt = item.role === "relay" ? (zh ? "中转" : "Relay") : (zh ? "出口" : "Exit");
          var tagTxt = isBottleneck ? (roleTxt + " · " + (zh ? "瓶颈" : "Cap")) : roleTxt;
          var pctRatio = Math.max(0, Math.min(1, Number(item.used_pct || 0) / 100));
          var fillCls = item.tripped ? "quota-topo-bar tripped" : (item.used_pct >= (breakerPctLbl - 10) ? "quota-topo-bar warn" : "quota-topo-bar");
          var tailTxt = isBottleneck
            ? (zh ? (" · 距熔断 " + item.safe_before_breaker_gb + "G") : (" · " + item.safe_before_breaker_gb + "G safe"))
            : "";
          return '<div class="quota-topo-row">' +
            '<span class="quota-topo-name">' + esc(item.name) + ' <span class="quota-topo-role' + (isBottleneck ? " warn" : "") + '">' + esc(tagTxt) + '</span></span>' +
            '<span class="' + fillCls + '" aria-hidden="true"><i style="--pct:' + pctRatio + '"></i>' + (breakerPctLbl > 0 && breakerPctLbl < 100 ? '<span class="quota-topo-tick" style="left:' + breakerPctLbl + '%"></span>' : '') + '</span>' +
            '<span class="quota-topo-stat">' + item.used_gb + ' / ' + Math.round(item.total_gb) + ' GB <span class="muted">(' + Math.round(item.used_pct) + '%' + tailTxt + ')</span></span>' +
          '</div>';
        }).join("");
        topoEl.innerHTML = topoHead + topoRows;
      } else {
        topoEl.hidden = true;
        topoEl.innerHTML = "";
      }
    }

    syncHeroQuotaSummary();
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
        glanceFill.style.setProperty("--pct", String(Math.max(0, Math.min(1, overallPct / 100))));
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
        var remGb = Math.max(0, Math.round((egressCap - egressUsed) * 100) / 100);
        var usedFmt = (Math.round(egressUsed * 100) / 100).toString();
        var totalFmt = Math.round(egressCap).toString() + " GB";
        var elUsed = document.getElementById("quota-hero-used");
        var elTotal = document.getElementById("quota-hero-total");
        var elPct = document.getElementById("quota-hero-percent");
        var elRem = document.getElementById("quota-hero-rem");
        var elFill = document.getElementById("quota-hero-fill");
        if (elUsed) elUsed.textContent = usedFmt;
        if (elTotal) elTotal.textContent = totalFmt;
        if (elPct) elPct.textContent = "(" + overallPct + "%)";
        if (elRem && !(typeof STATE !== "undefined" && STATE && STATE.trafficReport && STATE.trafficReport.total && STATE.trafficReport.total.runway)) {
          elRem.textContent = remGb + " GB";
        }
        if (elFill) {
          elFill.style.setProperty("--pct", String(Math.max(0, Math.min(1, overallPct / 100))));
          elFill.style.background = overallPct >= 85 ? "var(--apple-red)" : (overallPct >= 75 ? "var(--apple-amber)" : "var(--apple-blue)");
        }
        var anyTripped = groups.some(function(g){ return g.status === "tripped" || (g.percent && g.percent >= 85); });
        if (typeof STATE !== "undefined" && STATE) {
          STATE.heroOverallPct = overallPct;
          STATE.heroAnyTripped = anyTripped;
        }
        syncHeroQuotaSummary();
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
          '<div class="' + barCls + '" role="progressbar" aria-label="' + esc(name) + ' 流量使用进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + barWidth + '"><i style="--pct:' + (barWidth / 100) + '"></i></div>' +
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
      var servingInit = document.getElementById("serving-node-ip");
      if (servingInit) { servingInit.style.display = ""; servingInit.textContent = "离线演示环境"; }
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
      jsonRequest("/api/status.json?_t=" + Date.now(), { signal: signal })
    ]).then(function (res) {
      if (signal && signal.aborted) return;
      if (typeof window !== "undefined" && (window.isTogglingHy2 || window.isRelayMutating)) return;
      var settings = res[0].status === "fulfilled" ? res[0].value : null;
      var nodes = res[1].status === "fulfilled" && Array.isArray(res[1].value) ? res[1].value : null;
      var quota = res[2].status === "fulfilled" && res[2].value && res[2].value.ok === true ? res[2].value : null;
      STATUS = res[3].status === "fulfilled" && res[3].value ? res[3].value : { _unavailable: true };
      var setup = null;
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
        var domTag = document.getElementById("current-domain-tag");
        if (domTag && settings.domain) domTag.textContent = settings.domain;
        if (settings.version && typeof window.ownlineUpdateVersionBadges === "function") {
          window.ownlineUpdateVersionBadges(settings.version);
        }
        jsonRequest("/api/password/state", { signal: signal }).then(function (result) {
          if (signal && signal.aborted) return;
          document.getElementById("change-password-link").style.display = result.ok === true ? "" : "none";
        }).catch(function () { document.getElementById("change-password-link").style.display = "none"; });
      }
      jsonRequest("/api/traffic/stats", { signal: signal }).then(function (ts) {
        if (signal && signal.aborted) return;
        renderTrafficBreakdown(ts);
      }).catch(function () {});
      STATE.csrfToken = setup && typeof setup.csrf_token === "string" ? setup.csrf_token : "";
      STATE.tencentConfigured = !!(settings && settings.tencent_configured === true);
      var canDiscover = !!STATE.csrfToken || !!(settings && settings.tencent_discovery === true) || STATE.tencentConfigured;
      STATE.nodeCheckAvailable = !!(settings && settings.node_check_supported === true);
      setOtherCheckBusy(!!otherCheckController);
      document.getElementById("other-connect-status").textContent = STATE.nodeCheckAvailable
        ? (zh ? "仅测试连接，尚未安装节点。" : "Testing connection only, node not installed yet.")
        : (zh ? "网页连接检测暂不可用，可核对后端状态或使用高级终端接入。" : "Web connection check unavailable; check backend status or use advanced terminal join.");
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
      var servingEl = document.getElementById("serving-node-ip");
      if (nodes) {
        document.getElementById("serving-node-title").textContent = zh ? "连接配置" : "Connection Profiles";
        if (servingEl) {
          if (nodes.length) {
            servingEl.style.display = "none";
            servingEl.textContent = "";
          } else {
            servingEl.style.display = "";
            servingEl.textContent = zh ? "暂无节点连接" : "No nodes connected";
          }
        }
        if (btn) {
          var aText = zh ? "添加节点" : "Add Node";
          btn.title = aText;
          btn.setAttribute("aria-label", aText);
        }
        var bManage = document.getElementById("btn-manage-servers");
        if (bManage) bManage.style.display = "none";
      } else {
        if (servingEl) {
          servingEl.style.display = "";
          servingEl.textContent = zh ? "无法获取服务器状态" : "Unable to reach server";
        }
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
      var recCard = document.getElementById("billing-reconcile-card");
      if (quota) {
        STATE.quota = quota;
        var threshold = quota.watermarks && quota.watermarks.tripped;
        quotaSettings.style.display = modernBackend && Number.isInteger(threshold) && threshold >= 1 && threshold <= 100 ? "" : "none";
        if (recCard) recCard.style.display = modernBackend ? "" : "none";
        var input = document.getElementById("quota-threshold");
        if (document.activeElement !== input && quotaSettings.style.display !== "none") input.value = threshold;
        renderQuotaList(NODES, quota);
      } else {
        STATE.quota = null;
        quotaSettings.style.display = "none";
        if (recCard) recCard.style.display = "none";
        if (nodes && nodes.length) renderQuotaList(nodes, null); else setQuotaMessage(quotaBox, "暂无流量统计");
      }
      renderNodes(NODES, STATUS, quota);
      if ((!NODES || !NODES.length) && typeof paintStatus === "function") paintStatus();
      if (NODES && NODES.length) {
        if (typeof ownlineProbeLocalPing === "function") {
          setTimeout(function () { ownlineProbeLocalPing(); }, 150);
        } else if (typeof window !== "undefined" && typeof window.ownlineProbeLocalPing === "function") {
          setTimeout(function () { window.ownlineProbeLocalPing(); }, 150);
        }
      }
      updateServerCountBadges();
    });
  }

  function updateServerCountBadges() {
    var zh = (typeof isZh === 'function') ? isZh() : true;
    var nodes = (typeof NODES !== 'undefined' && Array.isArray(NODES)) ? NODES : [];
    var distinctHosts = {};
    nodes.forEach(function (n) {
      var h = n.host || n.ip;
      if (h) distinctHosts[h] = true;
    });
    var serverCount = Object.keys(distinctHosts).length || nodes.length;
    var badge = document.getElementById("nodes-count-badge");
    if (badge) badge.textContent = serverCount ? (zh ? serverCount + " 台服务器" : serverCount + (serverCount > 1 ? " servers" : " server")) : "";
    var servingIp = document.getElementById("serving-node-ip");
    if (servingIp) {
      if (serverCount > 0) {
        servingIp.style.display = "none";
        servingIp.textContent = "";
      } else {
        servingIp.style.display = "";
        servingIp.textContent = zh ? "暂无节点连接" : "No nodes connected";
      }
    }
    syncHeroQuotaSummary();
  }
  if (typeof window !== "undefined") {
    window.ownlineUpdateServerCountBadges = updateServerCountBadges;
    window.ownlineRenderTrafficBreakdown = renderTrafficBreakdown;
    window.ownlineRenderQuotaList = renderQuotaList;
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
    var recForm = document.getElementById("billing-reconcile-form");
    if (recForm) {
      var clearRecResult = function () {
        var box = document.getElementById("billing-reconcile-result");
        if (box) box.textContent = "";
      };
      if (typeof recForm.addEventListener === "function") {
        recForm.addEventListener("input", clearRecResult);
        recForm.addEventListener("invalid", clearRecResult, true);
      }
      recForm.onsubmit = function (event) {
        event.preventDefault();
        var zh = (typeof isZh === "function") ? isZh() : true;
        var offInput = document.getElementById("billing-official-gb");
        var rdayInput = document.getElementById("billing-reset-day");
        var resBox = document.getElementById("billing-reconcile-result");
        var btn = document.getElementById("btn-billing-reconcile");
        var officialGb = Number(offInput ? offInput.value : "");
        if (!Number.isFinite(officialGb) || officialGb < 0 || (offInput && offInput.value.trim() === "")) {
          if (resBox) resBox.textContent = zh ? "请输入有效的云控制台已用流量（GB）。" : "Enter valid cloud billing GB.";
          return;
        }
        var payload = { official_gb: officialGb };
        if (rdayInput && rdayInput.value.trim() !== "") {
          payload.official_reset_day = Number(rdayInput.value);
        }
        if (btn) btn.disabled = true;
        if (resBox) resBox.textContent = zh ? "正在核对..." : "Reconciling...";
        fetch(safeUrl("/api/quota/reconcile"), {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data || !data.ok) {
              if (resBox) resBox.textContent = (data && data.error) || (zh ? "核对未完成。" : "Reconcile failed.");
              return;
            }
            var verdict = data.status === "aligned"
              ? (zh ? "已对齐" : "Aligned")
              : (data.status === "minor_drift" ? (zh ? "轻微偏差" : "Minor drift") : (zh ? "差异偏大" : "Discrepancy"));
            var sign = Number(data.delta_gb) >= 0 ? "+" : "";
            var mismatchDetail = (data.panel_reset_day && data.official_reset_day)
              ? (zh ? ("（面板每月 " + data.panel_reset_day + " 号 vs 账单每月 " + data.official_reset_day + " 号）") : (" (panel " + data.panel_reset_day + " vs official " + data.official_reset_day + ")"))
              : "";
            var resetText = data.reset_day_match === true
              ? (zh ? " · 重置日一致" : " · Reset day matches")
              : (data.reset_day_match === false ? ((zh ? " · 重置日不一致" : " · Reset day mismatch") + mismatchDetail) : "");
            if (resBox) {
              resBox.textContent = verdict + "：面板 " + data.panel_gb + " GB / 云账单 " + data.official_gb + " GB（差 " + sign + data.delta_gb + " GB，" + data.delta_pct + "%）" + resetText;
            }
          })
          .catch(function () {
            if (resBox) resBox.textContent = zh ? "账单核对失败，请稍后重试。" : "Failed to reconcile billing.";
          })
          .finally(function () {
            if (btn) btn.disabled = false;
          });
      };
    }
  }


