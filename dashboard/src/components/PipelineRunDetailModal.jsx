import { useEffect, useState } from 'react';
import { X, Loader2, AlertTriangle } from 'lucide-react';

function prettyStage(stage) {
  if (!stage) return 'queued';
  if (stage === 'done') return 'completed';
  return stage;
}

function stageColor(status) {
  if (status === 'success') return '#2ed573';
  if (status === 'failed') return '#ff4757';
  if (status === 'running') return '#ffb13b';
  if (status === 'cancelled') return '#9aa0aa';
  return '#9aa0aa';
}

function formatDateTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString();
}

function formatDuration(ms) {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}

// Returns { text, inProgress } describing the span between two timestamps.
// Still in progress (endIso missing but startIso present) counts elapsed time against now.
function stageDuration(startIso, endIso) {
  if (!startIso) return { text: '—', inProgress: false };
  const start = new Date(startIso).getTime();
  if (!Number.isFinite(start)) return { text: '—', inProgress: false };
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const text = formatDuration(end - start);
  return { text: text || '—', inProgress: !endIso };
}

const STAGE_ROWS = [
  { key: 'scrape', label: 'Scraping', startField: 'scrape_started_at', endField: 'scrape_finished_at' },
  { key: 'clean', label: 'Cleaning', startField: 'clean_started_at', endField: 'clean_finished_at' },
  { key: 'enrich', label: 'Enriching', startField: 'enrich_started_at', endField: 'enrich_finished_at' },
];

const SOURCE_COLUMNS = [
  { key: 'scraped', label: 'Scraped' },
  { key: 'duplicate', label: 'Duplicate' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'date_filtered', label: 'Date filtered' },
  { key: 'kept', label: 'Kept' },
  { key: 'enriched', label: 'Enriched' },
  { key: 'saved', label: 'Saved' },
];

function SummaryField({ label, children }) {
  return (
    <div>
      <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-light)', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: '0.9rem', color: 'var(--text-dark)', wordBreak: 'break-word' }}>{children}</div>
    </div>
  );
}

export default function PipelineRunDetailModal({ open, runId, projectName, onClose }) {
  const [run, setRun] = useState(null);
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !runId) return;

    let cancelled = false;
    setLoading(true);
    setError('');
    setRun(null);
    setSources([]);

    fetch(`/api/pipeline-runs/${runId}`)
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail || data?.error || `Failed to load run (${res.status})`);
        if (cancelled) return;
        setRun(data?.run || null);
        setSources(Array.isArray(data?.sources) ? data.sources : []);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Failed to load run details.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, runId]);

  if (!open) return null;

  const total = run ? stageDuration(run.started_at, run.finished_at) : null;

  return (
    <div className="confirm-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="confirm-modal run-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="run-detail-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="confirm-modal-header">
          <div>
            <h2 id="run-detail-modal-title" className="confirm-modal-title">
              Pipeline run details
            </h2>
            {projectName ? (
              <p style={{ margin: '4px 0 0', color: 'var(--text-light)', fontSize: '0.85rem' }}>{projectName}</p>
            ) : null}
          </div>
          <button type="button" className="confirm-modal-close" onClick={onClose} aria-label="Close dialog">
            <X size={18} />
          </button>
        </div>

        <div className="run-detail-body">
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', padding: '24px 0' }}>
              <Loader2 size={18} className="spin" /> Loading run details...
            </div>
          ) : error ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#b42318', padding: '12px 0' }}>
              <AlertTriangle size={18} /> {error}
            </div>
          ) : !run ? null : (
            <>
              <div className="run-detail-summary-grid">
                <SummaryField label="Run ID">
                  <code style={{ fontSize: '0.8rem' }}>{run.id}</code>
                </SummaryField>
                <SummaryField label="Project">{projectName || run.project_name || (run.project_id != null ? `Project #${run.project_id}` : 'Unassigned')}</SummaryField>
                <SummaryField label="Status">
                  <span style={{ color: stageColor(run.status), fontWeight: 700, textTransform: 'uppercase', fontSize: '0.8rem' }}>
                    {run.status}
                  </span>
                </SummaryField>
                <SummaryField label="Current stage">{prettyStage(run.stage)}</SummaryField>
                <SummaryField label="Started at">{formatDateTime(run.started_at)}</SummaryField>
                <SummaryField label="Finished at">{formatDateTime(run.finished_at)}</SummaryField>
                <SummaryField label="Total duration">
                  {total.text}
                  {total.inProgress ? ' (in progress)' : ''}
                </SummaryField>
                <SummaryField label="Message">{run.message || '—'}</SummaryField>
                {run.error ? <SummaryField label="Error">{run.error}</SummaryField> : null}
              </div>

              <div className="run-detail-section">
                <h3 className="run-detail-section-title">Per-stage timings</h3>
                {!run.has_detail ? (
                  <div className="run-detail-fallback">
                    Details unavailable for legacy run — this run finished before per-stage timing was tracked.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {STAGE_ROWS.map(({ key, label, startField, endField }) => {
                      const duration = stageDuration(run[startField], run[endField]);
                      return (
                        <div
                          key={key}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '8px 12px',
                            borderRadius: 10,
                            background: 'rgba(0,0,0,0.03)',
                          }}
                        >
                          <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{label}</span>
                          <span style={{ fontSize: '0.85rem', color: 'var(--text-light)' }}>
                            {duration.text}
                            {duration.inProgress ? ' (in progress)' : ''}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="run-detail-section">
                <h3 className="run-detail-section-title">Per-source breakdown</h3>
                {!run.has_detail ? (
                  <div className="run-detail-fallback">
                    Details unavailable for legacy run — this run finished before per-source stats were tracked.
                  </div>
                ) : sources.length === 0 ? (
                  <div className="run-detail-fallback">
                    No per-source data recorded for this run yet.
                  </div>
                ) : (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                      <thead>
                        <tr style={{ textAlign: 'left', background: 'rgba(0,0,0,0.03)' }}>
                          <th style={{ padding: '8px 10px' }}>Source</th>
                          {SOURCE_COLUMNS.map((col) => (
                            <th key={col.key} style={{ padding: '8px 10px', textAlign: 'right' }}>
                              {col.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sources.map((row) => (
                          <tr key={row.source} style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                            <td style={{ padding: '8px 10px', wordBreak: 'break-word', maxWidth: 220 }}>{row.source}</td>
                            {SOURCE_COLUMNS.map((col) => (
                              <td key={col.key} style={{ padding: '8px 10px', textAlign: 'right' }}>
                                {row[col.key] ?? 0}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="confirm-modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
