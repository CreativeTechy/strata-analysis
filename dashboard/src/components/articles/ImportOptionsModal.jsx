import { useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FolderInput, X } from 'lucide-react';
import Dialog from '../Dialog.jsx';

// Lets the user pick between a file picker and a folder picker for import.
// Every supported format goes through the project-documents pipeline (see
// ArticlesPage's importDocumentFiles), which is project-scoped, so nothing
// can be imported until a specific project is chosen above.
export default function ImportOptionsModal({ open, hasProject, disabled, onClose, onChooseFiles, onChooseFolder }) {
  const { t } = useTranslation(['articles', 'common']);
  const titleId = useId();
  const messageId = useId();
  const firstOptionRef = useRef(null);
  if (!open) return null;

  return (
    <Dialog titleId={titleId} descriptionId={messageId} onClose={onClose} initialFocusRef={firstOptionRef}>
      <div className="confirm-modal-header">
        <div>
          <h2 id={titleId} className="confirm-modal-title">
            {t('importModal.title')}
          </h2>
        </div>
        <button type="button" className="confirm-modal-close" onClick={onClose} aria-label={t('common:a11y.closeDialog')}>
          <X size={18} />
        </button>
      </div>

      <p id={messageId} className="confirm-modal-message">
        {hasProject
          ? t('importModal.messageWithProject')
          : t('importModal.messageNoProject')}
      </p>

      <div className="import-options-list">
        <button ref={firstOptionRef} type="button" className="import-option-card" onClick={onChooseFiles} disabled={disabled || !hasProject}>
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
    </Dialog>
  );
}
