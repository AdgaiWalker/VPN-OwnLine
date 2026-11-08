const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('button placement: management-help is removed and buttons relocated contextually', () => {
  // 1. The old generic dumping ground #management-help must not exist
  assert.equal(html.includes('id="management-help"'), false, '#management-help should be eliminated');

  // 2. Backup and restore buttons are inside #nodes-section
  const nodesSectionMatch = html.match(/<details[^>]*id="nodes-section"[^>]*>([\s\S]*?)<\/details>/);
  assert(nodesSectionMatch, 'missing #nodes-section');
  const nodesSectionHtml = nodesSectionMatch[1];
  assert(nodesSectionHtml.includes('id="backup-export"'), '#backup-export must be inside #nodes-section');
  assert(nodesSectionHtml.includes('id="backup-restore"'), '#backup-restore must be inside #nodes-section');
  assert(nodesSectionHtml.includes('id="backup-file"'), '#backup-file must be inside #nodes-section');
  assert(nodesSectionHtml.includes('id="backup-note"'), '#backup-note must be inside #nodes-section');

  // 3. Quota settings form is inside #quota-section
  const quotaSectionMatch = html.match(/<details[^>]*id="quota-section"[^>]*>([\s\S]*?)<\/details>/);
  assert(quotaSectionMatch, 'missing #quota-section');
  const quotaSectionHtml = quotaSectionMatch[1];
  assert(quotaSectionHtml.includes('id="quota-settings"'), '#quota-settings must be inside #quota-section');
  assert(quotaSectionHtml.includes('id="quota-form"'), '#quota-form must be inside #quota-section');

  // 4. Revoke Old Subscription is inside #download-help in client hub
  const downloadHelpMatch = html.match(/<details[^>]*id="download-help"[^>]*>([\s\S]*?)<\/details>/);
  assert(downloadHelpMatch, 'missing #download-help');
  const downloadHelpHtml = downloadHelpMatch[1];
  assert(downloadHelpHtml.includes('id="btn-rotate"'), '#btn-rotate must be inside #download-help');
  assert(downloadHelpHtml.includes('window.ownlineRotate()'), 'ownlineRotate must be wired');

  // 5. Health check, Copy Diagnostics, and Syslogs are inside #section-logs
  const sectionLogsMatch = html.match(/<details[^>]*id="section-logs"[^>]*>([\s\S]*?)<\/details>/);
  assert(sectionLogsMatch, 'missing #section-logs');
  const sectionLogsHtml = sectionLogsMatch[1];
  assert(sectionLogsHtml.includes('window.ownlineHealth()'), 'Health check must be inside #section-logs');
  assert(sectionLogsHtml.includes('id="btn-copy-diag"'), 'Copy diagnostics must be inside #section-logs');
  assert(sectionLogsHtml.includes('id="health"'), '#health result box must be inside #section-logs');
  assert(sectionLogsHtml.includes('id="syslog-box"'), '#syslog-box must be inside #section-logs');

  // 6. Change admin password link is in site footer
  const footerMatch = html.match(/<footer[^>]*class="site-footer"[^>]*>([\s\S]*?)<\/footer>/);
  assert(footerMatch, 'missing footer.site-footer');
  assert(footerMatch[1].includes('id="change-password-link"'), '#change-password-link must be in footer');
});

test('quota hero banner and integrated node quota bar exist', () => {
  assert(html.includes('id="quota-hero-banner"'), '#quota-hero-banner must exist');
  assert(html.includes('id="quota-hero-used"'), '#quota-hero-used must exist');
  assert(html.includes('id="quota-hero-total"'), '#quota-hero-total must exist');
  assert(html.includes('id="quota-hero-fill"'), '#quota-hero-fill must exist');
  assert(html.includes('node-quota-row'), 'node quota row class must exist in index.html');
});

test('nodeMenu: concise action items without jargon, self-heal hidden when node is healthy', () => {
  const vm = require('node:vm');
  function source(name) {
    const match = html.match(new RegExp('^  function ' + name + '\\([^\\n]*\\)\\s*\\{[\\s\\S]*?^  \\}', 'm'));
    assert(match, `missing ${name}`);
    return match[0];
  }
  let capturedTitle, capturedMsg, capturedItems;
  const c = vm.createContext({
    NODES: [
      { name: '硅谷', host: '203.0.113.10', port: 443, role: 'exit', health: 'ok' },
      { name: '坏节点', host: '198.51.100.4', port: 443, role: 'exit', health: 'bad' }
    ],
    STATUS: {
      '硅谷': { ok: true, ms: 2, cn_ok: true, cn_ms: 151 },
      '坏节点': { ok: false, ms: 0, reason: 'port' }
    },
    choose: (title, msg, items) => {
      capturedTitle = title;
      capturedMsg = msg;
      capturedItems = items;
      return Promise.resolve(-1);
    }
  });
  vm.runInContext(source('nodeMenu'), c);

  // 1. Healthy node check
  c.nodeMenu(0);
  assert.equal(capturedTitle, '硅谷');
  assert.match(capturedMsg, /203\.0\.113\.10 · 端口 443/);
  assert.match(capturedMsg, /在线 · 延迟 151ms/);
  const healthyLabels = capturedItems.map(it => it.label);
  assert.deepEqual([...healthyLabels], [
    '修改名称与端口',
    '暂停使用',
    '绑定住宅 IP',
    '设置到期提醒',
    '重置密钥（断开所有设备）',
    '删除节点'
  ]);
  // Verify self-heal is NOT shown for healthy node
  assert.equal(healthyLabels.includes('一键修复重启'), false, 'Self-heal must not show for healthy node');
  // Verify no mechanical "Title · Redundant description"
  healthyLabels.forEach(l => {
    assert.equal(l.includes('·'), false, `Label "${l}" should not contain redundant middle dots`);
  });

  // 2. Unhealthy node check: fake self-heal (guaranteed to fail) must never be offered
  c.nodeMenu(1);
  const badLabels = capturedItems.map(it => it.label);
  assert.equal(badLabels.includes('一键修复重启'), false, 'Fake self-heal must not be offered');
  assert.equal(html.includes('ownlineRepairNode'), false, 'repair button must be removed');
  assert.equal(html.includes('ownlineRepairAllBad'), false, 'repair-all button must be removed');
});

test('apple hig: round icon buttons and credentials form autofill protection', () => {
  // 1. #btn-enter-setup must be an icon button with svg and must not be overwritten by textContent in refreshState
  assert(html.includes('id="btn-enter-setup"'), '#btn-enter-setup must exist');
  assert(html.includes('class="icon-btn-round" type="button" id="btn-enter-setup"'), '#btn-enter-setup must have class icon-btn-round');
  assert(html.includes('<svg class="ico" width="14" height="14"><use href="#i-plus"/></svg>'), '#btn-enter-setup must contain plus svg icon');
  assert.equal(html.includes('btn.textContent = zh ? "+ 添加节点" : "+ Add Node";'), false, 'refreshState must not wipe out plus icon with btn.textContent');

  // 2. .icon-btn-round must defensively contain overflow and nowrap
  assert.match(html, /\.icon-btn-round\s*\{[\s\S]*?overflow:\s*hidden;/);
  assert.match(html, /\.icon-btn-round\s*\{[\s\S]*?white-space:\s*nowrap;/);

  // 3. Settings dialog: username must have autocomplete="off" and current account must be displayed
  assert(html.includes('id="settings-display-username"'), 'Current account display must exist');
  assert.match(html, /<input[^>]*id="settings-username"[^>]*autocomplete="off"[^>]*>/, '#settings-username must have autocomplete="off" to prevent IP autofill');
  assert.equal(html.includes('id="settings-username" type="text" autocomplete="username"'), false, '#settings-username must not declare autocomplete="username"');

  // 4. change-password.html: username must also have autocomplete="off" and current account display
  const cpPath = path.join(__dirname, '../web/change-password.html');
  const cpHtml = fs.readFileSync(cpPath, 'utf8');
  assert(cpHtml.includes('id="display-username"'), 'Current account display must exist in change-password.html');
  assert.match(cpHtml, /<input[^>]*id="username"[^>]*autocomplete="off"[^>]*>/, '#username in change-password.html must have autocomplete="off"');
});

