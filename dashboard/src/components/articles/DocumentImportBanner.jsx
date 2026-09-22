import { AlertTriangle, Info, X } from 'lucide-react';

/** Live status for a document import (PDF/DOC/XLS/CSV/image/JSON/JSONL/NDJSON)
 *  going through the project-documents pipeline: upload -> extract/parse ->
 *  LLM-split (or, for JSON/JSONL/NDJSON, straight to candidates) -> auto-
 *  approve. That pipeline has no single progress counter, so this just shows
 *  the current stage's message. `status.warning` - set when a document
 *  reported a non-fatal note (e.g. a .jsonl/.ndjson file that exceeded the
 *  per-file record cap and left records behind - see
 *  ArticlesPage's importDocumentFiles) - swaps the icon/border so a partial
 *  import doesn't read identically to a clean one. */
export default function DocumentImportBanner({ status, onDismiss }) {
  return (
    <div className={`glass-card articles-import-banner ${status.warning ? 'is-warning' : ''}`}>
      {status.warning ? <AlertTriangle size={18} /> : <Info size={18} />}
      <div className="articles-import-banner-body">
        <div className="articles-import-headline">
          <strong>{status.message}</strong>
        </div>
      </div>
      {status.done ? (
        <button type="button" className="articles-import-banner-close" onClick={onDismiss} aria-label="Dismiss import summary">
          <X size={16} />
        </button>
      ) : null}
    </div>
  );
}
