import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import '../styles/IntelligenceDashboard.css';

// Same status palette as StatsOverview.jsx's sentiment donut, reused here so
// a "positive" slice reads the same color everywhere in the app.
const COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
const SENTIMENT_KEYS = ['positive', 'neutral', 'negative', 'mixed'];

// Labels the demographic breakdown APIs' bucket values (region/gender/age_range/segment)
// - see backend/services/articles/articles_store.py's _demographic_sentiment_breakdown.
function labelize(value) {
  return String(value || 'unknown')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// These breakdowns are open-ended text buckets, so navigation is capped to
// the top `limit` buckets (already sorted desc by the backend) with the
// long tail folded into one "Other" slice, rather than growing unbounded.
function capBreakdown(entries, limit = 7) {
  if (entries.length <= limit) return entries;
  const rest = entries.slice(limit);
  const other = rest.reduce((acc, entry) => ({
    value: 'other',
    total: acc.total + Number(entry.total || 0),
    positive: acc.positive + Number(entry.positive || 0),
    negative: acc.negative + Number(entry.negative || 0),
    neutral: acc.neutral + Number(entry.neutral || 0),
    mixed: acc.mixed + Number(entry.mixed || 0),
  }), { value: 'other', total: 0, positive: 0, negative: 0, neutral: 0, mixed: 0 });
  return [...entries.slice(0, limit), other];
}

/**
 * One pie chart at a time for a demographic breakdown (region / gender /
 * age_range / segment), each slice being that bucket's positive/neutral/
 * negative/mixed sentiment split - with left/right arrows to step through
 * the buckets instead of showing them all at once.
 */
export default function DemographicPieCarousel({ data, emptyLabel }) {
  const [index, setIndex] = useState(0);
  const buckets = capBreakdown((Array.isArray(data) ? data : []).filter((entry) => Number(entry?.total) > 0));

  if (buckets.length === 0) {
    return <p className="intelligence-empty">{emptyLabel || 'No data detected on analyzed articles yet.'}</p>;
  }

  const safeIndex = Math.min(index, buckets.length - 1);
  const bucket = buckets[safeIndex];
  const slices = SENTIMENT_KEYS.map((key) => ({ key, value: Number(bucket[key] || 0) })).filter((slice) => slice.value > 0);
  const canNavigate = buckets.length > 1;
  const goTo = (nextIndex) => setIndex((nextIndex + buckets.length) % buckets.length);

  return (
    <div className="demographic-pie-carousel">
      <div className="demographic-pie-carousel-nav">
        <button
          type="button"
          className="demographic-pie-carousel-arrow"
          onClick={() => goTo(safeIndex - 1)}
          disabled={!canNavigate}
          aria-label="Previous value"
        >
          <ChevronLeft size={22} />
        </button>
        <span className="demographic-pie-carousel-label">{labelize(bucket.value)}</span>
        <button
          type="button"
          className="demographic-pie-carousel-arrow"
          onClick={() => goTo(safeIndex + 1)}
          disabled={!canNavigate}
          aria-label="Next value"
        >
          <ChevronRight size={22} />
        </button>
      </div>
      <div className="intelligence-donut">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={slices} dataKey="value" nameKey="key" outerRadius="88%" paddingAngle={3} stroke="none">
              {slices.map((slice) => <Cell key={slice.key} fill={COLORS[slice.key]} />)}
            </Pie>
            <Tooltip formatter={(value, name) => [`${value} articles`, labelize(name)]} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <span className="demographic-pie-carousel-count">{bucket.total} article{bucket.total === 1 ? '' : 's'}</span>
      {canNavigate && (
        <div className="demographic-pie-carousel-dots">
          {buckets.map((entry, entryIndex) => (
            <button
              key={entry.value}
              type="button"
              className={`demographic-pie-carousel-dot ${entryIndex === safeIndex ? 'active' : ''}`}
              onClick={() => goTo(entryIndex)}
              aria-label={`Show ${labelize(entry.value)}`}
              aria-current={entryIndex === safeIndex}
            />
          ))}
        </div>
      )}
      <div className="report-gender-sentiment-legend">
        {SENTIMENT_KEYS.map((key) => <span key={key}><i style={{ background: COLORS[key] }} />{key}</span>)}
      </div>
    </div>
  );
}
