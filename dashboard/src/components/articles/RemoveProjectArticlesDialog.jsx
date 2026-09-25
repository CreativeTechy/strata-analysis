import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle, X } from 'lucide-react';
import { getProjectArticleRemovalPreview, removeProjectArticles } from '../../api/articlesApi.js';
import { formatNumber } from '../../lib/i18nFormat.js';

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Confirmation for removing every article from one project (SM-101) - the
 * scoped replacement for the old global "Delete All Articles". Shows what the
 * removal affects (from GET .../articles/removal-preview) before the user
 * commits, and requires typing the project's exact name; the backend checks
 * that same name, so the disabled button isn't the only guard.
 *
 * Callers mount it only while it's open (`{open && <... />}`), so every
 * opening starts from fresh state - no leftover typed name or error.
 *
 * Unlike ConfirmModal this manages its own focus: it opens on Cancel (the
 * safe choice), keeps Tab inside the dialog, closes on Escape unless a
 * removal is in flight, and hands focus back to whatever opened it.
 */
export default function RemoveProjectArticlesDialog({ open, project, onClose, onRemoved }) {
  const { t, i18n } = useTranslation(['articles', 'common']);
  const locale = i18n.language;
  const titleId = useId();
  const descriptionId = useId();
  const inputId = useId();
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const returnFocusRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [previewState, setPreviewState] = useState('loading');
  const [typed, setTyped] = useState('');
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState('');

  const projectId = project?.id;

  useEffect(() => {
    if (!open || projectId == null) return undefined;
    const controller = new AbortController();
    getProjectArticleRemovalPreview(projectId, controller.signal)
      .then((data) => {
        setPreview(data);
        setPreviewState('ready');
      })
      .catch((err) => {
        if (err?.name !== 'AbortError') setPreviewState('failed');
      });
    return () => controller.abort();
  }, [open, projectId]);

  useEffect(() => {
    if (!open) return undefined;
    returnFocusRef.current = document.activeElement;
    cancelRef.current?.focus();
    return () => {
      const target = returnFocusRef.current;
      if (target && typeof target.focus === 'function' && document.contains(target)) target.focus();
    };
  }, [open]);

  if (!open || !project) return null;

  const projectName = String(preview?.project?.name ?? project.name ?? '');
  const nameMatches = typed.trim() !== '' && typed.trim() === projectName.trim();
  const linked = Number(preview?.linked_articles) || 0;
  const activeRun = preview?.active_run || null;
  const canRemove = previewState === 'ready' && linked > 0 && !activeRun && nameMatches && !removing;

  const close = () => {
    if (!removing) onClose?.();
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      close();
      return;
    }
    if (event.key !== 'Tab' || !dialogRef.current) return;
    const focusable = [...dialogRef.current.querySelectorAll(FOCUSABLE)];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const errorMessage = (err) => {
    if (err?.status === 400) return t('removeProject.errors.mismatch');
    if (err?.status === 409) return t('removeProject.errors.activeRun');
    if (err?.status === 404) return t('removeProject.errors.notFound');
    return t('removeProject.errors.failed');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!canRemove) return;
    setRemoving(true);
    setError('');
    try {
      const result = await removeProjectArticles(project.id, typed.trim());
      setRemoving(false);
      onRemoved?.(result, projectName);
    } catch (err) {
      setRemoving(false);
      setError(errorMessage(err));
    }
  };

  return (
    <div className="confirm-modal-backdrop" role="presentation" onClick={close}>
      <div
        ref={dialogRef}
        className="confirm-modal remove-articles-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="confirm-modal-header">
          <h2 id={titleId} className="confirm-modal-title" dir="auto">
            {t('removeProject.title', { name: projectName })}
          </h2>
          <button
            type="button"
            className="confirm-modal-close"
            onClick={close}
            disabled={removing}
            aria-label={t('common:a11y.closeDialog')}
          >
            <X size={18} />
          </button>
        </div>

        <p id={descriptionId} className="confirm-modal-message">{t('removeProject.intro')}</p>

        {previewState === 'loading' ? (
          <p className="remove-articles-status" role="status">{t('removeProject.loading')}</p>
        ) : null}
        {previewState === 'failed' ? (
          <p className="remove-articles-error" role="alert">{t('removeProject.previewFailed')}</p>
        ) : null}

        {previewState === 'ready' ? (
          <>
            <dl className="remove-articles-counts">
              <div>
                <dt>{t('removeProject.countLinked')}</dt>
                <dd>{formatNumber(linked, locale)}</dd>
              </div>
              <div>
                <dt>{t('removeProject.countDeleted')}</dt>
                <dd>{formatNumber(Number(preview?.only_in_project) || 0, locale)}</dd>
              </div>
              <div>
                <dt>{t('removeProject.countKept')}</dt>
                <dd>{formatNumber(Number(preview?.shared_with_other_projects) || 0, locale)}</dd>
              </div>
            </dl>

            {linked === 0 ? (
              <p className="remove-articles-status" role="status">{t('removeProject.empty')}</p>
            ) : null}

            {activeRun ? (
              <div className="remove-articles-error" role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <span>
                  {t('removeProject.activeRun', {
                    analyzed: formatNumber(Number(activeRun.articles_analyzed) || 0, locale),
                    selected: formatNumber(Number(activeRun.articles_selected) || 0, locale),
                  })}{' '}
                  <Link to={activeRun.id ? `/pipeline-runs/${activeRun.id}` : '/pipeline-runs'}>
                    {t('removeProject.activeRunLink')}
                  </Link>
                </span>
              </div>
            ) : null}
          </>
        ) : null}

        <form onSubmit={handleSubmit}>
          {previewState === 'ready' && linked > 0 && !activeRun ? (
            <div className="remove-articles-confirm">
              <label htmlFor={inputId}>{t('removeProject.confirmLabel')}</label>
              <p className="remove-articles-expected" dir="auto">{projectName}</p>
              <input
                id={inputId}
                type="text"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                disabled={removing}
                autoComplete="off"
                spellCheck={false}
                dir="auto"
              />
            </div>
          ) : null}

          {error ? <p className="remove-articles-error" role="alert">{error}</p> : null}

          <div className="confirm-modal-actions">
            <button ref={cancelRef} type="button" className="btn-secondary" onClick={close} disabled={removing}>
              {t('common:actions.cancel')}
            </button>
            <button type="submit" className="btn-danger" disabled={!canRemove}>
              {removing ? t('removeProject.submitting') : t('removeProject.submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
