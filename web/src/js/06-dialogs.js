  function mountSheet(content, resolve, initialSelector) {
    var previous = document.activeElement;
    var w = document.createElement("dialog");
    w.className = "sheet";
    w.innerHTML = '<div class="sheet-inner">' + content + '</div>';
    document.body.appendChild(w);
    var done = false;
    function close(value) {
      if (done) return;
      done = true;
      w.close();
      w.remove();
      resolve(value);
      if (previous && previous.isConnected) previous.focus();
    }
    w.addEventListener("cancel", function (e) { e.preventDefault(); close(null); });
    w.addEventListener("click", function (e) { if (e.target === w) close(null); });
    w.showModal();
    requestAnimationFrame(function () {
      var first = w.querySelector(initialSelector || ".sbtn.ok,.sbtn.danger,.sbtn");
      if (first) first.focus();
    });
    return close;
  }

  function dialog(o) {
    o = o || {};
    return new Promise(function (resolve) {
      var msg = esc(o.message || "").replace(/\n/g, "<br>");
      var content = "<h2>" + esc(o.title || "") + "</h2>" + (msg ? "<p>" + msg + "</p>" : "") +
        '<div class="sheetbtns">' +
        (o.cancelText === null ? "" : '<button type="button" class="sbtn cancel">' + esc(o.cancelText || "取消") + "</button>") +
        '<button type="button" class="sbtn ' + (o.danger ? "danger" : "ok") + '">' + esc(o.confirmText || "确定") + "</button></div>";
      var close = mountSheet(content, resolve);
      var active = document.querySelector("dialog.sheet[open]");
      if (active) {
        var confirmBtn = active.querySelector(".sbtn.ok,.sbtn.danger");
        if (confirmBtn) confirmBtn.addEventListener("click", function () { close(true); });
        var cancelBtn = active.querySelector(".sbtn.cancel");
        if (cancelBtn) cancelBtn.addEventListener("click", function () { close(false); });
      }
    });
  }

  function choose(title, message, actions) {
    return new Promise(function (resolve) {
      var content = "<h2>" + esc(title) + "</h2>" + (message ? "<p>" + esc(message).replace(/\n/g, "<br>") + "</p>" : "") +
        '<div class="sheetbtns">' + actions.map(function (a, i) {
          return '<button type="button" class="sbtn ' + (a.danger ? "danger" : "") + '" data-i="' + i + '">' + esc(a.label) + "</button>";
        }).join("") +
        '<button type="button" class="sbtn cancel">取消</button></div>';
      var close = mountSheet(content, resolve, ".sbtn[data-i]");
      var active = document.querySelector("dialog.sheet[open]");
      if (active) {
        var bs = active.querySelectorAll(".sbtn[data-i]");
        for (var i = 0; i < bs.length; i++) {
          bs[i].addEventListener("click", function () { close(parseInt(this.getAttribute("data-i"), 10)); });
        }
        var cancelBtn = active.querySelector(".sbtn.cancel");
        if (cancelBtn) cancelBtn.addEventListener("click", function () { close(-1); });
      }
    });
  }

  function formSheet(title, fields, confirmText) {
    return new Promise(function (resolve) {
      var content = "<h2>" + esc(title) + "</h2>" + fields.map(function (f, i) {
        return '<div class="field" style="margin-bottom:10px"><label for="sf' + i + '" style="display:block;margin-bottom:4px;font-size:13px;color:var(--muted)">' + esc(f.label) + "</label>" +
          '<input id="sf' + i + '" type="' + (f.type || "text") + '" value="' + esc(f.value === undefined ? "" : String(f.value)) + '" placeholder="' + esc(f.ph || "") + '" style="width:100%;padding:8px 10px;border:1px solid var(--line);background:var(--surface-card)"></div>';
      }).join("") +
        '<div class="sheetbtns" style="margin-top:12px"><button type="button" class="sbtn cancel">取消</button><button type="button" class="sbtn ok">' + esc(confirmText || "保存") + "</button></div>";
      var close = mountSheet(content, resolve, "#sf0");
      var active = document.querySelector("dialog.sheet[open]");
      function save() {
        close(fields.map(function (f, i) { return document.getElementById("sf" + i).value.trim(); }));
      }
      if (active) {
        var okBtn = active.querySelector(".sbtn.ok");
        if (okBtn) okBtn.addEventListener("click", save);
        var cancelBtn = active.querySelector(".sbtn.cancel");
        if (cancelBtn) cancelBtn.addEventListener("click", function () { close(null); });
        active.addEventListener("keydown", function (e) {
          if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); save(); }
        });
      }
    });
  }

