import { useTranslation } from 'react-i18next';
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from 'recharts';
import ResponsiveContainer from './ResponsiveChartContainer.jsx';
import '../styles/DemographicSentimentChart.css';
import { formatPercent } from '../lib/i18nFormat.js';

// Same status palette and fixed series order as StatsOverview.jsx's sentiment
// donut, reused here so a "positive" segment reads the same color everywhere
// in the app rather than introducing a second palette for the same meaning.
const SENTIMENT_COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
const SENTIMENT_KEYS = ['positive', 'neutral', 'negative', 'mixed'];

// region/gender/age_range are open-ended text buckets straight off the DB, so
// this transform (not a translation lookup) is what turns e.g. "north_america"
// into "North America" - left untranslated on purpose, same as
// DashboardOverview.jsx's distributionLabel().
function labelize(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// SENTIMENT_KEYS, unlike the bucket values above, is a fixed 4-value enum -
// translated through a label map (dashboard:sentiment.*) so the object keys
// (used for colors/data lookups) stay the untranslated code.
function sentimentLabel(t, key) {
  return t(`dashboard:sentiment.${key}`, labelize(key));
}

function ChartTooltip({ active, payload, label, t, locale }) {
  if (!active || !payload?.length) return null;
  const bucket = payload[0]?.payload;
  return (
    <div className="demographic-chart-tooltip">
      <strong>{labelize(label)}</strong>
      <span>{t('dashboard:counts.recordsCount', { count: bucket?.total || 0 })}</span>
      <ul>
        {SENTIMENT_KEYS.map((key) => (
          <li key={key}>
            <i style={{ background: SENTIMENT_COLORS[key] }} />
            {sentimentLabel(t, key)}
            <b>{formatPercent(Math.round(bucket?.[key] || 0), locale, { alreadyWhole: true })}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A 100%-stacked horizontal bar per distinct value of one demographic
 * dimension (region / gender / age_range), each bar broken into its
 * positive/neutral/negative/mixed share - the "50% of X are positive" stat
 * as a chart. `data` is the API's *_breakdown shape:
 * [{value, total, positive, negative, neutral, mixed, positive_pct, negative_pct}]
 * already sorted by total desc.
 */
export default function DemographicSentimentChart({ title, data, maxBuckets = 7 }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const nonEmpty = (Array.isArray(data) ? data : []).filter((item) => Number(item?.total) > 0);
  const rows = nonEmpty.slice(0, maxBuckets).map((item) => {
    const total = Number(item.total) || 0;
    const pct = (count) => (total ? (Number(count || 0) / total) * 100 : 0);
    return {
      value: item.value,
      total,
      positive: pct(item.positive),
      neutral: pct(item.neutral),
      negative: pct(item.negative),
      mixed: pct(item.mixed),
    };
  });
  const droppedCount = nonEmpty.length - rows.length;
  const allRecords = nonEmpty.reduce((sum, item) => sum + Number(item.total || 0), 0);
  const unknownRecords = nonEmpty.find((item) => String(item.value).toLowerCase() === 'unknown')?.total || 0;

  if (rows.length < 2) {
    return (
      <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
        <strong>{t('dashboard:demographicChart.notEnoughSignalTitle')}</strong>
        <span dir="auto">{t('dashboard:demographicChart.notEnoughSignalBody', { title })}</span>
      </div>
    );
  }

  const chartHeight = Math.max(140, rows.length * 44);
  const knownRecords = allRecords - unknownRecords;
  const coveragePct = allRecords ? Math.round((knownRecords / allRecords) * 100) : 0;

  return (
    <div className="demographic-chart">
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tickFormatter={(value) => formatPercent(value, locale, { alreadyWhole: true })} />
          <YAxis type="category" dataKey="value" width={110} tickFormatter={labelize} />
          <Tooltip content={<ChartTooltip t={t} locale={locale} />} />
          <Legend formatter={(key) => sentimentLabel(t, key)} />
          {SENTIMENT_KEYS.map((key) => (
            <Bar key={key} dataKey={key} name={key} stackId="sentiment" fill={SENTIMENT_COLORS[key]} stroke="#fff" strokeWidth={2} />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <p className="demographic-chart-note">
        {t('dashboard:demographicChart.coverageNote', {
          pct: formatPercent(coveragePct, locale, { alreadyWhole: true }),
          known: knownRecords,
          total: allRecords,
        })}
      </p>
      {droppedCount > 0 && (
        <p className="demographic-chart-note">{t('dashboard:counts.moreValues', { count: droppedCount })}</p>
      )}
    </div>
  );
}
