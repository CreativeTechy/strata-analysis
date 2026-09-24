import { useTranslation } from 'react-i18next';
import '../styles/DemographicSentimentChart.css';
import { formatNumber, formatPercent } from '../lib/i18nFormat.js';

// cohort_dimension/cohort_value are open-ended survey metadata straight off
// the DB, so this stays a plain transform rather than a translation lookup -
// same rationale as DashboardOverview.jsx's distributionLabel(). `fallback`
// is the one translatable piece (the default shown when a study has no
// per-cohort breakdown at all).
function label(value, fallback) {
  return String(value || fallback).replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function SurveyObservationsChart({ observations = [] }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  if (!observations.length) return null;
  const study = observations[0];
  const allAdultsLabel = t('dashboard:survey.allAdults');
  return (
    <div className="survey-observations">
      <div className="survey-observations-header">
        <div><strong>{t('dashboard:survey.publishedResults')}</strong><span dir="auto">{study.question}</span></div>
        <span dir="auto">{study.population || t('dashboard:survey.populationFallback')}{study.sample_size ? ` · n=${formatNumber(study.sample_size, locale)}` : ''}</span>
      </div>
      <div className="survey-observation-grid">
        {observations.map((item) => (
          <div className="survey-observation" key={`${item.study_key}-${item.cohort_dimension}-${item.cohort_value}-${item.answer}`}>
            <span>{label(item.cohort_dimension, allAdultsLabel)} · {label(item.cohort_value, allAdultsLabel)}</span>
            <strong>{formatPercent(Number(item.percentage), locale, { alreadyWhole: true })}</strong>
            <div className="survey-bar"><i style={{ width: `${Number(item.percentage)}%` }} /></div>
            <small dir="auto">{item.answer}</small>
          </div>
        ))}
      </div>
      <p className="demographic-chart-note">{t('dashboard:survey.note')}</p>
    </div>
  );
}
