  // 07b-local-ping.js - Client-Side Real-Time Network Probing
  var LOCAL_DEVICE_PING = {
    ms: null,
    probing: false,
    lastProbeTime: 0,
    status: "ok"
  };
  if (typeof window !== "undefined") {
    window.LOCAL_DEVICE_PING = LOCAL_DEVICE_PING;
  }

  function probeDeviceLocalLatency() {
    LOCAL_DEVICE_PING.probing = true;
    updateHeaderLocalPingUI();

    var attempt = function () {
      var startTime = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
      var controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
      var timer = controller ? setTimeout(function () { try { controller.abort(); } catch (e) {} }, 3000) : null;
      var url = "/api/ping?_t=" + Date.now() + "_" + Math.random().toString(36).slice(2, 6);

      return fetch(url, {
        method: "GET",
        cache: "no-store",
        signal: controller ? controller.signal : undefined
      }).then(function () {
        if (timer) clearTimeout(timer);
        var now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        return Math.max(1, Math.round(now - startTime));
      }).catch(function () {
        if (timer) clearTimeout(timer);
        return null;
      });
    };

    // 2-round sampling: warm-up + measurement to eliminate first-packet/TLS renegotiation jitter
    return attempt().then(function (r1) {
      if (r1 === null) {
        LOCAL_DEVICE_PING.ms = null;
        LOCAL_DEVICE_PING.probing = false;
        LOCAL_DEVICE_PING.status = "bad";
        LOCAL_DEVICE_PING.lastProbeTime = Date.now();
        updateHeaderLocalPingUI();
        if (typeof paintStatus === "function") paintStatus();
        return null;
      }
      return new Promise(function (resolve) {
        setTimeout(function () {
          attempt().then(function (r2) {
            var best = (r2 !== null) ? Math.min(r1, r2) : r1;
            LOCAL_DEVICE_PING.ms = best;
            LOCAL_DEVICE_PING.probing = false;
            LOCAL_DEVICE_PING.status = best <= 80 ? "fast" : (best <= 220 ? "medium" : "slow");
            LOCAL_DEVICE_PING.lastProbeTime = Date.now();
            updateHeaderLocalPingUI();
            if (typeof paintStatus === "function") paintStatus();
            resolve(best);
          });
        }, 60);
      });
    });
  }

  function updateHeaderLocalPingUI() {
    var pill = document.getElementById("header-local-ping");
    if (!pill) return;
    var zh = (typeof isZh === "function") ? isZh() : true;

    if (LOCAL_DEVICE_PING.probing) {
      pill.style.display = "inline-flex";
      pill.className = "ping-pill local-ping probing";
      pill.textContent = zh ? "📱 本机: 测速中..." : "📱 Local: Probing...";
      pill.title = zh ? "正在测量当前设备到控制台网关的往返物理延迟..." : "Measuring RTT from this device to gateway...";
      return;
    }

    if (LOCAL_DEVICE_PING.ms != null) {
      pill.style.display = "inline-flex";
      var ms = LOCAL_DEVICE_PING.ms;
      var cls = ms <= 80 ? "fast" : (ms <= 220 ? "medium" : "slow");
      pill.className = "ping-pill local-ping " + cls;
      pill.textContent = "📱 " + (zh ? "本机 " : "Local ") + ms + "ms";
      var qualityText = ms <= 80 ? (zh ? "局域网及接入网络质量优秀" : "Local network quality is excellent")
        : (ms <= 220 ? (zh ? "当前网络存在轻微波动或中等延迟" : "Moderate network latency detected")
        : (zh ? "当前本地网络/WiFi延迟偏高，可能影响连接流畅度" : "High local network latency detected"));
      pill.title = (zh ? ("当前设备直连管理网关真实往返延迟: " + ms + "ms\n" + qualityText)
                       : ("Real device RTT to gateway: " + ms + "ms\n" + qualityText));
      return;
    }

    if (LOCAL_DEVICE_PING.status === "bad") {
      pill.style.display = "inline-flex";
      pill.className = "ping-pill local-ping slow";
      pill.textContent = zh ? "📱 本机网络异常" : "📱 Local Network Error";
      pill.title = zh ? "无法连接到网关，请检查当前网络状态" : "Unable to reach gateway, please check network connection";
    }
  }

  function initLocalPing() {
    setTimeout(function () {
      probeDeviceLocalLatency();
    }, 800);
  }

  if (typeof window !== "undefined") {
    window.LOCAL_DEVICE_PING = LOCAL_DEVICE_PING;
    window.ownlineProbeLocalPing = probeDeviceLocalLatency;
    window.updateHeaderLocalPingUI = updateHeaderLocalPingUI;
    window.initLocalPing = initLocalPing;
  }
