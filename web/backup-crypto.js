/* Node configuration exports are encrypted in the browser before downloading. */
(function (root) {
  'use strict';
  var ITERATIONS = 310000;
  var encoder = new TextEncoder();
  function bytesToBase64(bytes) {
    var result = '';
    for (var i = 0; i < bytes.length; i += 8192) {
      result += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
    }
    return btoa(result);
  }
  function base64ToBytes(value) {
    if (typeof value !== 'string' || value.length > 2000000) throw new Error('备份文件格式不正确');
    var text = atob(value);
    var result = new Uint8Array(text.length);
    for (var i = 0; i < text.length; i++) result[i] = text.charCodeAt(i);
    return result;
  }
  async function derive(password, salt, iterations) {
    var material = await root.crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveKey']);
    return root.crypto.subtle.deriveKey(
      {name: 'PBKDF2', hash: 'SHA-256', salt: salt, iterations: iterations},
      material, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']
    );
  }
  async function encrypt(data, password) {
    var salt = root.crypto.getRandomValues(new Uint8Array(16));
    var iv = root.crypto.getRandomValues(new Uint8Array(12));
    var key = await derive(password, salt, ITERATIONS);
    var ciphertext = await root.crypto.subtle.encrypt({name: 'AES-GCM', iv: iv}, key, encoder.encode(JSON.stringify(data)));
    return {format: 'ownline-node-backup', version: 1, kdf: 'PBKDF2-SHA256', iterations: ITERATIONS,
      cipher: 'AES-256-GCM', salt: bytesToBase64(salt), iv: bytesToBase64(iv),
      ciphertext: bytesToBase64(new Uint8Array(ciphertext))};
  }
  async function decrypt(data, password) {
    if (!data || data.format !== 'ownline-node-backup' || data.version !== 1 || data.kdf !== 'PBKDF2-SHA256' ||
        data.cipher !== 'AES-256-GCM' || data.iterations !== ITERATIONS) throw new Error('不支持的备份格式');
    var salt = base64ToBytes(data.salt), iv = base64ToBytes(data.iv), ciphertext = base64ToBytes(data.ciphertext);
    if (salt.length !== 16 || iv.length !== 12 || ciphertext.length < 16) throw new Error('备份文件格式不正确');
    var key = await derive(password, salt, data.iterations);
    var plain = await root.crypto.subtle.decrypt({name: 'AES-GCM', iv: iv}, key, ciphertext);
    return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(plain));
  }
  root.OwnlineBackupCrypto = {encrypt: encrypt, decrypt: decrypt};
})(globalThis);
