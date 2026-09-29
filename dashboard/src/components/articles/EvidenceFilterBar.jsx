import { useTranslation } from 'react-i18next';
import { Link2, X } from 'lucide-react';
import { EVIDENCE_DIMENSIONS } from '../../lib/evidenceLinks.js';
import { formatDate, formatLanguageName } from '../../lib/i18nFormat.js';

const PERIOD_LABEL_KEYS = { '7d': 'dashboard:periods.last7d', '30d': 'dashboard:periods.last30d', all: 'dashboard:periods.allTime' };

// Region/gender/age_range/segment buckets are open-ended analysis text - the
// same plain transform the dashboard's distribution legends use, so the chip
// reads exactly like the slice that was clicked.
function bucketLabel(t, value) {
  if (value === 'unknown') return t('dashboard:distributions.bucket.unknown');
  return String(value).replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function dimensionValueLabel(t, locale, key, value) {
  switch (key) {
    case 'language': {
      if (value === 'unknown') return t('dashboard:distributions.language.unknown');
      const name = formatLanguageName(value, locale);
      return name ? `${name} (${value.toUpperCase()})` : value.toUpperCase();
    }
    case 'trust': return t(`sources:trustTier.${value}`, value);
    case 'emotion': return t(`dashboard:emotionAxis.${value}`, value);
    case 'date': return formatDate(value, locale, { month: 'short', day: 'numeric', year: 'numeric' }) || value;
    case 'platform': return value;
    default: return bucketLabel(t, value);
  }
}

function Chip({ label, value, onRemove, removeLabel }) {
  return (
    <span className="panel-chip articles-evidence-chip">
      <span className="articles-evidence-chip-label">{label}</span>
      <strong dir="auto">{value}</strong>
      <button type="button" onClick={onRemove} aria-label={removeLabel} title={removeLabel}>
        <X size={12} />
      </button>
    </span>
  );
}

/**
 * What a dashboard/report evidence link narrowed the list to - its scope
 * (period or analysis run) and the chart bucket it was opened from - as
 * removable chips, so a reader can see why the list is what it is and widen
 * it one step at a time. Renders nothing when no evidence param is active.
 */
export default function EvidenceFilterBar({ evidence, sentiment, run, onRemove, onRemoveSentiment, onClear }) {
  const { t, i18n } = useTranslation(['articles', 'dashboard', 'sources']);
  const locale = i18n.language;
  const dimensions = EVIDENCE_DIMENSIONS.filter((key) => evidence[key]);
  const hasScope = Boolean(evidence.run_id || evidence.period);
  if (!hasScope && !dimensions.length) return null;

  const runLabel = run?.sequence_number != null
    ? t('dashboard:runLabel.short', { number: run.sequence_number })
    : t('evidence.runFallback');

  return (
    <div className="glass-card articles-evidence-bar" role="region" aria-label={t('evidence.ariaLabel')}>
      <span className="articles-evidence-title"><Link2 size={14} /> {t('evidence.title')}</span>
      <div className="articles-evidence-chips">
        {evidence.run_id ? (
          <Chip label={t('evidence.scope')} value={runLabel} onRemove={() => onRemove('run_id')} removeLabel={t('evidence.remove', { label: runLabel })} />
        ) : null}
        {evidence.period ? (
          <Chip label={t('evidence.scope')} value={t(PERIOD_LABEL_KEYS[evidence.period])} onRemove={() => onRemove('period')} removeLabel={t('evidence.remove', { label: t(PERIOD_LABEL_KEYS[evidence.period]) })} />
        ) : null}
        {sentiment && sentiment !== 'all' ? (
          <Chip label={t('evidence.dimensions.sentiment')} value={t(`sentiment.${sentiment}`, sentiment)} onRemove={onRemoveSentiment} removeLabel={t('evidence.remove', { label: t(`sentiment.${sentiment}`, sentiment) })} />
        ) : null}
        {dimensions.map((key) => {
          const value = dimensionValueLabel(t, locale, key, evidence[key]);
          return <Chip key={key} label={t(`evidence.dimensions.${key}`)} value={value} onRemove={() => onRemove(key)} removeLabel={t('evidence.remove', { label: value })} />;
        })}
      </div>
      <button type="button" className="articles-evidence-clear" onClick={onClear}>{t('evidence.clear')}</button>
      {evidence.run_id ? <p className="articles-evidence-note">{t('evidence.runNote', { run: runLabel })}</p> : null}
    </div>
  );
}
