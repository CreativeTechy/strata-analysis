import { useEffect, useRef } from 'react';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

const focusableWithin = (root) => (root ? [...root.querySelectorAll(FOCUSABLE)] : []);

/**
 * The one modal-dialog lifecycle every dashboard dialog shares (SM-137),
 * lifted from RemoveProjectArticlesDialog (SM-101): on open it focuses
 * `initialFocusRef` (falling back to the first focusable control, then the
 * panel itself), keeps Tab/Shift+Tab inside the panel, closes on Escape or a
 * backdrop click unless `busy`, and on close hands focus back to whatever had
 * it when the dialog opened - provided that element is still on the page.
 *
 * Render it only while the dialog is open: mounting is "open", unmounting is
 * "close", so focus capture and restoration need no extra state.
 *
 * Keys are handled on the document rather than the panel so the trap still
 * holds when focus falls to <body> - which browsers do when the focused
 * button becomes disabled while a confirmation is pending. That assumes one
 * open dialog at a time, which is all the dashboard ever shows.
 *
 * A backdrop click only closes when the press also started on the backdrop,
 * so selecting text in a field and releasing outside the panel doesn't throw
 * away what was typed.
 */
export default function Dialog({
  titleId,
  descriptionId,
  onClose,
  busy = false,
  initialFocusRef,
  className = 'confirm-modal',
  children,
}) {
  const panelRef = useRef(null);
  const latestRef = useRef({ busy, onClose });
  const pressStartedOnBackdropRef = useRef(false);

  useEffect(() => {
    latestRef.current = { busy, onClose };
  });

  useEffect(() => {
    const returnFocusTo = document.activeElement;
    const preferred = initialFocusRef?.current;
    const target = preferred && !preferred.disabled
      ? preferred
      : focusableWithin(panelRef.current)[0] || panelRef.current;
    target?.focus();

    const handleKeyDown = (event) => {
      const panel = panelRef.current;
      if (!panel) return;
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (!latestRef.current.busy) latestRef.current.onClose?.();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = focusableWithin(panel);
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const inside = focusable.includes(active);
      if (event.shiftKey && (!inside || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (returnFocusTo && typeof returnFocusTo.focus === 'function' && document.contains(returnFocusTo)) {
        returnFocusTo.focus();
      }
    };
  }, [initialFocusRef]);

  const handleBackdropMouseDown = (event) => {
    pressStartedOnBackdropRef.current = event.target === event.currentTarget;
  };

  const handleBackdropClick = (event) => {
    const startedOnBackdrop = pressStartedOnBackdropRef.current;
    pressStartedOnBackdropRef.current = false;
    if (event.target !== event.currentTarget || !startedOnBackdrop) return;
    if (!busy) onClose?.();
  };

  return (
    <div
      className="confirm-modal-backdrop"
      role="presentation"
      onMouseDown={handleBackdropMouseDown}
      onClick={handleBackdropClick}
    >
      <div
        ref={panelRef}
        className={className}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={busy || undefined}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  );
}
