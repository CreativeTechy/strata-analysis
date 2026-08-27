import { Info, X } from 'lucide-react';

/** Live status for a document import (PDF/DOC/XLS/CSV/image/JSON) going
 *  through the project-documents pipeline: upload -> extract -> LLM-split ->
 *  auto-approve. That pipeline has no single progress counter the way a JSONL
 *  import's line count does, so this just shows the current stage's message. */
export default function DocumentImportBanner({ status, onDismiss }) {
  return (
    <div className="glass-card articles-import-banner">
      <Info size={18} />
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
