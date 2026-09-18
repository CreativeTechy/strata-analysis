import '../styles/DemographicSentimentChart.css';

function label(value) {
  return String(value || 'All adults').replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function SurveyObservationsChart({ observations = [] }) {
  if (!observations.length) return null;
  const study = observations[0];
  return (
    <div className="survey-observations">
      <div className="survey-observations-header">
        <div><strong>Published survey results</strong><span>{study.question}</span></div>
        <span>{study.population || 'Survey population'}{study.sample_size ? ` · n=${study.sample_size.toLocaleString()}` : ''}</span>
      </div>
      <div className="survey-observation-grid">
        {observations.map((item) => (
          <div className="survey-observation" key={`${item.study_key}-${item.cohort_dimension}-${item.cohort_value}-${item.answer}`}>
            <span>{label(item.cohort_dimension)} · {label(item.cohort_value)}</span>
            <strong>{Number(item.percentage).toFixed(0)}%</strong>
            <div className="survey-bar"><i style={{ width: `${Number(item.percentage)}%` }} /></div>
            <small>{item.answer}</small>
          </div>
        ))}
      </div>
      <p className="demographic-chart-note">These percentages are published survey observations. They are separate from sentiment inferred from analyzed records.</p>
    </div>
  );
}
