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
