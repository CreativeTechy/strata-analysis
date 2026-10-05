import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import Dialog from './Dialog.jsx';

export default function ConfirmModal({ open = false, ...props }) {
  if (!open) return null;
  // Mounted only while open, so every opening starts with no pending
  // confirmation left over from the last one.
  return <ConfirmModalDialog {...props} />;
}

// While a confirmation returned by `onConfirm` is pending, the dialog is busy:
// confirm, cancel and close are disabled and Escape/backdrop are ignored, so
// the same action can't be submitted twice. `busy` lets a caller extend that
// to work it tracks itself.
function ConfirmModalDialog({
  title,
  message,
  confirmLabel,
  cancelLabel,
  confirmButtonStyle,
  busy = false,
  onConfirm,
  onClose,
  hideCancel = false,
  children,
}) {
  const { t } = useTranslation('common');
  const titleId = useId();
  const messageId = useId();
  const cancelRef = useRef(null);
  const confirmRef = useRef(null);
  const pendingRef = useRef(false);
  const [pending, setPending] = useState(false);
  const isBusy = busy || pending;

  const resolvedConfirmLabel = confirmLabel ?? t('actions.confirm');
  const resolvedCancelLabel = cancelLabel ?? t('actions.cancel');

  const close = () => {
    if (!isBusy) onClose?.();
  };

  const confirm = async () => {
    if (isBusy || pendingRef.current) return;
    pendingRef.current = true;
    try {
      const result = (onConfirm || onClose)?.();
      if (result && typeof result.then === 'function') {
        setPending(true);
        await result;
      }
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  return (
    <Dialog
      titleId={titleId}
      descriptionId={message ? messageId : undefined}
      onClose={onClose}
      busy={isBusy}
      initialFocusRef={hideCancel ? confirmRef : cancelRef}
    >
      <div className="confirm-modal-header">
        <div>
          <h2 id={titleId} className="confirm-modal-title">
            {title}
          </h2>
        </div>
        <button
          type="button"
          className="confirm-modal-close"
          onClick={close}
          disabled={isBusy}
          aria-label={t('a11y.closeDialog')}
        >
          <X size={18} />
        </button>
      </div>

      {message && (
        <p id={messageId} className="confirm-modal-message">
          {message}
        </p>
      )}

      {children}

      <div className="confirm-modal-actions">
        {!hideCancel && (
          <button ref={cancelRef} type="button" className="btn-secondary" onClick={close} disabled={isBusy}>
            {resolvedCancelLabel}
          </button>
        )}
        <button
          ref={confirmRef}
          type="button"
          className="btn-primary"
          onClick={confirm}
          style={confirmButtonStyle}
          disabled={isBusy}
        >
          {resolvedConfirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
