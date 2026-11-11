(function () {
  "use strict";

  var LOCAL_PING_STATE = {
    results: {},
    isProbing: false,
    lastProbeTime: 0
  };
  window.LOCAL_PING_STATE = LOCAL_PING_STATE;

  function probeTargetSingleAttempt(host, port, timeoutMs) {
    port = port || 443;
    timeoutMs = timeoutMs || 2500;
    var url = "https://" + host + ":" + port + "/__probe_ping?_t=" + Date.now() + "_" + Math.random().toString(36).slice(2, 7);
    var startTime = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();

    var controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var signal = controller ? controller.signal : undefined;
    var timer = null;

    var probePromise = new Promise(function (resolve) {
      if (controller) {
        timer = setTimeout(function () {
          try { controller.abort(); } catch (e) {}
          resolve({ ok: false, ms: null, timeout: true });
        }, timeoutMs);
      } else {
        timer = setTimeout(function () {
          resolve({ ok: false, ms: null, timeout: true });
        }, timeoutMs);
      }

      fetch(url, {
        mode: "no-cors",
        cache: "no-store",
        signal: signal
      }).then(function () {
        if (timer) clearTimeout(timer);
        var now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        var elapsed = Math.round(now - startTime);
        resolve({ ok: true, ms: elapsed, timeout: false });
      }).catch(function (err) {
        if (timer) clearTimeout(timer);
        var now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        var elapsed = Math.round(now - startTime);
        if (err && err.name === "AbortError") {
          resolve({ ok: false, ms: null, timeout: true });
        } else if (elapsed >= timeoutMs) {
          resolve({ ok: false, ms: null, timeout: true });
        } else {
          // Network error after TCP SYN/ACK or TLS alert: elapsed reflects physical RTT
          resolve({ ok: true, ms: elapsed, timeout: false });
        }
      });
    });

    return probePromise;
  }

  function probeHostLatency(host, port) {
    // 2-round sampling: warm-up + measurement to eliminate DNS/handshake cold-start jitter
    return probeTargetSingleAttempt(host, port, 2500).then(function (r1) {
      if (!r1.ok) {
        return r1;
      }
      return new Promise(function (resolve) {
        setTimeout(function () {
          probeTargetSingleAttempt(host, port, 2500).then(function (r2) {
            if (!r2.ok) {
              resolve(r1);
            } else {
              var bestMs = Math.min(r1.ms, r2.ms);
              resolve({ ok: true, ms: bestMs, timeout: false });
            }
          });
        }, 80);
      });
    });
  }

  function ownlineProbeLocalPing(force) {
    if (LOCAL_PING_STATE.isProbing && !force) {
      return Promise.resolve(LOCAL_PING_STATE.results);
    }
    var nodes = window.NODES || [];
    if (!nodes.length) {
      return Promise.resolve(LOCAL_PING_STATE.results);
    }

    LOCAL_PING_STATE.isProbing = true;

    // Collect unique hosts to probe
    var targets = {};
    nodes.forEach(function (n) {
      if (!n || !n.host) return;
      var host = n.host;
      var port = n.port || 443;
      var key = host;
      if (!targets[key]) {
        targets[key] = { host: host, port: port };
      }
      LOCAL_PING_STATE.results[key] = {
        probing: true,
        ms: (LOCAL_PING_STATE.results[key] && LOCAL_PING_STATE.results[key].ms != null)
          ? LOCAL_PING_STATE.results[key].ms
          : null,
        ok: true,
        ts: Date.now()
      };
    });

    if (typeof window.paintStatus === "function") {
      window.paintStatus();
    }

    var promises = Object.keys(targets).map(function (key) {
      var t = targets[key];
      return probeHostLatency(t.host, t.port).then(function (res) {
        LOCAL_PING_STATE.results[key] = {
          probing: false,
          ms: res.ok ? res.ms : null,
          ok: res.ok,
          timeout: res.timeout || false,
          ts: Date.now()
        };
        if (typeof window.paintStatus === "function") {
          window.paintStatus();
        }
      });
    });

    return Promise.all(promises).then(function () {
      LOCAL_PING_STATE.isProbing = false;
      LOCAL_PING_STATE.lastProbeTime = Date.now();
      if (typeof window.paintStatus === "function") {
        window.paintStatus();
      }
      return LOCAL_PING_STATE.results;
    }).catch(function () {
      LOCAL_PING_STATE.isProbing = false;
      if (typeof window.paintStatus === "function") {
        window.paintStatus();
      }
      return LOCAL_PING_STATE.results;
    });
  }

  function initLocalPing() {
    // Quiet background pre-probing after initial UI sync
    setTimeout(function () {
      ownlineProbeLocalPing();
    }, 2000);
  }

  window.ownlineProbeLocalPing = ownlineProbeLocalPing;
  window.initLocalPing = initLocalPing;
  window.probeHostLatency = probeHostLatency;
  window.probeTargetSingleAttempt = probeTargetSingleAttempt;
})();
