/**
 * Document management for an existing study — the same upload/extract/review
 * flow the "New competitor study" wizard offers on its (optional) last step,
 * pulled out here so a study that skipped it, or just wants to add more
 * evidence later, has somewhere to do that without starting a new study.
 *
 * `DocumentsPanel` is the reusable piece (studyId in, everything else is its
 * own state) — CompetitorOnboarding.jsx's step 3 uses it too, so upload/poll/
 * review logic lives in exactly one place. `CompetitorDocumentsPage` is the
 * standalone route wrapper for an already-created study.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle, Check, CheckCircle2, ChevronLeft, ChevronRight, FileCheck, ListChecks, Loader2, ScanText, Trash2, Upload, X,
} from 'lucide-react';
import {
  approveAllDocumentArticles, deleteDocument, getStudy, listDocumentArticles, listDocuments,
  pollArticleCandidates, pollDocumentExtraction, setDocumentArticleStatus, uploadDocuments,
} from '../api/competitorApi.js';
import { getPageNumbers } from '../lib/articleHelpers.jsx';
import '../styles/Competitors.css';

const DOCUMENT_ACTIVE_STATUSES = new Set(['uploaded', 'processing']);
const ARTICLES_ACTIVE_STATUSES = new Set(['pending', 'generating']);

// Article candidates are already fetched in full for the study, so review-step
// pagination just slices the in-memory list - no extra API calls needed.
const CANDIDATES_PAGE_SIZE = 10;

export function DocumentsPanel({ studyId }) {
  const { t } = useTranslation(['competitors', 'common']);
  const [error, setError] = useState('');
  const [loadingInitial, setLoadingInitial] = useState(true);

  const [documents, setDocuments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [uploadingDocs, setUploadingDocs] = useState(false);
  const [extractingDocs, setExtractingDocs] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const fileInputRef = useRef(null);

  const [articleCandidates, setArticleCandidates] = useState([]);
  const [reviewingArticles, setReviewingArticles] = useState(false);
  const [decidingCandidate, setDecidingCandidate] = useState({});
  const [approvingAll, setApprovingAll] = useState(false);

  const documentById = useMemo(
    () => Object.fromEntries(documents.map((document) => [document.id, document])),
    [documents],
  );
  const candidatesByDocument = useMemo(() => {
    const groups = new Map();
    for (const candidate of articleCandidates) {
      if (!groups.has(candidate.document_id)) groups.set(candidate.document_id, []);
      groups.get(candidate.document_id).push(candidate);
    }
    return groups;
  }, [articleCandidates]);
  // Grouped-by-document order (not raw articleCandidates order) so a page's
  // slice never interleaves two documents' rows.
  const orderedCandidates = useMemo(
    () => [...candidatesByDocument.values()].flat(),
    [candidatesByDocument],
  );
  const [candidatesPage, setCandidatesPage] = useState(1);
  const totalCandidatePages = Math.max(1, Math.ceil(orderedCandidates.length / CANDIDATES_PAGE_SIZE));
  useEffect(() => {
    setCandidatesPage((prev) => Math.min(prev, totalCandidatePages));
  }, [totalCandidatePages]);
  const candidatePageNumbers = useMemo(
    () => getPageNumbers(candidatesPage, totalCandidatePages),
    [candidatesPage, totalCandidatePages],
  );
  const pagedCandidatesByDocument = useMemo(() => {
    const start = (candidatesPage - 1) * CANDIDATES_PAGE_SIZE;
    const pageCandidates = orderedCandidates.slice(start, start + CANDIDATES_PAGE_SIZE);
    const groups = new Map();
    for (const candidate of pageCandidates) {
      if (!groups.has(candidate.document_id)) groups.set(candidate.document_id, []);
      groups.get(candidate.document_id).push(candidate);
    }
    return groups;
  }, [orderedCandidates, candidatesPage]);
  const pendingCandidateCount = useMemo(
    () => articleCandidates.filter((candidate) => candidate.status === 'pending').length,
    [articleCandidates],
  );
  const approvedCandidateCount = useMemo(
    () => articleCandidates.filter((candidate) => candidate.status === 'approved').length,
    [articleCandidates],
  );

  const refreshArticleCandidates = async (id) => {
    const result = await listDocumentArticles(id);
    setArticleCandidates(result.articles || []);
  };

  // On mount, pick up wherever this study's documents already are — including
  // extraction or article-splitting still running from an earlier visit —
  // rather than assuming a fresh upload is the only way documents get here.
  useEffect(() => {
    if (!studyId) return undefined;
    let cancelled = false;
    (async () => {
      setLoadingInitial(true);
      setError('');
      try {
        const { documents: initialDocs } = await listDocuments(studyId);
        if (cancelled) return;
        setDocuments(initialDocs || []);

        const extractingIds = (initialDocs || [])
          .filter((document) => DOCUMENT_ACTIVE_STATUSES.has(document.status))
          .map((document) => document.id);
        if (extractingIds.length) {
          setExtractingDocs(true);
          await pollDocumentExtraction(studyId, extractingIds, (updated) => {
            if (!cancelled) setDocuments(updated);
          });
          if (!cancelled) setExtractingDocs(false);
        }

        const latest = cancelled ? initialDocs : (await listDocuments(studyId)).documents;
        const articleIds = (latest || [])
          .filter((document) => ARTICLES_ACTIVE_STATUSES.has(document.articles_status))
          .map((document) => document.id);
        if (articleIds.length && !cancelled) {
          setReviewingArticles(true);
          await pollArticleCandidates(studyId, articleIds, (updated) => {
            if (!cancelled) setDocuments(updated);
          });
          if (!cancelled) setReviewingArticles(false);
        }

        if (!cancelled) await refreshArticleCandidates(studyId);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoadingInitial(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId]);

  const addPendingFiles = (fileList) => {
    setPendingFiles((current) => [...current, ...Array.from(fileList || [])]);
  };

  const removePendingFile = (index) => {
    setPendingFiles((current) => current.filter((_, i) => i !== index));
  };

  // Upload whatever files are staged, then poll until each one's background
  // extraction (text library or OCR, decided server-side) settles, then poll
  // again until the candidate articles split out of that text are ready too —
  // the upload button re-enables as soon as the files are saved, so a second
  // batch can go up while the first is still extracting; both polls just
  // re-list from the server, so overlapping calls converge on the same truth
  // rather than conflicting.
  const uploadPendingDocuments = async () => {
    if (!pendingFiles.length) return;
    setError('');
    setUploadingDocs(true);
    let uploadedIds;
    try {
      const result = await uploadDocuments(studyId, pendingFiles);
      uploadedIds = (result.documents || []).map((document) => document.id);
      setPendingFiles([]);
    } catch (caught) {
      setError(caught.message);
      setUploadingDocs(false);
      return;
    }
    setUploadingDocs(false);
    if (!uploadedIds.length) return;
    setExtractingDocs(true);
    try {
      await pollDocumentExtraction(studyId, uploadedIds, setDocuments);
      await pollArticleCandidates(studyId, uploadedIds, setDocuments);
      await refreshArticleCandidates(studyId);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setExtractingDocs(false);
    }
  };

  const removeDocument = async (documentId) => {
    try {
      await deleteDocument(documentId);
      setDocuments((current) => current.filter((document) => document.id !== documentId));
    } catch (caught) {
      setError(caught.message);
    }
  };

  const decideCandidate = async (candidateId, status) => {
    setDecidingCandidate((current) => ({ ...current, [candidateId]: true }));
    try {
      const result = await setDocumentArticleStatus(candidateId, status);
      setArticleCandidates((current) =>
        current.map((candidate) => (candidate.id === candidateId ? result.article : candidate)),
      );
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDecidingCandidate((current) => ({ ...current, [candidateId]: false }));
    }
  };

  const approveAllPending = async () => {
    setError('');
    setApprovingAll(true);
    try {
      await approveAllDocumentArticles(studyId);
      await refreshArticleCandidates(studyId);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setApprovingAll(false);
    }
  };

  if (loadingInitial) {
    return (
      <div className="cs-panel">
        <div className="cs-skeleton" style={{ height: 160 }} />
      </div>
    );
  }

  return (
    <div className="cs-panel">
      {error ? (
        <div className="cs-alert cs-alert-error" style={{ marginBottom: 16 }}>
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span dir="auto">{error}</span>
        </div>
      ) : null}

      <div className="cs-field">
        <label className="cs-label" htmlFor="cs-documents-files">{t('documentsPanel.filesLabel')}</label>
        <div
          className={`cs-dropzone${dropActive ? ' cs-dropzone-active' : ''}`}
          role="button"
          tabIndex={0}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          onDragEnter={(event) => { event.preventDefault(); setDropActive(true); }}
          onDragOver={(event) => { event.preventDefault(); setDropActive(true); }}
          onDragLeave={(event) => { event.preventDefault(); setDropActive(false); }}
          onDrop={(event) => {
            event.preventDefault();
            setDropActive(false);
            addPendingFiles(event.dataTransfer.files);
          }}
        >
          <div className="cs-dropzone-icon"><Upload size={20} /></div>
          <div className="cs-dropzone-title">{t('documentsPanel.dropzoneTitle')}</div>
          <div className="cs-dropzone-hint">{t('documentsPanel.dropzoneHint')}</div>
          <div className="cs-dropzone-types">
            {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG', 'JSON', 'JSONL'].map((ext) => (
              <span key={ext} className="cs-pill cs-pill-signal">{ext}</span>
            ))}
          </div>
          <div className="cs-dropzone-hint" style={{ marginTop: 6 }}>
            {t('documentsPanel.jsonHint')}
          </div>
          <input
            id="cs-documents-files"
            ref={fileInputRef}
            className="cs-sr-only"
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.json,.jsonl,.ndjson"
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => {
              addPendingFiles(event.target.files);
              event.target.value = '';
            }}
          />
        </div>
      </div>

      {pendingFiles.length ? (
        <div className="cs-rows" style={{ marginBottom: 14 }}>
          {pendingFiles.map((file, index) => (
            <div key={`${file.name}-${index}`} className="cs-row">
              <div className="cs-row-main">
                <div className="cs-row-name" dir="auto">{file.name}</div>
                <div className="cs-row-desc">{(file.size / 1024).toFixed(0)} KB {t('documentsPanel.notUploadedYet')}</div>
              </div>
              <div className="cs-row-side">
                <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removePendingFile(index)}>
                  <Trash2 size={13} /> {t('common:actions.remove')}
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            className="cs-btn cs-btn-primary"
            onClick={uploadPendingDocuments}
            disabled={uploadingDocs}
          >
            {uploadingDocs ? <Loader2 size={15} className="cs-spin" /> : <Upload size={15} />}
            {uploadingDocs ? t('documentsPanel.uploadingEllipsis') : t('documentsPanel.uploadFiles', { count: pendingFiles.length })}
          </button>
        </div>
      ) : null}

      {documents.length ? (
        <div className="cs-field">
          <label className="cs-label">
            {t('documentsPanel.uploadedLabel')}
            <span className="cs-label-hint">
              {t('documentsPanel.fileCount', { count: documents.length })}
              {extractingDocs ? ` ${t('documentsPanel.readingContents')}` : ''}
            </span>
          </label>
          <div className="cs-rows">
            {documents.map((document) => {
              const active = document.status === 'uploaded' || document.status === 'processing';
              const progress = active && document.total_chunks ? ` (${document.processed_chunks || 0}/${document.total_chunks})` : '';
              const methodLabel = document.extraction_method === 'ocr'
                ? t('documentsPanel.extractedOcr')
                : document.extraction_method === 'mixed'
                  ? t('documentsPanel.extractedMixed')
                  : t('documentsPanel.extracted');
              return (
                <div key={document.id} className="cs-row" style={{ alignItems: 'flex-start' }}>
                  <div className="cs-row-main">
                    <div className="cs-row-name" dir="auto">{document.original_filename}</div>
                    <div className="cs-row-desc">{(document.size_bytes / 1024).toFixed(0)} KB</div>
                    {document.extraction_error ? (
                      <div
                        style={{
                          display: 'flex', gap: 6, alignItems: 'flex-start', marginTop: 5,
                          fontSize: '0.79rem', color: '#b91c1c', whiteSpace: 'normal', lineHeight: 1.5,
                        }}
                      >
                        <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 2 }} />
                        <span dir="auto">{document.extraction_error}</span>
                      </div>
                    ) : null}
                  </div>
                  <div className="cs-row-side">
                    {active ? (
                      <span className="cs-pill cs-pill-pending">
                        <span className="cs-spinner" style={{ width: 11, height: 11 }} /> {t('documentsPanel.readingWithProgress', { progress })}
                      </span>
                    ) : document.status === 'failed' ? (
                      <span className="cs-pill cs-pill-rejected"><AlertTriangle size={11} /> {t('documentsPanel.notExtracted')}</span>
                    ) : (
                      <span className="cs-pill cs-pill-valid"><ScanText size={11} /> {methodLabel}</span>
                    )}
                    <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removeDocument(document.id)}>
                      <Trash2 size={13} /> {t('common:actions.remove')}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {reviewingArticles ? (
        <div className="cs-panel" style={{ marginBottom: 16, background: '#fcfdff' }}>
          <div className="cs-progress-row cs-progress-row-active">
            <span className="cs-spinner" />
            <span>{t('documentsPanel.readingIntoArticles')}</span>
          </div>
        </div>
      ) : null}

      {articleCandidates.length ? (
        <div className="cs-field">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
            <label className="cs-label" style={{ marginBottom: 0 }}>
              {t('documentsPanel.reviewHeading')}
              <span className="cs-label-hint">
                {t('documentsPanel.reviewSummary', { approved: approvedCandidateCount, pending: pendingCandidateCount })}
              </span>
            </label>
            <button
              type="button"
              className="cs-btn cs-btn-primary cs-btn-sm"
              onClick={approveAllPending}
              disabled={approvingAll || !pendingCandidateCount}
            >
              {approvingAll ? <Loader2 size={15} className="cs-spin" /> : <ListChecks size={15} />}
              {approvingAll
                ? t('documentsPanel.approvingEllipsis')
                : pendingCandidateCount
                  ? t('documentsPanel.approveAllWithCount', { count: pendingCandidateCount })
                  : t('documentsPanel.approveAll')}
            </button>
          </div>

          {[...pagedCandidatesByDocument.entries()].map(([documentId, candidates]) => (
            <div key={documentId} style={{ marginBottom: 18 }}>
              <div style={{ fontSize: '0.76rem', fontWeight: 650, color: 'var(--text-light)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em' }} dir="auto">
                {documentById[documentId]?.original_filename || t('documentsPanel.documentFallback')}
              </div>
              <div className="cs-rows">
                {candidates.map((candidate) => (
                  <div key={candidate.id} className="cs-row" style={{ alignItems: 'flex-start' }}>
                    <div className="cs-row-main">
                      <div className="cs-row-name" dir="auto">{candidate.title}</div>
                      <div className="cs-row-desc" style={{ whiteSpace: 'normal', maxWidth: 'none' }} dir="auto">
                        {candidate.summary}
                      </div>
                    </div>
                    <div className="cs-row-side">
                      {candidate.status === 'approved' ? (
                        <span className="cs-pill cs-pill-valid"><Check size={11} /> {t('documentsPanel.approved')}</span>
                      ) : candidate.status === 'rejected' ? (
                        <span className="cs-pill cs-pill-rejected"><X size={11} /> {t('documentsPanel.rejected')}</span>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="cs-btn cs-btn-sm cs-btn-danger"
                            disabled={decidingCandidate[candidate.id]}
                            onClick={() => decideCandidate(candidate.id, 'rejected')}
                          >
                            <X size={13} /> {t('documentsPanel.rejectAction')}
                          </button>
                          <button
                            type="button"
                            className="cs-btn cs-btn-sm cs-btn-primary"
                            disabled={decidingCandidate[candidate.id]}
                            onClick={() => decideCandidate(candidate.id, 'approved')}
                          >
                            {decidingCandidate[candidate.id] ? <Loader2 size={13} className="cs-spin" /> : <Check size={13} />} {t('documentsPanel.approveAction')}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {totalCandidatePages > 1 && (
            <div className="cs-candidates-pager" role="navigation" aria-label={t('documentsPanel.paginationAria')}>
              <button
                type="button"
                className="cs-btn cs-btn-ghost cs-btn-sm"
                onClick={() => setCandidatesPage((prev) => Math.max(1, prev - 1))}
                disabled={candidatesPage <= 1}
              >
                <ChevronLeft size={14} className="rtl-mirror" /> {t('common:actions.previous')}
              </button>
              {candidatePageNumbers.map((page, index) =>
                page === '...' ? (
                  <span key={`ellipsis-${index}`} className="cs-candidates-pager-ellipsis">&hellip;</span>
                ) : (
                  <button
                    type="button"
                    key={page}
                    className={`cs-candidates-pager-btn${page === candidatesPage ? ' active' : ''}`}
                    onClick={() => setCandidatesPage(page)}
                    aria-current={page === candidatesPage ? 'page' : undefined}
                  >
                    {page}
                  </button>
                ),
              )}
              <button
                type="button"
                className="cs-btn cs-btn-ghost cs-btn-sm"
                onClick={() => setCandidatesPage((prev) => Math.min(totalCandidatePages, prev + 1))}
                disabled={candidatesPage >= totalCandidatePages}
              >
                {t('common:actions.next')} <ChevronRight size={14} className="rtl-mirror" />
              </button>
            </div>
          )}
        </div>
      ) : null}

      {!documents.length && !pendingFiles.length ? (
        <div className="cs-empty">
          <div className="cs-empty-icon"><FileCheck size={20} /></div>
          <h3>{t('documentsPanel.emptyTitle')}</h3>
          <p>{t('documentsPanel.emptyBodyStandalone')}</p>
        </div>
      ) : null}
    </div>
  );
}

export default function CompetitorDocumentsPage() {
  const { t } = useTranslation('competitors');
  const { studyId } = useParams();
  const navigate = useNavigate();
  const [study, setStudy] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const detail = await getStudy(studyId);
        if (!cancelled) setStudy(detail.study);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId]);

  return (
    <div className="cs-page">
      <div className="cs-head">
        <div>
          <Link to={`/competitors/${studyId}`} className="cs-link-back">
            <ChevronRight size={14} className="rtl-mirror" style={{ transform: 'rotate(180deg)' }} /> {t('shared.reports')}
          </Link>
          <h1 dir="auto">{study?.name || t('shared.competitorStudyFallback')} — {t('documents.pageTitleWord')}</h1>
          <p>{t('documents.pageHint')}</p>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span dir="auto">{error}</span>
        </div>
      ) : null}

      <DocumentsPanel studyId={studyId} />

      <div className="cs-wizard-foot">
        <button type="button" className="cs-btn cs-btn-primary" onClick={() => navigate(`/competitors/${studyId}`)}>
          <CheckCircle2 size={15} /> {t('documents.doneButton')}
        </button>
      </div>
    </div>
  );
}
