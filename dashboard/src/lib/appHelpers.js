// Pure formatting/derivation helpers shared by App.jsx's dashboard and
// reports views - no React, no fetch, so these are unit-testable directly.

export const SENTIMENT_COLORS = {
  positive: '#16a34a',
  negative: '#e11d48',
  neutral: '#64748b',
  mixed: '#f59e0b',
};

export function dominantSentimentFromStats(stats) {
  const total = Number(stats?.total) || 0;
  if (!total) {
    return { label: 'No data yet', color: 'var(--text-light)', pct: 0 };
  }
  const entries = [
    { label: 'Positive', key: 'positive', value: Number(stats.positive) || 0 },
    { label: 'Negative', key: 'negative', value: Number(stats.negative) || 0 },
    { label: 'Neutral', key: 'neutral', value: Number(stats.neutral) || 0 },
    { label: 'Mixed', key: 'mixed', value: Number(stats.mixed) || 0 },
  ].sort((a, b) => b.value - a.value);
  const top = entries[0];
  const pct = Math.round((top.value / total) * 100);
  return { label: `${top.label} - ${pct}%`, color: SENTIMENT_COLORS[top.key] };
}

export const REPORT_PERIODS = [
  { key: '7d', label: 'Last 7 days', days: 7 },
  { key: '30d', label: 'Last 30 days', days: 30 },
  { key: 'all', label: 'All time', days: null },
];

// Non-overlapping, back-to-back windows: offsetWindows=0 is "now minus N
// days through now", offsetWindows=1 is the equal-length window right
// before that - what "compare to previous period" diffs against.
export function timeAgo(dateString) {
  if (!dateString) return null;
  const diffMs = Date.now() - new Date(dateString).getTime();
  if (!Number.isFinite(diffMs)) return null;
  if (diffMs < 60000) return 'just now';
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatRunLabel(run) {
  const value = run?.finished_at || run?.created_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return 'Run';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

// sequence_number is this project's Nth analysis run ever (oldest = 1),
// computed server-side so it stays fixed regardless of how many runs are in
// the currently-fetched list or what order they're shown in. `index` is only
// a fallback for the rare case a run has no sequence_number (e.g. a
// competitor-analysis pipeline row).
export function pipelineRunNumber(run, index) {
  return run?.sequence_number ?? (index + 1);
}

// Full label (with date/time) for the tab list, where several runs are
// shown side by side and the date disambiguates them at a glance.
export function pipelineRunTitle(run, index) {
  return `Pipeline #${pipelineRunNumber(run, index)}: ${formatRunLabel(run)}`;
}
