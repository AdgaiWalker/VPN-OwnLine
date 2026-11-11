const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('system updater ui: version elements in preferences dialog, header, and footer', () => {
  // 1. Settings icon in header has subtle update notification dot
  assert(html.includes('id="settings-update-dot"'), '#settings-update-dot must exist on settings button');

  // 2. Preferences dialog has system version section
  assert(html.includes('id="settings-lbl-version"'), '#settings-lbl-version must exist in preferences');
  assert(html.includes('id="current-version-tag"'), '#current-version-tag must exist in preferences');
  assert(html.includes('id="update-info-card"'), '#update-info-card must exist');
  assert(html.includes('id="btn-check-update"'), '#btn-check-update must exist');

  // 3. Action and progress boxes
  assert(html.includes('id="update-action-box"'), '#update-action-box must exist for new release notice');
  assert(html.includes('id="btn-perform-upgrade"'), '#btn-perform-upgrade button must exist');
  assert(html.includes('id="update-progress-box"'), '#update-progress-box must exist for in-progress feedback');

  // 4. Footer has version tag
  assert(html.includes('id="footer-version-tag"'), '#footer-version-tag must exist in site-footer');
});

test('system updater ui: function signatures and updater methods exist in client script', () => {
  assert(html.includes('function ownlineCheckUpdate'), 'ownlineCheckUpdate must exist');
  assert(html.includes('function ownlinePerformUpgrade'), 'ownlinePerformUpgrade must exist');
  assert(html.includes('function pollForRecovery'), 'pollForRecovery must exist');
  assert(html.includes('function initUpdater'), 'initUpdater must exist');
});
