import { AlertTriangle, Info, X } from 'lucide-react';

/** Live view of one import job: how far through the file it is, how fast it is
 *  going, and what it could not read. `run` is whatever the last poll returned,
 *  so this renders the same whether the job is queued, running or finished. */
export default function ImportProgressBanner({ run, onDismiss }) {
  const done = run.status === 'success' || run.status === 'failed';
  const total = run.total_lines || 0;
  const processed = run.processed || 0;
  const percent = total ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const rate = run.rate_per_second || 0;
  const logs = run.logs || [];

  return (
    <div className={`glass-card articles-import-banner ${run.status === 'failed' ? 'is-failed' : ''}`}>
      {run.status === 'failed' ? <AlertTriangle size={18} /> : <Info size={18} />}
      <div className="articles-import-banner-body">
        {run._batchLabel ? <p className="articles-import-batch-label">{run._batchLabel}</p> : null}
        <div className="articles-import-headline">
          <strong>{run.message || 'Importing...'}</strong>
          {!done && rate > 0 ? <span className="articles-import-rate">{Math.round(rate).toLocaleString()} articles/s</span> : null}
        </div>

        {!done ? (
          <div
            className="articles-import-progress"
            role="progressbar"
            aria-valuenow={total ? percent : undefined}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Import progress"
          >
            {/* Without a line count there is no honest percentage, so show an
                indeterminate bar rather than a made-up one. */}
            <div
              className={`articles-import-progress-fill ${total ? '' : 'is-indeterminate'}`}
              style={total ? { width: `${percent}%` } : undefined}
            />
          </div>
        ) : null}

        <div className="articles-import-counts">
          <span>{(run.saved || 0).toLocaleString()} saved</span>
          {total ? <span>of ~{total.toLocaleString()} lines</span> : null}
          {run.skipped ? <span>{run.skipped.toLocaleString()} skipped</span> : null}
          {done && run.elapsed_seconds ? <span>in {run.elapsed_seconds}s</span> : null}
        </div>

        {done && run.status === 'success' ? (
          <p className="articles-import-note">Articles matching an existing URL were updated in place.</p>
        ) : null}

        {run.errors?.length ? (
          <ul className="articles-import-errors">
            {run.errors.slice(0, 5).map((item) => (
              <li key={item.line}>
                Line {item.line}: {item.error}
              </li>
            ))}
            {run.errors.length > 5 ? <li>and {run.errors.length - 5} more...</li> : null}
          </ul>
        ) : null}

        {!done && logs.length ? <p className="articles-import-log">{logs[logs.length - 1].message}</p> : null}
      </div>
      {done ? (
        <button type="button" className="articles-import-banner-close" onClick={onDismiss} aria-label="Dismiss import summary">
          <X size={16} />
        </button>
      ) : null}
    </div>
  );
}
