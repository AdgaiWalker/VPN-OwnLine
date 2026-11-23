const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const onboarding = JSON.parse(fs.readFileSync(path.join(__dirname, '../web/src/data/onboarding.json'), 'utf8'));
const skillMd = fs.readFileSync(path.join(__dirname, '../skills/ownline-local/SKILL.md'), 'utf8');

test('ssh ai prompt: HTML elements, onboarding brief, and SKILL.md exist', () => {
  assert(html.includes('id="btn-copy-ssh-ai-prompt"'), '#btn-copy-ssh-ai-prompt button must exist in index.html');
  assert(html.includes('id="ai-ssh-prompt-text"'), '#ai-ssh-prompt-text pre element must exist in index.html');
  assert(html.includes('data-i18n="ssh_copy_ai_prompt"'), 'data-i18n attribute for copy button must exist');
  assert(html.includes('data-i18n="ssh_need_assist"'), 'data-i18n attribute for prompt label must exist');

  // Verify prompt content integrity
  assert(html.includes('Evergreen · OwnLine'), 'Prompt must mention Evergreen · OwnLine');
  assert(html.includes('Ubuntu 22.04+'), 'Prompt must specify Ubuntu 22.04+ compatibility');
  assert(html.includes('Debian 12+'), 'Prompt must specify Debian 12+ compatibility');
  assert(html.includes('22、443、8443'), 'Prompt must specify ports 22, 443, 8443');
  assert(html.includes('verify.py'), 'Prompt must reference verify.py for turnkey test');

  // Verify canonical SSOT brief and SKILL.md integrity
  assert.equal(typeof onboarding.agent_brief, 'string', 'onboarding.json must define agent_brief');
  assert(onboarding.agent_brief.includes('Evergreen · OwnLine'), 'agent_brief must reference project');
  assert(onboarding.agent_brief.includes('ownline.py vault request'), 'agent_brief must reference blind vault CLI');
  assert(skillMd.includes('Evergreen OwnLine Local Agent Skill'), 'SKILL.md must have title');

  // Verify blind vault & zero plaintext secret policy
  assert(html.includes('ownline.py vault request'), 'index.html prompt must reference blind vault CLI');
  assert(skillMd.includes('ownline.py vault request'), 'SKILL.md must reference blind vault CLI');
  assert(!html.includes('填入新服务器 IP、密码、密钥'), 'index.html must not tell users to paste secrets in chat');
  assert(!onboarding.agent_brief.includes('填入新服务器 IP、密码、密钥'), 'agent_brief must not tell users to paste secrets in chat');
  assert(!skillMd.includes('填入新服务器 IP、密码、密钥'), 'SKILL.md must not tell users to paste secrets in chat');
});

test('ssh ai prompt: i18n dictionary contains required keys in both zh and en', () => {
  const i18nSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/01-i18n.js'), 'utf8');
  assert(i18nSrc.includes('ssh_need_assist: "Need autonomous onboarding with local Agent?"'), 'en ssh_need_assist key missing');
  assert(i18nSrc.includes('ssh_copy_ai_prompt: "Copy Agent Task Brief"'), 'en ssh_copy_ai_prompt key missing');
  assert(i18nSrc.includes('ssh_need_assist: "借助本地 Agent 全自动装配？"'), 'zh ssh_need_assist key missing');
  assert(i18nSrc.includes('ssh_copy_ai_prompt: "复制 Agent 任务书"'), 'zh ssh_copy_ai_prompt key missing');
});

test('ssh ai prompt: setupAiPrompt binds copy handler for ssh prompt button', async () => {
  let copiedText = null;
  const mockBtn = {
    textContent: '复制 Agent 任务书',
    onclick: null
  };
  const mockPre = {
    textContent: '你是一个在「Evergreen · OwnLine」代码仓库根目录下工作的本地运维智能体...'
  };

  const sandbox = {
    document: {
      getElementById: (id) => {
        if (id === 'btn-copy-ssh-ai-prompt') return mockBtn;
        if (id === 'ai-ssh-prompt-text') return mockPre;
        return null;
      }
    },
    navigator: {
      clipboard: {
        writeText: (txt) => {
          copiedText = txt;
          return Promise.resolve();
        }
      }
    },
    setTimeout: (fn) => setTimeout(fn, 10),
    isZh: () => true
  };
  vm.createContext(sandbox);

  const connSrc = fs.readFileSync(path.join(__dirname, '../web/src/js/03-connection.js'), 'utf8');
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/src/js/00-setup-input.js'), 'utf8'), sandbox);
  vm.runInContext(connSrc + '; if (typeof setupAiPrompt === "function") setupAiPrompt();', sandbox);

  assert.equal(typeof mockBtn.onclick, 'function', 'onclick handler should be attached');
  await mockBtn.onclick();
  assert.equal(copiedText, mockPre.textContent, 'clipboard should receive prompt text');
  assert.equal(mockBtn.textContent, '已复制', 'button text should temporarily switch to 已复制');
});
