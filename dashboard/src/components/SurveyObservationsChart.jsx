import { useTranslation } from 'react-i18next';
import '../styles/DemographicSentimentChart.css';
import { formatNumber, formatPercent } from '../lib/i18nFormat.js';
import { useTranslatedLabels } from '../i18n/useTranslatedLabels.js';

// Survey metadata (question, population, cohort, answer) is open-ended text
// straight off the DB, so it is translated server-side (see
// i18n/useTranslatedLabels.js); until that arrives a cohort shows as a plain
// capitalize transform and the rest as written.
function label(value, translated) {
  return translated || String(value).replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

const SURVEY_TEXT_FIELDS = ['question', 'population', 'cohort_dimension', 'cohort_value', 'answer'];

export default function SurveyObservationsChart({ observations = [] }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const translatedFor = useTranslatedLabels(observations.flatMap((item) => SURVEY_TEXT_FIELDS.map((field) => item[field])));
  const text = (value) => (value ? translatedFor(value) || value : value);
  const allAdultsLabel = t('dashboard:survey.allAdults');
  const cohort = (value) => (value ? label(value, translatedFor(value)) : allAdultsLabel);
  if (!observations.length) return null;
  const study = observations[0];
  return (
    <div className="survey-observations">
      <div className="survey-observations-header">
        <div><strong>{t('dashboard:survey.publishedResults')}</strong><span dir="auto">{text(study.question)}</span></div>
        <span dir="auto">{text(study.population) || t('dashboard:survey.populationFallback')}{study.sample_size ? ` · n=${formatNumber(study.sample_size, locale)}` : ''}</span>
      </div>
      <div className="survey-observation-grid">
        {observations.map((item) => (
          <div className="survey-observation" key={`${item.study_key}-${item.cohort_dimension}-${item.cohort_value}-${item.answer}`}>
            <span dir="auto">{cohort(item.cohort_dimension)} · {cohort(item.cohort_value)}</span>
            <strong>{formatPercent(Number(item.percentage), locale, { alreadyWhole: true })}</strong>
            <div className="survey-bar"><i style={{ width: `${Number(item.percentage)}%` }} /></div>
            <small dir="auto">{text(item.answer)}</small>
          </div>
        ))}
      </div>
      <p className="demographic-chart-note">{t('dashboard:survey.note')}</p>
    </div>
  );
}
