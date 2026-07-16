const VALID_TONES = new Set([
  'neutral',
  'positive',
  'enthusiastic',
  'optimistic',
  'critical',
  'skeptical',
  'negative',
  'concerned',
  'angry',
  'sarcastic',
  'humorous',
  'formal',
  'informal',
]);

function normalizeTone(value) {
  const tone = String(value || '').trim().toLowerCase();
  return VALID_TONES.has(tone) ? tone : 'neutral';
}

// Deterministic overall_tone for a single article, derived only from
// writer_tone and article_tone. Never guessed by the AI.
export function computeOverallTone(articleTone, writerTone) {
  const article = normalizeTone(articleTone);
  const writer = normalizeTone(writerTone);
  if (article === writer) return article;
  if (article === 'neutral' && writer !== 'neutral') return writer;
  if (writer === 'neutral' && article !== 'neutral') return article;
  return 'mixed';
}
