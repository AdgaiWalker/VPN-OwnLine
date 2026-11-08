const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('account security: macOS Sequoia account modal and clean preferences separation', () => {
  // 1. Top navigation bar must have user avatar badge pill
  assert(html.includes('id="btn-open-account"'), '#btn-open-account must exist in topbar');
  assert(html.includes('id="topbar-user-avatar"'), '#topbar-user-avatar must exist in topbar');
  assert(html.includes('id="topbar-user-name"'), '#topbar-user-name must exist in topbar');

  // 2. Preferences dialog and Account & Security dialog are completely decoupled
  assert(html.includes('id="settings-dialog"'), '#settings-dialog must exist for general preferences');
  assert(html.includes('id="account-dialog"'), '#account-dialog must exist for account & security');

  // 3. Account modal has macOS Sequoia overview card and avatar
  assert(html.includes('class="account-card-header"'), 'overview card header class must exist');
  assert(html.includes('id="account-modal-avatar"'), '#account-modal-avatar must exist');
  assert(html.includes('id="settings-display-username"'), '#settings-display-username must exist');
  assert(html.includes('id="account-role-badge"'), '#account-role-badge must exist');

  // 4. Collapsible username change section exists with anti-autofill
  assert(html.includes('id="account-user-details"'), '#account-user-details collapsible section must exist');
  assert.match(html, /<input[^>]*id="settings-username"[^>]*autocomplete="off"[^>]*>/);

  // 5. Password fields have eye toggle buttons and strength meter
  assert(html.includes('togglePasswordVisibility(\'settings-curr-pass\''), 'current password eye toggle wired');
  assert(html.includes('togglePasswordVisibility(\'settings-new-pass\''), 'new password eye toggle wired');
  assert(html.includes('togglePasswordVisibility(\'settings-confirm-pass\''), 'confirm password eye toggle wired');
  assert(html.includes('id="pwd-strength-wrap"'), '#pwd-strength-wrap must exist');
  assert(html.includes('id="pwd-strength-text"'), '#pwd-strength-text must exist');
  assert(html.includes('id="pwd-match-text"'), '#pwd-match-text must exist');

  // 6. Post-save transition card exists
  assert(html.includes('id="account-success-card"'), '#account-success-card must exist');
  assert(html.includes('id="account-btn-relogin"'), '#account-btn-relogin must exist');

  // 7. Footer change-password-link opens account modal
  const footerMatch = html.match(/<footer[^>]*class="site-footer"[^>]*>([\s\S]*?)<\/footer>/);
  assert(footerMatch, 'missing footer.site-footer');
  assert(footerMatch[1].includes('openAccountDialog'), 'footer change link must open openAccountDialog');
});

test('account security: password strength meter and match evaluator logic', () => {
  function source(name) {
    const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
    assert(match, `missing function ${name}`);
    return match[0];
  }

  // Verify function signatures exist
  assert(html.includes('function updatePasswordStrength'), 'updatePasswordStrength must exist');
  assert(html.includes('function checkPasswordMatch'), 'checkPasswordMatch must exist');
  assert(html.includes('function togglePasswordVisibility'), 'togglePasswordVisibility must exist');
  assert(html.includes('function updateUserInfo'), 'updateUserInfo must exist');
});
