const test = require('node:test');
const assert = require('node:assert/strict');
require('../web/backup-crypto.js');

test('node backups encrypt in the browser and reject incorrect passwords or tampering', async () => {
  const input = {nodes: [{name: 'test-node', host: '198.51.100.1', port: 443, uuid: 'private-test-value'}], sub_token: 'abcd1234'};
  const password = 'a sufficiently long password';
  const encrypted = await globalThis.OwnlineBackupCrypto.encrypt(input, password);
  assert(!JSON.stringify(encrypted).includes('private-test-value'));
  assert(!JSON.stringify(encrypted).includes('abcd1234'));
  assert.deepEqual(await globalThis.OwnlineBackupCrypto.decrypt(encrypted, password), input);
  await assert.rejects(globalThis.OwnlineBackupCrypto.decrypt(encrypted, 'wrong password'));
  const bytes = Uint8Array.from(atob(encrypted.ciphertext), c => c.charCodeAt(0));
  bytes[0] ^= 1;
  const damaged = {...encrypted, ciphertext: btoa(String.fromCharCode(...bytes))};
  await assert.rejects(globalThis.OwnlineBackupCrypto.decrypt(damaged, password));
  const second = await globalThis.OwnlineBackupCrypto.encrypt(input, password);
  assert.notEqual(encrypted.salt, second.salt);
  assert.notEqual(encrypted.iv, second.iv);
});

test('rejects unexpected work factors and unsupported encrypted formats', async () => {
  const encrypted = await globalThis.OwnlineBackupCrypto.encrypt({nodes: []}, 'a sufficiently long password');
  await assert.rejects(globalThis.OwnlineBackupCrypto.decrypt({...encrypted, iterations: 1}, 'a sufficiently long password'));
  await assert.rejects(globalThis.OwnlineBackupCrypto.decrypt({...encrypted, version: 2}, 'a sufficiently long password'));
});
