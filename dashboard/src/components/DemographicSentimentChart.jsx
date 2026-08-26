import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import '../styles/DemographicSentimentChart.css';

// Same status palette and fixed series order as StatsOverview.jsx's sentiment
// donut, reused here so a "positive" segment reads the same color everywhere
// in the app rather than introducing a second palette for the same meaning.
const SENTIMENT_COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
const SENTIMENT_KEYS = ['positive', 'neutral', 'negative', 'mixed'];

function labelize(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const bucket = payload[0]?.payload;
  return (
    <div className="demographic-chart-tooltip">
      <strong>{labelize(label)}</strong>
      <span>{bucket?.total || 0} article{bucket?.total === 1 ? '' : 's'}</span>
      <ul>
        {SENTIMENT_KEYS.map((key) => (
          <li key={key}>
            <i style={{ background: SENTIMENT_COLORS[key] }} />
            {labelize(key)}
            <b>{Math.round(bucket?.[key] || 0)}%</b>
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

  if (rows.length < 2) {
    return (
      <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
        <strong>Not enough signal yet</strong>
        <span>{title} needs at least two distinct values across analyzed articles before a comparison chart is meaningful.</span>
      </div>
    );
  }

  const chartHeight = Math.max(140, rows.length * 44);

  return (
    <div className="demographic-chart">
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tickFormatter={(value) => `${value}%`} />
          <YAxis type="category" dataKey="value" width={110} tickFormatter={labelize} />
          <Tooltip content={<ChartTooltip />} />
          <Legend formatter={labelize} />
          {SENTIMENT_KEYS.map((key) => (
            <Bar key={key} dataKey={key} name={key} stackId="sentiment" fill={SENTIMENT_COLORS[key]} stroke="#fff" strokeWidth={2} />
          ))}
        </BarChart>
      </ResponsiveContainer>
      {droppedCount > 0 && (
        <p className="demographic-chart-note">+{droppedCount} more value{droppedCount === 1 ? '' : 's'} not shown</p>
      )}
    </div>
  );
}
