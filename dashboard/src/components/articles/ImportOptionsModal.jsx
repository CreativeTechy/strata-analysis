import { useTranslation } from 'react-i18next';
import { Upload, FolderInput, X } from 'lucide-react';

// Lets the user pick between a file picker and a folder picker for import.
// Every supported format goes through the project-documents pipeline (see
// ArticlesPage's importDocumentFiles), which is project-scoped, so nothing
// can be imported until a specific project is chosen above.
export default function ImportOptionsModal({ open, hasProject, disabled, onClose, onChooseFiles, onChooseFolder }) {
  const { t } = useTranslation(['articles', 'common']);
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
              {t('importModal.title')}
            </h2>
          </div>
          <button type="button" className="confirm-modal-close" onClick={onClose} aria-label={t('common:a11y.closeDialog')}>
            <X size={18} />
          </button>
        </div>

        <p className="confirm-modal-message">
          {hasProject
            ? t('importModal.messageWithProject')
            : t('importModal.messageNoProject')}
        </p>

        <div className="import-options-list">
          <button type="button" className="import-option-card" onClick={onChooseFiles} disabled={disabled || !hasProject}>
            <span className="import-option-icon">
              <Upload size={20} />
            </span>
            <span className="import-option-copy">
              <strong>{t('importModal.uploadFiles')}</strong>
              <span>{t('importModal.uploadFilesHint')}</span>
            </span>
          </button>
          <button type="button" className="import-option-card" onClick={onChooseFolder} disabled={disabled || !hasProject}>
            <span className="import-option-icon">
              <FolderInput size={20} />
            </span>
            <span className="import-option-copy">
              <strong>{t('importModal.uploadFolder')}</strong>
              <span>{t('importModal.uploadFolderHint')}</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
