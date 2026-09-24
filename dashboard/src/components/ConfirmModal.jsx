import React from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

export default function ConfirmModal({
  open = false,
  title,
  message,
  confirmLabel,
  cancelLabel,
  confirmButtonStyle,
  onConfirm,
  onClose,
  hideCancel = false,
  children,
}) {
  const { t } = useTranslation('common');

  if (!open) return null;

  const resolvedConfirmLabel = confirmLabel ?? t('actions.confirm');
  const resolvedCancelLabel = cancelLabel ?? t('actions.cancel');

  return (
    <div className="confirm-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="confirm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        aria-describedby="confirm-modal-message"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="confirm-modal-header">
          <div>
            <h2 id="confirm-modal-title" className="confirm-modal-title">
              {title}
            </h2>
          </div>
          <button type="button" className="confirm-modal-close" onClick={onClose} aria-label={t('a11y.closeDialog')}>
            <X size={18} />
          </button>
        </div>

        {message && (
          <p id="confirm-modal-message" className="confirm-modal-message">
            {message}
          </p>
        )}

        {children}

        <div className="confirm-modal-actions">
          {!hideCancel && (
            <button type="button" className="btn-secondary" onClick={onClose}>
              {resolvedCancelLabel}
            </button>
          )}
          <button type="button" className="btn-primary" onClick={onConfirm || onClose} style={confirmButtonStyle}>
            {resolvedConfirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
