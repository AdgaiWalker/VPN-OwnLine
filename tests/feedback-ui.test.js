const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

test('feedback ui: quick feedback entry points and dialog structure', () => {
  // 1. Topbar feedback button
  assert(html.includes('id="btn-open-feedback"'), '#btn-open-feedback must exist in topbar');
  assert(html.includes('class="icon-btn-round" id="btn-open-feedback"'), '#btn-open-feedback must have class icon-btn-round');
  assert(html.includes('<use href="#i-feedback"/>'), '#btn-open-feedback must reference #i-feedback SVG');
  assert(html.includes('window.openFeedbackDialog()'), '#btn-open-feedback must trigger openFeedbackDialog');

  // 2. Footer feedback button
  const footerMatch = html.match(/<footer[^>]*class="site-footer"[^>]*>([\s\S]*?)<\/footer>/);
  assert(footerMatch, 'missing footer.site-footer');
  assert(footerMatch[1].includes('id="btn-footer-feedback"'), '#btn-footer-feedback must exist in footer');

  // 3. Feedback dialog modal structure
  assert(html.includes('id="feedback-dialog"'), '#feedback-dialog must exist');
  assert(html.includes('id="feedback-form"'), '#feedback-form must exist');
  assert(html.includes('id="fb-type-conn-wrap"'), '#fb-type-conn-wrap must exist');
  assert(html.includes('id="fb-type-client-wrap"'), '#fb-type-client-wrap must exist');
  assert(html.includes('id="fb-type-suggest-wrap"'), '#fb-type-suggest-wrap must exist');
  assert(html.includes('id="fb-type-bug-wrap"'), '#fb-type-bug-wrap must exist');
  assert(html.includes('id="feedback-message"'), '#feedback-message textarea must exist');
  assert(html.includes('id="feedback-contact"'), '#feedback-contact input must exist');
  assert(html.includes('id="feedback-attach-diag"'), '#feedback-attach-diag checkbox must exist');
  assert(html.includes('id="btn-copy-feedback"'), '#btn-copy-feedback must exist');
  assert(html.includes('id="btn-submit-feedback"'), '#btn-submit-feedback must exist');
  assert(html.includes('id="feedback-success-card"'), '#feedback-success-card must exist');
});

test('feedback logic: functions exported and i18n keys present', () => {
  assert(html.includes('window.openFeedbackDialog = openFeedbackDialog;'), 'openFeedbackDialog must be exported to window');
  assert(html.includes('window.selectFeedbackType = selectFeedbackType;'), 'selectFeedbackType must be exported to window');
  assert(html.includes('window.updateFeedbackCharCount = updateFeedbackCharCount;'), 'updateFeedbackCharCount must be exported to window');
  assert(html.includes('window.ownlineSubmitFeedback = ownlineSubmitFeedback;'), 'ownlineSubmitFeedback must be exported to window');
  assert(html.includes('window.ownlineCopyFeedbackAndDiag = ownlineCopyFeedbackAndDiag;'), 'ownlineCopyFeedbackAndDiag must be exported to window');

  // Bilingual i18n
  assert(html.includes('footer_feedback: "Feedback"'), 'i18n.en footer_feedback must exist');
  assert(html.includes('footer_feedback: "快捷反馈"'), 'i18n.zh footer_feedback must exist');
  assert(html.includes('feedback_dialog_title: "Quick Feedback"'), 'i18n.en feedback_dialog_title must exist');
  assert(html.includes('feedback_dialog_title: "快捷反馈与建议"'), 'i18n.zh feedback_dialog_title must exist');
});
