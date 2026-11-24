const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('add-server defaults to zero-CLI Direct SSH form while keeping terminal join as advanced option', () => {
  assert(html.includes('id="tab-btn-ssh-direct"'), '#tab-btn-ssh-direct tab button must exist');
  assert(html.includes('id="tab-btn-reverse-join"'), '#tab-btn-reverse-join tab button must exist');
  assert(html.includes('id="box-reverse-join"'), '#box-reverse-join container must exist');
  assert(html.includes('id="box-ssh-direct"'), '#box-ssh-direct container must exist');
  assert(html.includes('id="btn-gen-reverse-join"'), '#btn-gen-reverse-join button must exist');
  assert(html.includes('id="reverse-join-cmd-box"'), '#reverse-join-cmd-box command card must exist');
  assert(html.includes('id="reverse-join-cmd-text"'), '#reverse-join-cmd-text code block must exist');
  assert(html.includes('id="btn-copy-reverse-join"'), '#btn-copy-reverse-join button must exist');

  assert.match(html, /<button[^>]*class="segbtn active"[^>]*id="tab-btn-ssh-direct"[^>]*aria-pressed="true"/);
  assert.match(html, /<button[^>]*class="segbtn"[^>]*id="tab-btn-reverse-join"[^>]*aria-pressed="false"/);
  assert.match(html, /<div id="box-reverse-join" style="display:none">/);
  assert.match(html, /<div id="box-ssh-direct" style="display:block">/);
});

test('reverse join ui: i18n dictionary contains honest keys in both zh and en', () => {
  const i18nSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/01-i18n.js'), 'utf8');
  assert(i18nSrc.includes('tab_ssh_direct: "Direct SSH (Recommended)"'), 'en tab_ssh_direct missing');
  assert(i18nSrc.includes('tab_ssh_direct: "填写服务器信息（推荐）"'), 'zh tab_ssh_direct missing');
  assert(i18nSrc.includes('tab_reverse_join: "Terminal Join (Advanced)"'), 'en tab_reverse_join missing');
  assert(i18nSrc.includes('tab_reverse_join: "免密终端接入（高级）"'), 'zh tab_reverse_join missing');
  assert(i18nSrc.includes('btn_gen_join_cmd: "Generate Join Command"'), 'en btn_gen_join_cmd missing');
  assert(i18nSrc.includes('btn_gen_join_cmd: "生成接入命令"'), 'zh btn_gen_join_cmd missing');
});
