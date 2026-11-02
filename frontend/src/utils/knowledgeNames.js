// Display values are resolved by the server from explicit IPN identities.
// Keep saved text available to editors, evidence review and revision history.
export const questionDisplayText = item => item?.display_question_text || item?.display_question || item?.question_text || item?.question || ''
export const answerDisplayText = answer => answer?.display_answer_text || answer?.answer_text || ''
export const featureDisplayName = feature => feature?.display_cn_name || feature?.primary_cn_name || feature?.legacy_name || ''
