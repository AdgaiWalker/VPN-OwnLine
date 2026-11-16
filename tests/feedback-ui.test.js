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

  // 3. Apple HIG Feedback dialog modal structure
  assert(html.includes('id="feedback-dialog"'), '#feedback-dialog must exist');
  assert(html.includes('id="feedback-form"'), '#feedback-form must exist');
  assert(html.includes('id="seg-btn-bug"'), '#seg-btn-bug must exist');
  assert(html.includes('id="seg-btn-idea"'), '#seg-btn-idea must exist');
  assert(html.includes('id="feedback-message"'), '#feedback-message textarea must exist');
  assert(html.includes('id="feedback-contact"'), '#feedback-contact input must exist');
  assert(html.includes('id="feedback-diag-glance"'), '#feedback-diag-glance must exist');
  assert(html.includes('id="btn-copy-feedback"'), '#btn-copy-feedback must exist');
  assert(html.includes('id="feedback-quick-tags"'), '#feedback-quick-tags must exist');
  assert(html.includes('id="btn-submit-feedback"'), '#btn-submit-feedback must exist');
  assert(html.includes('id="btn-email-feedback"'), '#btn-email-feedback must exist');
  assert(html.includes('praxiswalker@gmail.com'), 'praxiswalker@gmail.com must be present');
  assert(html.includes('id="feedback-success-card"'), '#feedback-success-card must exist');
});

test('feedback logic: functions exported and i18n keys present', () => {
  assert(html.includes('window.openFeedbackDialog = openFeedbackDialog;'), 'openFeedbackDialog must be exported to window');
  assert(html.includes('window.insertFeedbackTag = insertFeedbackTag;'), 'insertFeedbackTag must be exported to window');
  assert(html.includes('window.selectFeedbackIntent = selectFeedbackIntent;'), 'selectFeedbackIntent must be exported to window');
  assert(html.includes('window.toggleFeedbackDiagDetails = toggleFeedbackDiagDetails;'), 'toggleFeedbackDiagDetails must be exported to window');
  assert(html.includes('window.updateFeedbackCharCount = updateFeedbackCharCount;'), 'updateFeedbackCharCount must be exported to window');
  assert(html.includes('window.ownlineSubmitFeedback = ownlineSubmitFeedback;'), 'ownlineSubmitFeedback must be exported to window');
  assert(html.includes('window.ownlineCopyFeedbackAndDiag = ownlineCopyFeedbackAndDiag;'), 'ownlineCopyFeedbackAndDiag must be exported to window');
  assert(html.includes('window.openMailToAuthor = openMailToAuthor;'), 'openMailToAuthor must be exported to window');
  assert(html.includes('window.openGitHubIssue = openGitHubIssue;'), 'openGitHubIssue must be exported to window');

  // Bilingual i18n
  assert(html.includes('footer_feedback: "Feedback"'), 'i18n.en footer_feedback must exist');
  assert(html.includes('footer_feedback: "快捷反馈"'), 'i18n.zh footer_feedback must exist');
  assert(html.includes('feedback_dialog_title: "Feedback & Ideas"'), 'i18n.en feedback_dialog_title must exist');
  assert(html.includes('feedback_dialog_title: "反馈与建议"'), 'i18n.zh feedback_dialog_title must exist');
  assert(html.includes('feedback_intent_bug: "Report Issue"'), 'i18n.en feedback_intent_bug must exist');
  assert(html.includes('feedback_intent_bug: "遇到问题"'), 'i18n.zh feedback_intent_bug must exist');
  assert(html.includes('feedback_intent_idea: "New Idea"'), 'i18n.en feedback_intent_idea must exist');
  assert(html.includes('feedback_intent_idea: "想要新功能"'), 'i18n.zh feedback_intent_idea must exist');
  assert(html.includes('feedback_success_title: "Thank You for Dogfooding"'), 'i18n.en feedback_success_title must exist');
  assert(html.includes('feedback_success_title: "感谢你帮大家踩坑"'), 'i18n.zh feedback_success_title must exist');
});
