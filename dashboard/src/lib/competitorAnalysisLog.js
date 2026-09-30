/**
 * A competitor-analysis run's progress lines (competitor_analysis.py's
 * `log(message, code, params)`) arrive as `{ ts, message, code?, params? }`:
 * `message` is the backend's English line, `code` + `params` are what this
 * turns into text in the UI's language - the same split apiError.js draws
 * for errors. An entry without a code (a run logged before codes existed) or
 * with a code this doesn't know falls back to the English `message`, so an
 * old run's trail never goes blank.
 *
 * `t` must include the `competitors` and `errors` namespaces, e.g.
 * `useTranslation(['competitors', 'errors']).t`.
 */

const humanize = (code) => String(code || '').replace(/_/g, ' ');

/** "3 duplicate stories" - one validation rejection reason with its count. */
export function rejectionReasonText(t, reason, count) {
  return t(`competitors:analysisLog.rejectionReasons.${reason}`, {
    count,
    defaultValue: `${count} ${humanize(reason)}`,
  });
}

/** All of a run's rejection reasons as one list, largest first when the
 *  caller passes them in that order. `reasons` is `[{ reason, count }]`. */
export function rejectionReasonsList(t, reasons) {
  return (reasons || [])
    .map(({ reason, count }) => rejectionReasonText(t, reason, count))
    .join(t('competitors:analysisLog.listSeparator'));
}

/** Why a competitor got no report - `reason_code` from generate_findings'
 *  `skipped` entries, falling back to the English `reason` it also carries. */
export function skipReasonText(t, { reason_code: reasonCode, reason } = {}) {
  if (!reasonCode) return reason || '';
  return t(`competitors:analysisLog.skipReasons.${reasonCode}`, { defaultValue: reason || humanize(reasonCode) });
}

function windowText(t, params) {
  if (params.window === 'documents') return t('competitors:analysisLog.window.documents', { count: params.documents || 0 });
  if (params.window === 'pipeline_run') return t('competitors:analysisLog.window.pipelineRun');
  if (params.window === 'days') return t('competitors:analysisLog.window.days', { count: params.days || 0 });
  return t('competitors:analysisLog.window.allTime');
}

// Params some codes carry as codes themselves (an impact level, an error
// code, a reason) - resolved to display text before the line is interpolated.
const PARAM_RESOLVERS = {
  checking_articles: (t, params) => ({ window: windowText(t, params) }),
  filtered_out: (t, params) => ({ reasons: rejectionReasonsList(t, params.reasons) }),
  finding_generated: (t, params) => ({
    impact: t(`competitors:labels.impact.${params.impact}`, { defaultValue: humanize(params.impact) }),
  }),
  competitor_failed: (t, params) => ({
    error: t(`errors:${params.error_code}`, { defaultValue: t('errors:llm_provider_error') }),
  }),
  competitor_skipped: (t, params) => ({ reason: skipReasonText(t, params) }),
};

export function analysisLogText(t, entry) {
  if (!entry) return '';
  const { code, message = '' } = entry;
  if (!code) return message;
  const params = entry.params || {};
  const resolved = PARAM_RESOLVERS[code]?.(t, params) || {};
  // `done` is the one line whose wording changes with a second count.
  const key = code === 'done' && params.skipped ? 'done_with_skipped' : code;
  return t(`competitors:analysisLog.${key}`, {
    ...params,
    ...resolved,
    count: code === 'done' ? params.generated : params.count,
    defaultValue: message,
  });
}
