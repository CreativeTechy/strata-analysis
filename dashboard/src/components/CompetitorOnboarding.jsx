/**
 * Competitor study onboarding.
 *
 *   1. Add competitors  — a study name plus the companies to track: import the
 *                         tracked-competitors JSONL exported by the scraper
 *                         app, or type names in by hand. Nothing here reads a
 *                         document — the competitor set is user-given, not
 *                         AI-derived.
 *   2. Review & track   — decide which of the added competitors actually get
 *                         a report. Only tracked competitors are analyzed;
 *                         anything left ignored (or removed) stays out.
 *   3. Add documents    — optional. Upload files to build the evidence a
 *                         report is written from; each document's extracted
 *                         text is split into candidate articles by the LLM,
 *                         and approving one turns it into a real article.
 *                         Skippable — evidence can be added later from the
 *                         workspace, and analysis runs from there too.
 *
 * Document extraction and article-splitting each run tens of seconds to
 * minutes in the background, so step 3 shows staged progress instead of an
 * indeterminate spinner.
 */

import { useMemo, useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight,
  FileCheck, Layers, ListChecks, Loader2, Plus, ScanText, Tags, Trash2, Upload, X,
} from 'lucide-react';
import {
  addCompetitor, approveAllDocumentArticles, avatarGradient, createStudy, deleteCompetitor,
  deleteDocument, importCompetitors, initials, listCompetitors, listDocumentArticles,
  pollArticleCandidates, pollDocumentExtraction, setCompetitorStatus, setDocumentArticleStatus,
  uploadDocuments,
} from '../competitorApi.js';
import '../styles/Competitors.css';

const STEPS = [
  { id: 1, label: 'Add competitors', icon: Layers },
  { id: 2, label: 'Review & track', icon: Tags },
  { id: 3, label: 'Add documents', icon: Upload },
];

/** Real-time progress lines from an analysis run's `logs` (see
 *  competitorApi.js's pollAnalysisRun `onUpdate`) — each poll can add more, so
 *  this auto-scrolls to keep the latest line in view. Styled like a checklist
 *  (a checkmark per finished line, a spinner on the most recent one while the
 *  run is still active). Renders nothing until there's at least one line, and
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

export default function CompetitorOnboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [error, setError] = useState('');
  const [studyName, setStudyName] = useState('');
  const [studyId, setStudyId] = useState(null);

  // ---- Step 1/2: competitors -------------------------------------------
  const [competitors, setCompetitors] = useState([]);
  const [manualName, setManualName] = useState('');
  const [manualWebsite, setManualWebsite] = useState('');
  const [manualDescription, setManualDescription] = useState('');
  const [addingManual, setAddingManual] = useState(false);
  const [importingCompetitors, setImportingCompetitors] = useState(false);
  const importInputRef = useRef(null);
  const [trackingBusy, setTrackingBusy] = useState({});
  const [removingCompetitor, setRemovingCompetitor] = useState({});
  const [trackingAll, setTrackingAll] = useState(false);

  // ---- Step 3: documents -------------------------------------------------
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
  const trackedCount = useMemo(
    () => competitors.filter((competitor) => competitor.status === 'tracked').length,
    [competitors],
  );

  const ensureStudy = async () => {
    if (studyId) return studyId;
    const created = await createStudy({ name: studyName.trim() || 'Untitled competitor study' });
    setStudyId(created.study.id);
    return created.study.id;
  };

  const refreshCompetitors = async (id) => {
    const result = await listCompetitors(id);
    setCompetitors(result.competitors || []);
  };

  // Step 1: type a name (website/description optional) and add it directly —
  // no discovery, no evidence requirement. Created 'tracked' by default since
  // typing a name in is already a deliberate "watch this company" action; the
  // next step is still there to change anyone's mind.
  const addManualCompetitor = async () => {
    const name = manualName.trim();
    if (!name) return;
    setError('');
    setAddingManual(true);
    try {
      const id = await ensureStudy();
      await addCompetitor(id, {
        name,
        website: manualWebsite.trim() || undefined,
        description: manualDescription.trim() || undefined,
        status: 'tracked',
      });
      await refreshCompetitors(id);
      setManualName('');
      setManualWebsite('');
      setManualDescription('');
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAddingManual(false);
    }
  };

  // A study built by scraping (rather than uploaded documents) hands its
  // tracked-competitor list over as JSONL via the scraper app's
  // `GET /api/competitors/export` - importing it here saves re-typing that
  // same list by hand.
  const handleImportFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || importingCompetitors) return;
    setError('');
    setImportingCompetitors(true);
    try {
      const id = await ensureStudy();
      await importCompetitors(id, file);
      await refreshCompetitors(id);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setImportingCompetitors(false);
    }
  };

  const toggleTracking = async (competitor) => {
    const nextStatus = competitor.status === 'tracked' ? 'ignored' : 'tracked';
    setTrackingBusy((current) => ({ ...current, [competitor.id]: true }));
    try {
      await setCompetitorStatus(competitor.id, nextStatus);
      await refreshCompetitors(studyId);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setTrackingBusy((current) => ({ ...current, [competitor.id]: false }));
    }
  };

  // One call per untracked competitor — the API has no bulk-status route, and
  // a study's competitor list is at most a few dozen rows, so this is cheap.
  const trackAllCompetitors = async () => {
    const untracked = competitors.filter((competitor) => competitor.status !== 'tracked');
    if (!untracked.length) return;
    setError('');
    setTrackingAll(true);
    try {
      await Promise.all(untracked.map((competitor) => setCompetitorStatus(competitor.id, 'tracked')));
      await refreshCompetitors(studyId);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setTrackingAll(false);
    }
  };

  const removeCompetitor = async (competitorId) => {
    setRemovingCompetitor((current) => ({ ...current, [competitorId]: true }));
    try {
      await deleteCompetitor(competitorId);
      setCompetitors((current) => current.filter((competitor) => competitor.id !== competitorId));
    } catch (caught) {
      setError(caught.message);
      setRemovingCompetitor((current) => ({ ...current, [competitorId]: false }));
    }
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

  // Step 3: create the study (if step 1 never did — documents alone are
  // enough to start one), upload whatever files are staged, then poll until
  // each one's background extraction (text library or OCR, decided
  // server-side) settles, then poll again until the candidate articles split
  // out of that text are ready too — the upload button re-enables as soon as
  // the files are saved, so a second batch can go up while the first is still
  // extracting; both polls just re-list from the server, so overlapping calls
  // converge on the same truth rather than conflicting.
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

  // Resume watching for any document still generating candidates when step 3
  // is (re)entered — uploading doesn't gate on generation finishing, so it
  // can still be running here. Reads documentsRef instead of depending on
  // `documents` directly so this only re-runs on an actual step change, not
  // on every document-list update the poll itself causes.
  useEffect(() => {
    if (step !== 3 || !studyId) return;
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

  const goToStep2 = async () => {
    setError('');
    try {
      const id = await ensureStudy();
      await refreshCompetitors(id);
      setStep(2);
    } catch (caught) {
      setError(caught.message);
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
            Name the companies this study tracks — import a list or add them one at a time — then
            decide which ones get a report. Documents are optional and can be added now or later;
            approving the articles split out of them is what gives a tracked competitor evidence to
            report on.
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

      {/* ---------------- Step 1: add competitors ---------------- */}
      {step === 1 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Layers size={16} /> Add your competitors</h2>
          <p className="cs-panel-hint">
            Import the tracked-competitors list exported from the scraper app, or add companies by
            hand. You can add more of either later from the workspace.
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
            <label className="cs-label">Import a list</label>
            <input
              ref={importInputRef}
              type="file"
              accept=".jsonl,.ndjson,application/x-ndjson"
              onChange={handleImportFile}
              style={{ display: 'none' }}
            />
            <button
              type="button"
              className="cs-btn"
              onClick={() => importInputRef.current?.click()}
              disabled={importingCompetitors}
              title="Import the tracked-competitors JSONL exported from the scraper app."
            >
              {importingCompetitors ? <Loader2 size={15} className="cs-spin" /> : <Upload size={15} />}
              {importingCompetitors ? 'Importing...' : 'Import JSONL'}
            </button>
          </div>

          <div className="cs-field">
            <label className="cs-label">Add one by hand</label>
            <div className="cs-grid-2">
              <input
                className="cs-input"
                value={manualName}
                placeholder="Company name"
                onChange={(event) => setManualName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    addManualCompetitor();
                  }
                }}
              />
              <input
                className="cs-input"
                value={manualWebsite}
                placeholder="Website (optional)"
                onChange={(event) => setManualWebsite(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    addManualCompetitor();
                  }
                }}
              />
            </div>
            <textarea
              className="cs-textarea"
              style={{ minHeight: 60, marginTop: 8 }}
              value={manualDescription}
              placeholder="What they do (optional)"
              onChange={(event) => setManualDescription(event.target.value)}
            />
            <button
              type="button"
              className="cs-btn cs-btn-primary"
              style={{ marginTop: 8 }}
              onClick={addManualCompetitor}
              disabled={addingManual || !manualName.trim()}
            >
              {addingManual ? <Loader2 size={15} className="cs-spin" /> : <Plus size={15} />}
              {addingManual ? 'Adding...' : 'Add competitor'}
            </button>
          </div>

          {competitors.length ? (
            <div className="cs-field">
              <label className="cs-label">
                Added
                <span className="cs-label-hint">{competitors.length} competitor{competitors.length === 1 ? '' : 's'}</span>
              </label>
              <div className="cs-pills">
                {competitors.map((competitor) => (
                  <span key={competitor.id} className="cs-pill">{competitor.name}</span>
                ))}
              </div>
            </div>
          ) : (
            <div className="cs-empty">
              <div className="cs-empty-icon"><Layers size={20} /></div>
              <h3>No competitors yet</h3>
              <p>Import a list or add one above to get started.</p>
            </div>
          )}

          <div className="cs-wizard-foot">
            <button
              type="button"
              className="cs-btn cs-btn-primary"
              onClick={goToStep2}
              disabled={!competitors.length}
            >
              <ArrowRight size={15} /> Continue to review
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 2: review & track competitors ---------------- */}
      {step === 2 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Tags size={16} /> Review & track</h2>
          <p className="cs-panel-hint">
            Only tracked competitors get a report. Untrack anything you added but don&rsquo;t want to
            follow, or remove it outright.
          </p>

          {competitors.length ? (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, flexWrap: 'wrap', gap: 10 }}>
              <span style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                <strong style={{ color: 'var(--text-dark)' }}>{trackedCount}</strong> tracked of{' '}
                <strong style={{ color: 'var(--text-dark)' }}>{competitors.length}</strong> added
              </span>
              <button
                type="button"
                className="cs-btn cs-btn-primary"
                onClick={trackAllCompetitors}
                disabled={trackingAll || trackedCount === competitors.length}
              >
                {trackingAll ? <Loader2 size={15} className="cs-spin" /> : <Check size={15} />}
                {trackingAll ? 'Tracking...' : `Track all${competitors.length - trackedCount ? ` (${competitors.length - trackedCount})` : ''}`}
              </button>
            </div>
          ) : null}

          {competitors.length === 0 ? (
            <div className="cs-empty">
              <div className="cs-empty-icon"><Tags size={20} /></div>
              <h3>No competitors yet</h3>
              <p>Go back and import a list or add one by hand.</p>
            </div>
          ) : (
            <div className="cs-rows">
              {competitors.map((competitor) => (
                <div key={competitor.id} className="cs-row">
                  <div className="cs-avatar" style={{ background: avatarGradient(competitor.name), width: 30, height: 30, fontSize: '0.72rem' }} aria-hidden="true">
                    {initials(competitor.name)}
                  </div>
                  <div className="cs-row-main">
                    <div className="cs-row-name">{competitor.name}</div>
                    {competitor.description ? <div className="cs-row-desc">{competitor.description}</div> : null}
                  </div>
                  <div className="cs-row-side">
                    <button
                      type="button"
                      className={`cs-btn cs-btn-sm${competitor.status === 'tracked' ? ' cs-btn-primary' : ''}`}
                      onClick={() => toggleTracking(competitor)}
                      disabled={Boolean(trackingBusy[competitor.id])}
                    >
                      {trackingBusy[competitor.id] ? (
                        <span className="cs-spinner" />
                      ) : competitor.status === 'tracked' ? (
                        <><Check size={13} /> Tracking</>
                      ) : (
                        'Track'
                      )}
                    </button>
                    <button
                      type="button"
                      className="cs-btn cs-btn-sm cs-btn-danger"
                      onClick={() => removeCompetitor(competitor.id)}
                      disabled={Boolean(removingCompetitor[competitor.id])}
                    >
                      <Trash2 size={13} /> Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(1)}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={() => setStep(3)}>
              <ArrowRight size={15} /> Continue to documents
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 3: add documents (optional) ---------------- */}
      {step === 3 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Upload size={16} /> Add documents <span className="cs-label-hint" style={{ marginLeft: 6 }}>optional</span></h2>
          <p className="cs-panel-hint">
            Upload files to give your tracked competitors something to be reported on. Each one is
            extracted as soon as it uploads — text where the file has any, OCR where it doesn&rsquo;t —
            and split into candidate articles for you to approve below. Skip this and add documents
            later from the workspace if you&rsquo;d rather do that first.
          </p>

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
                {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG', 'JSON', 'JSONL'].map((ext) => (
                  <span key={ext} className="cs-pill cs-pill-signal">{ext}</span>
                ))}
              </div>
              {/* A JSON/JSONL upload is already a list of articles, so it skips
                  the LLM split entirely - worth saying, since it also means
                  those files keep each record's own link and date. */}
              <div className="cs-dropzone-hint" style={{ marginTop: 6 }}>
                JSON/JSONL exports are read as articles directly — one record per article, no splitting.
              </div>
              <input
                id="cs-offline-files"
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
              <p>Add some above, or finish now and add them later from the workspace.</p>
            </div>
          ) : null}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(2)}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={finish} disabled={uploadingDocs}>
              <CheckCircle2 size={15} /> {documents.length ? 'Finish' : 'Skip & finish'}
            </button>
          </div>
        </div>
      ) : null}

    </div>
  );
}
