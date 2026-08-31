import { Upload, FolderInput, X } from 'lucide-react';

// Lets the user pick between a file picker and a folder picker for import,
// with the accepted formats spelled out - which formats are accepted depends
// on whether a project is in scope (see ArticlesPage's importDocumentFiles).
export default function ImportOptionsModal({ open, hasProject, disabled, onClose, onChooseFiles, onChooseFolder }) {
  if (!open) return null;

  return (
    <div className="confirm-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="confirm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="confirm-modal-header">
          <div>
            <h2 id="import-modal-title" className="confirm-modal-title">
              Import articles
            </h2>
          </div>
          <button type="button" className="confirm-modal-close" onClick={onClose} aria-label="Close dialog">
            <X size={18} />
          </button>
        </div>

        <p className="confirm-modal-message">
          {hasProject
            ? 'JSONL exports (.jsonl, .ndjson) import unlinked or into this project. PDF, Word, Excel, CSV, image, and JSON documents are extracted, split into articles, and added to the project currently in scope.'
            : 'JSONL exports (.jsonl, .ndjson) can be imported without a project. Select a project scope above to also import PDF, Word, Excel, CSV, image, or JSON documents.'}
        </p>

        <div className="import-options-list">
          <button type="button" className="import-option-card" onClick={onChooseFiles} disabled={disabled}>
            <span className="import-option-icon">
              <Upload size={20} />
            </span>
            <span className="import-option-copy">
              <strong>Upload file(s)</strong>
              <span>Pick one or more files from your computer.</span>
            </span>
          </button>
          <button type="button" className="import-option-card" onClick={onChooseFolder} disabled={disabled}>
            <span className="import-option-icon">
              <FolderInput size={20} />
            </span>
            <span className="import-option-copy">
              <strong>Upload a folder</strong>
              <span>Import every supported file found inside a folder.</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
