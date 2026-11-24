function hasSSHPrivateKeyHeader(text) {
  return /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/.test(text);
}

function bindSSHKeyPaste(input, onKeyChange) {
  input.addEventListener("paste", function (event) {
    const text = event.clipboardData && event.clipboardData.getData("text/plain");
    if (!text || !hasSSHPrivateKeyHeader(text)) return;
    event.preventDefault();
    input.value = "";
    onKeyChange(text);
  });
  input.addEventListener("input", function () { onKeyChange(""); });
}

async function copySetupText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const input = document.createElement("textarea");
    input.value = text;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    try {
      input.select();
      return document.execCommand("copy");
    } catch (_) {
      return false;
    } finally {
      input.remove();
    }
  }
}

function _setSecretToggleState(btn, visible) {
  btn.setAttribute("aria-pressed", String(visible));
  btn.setAttribute("aria-label", visible ? "隐藏密码" : "显示密码");
  const useEl = typeof btn.querySelector === "function" ? btn.querySelector("use") : null;
  if (useEl && typeof useEl.setAttribute === "function") {
    useEl.setAttribute("href", visible ? "#i-eye-off" : "#i-eye");
  }
}

function initSecretToggles(root) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  const doc = typeof document !== "undefined" ? document : root;
  const buttons = root.querySelectorAll("[data-toggle-secret]");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const targetId = btn.getAttribute("data-toggle-secret");
      const input = targetId && typeof doc.getElementById === "function" ? doc.getElementById(targetId) : null;
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      _setSecretToggleState(btn, show);
    });
  });
}

function resetSecretToggles(root) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  const doc = typeof document !== "undefined" ? document : root;
  root.querySelectorAll("[data-toggle-secret]").forEach(function (btn) {
    const targetId = btn.getAttribute("data-toggle-secret");
    const input = targetId && typeof doc.getElementById === "function" ? doc.getElementById(targetId) : null;
    if (input && input.type === "text") input.type = "password";
    _setSecretToggleState(btn, false);
  });
}

function initAccessibleValidation(root) {
  if (!root || typeof root.querySelectorAll !== "function" || typeof root.addEventListener !== "function") return;
  const flagged = typeof WeakSet !== "undefined" ? new WeakSet() : null;
  const syncAria = function (el) {
    if (!el || typeof el.matches !== "function" || !el.matches("input, select, textarea")) return;
    let invalid = false;
    try {
      invalid = el.matches(":user-invalid");
    } catch (_) {
      return;
    }
    if (invalid) {
      el.setAttribute("aria-invalid", "true");
      if (flagged) flagged.add(el);
    } else if ((flagged && flagged.has(el)) || el.getAttribute("aria-invalid") !== "true") {
      el.setAttribute("aria-invalid", "false");
      if (flagged) flagged.delete(el);
    }
  };
  root.querySelectorAll("input, select, textarea").forEach(function (el) { syncAria(el); });
  root.addEventListener("blur", function (e) { syncAria(e.target); }, true);
  root.addEventListener("input", function (e) {
    if (e.target && typeof e.target.hasAttribute === "function" && e.target.hasAttribute("aria-invalid")) {
      syncAria(e.target);
    }
  });
  root.addEventListener("change", function (e) { syncAria(e.target); }, true);
  root.addEventListener("invalid", function (e) { syncAria(e.target); }, true);
  root.addEventListener("reset", function (e) {
    const form = e.target;
    if (!form || !form.elements) return;
    setTimeout(function () {
      Array.prototype.forEach.call(form.elements, function (el) { syncAria(el); });
    }, 0);
  }, true);
}
