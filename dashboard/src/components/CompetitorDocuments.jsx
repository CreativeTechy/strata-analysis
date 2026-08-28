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
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle, Check, CheckCircle2, ChevronRight, FileCheck, ListChecks, Loader2, ScanText, Trash2, Upload, X,
} from 'lucide-react';
import {
  approveAllDocumentArticles, deleteDocument, getStudy, listDocumentArticles, listDocuments,
  pollArticleCandidates, pollDocumentExtraction, setDocumentArticleStatus, uploadDocuments,
} from '../api/competitorApi.js';
import '../styles/Competitors.css';

const DOCUMENT_ACTIVE_STATUSES = new Set(['uploaded', 'processing']);
const ARTICLES_ACTIVE_STATUSES = new Set(['pending', 'generating']);

export function DocumentsPanel({ studyId }) {
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
          <span>{error}</span>
        </div>
      ) : null}

      <div className="cs-field">
        <label className="cs-label" htmlFor="cs-documents-files">Files</label>
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
          <div className="cs-dropzone-title">Drag files here, or click to browse</div>
          <div className="cs-dropzone-hint">Multiple files at once are fine</div>
          <div className="cs-dropzone-types">
            {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG', 'JSON', 'JSONL'].map((ext) => (
              <span key={ext} className="cs-pill cs-pill-signal">{ext}</span>
            ))}
          </div>
          <div className="cs-dropzone-hint" style={{ marginTop: 6 }}>
            JSON/JSONL exports are read as articles directly — one record per article, no splitting.
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
                <div className="cs-row-name">{file.name}</div>
                <div className="cs-row-desc">{(file.size / 1024).toFixed(0)} KB — not uploaded yet</div>
              </div>
              <div className="cs-row-side">
                <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removePendingFile(index)}>
                  <Trash2 size={13} /> Remove
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
            {uploadingDocs ? 'Uploading...' : `Upload ${pendingFiles.length} file${pendingFiles.length === 1 ? '' : 's'}`}
          </button>
        </div>
      ) : null}

      {documents.length ? (
        <div className="cs-field">
          <label className="cs-label">
            Uploaded
            <span className="cs-label-hint">
              {documents.length} file{documents.length === 1 ? '' : 's'}
              {extractingDocs ? ' — reading contents...' : ''}
            </span>
          </label>
          <div className="cs-rows">
            {documents.map((document) => {
              const active = document.status === 'uploaded' || document.status === 'processing';
              const progress = active && document.total_chunks ? ` (${document.processed_chunks || 0}/${document.total_chunks})` : '';
              const methodLabel = document.extraction_method === 'ocr'
                ? 'Extracted (OCR)'
                : document.extraction_method === 'mixed'
                  ? 'Extracted (mixed)'
                  : 'Extracted';
              return (
                <div key={document.id} className="cs-row" style={{ alignItems: 'flex-start' }}>
                  <div className="cs-row-main">
                    <div className="cs-row-name">{document.original_filename}</div>
                    <div className="cs-row-desc">{(document.size_bytes / 1024).toFixed(0)} KB</div>
                    {document.extraction_error ? (
                      <div
                        style={{
                          display: 'flex', gap: 6, alignItems: 'flex-start', marginTop: 5,
                          fontSize: '0.79rem', color: '#b91c1c', whiteSpace: 'normal', lineHeight: 1.5,
                        }}
                      >
                        <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 2 }} />
                        <span>{document.extraction_error}</span>
                      </div>
                    ) : null}
                  </div>
                  <div className="cs-row-side">
                    {active ? (
                      <span className="cs-pill cs-pill-pending">
                        <span className="cs-spinner" style={{ width: 11, height: 11 }} /> Reading{progress}...
                      </span>
                    ) : document.status === 'failed' ? (
                      <span className="cs-pill cs-pill-rejected"><AlertTriangle size={11} /> Not extracted</span>
                    ) : (
                      <span className="cs-pill cs-pill-valid"><ScanText size={11} /> {methodLabel}</span>
                    )}
                    <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removeDocument(document.id)}>
                      <Trash2 size={13} /> Remove
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
            <span>Reading your documents into articles...</span>
          </div>
        </div>
      ) : null}

      {articleCandidates.length ? (
        <div className="cs-field">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
            <label className="cs-label" style={{ marginBottom: 0 }}>
              Review extracted articles
              <span className="cs-label-hint">
                {approvedCandidateCount} approved, {pendingCandidateCount} pending
              </span>
            </label>
            <button
              type="button"
              className="cs-btn cs-btn-primary cs-btn-sm"
              onClick={approveAllPending}
              disabled={approvingAll || !pendingCandidateCount}
            >
              {approvingAll ? <Loader2 size={15} className="cs-spin" /> : <ListChecks size={15} />}
              {approvingAll ? 'Approving...' : `Approve all${pendingCandidateCount ? ` (${pendingCandidateCount})` : ''}`}
            </button>
          </div>

          {[...candidatesByDocument.entries()].map(([documentId, candidates]) => (
            <div key={documentId} style={{ marginBottom: 18 }}>
              <div style={{ fontSize: '0.76rem', fontWeight: 650, color: 'var(--text-light)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                {documentById[documentId]?.original_filename || 'Document'}
              </div>
              <div className="cs-rows">
                {candidates.map((candidate) => (
                  <div key={candidate.id} className="cs-row" style={{ alignItems: 'flex-start' }}>
                    <div className="cs-row-main">
                      <div className="cs-row-name">{candidate.title}</div>
                      <div className="cs-row-desc" style={{ whiteSpace: 'normal', maxWidth: 'none' }}>
                        {candidate.summary}
                      </div>
                    </div>
                    <div className="cs-row-side">
                      {candidate.status === 'approved' ? (
                        <span className="cs-pill cs-pill-valid"><Check size={11} /> Approved</span>
                      ) : candidate.status === 'rejected' ? (
                        <span className="cs-pill cs-pill-rejected"><X size={11} /> Rejected</span>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="cs-btn cs-btn-sm cs-btn-danger"
                            disabled={decidingCandidate[candidate.id]}
                            onClick={() => decideCandidate(candidate.id, 'rejected')}
                          >
                            <X size={13} /> Reject
                          </button>
                          <button
                            type="button"
                            className="cs-btn cs-btn-sm cs-btn-primary"
                            disabled={decidingCandidate[candidate.id]}
                            onClick={() => decideCandidate(candidate.id, 'approved')}
                          >
                            {decidingCandidate[candidate.id] ? <Loader2 size={13} className="cs-spin" /> : <Check size={13} />} Approve
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {!documents.length && !pendingFiles.length ? (
        <div className="cs-empty">
          <div className="cs-empty-icon"><FileCheck size={20} /></div>
          <h3>No documents yet</h3>
          <p>Add some above to give this study evidence to report on.</p>
        </div>
      ) : null}
    </div>
  );
}

export default function CompetitorDocumentsPage() {
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
            <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> Reports
          </Link>
          <h1>{study?.name || 'Competitor study'} — Documents</h1>
          <p>
            Upload files to give this study evidence to report on. Each one is extracted as soon as
            it uploads — text where the file has any, OCR where it doesn&rsquo;t — and split into
            candidate articles for you to approve; approving is what makes an article usable evidence.
          </p>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{error}</span>
        </div>
      ) : null}

      <DocumentsPanel studyId={studyId} />

      <div className="cs-wizard-foot">
        <button type="button" className="cs-btn cs-btn-primary" onClick={() => navigate(`/competitors/${studyId}`)}>
          <CheckCircle2 size={15} /> Done
        </button>
      </div>
    </div>
  );
}
