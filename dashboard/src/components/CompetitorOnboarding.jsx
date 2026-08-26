/**
 * Competitor study onboarding.
 *
 *   1. Upload documents — a study name plus the files themselves. Each upload
 *                         is saved immediately, then extracted (text library or
 *                         OCR, decided server-side) in the background; this step
 *                         polls and shows each file's status as it resolves.
 *                         Extraction success also kicks off splitting the text
 *                         into candidate articles, reviewed next.
 *   2. Review articles  — each document's extracted text is split into candidate
 *                         articles by the LLM; approving one turns it into a real
 *                         article the analysis can read. "Approve all" is the
 *                         fast path.
 *   3. Analyze & report — reads the approved articles for the companies they are
 *                         actually about, tracks each one, writes a report card
 *                         per company, then opens the workspace.
 *
 * Extraction and analysis each run tens of seconds to minutes, so both show
 * staged progress instead of an indeterminate spinner.
 */

import { useMemo, useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight,
  FileCheck, ListChecks, Loader2, Plus, ScanText, Sparkles, Trash2, Upload, X,
} from 'lucide-react';
import {
  analyzeDocuments, approveAllDocumentArticles, createStudy, deleteDocument, listDocumentArticles,
  pollArticleCandidates, pollDocumentExtraction, setDocumentArticleStatus, uploadDocuments,
} from '../competitorApi.js';
import '../styles/Competitors.css';

/** Offline swaps step 3 for its own "Review articles" and skips step 4
 *  (Competitors) and step 5 (Channels) entirely — there's nothing to track or
 *  find channels for yet, so they're left out of the chip row rather than
 *  shown as passed-through. Step 5 (Channels)/6 (Schedule) also collapse into
 *  a single id 5: there's nothing to re-scrape or review, so instead it runs
 *  analysis straight off the approved articles and shows the resulting report. */
const STEPS = [
  { id: 1, label: 'Upload documents', icon: Upload },
  { id: 2, label: 'Review articles', icon: FileCheck },
  { id: 3, label: 'Analyze & report', icon: ScanText },
];

// Mirrors document_analysis.py's two-stage shape: name the companies the
// documents are actually about, then run the same evidence-validation +
// finding-generation an online study uses.
const DOCUMENT_ANALYSIS_STAGES = [
  'Reading approved articles for company names',
  'Matching evidence to each company',
  'Writing findings',
];

/** Real-time progress lines from an analysis run's `logs` (see
 *  competitorApi.js's pollAnalysisRun `onUpdate`) — each poll can add more, so
 *  this auto-scrolls to keep the latest line in view. Styled like StageList
 *  (same row/icon language: a checkmark per finished line, a spinner on the
 *  most recent one while the run is still active) so the real detail trail
 *  reads as a continuation of that same progress UI rather than a separate
 *  terminal-style log. Renders nothing until there's at least one line, and
 *  stays visible after the run finishes so the trail can still be reviewed.
 *  Exported so CompetitorRunAnalysis.jsx can reuse it, the same way
 *  CompetitorEditPage.jsx reuses ListEditor from this file. */
export function DiscoveryLog({ logs, active }) {
  const boxRef = useRef(null);
  const [now, setNow] = useState(null);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [logs?.length]);

  // The backend can go quiet for a while on a single slow step (an LLM call
  // has no sub-progress to report) - without this, the last line just sits
  // there and reads as stuck. Ticking a counter next to it at least shows
  // time is passing, not that the run died. `Date.now()` only ever runs here,
  // inside an effect, never during render.
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, logs?.length]);

  if (!logs?.length) return null;

  const lastTs = new Date(logs[logs.length - 1].ts).getTime();
  const elapsed = now ? Math.max(0, Math.round((now - lastTs) / 1000)) : 0;

  return (
    <div className="cs-panel cs-discovery-log" style={{ marginTop: 14, background: '#fcfdff' }}>
      <div className="cs-progress" ref={boxRef}>
        {logs.map((entry, index) => {
          const isCurrent = active && index === logs.length - 1;
          return (
            <div
              key={index}
              className={`cs-progress-row${isCurrent ? ' cs-progress-row-active' : ' cs-progress-row-done'}`}
            >
              {isCurrent ? <span className="cs-spinner" /> : <CheckCircle2 size={15} />}
              <span>
                {entry.message}
                {isCurrent && elapsed >= 4 ? ` (still working, ${elapsed}s)` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Staged feedback for a slow request. Advances on a timer purely so the wait
 *  reads as progress; it never claims the work finished — that is driven by the
 *  response, which replaces this component entirely. Rendered only while a
 *  request is in flight, so each run mounts it fresh at stage zero. */
function StageList({ stages }) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveIndex((current) => Math.min(current + 1, stages.length - 1));
    }, 2600);
    return () => clearInterval(timer);
  }, [stages.length]);

  return (
    <div className="cs-progress">
      {stages.map((stage, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        return (
          <div
            key={stage}
            className={`cs-progress-row${active ? ' cs-progress-row-active' : ''}${done ? ' cs-progress-row-done' : ''}`}
          >
            {done ? <CheckCircle2 size={15} /> : active ? <span className="cs-spinner" /> : <span style={{ width: 15 }} />}
            <span>{stage}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ListEditor({ label, hint, values, onChange, placeholder }) {
  const [draft, setDraft] = useState('');
  const items = Array.isArray(values) ? values : [];

  const add = () => {
    const value = draft.trim();
    if (!value || items.includes(value)) {
      setDraft('');
      return;
    }
    onChange([...items, value]);
    setDraft('');
  };

  return (
    <div className="cs-field">
      <label className="cs-label">
        {label}
        {hint ? <span className="cs-label-hint">{hint}</span> : null}
      </label>
      <div className="cs-pills" style={{ marginBottom: items.length ? 9 : 0 }}>
        {items.map((item) => (
          <span key={item} className="cs-pill">
            {item}
            <button
              type="button"
              onClick={() => onChange(items.filter((value) => value !== item))}
              aria-label={`Remove ${item}`}
              style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'flex', color: 'inherit' }}
            >
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          className="cs-input"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="cs-btn" onClick={add} disabled={!draft.trim()}>
          <Plus size={14} /> Add
        </button>
      </div>
    </div>
  );
}

/** Fixed-list country multi-select: type to filter, click a match to add,
 *  selected countries render as removable pills. Modeled on ListEditor above,
 *  since free text would let "USA" and "United States" reach the discovery
 *  prompt as different values. */
export default function CompetitorOnboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [error, setError] = useState('');
  const [studyName, setStudyName] = useState('');
  const [studyId, setStudyId] = useState(null);

  const [documents, setDocuments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [uploadingDocs, setUploadingDocs] = useState(false);
  const [extractingDocs, setExtractingDocs] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const fileInputRef = useRef(null);
  const documentsRef = useRef(documents);
  useEffect(() => {
    documentsRef.current = documents;
  }, [documents]);

  const [articleCandidates, setArticleCandidates] = useState([]);
  const [reviewingArticles, setReviewingArticles] = useState(false);
  const [decidingCandidate, setDecidingCandidate] = useState({});
  const [approvingAll, setApprovingAll] = useState(false);

  const [analyzingDocuments, setAnalyzingDocuments] = useState(false);
  const [documentAnalysis, setDocumentAnalysis] = useState(null);

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

  const ensureStudy = async () => {
    if (studyId) return studyId;
    const created = await createStudy({ name: studyName.trim() || 'Untitled competitor study' });
    setStudyId(created.study.id);
    return created.study.id;
  };

  const addPendingFiles = (fileList) => {
    setPendingFiles((current) => [...current, ...Array.from(fileList || [])]);
  };

  const removePendingFile = (index) => {
    setPendingFiles((current) => current.filter((_, i) => i !== index));
  };

  const refreshArticleCandidates = async (id) => {
    const result = await listDocumentArticles(id);
    setArticleCandidates(result.articles || []);
  };

  // Offline step 2: create the study (if needed), upload whatever files are
  // staged, then poll until each one's background extraction (text library or
  // OCR, decided server-side) settles, then poll again until the candidate
  // articles split out of that text are ready too — the upload button
  // re-enables as soon as the files are saved, so a second batch can go up
  // while the first is still extracting; both polls just re-list from the
  // server, so overlapping calls converge on the same truth rather than
  // conflicting.
  const uploadPendingDocuments = async () => {
    if (!pendingFiles.length) return;
    setError('');
    setUploadingDocs(true);
    let id;
    let uploadedIds;
    try {
      id = await ensureStudy();
      const result = await uploadDocuments(id, pendingFiles);
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
      await pollDocumentExtraction(id, uploadedIds, setDocuments);
      await pollArticleCandidates(id, uploadedIds, setDocuments);
      await refreshArticleCandidates(id);
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

  // Offline step 3: resume watching for any document still generating
  // candidates when this step is (re)entered — Continue on step 2 isn't
  // gated on generation finishing, so it can still be running here. Reads
  // documentsRef instead of depending on `documents` directly so this only
  // re-runs on an actual step change, not on every document-list update the
  // poll itself causes.
  useEffect(() => {
    if (step !== 2 || !studyId) return;
    let cancelled = false;
    (async () => {
      const activeIds = documentsRef.current
        .filter((document) => document.articles_status === 'pending' || document.articles_status === 'generating')
        .map((document) => document.id);
      if (activeIds.length) {
        setReviewingArticles(true);
        try {
          await pollArticleCandidates(studyId, activeIds, (updated) => {
            if (!cancelled) setDocuments(updated);
          });
        } catch (caught) {
          if (!cancelled) setError(caught.message);
        } finally {
          if (!cancelled) setReviewingArticles(false);
        }
      }
      if (!cancelled) {
        try {
          await refreshArticleCandidates(studyId);
        } catch (caught) {
          if (!cancelled) setError(caught.message);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, studyId]);

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

  // Step 5 (offline): names the competitors the approved articles are
  // actually about, tracks them, then generates one finding card per company
  // — the same report an online study ends up with, just derived from
  // documents rather than from a name the user typed.
  const runDocumentAnalysis = async () => {
    setError('');
    setAnalyzingDocuments(true);
    try {
      const result = await analyzeDocuments(studyId);
      setDocumentAnalysis(result);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAnalyzingDocuments(false);
    }
  };

  const finish = () => {
    navigate(`/competitors/${studyId}`);
  };

  return (
    <div className="cs-page cs-wizard">
      <div className="cs-head">
        <div>
          <h1>New competitor study</h1>
          <p>
            Upload the documents this study is built from. Strata splits them into articles for you
            to approve, works out which companies those articles are actually about, and writes a
            report card for each one.
          </p>
        </div>
      </div>

      <div className="cs-steps" role="list">
        {STEPS.map((item, index) => {
          const state = step === item.id ? ' cs-step-active' : step > item.id ? ' cs-step-done' : '';
          const Icon = item.icon;
          // Only steps already completed can be jumped back to — their data is
          // already loaded. A step not yet reached has nothing to show yet, so
          // it stays inert rather than opening a blank/broken panel.
          const clickable = step > item.id;
          return (
            <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button
                type="button"
                className={`cs-step${state}${clickable ? ' cs-step-clickable' : ''}`}
                role="listitem"
                aria-current={step === item.id}
                onClick={clickable ? () => setStep(item.id) : undefined}
                disabled={!clickable}
                title={clickable ? `Back to ${item.label}` : undefined}
              >
                <span className="cs-step-num">
                  {step > item.id ? <Check size={12} /> : index + 1}
                </span>
                <Icon size={14} />
                <span>{item.label}</span>
              </button>
              {index < STEPS.length - 1 ? <ChevronRight size={14} className="cs-step-sep" /> : null}
            </div>
          );
        })}
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      ) : null}

      {/* ---------------- Step 1: upload documents ---------------- */}
      {step === 1 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Upload size={16} /> Upload your documents</h2>
          <p className="cs-panel-hint">
            Add every file you want this study built from. Each one is extracted as soon as it
            uploads — text where the file has any, OCR where it doesn&rsquo;t — and you can add more
            later from the workspace.
          </p>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-offline-study-name">Study name</label>
            <input
              id="cs-offline-study-name"
              className="cs-input"
              value={studyName}
              placeholder="Q3 competitor study"
              onChange={(event) => setStudyName(event.target.value)}
            />
          </div>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-offline-files">Files</label>
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
                {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG'].map((ext) => (
                  <span key={ext} className="cs-pill cs-pill-signal">{ext}</span>
                ))}
              </div>
              <input
                id="cs-offline-files"
                ref={fileInputRef}
                className="cs-sr-only"
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg"
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
                disabled={uploadingDocs || !studyName.trim()}
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
                        {/* Always shown when present — a partial extraction failure
                            (some pages/sheets ok, others not) must not hide behind a
                            plain "Extracted" pill just because status ended up ok. */}
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
          ) : (
            <div className="cs-empty">
              <div className="cs-empty-icon"><Upload size={20} /></div>
              <h3>No documents yet</h3>
              <p>Choose files above, then upload them to attach them to this study.</p>
            </div>
          )}

          <div className="cs-wizard-foot">
            <button
              type="button"
              className="cs-btn cs-btn-primary"
              onClick={() => setStep(2)}
              disabled={!documents.length || uploadingDocs}
            >
              <ArrowRight size={15} /> Continue to review articles
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 2: review extracted articles ---------------- */}
      {step === 2 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><FileCheck size={16} /> Review extracted articles</h2>
          <p className="cs-panel-hint">
            Each item below was split out of one of your documents. Approving one turns it into an
            article your study can run analysis on later;
            rejecting leaves it out. Nothing here is final — you can leave items pending and decide later.
          </p>

          {reviewingArticles ? (
            <div className="cs-panel" style={{ marginBottom: 16, background: '#fcfdff' }}>
              <div className="cs-progress-row cs-progress-row-active">
                <span className="cs-spinner" />
                <span>Reading your documents into articles...</span>
              </div>
            </div>
          ) : null}

          {!reviewingArticles && !articleCandidates.length ? (
            <div className="cs-empty">
              <div className="cs-empty-icon"><FileCheck size={20} /></div>
              <h3>No articles yet</h3>
              <p>
                {documents.some((document) => document.articles_status === 'failed')
                  ? 'Splitting a document into articles failed — check its error on the upload step.'
                  : 'Nothing usable was found in your documents.'}
              </p>
            </div>
          ) : null}

          {articleCandidates.length ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
                <span style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                  <strong style={{ color: 'var(--text-dark)' }}>{approvedCandidateCount}</strong> approved,{' '}
                  <strong style={{ color: 'var(--text-dark)' }}>{pendingCandidateCount}</strong> pending review
                </span>
                <button
                  type="button"
                  className="cs-btn cs-btn-primary"
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
            </>
          ) : null}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(1)}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={() => setStep(3)} disabled={reviewingArticles}>
              <ArrowRight size={15} /> Continue to analysis
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 3: analyze & report ---------------- */}
      {step === 3 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><ScanText size={16} /> Analyze & report</h2>
          <p className="cs-panel-hint">
            {documents.length} document{documents.length === 1 ? '' : 's'} uploaded,{' '}
            {approvedCandidateCount} article{approvedCandidateCount === 1 ? '' : 's'} approved.
            We&rsquo;ll read those articles for the companies they&rsquo;re actually about, track each
            one, then generate a report card per company. You can re-run this later from the workspace
            once you approve more documents.
          </p>

          {analyzingDocuments ? <StageList stages={DOCUMENT_ANALYSIS_STAGES} /> : null}

          {!analyzingDocuments && documentAnalysis ? (
            <div className="cs-alert cs-alert-info" style={{ marginBottom: 16 }}>
              <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                Generated {documentAnalysis.generated} report{documentAnalysis.generated === 1 ? '' : 's'} from{' '}
                {documentAnalysis.articles_considered} approved article{documentAnalysis.articles_considered === 1 ? '' : 's'}
                {documentAnalysis.derived_competitors?.length
                  ? `, covering ${documentAnalysis.derived_competitors.map((c) => c.name).join(', ')}`
                  : ''}.
                {documentAnalysis.skipped?.length ? (
                  <> {documentAnalysis.skipped.length} competitor{documentAnalysis.skipped.length === 1 ? '' : 's'} had no
                    usable evidence.</>
                ) : null}
                {documentAnalysis.derivation_error ? <> {documentAnalysis.derivation_error}</> : null}
              </span>
            </div>
          ) : null}

          {!analyzingDocuments ? (
            <button type="button" className="cs-btn cs-btn-primary" onClick={runDocumentAnalysis} style={{ marginBottom: 16 }}>
              <Sparkles size={15} /> {documentAnalysis ? 'Re-run analysis' : 'Run analysis'}
            </button>
          ) : null}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(2)} disabled={analyzingDocuments}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={finish} disabled={analyzingDocuments}>
              <CheckCircle2 size={15} /> Open workspace
            </button>
          </div>
        </div>
      ) : null}

    </div>
  );
}
