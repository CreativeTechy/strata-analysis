import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, BarChart3, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, FileSearch, Filter, Minus, PanelRightClose, Quote, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import {
  compareEvidenceRuns, getEvidenceClaim, getEvidenceWorkspace, retryEvidenceRun,
  reviewEvidenceClaim, reviewEvidenceProvenance,
} from '../api/projectsApi.js';
import '../styles/Evidence.css';

const LABELS = {
  supported: 'Supported', contradicted: 'Contradicted', mixed_evidence: 'Mixed evidence',
  insufficient_evidence: 'Insufficient evidence', not_yet_verifiable: 'Not yet verifiable',
  assessment_unavailable: 'Assessment unavailable',
};

const MATRIX_PAGE_SIZE = 5;
const CLAIM_PAGE_SIZE = 5;

const CLAIM_TABS = [
  { key: 'all', label: 'All claims' },
  { key: 'needs_review', label: 'Needs review' },
  { key: 'supported', label: 'Supported', assessment: 'supported' },
  { key: 'contradicted', label: 'Contradicted', assessment: 'contradicted' },
  { key: 'mixed_evidence', label: 'Mixed', assessment: 'mixed_evidence' },
  { key: 'insufficient_evidence', label: 'Insufficient', assessment: 'insufficient_evidence' },
  { key: 'not_yet_verifiable', label: 'Not yet verifiable', assessment: 'not_yet_verifiable' },
  { key: 'assessment_unavailable', label: 'Unavailable', assessment: 'assessment_unavailable' },
];

const MATRIX_STATES = {
  supporting: { label: 'Supports' },
  contradicting: { label: 'Conflicts' },
  contextual: { label: 'Context' },
  review: { label: 'Review' },
  missing: { label: 'None' },
};

function MatrixStateIcon({ stateKey, size = 14 }) {
  if (stateKey === 'supporting') return <CheckCircle2 size={size} />;
  if (stateKey === 'contradicting') return <XCircle size={size} />;
  if (stateKey === 'contextual') return <Quote size={size} />;
  if (stateKey === 'review') return <AlertTriangle size={size} />;
  return <Minus size={size} />;
}

function shortSourceName(value) {
  const source = String(value || 'Unknown source');
  const known = {
    'UK Department for Energy Security and Net Zero': 'UK Energy Department',
    'UK Parliament - Scottish Affairs Committee': 'Scottish Affairs Committee',
    'House of Commons Library': 'Commons Library',
    'Society of Motor Manufacturers and Traders': 'SMMT',
    'Climate Change Committee': 'Climate Committee',
  };
  if (known[source]) return known[source];
  return source.length > 28 ? `${source.slice(0, 26).trim()}…` : source;
}

function evidencePublisher(item) {
  const meta = sourceMeta(item);
  const provenance = item?.current_provenance || meta.provenance || {};
  return provenance.publisher || meta.source || 'Unknown source';
}

function matrixCellState(row, publisher) {
  const items = row.sources.filter((item) => item.publisher === publisher);
  const relationship = items.find((item) => item.relationship === 'contradicting')?.relationship
    || items.find((item) => item.relationship === 'supporting')?.relationship
    || items[0]?.relationship;
  const qualified = items.some((item) => item.citation_valid && item.qualifies);
  const stateKey = qualified && relationship ? relationship : items.length ? 'review' : 'missing';
  return { items, stateKey, state: MATRIX_STATES[stateKey] || MATRIX_STATES.missing };
}

function formatDate(value) {
  if (!value) return 'Unknown date';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString();
}

function formatDateTime(value) {
  if (!value) return 'Unknown time';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function sourceMeta(item) {
  return item?.source_snapshot || {};
}

export default function EvidenceWorkspacePage({ projects = [] }) {
  const { projectId } = useParams();
  const [search, setSearch] = useSearchParams();
  const { hasPermission } = useAuth();
  const canReview = hasPermission('projects.update');
  const canRetry = hasPermission('pipeline.run');
  const project = projects.find((item) => Number(item.id) === Number(projectId));
  const runId = search.get('run_id') || '';
  const topic = search.get('topic') || '';
  const searchText = search.get('search') || '';
  const assessmentFilter = search.get('assessment') || '';
  const typeFilter = search.get('claim_type') || '';
  const publisherFilter = search.get('publisher') || '';
  const reviewFilter = search.get('review_status') || '';
  const provenanceFilter = search.get('provenance_status') || '';
  const coverageFilter = search.get('coverage') || '';
  const offset = Number(search.get('offset') || 0);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [decision, setDecision] = useState('supported');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [compareBase, setCompareBase] = useState('');
  const [comparison, setComparison] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [provenanceTarget, setProvenanceTarget] = useState(null);
  const [provenanceDecision, setProvenanceDecision] = useState('verified');
  const [provenanceReason, setProvenanceReason] = useState('');
  const [view, setView] = useState('review');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [matrixPage, setMatrixPage] = useState(0);
  const [matrixSourceMode, setMatrixSourceMode] = useState('active');
  const [matrixDetail, setMatrixDetail] = useState(null);
  const [matrixDetailLoading, setMatrixDetailLoading] = useState(false);

  const updateFilters = (changes) => {
    const next = new URLSearchParams(search);
    Object.entries(changes).forEach(([key, value]) => {
      if (value === '' || value === null || value === undefined) next.delete(key);
      else next.set(key, String(value));
    });
    if (!Object.hasOwn(changes, 'offset')) next.delete('offset');
    setMatrixPage(0);
    setMatrixDetail(null);
    setSearch(next, { replace: true });
  };

  const load = async (signal) => {
    setLoading(true); setError('');
    try {
      const result = await getEvidenceWorkspace(projectId, {
        run_id: runId, topic, search: searchText, assessment: assessmentFilter,
        claim_type: typeFilter, publisher: publisherFilter, review_status: reviewFilter,
        provenance_status: provenanceFilter, coverage: coverageFilter,
        limit: view === 'matrix' ? MATRIX_PAGE_SIZE : CLAIM_PAGE_SIZE,
        offset: view === 'matrix' ? matrixPage * MATRIX_PAGE_SIZE : offset,
      }, signal);
      setData(result);
      if (!runId && result.selected_run_id) updateFilters({ run_id: result.selected_run_id });
    } catch (err) {
      if (err?.name !== 'AbortError') setError(err?.message || 'Failed to load evidence.');
    } finally { setLoading(false); }
  };

  useEffect(() => {
    const controller = new AbortController();
    // load owns the request lifecycle and the abort signal prevents stale updates.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load(controller.signal);
    return () => controller.abort();
  }, [projectId, runId, topic, searchText, assessmentFilter, typeFilter, publisherFilter, reviewFilter, provenanceFilter, coverageFilter, offset, view, matrixPage]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // This clears details that belong to the previous URL-scoped claim set.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected(null); setComparison(null); setProvenanceTarget(null); setMatrixDetail(null);
  }, [runId, topic, assessmentFilter, typeFilter, publisherFilter, reviewFilter, provenanceFilter, coverageFilter]);

  useEffect(() => {
    const current = data?.runs?.find((item) => String(item.id) === String(data?.selected_run_id));
    if (!['pending', 'running'].includes(current?.evidence_status)) return undefined;
    const timer = window.setTimeout(() => load(), 1500);
    return () => window.clearTimeout(timer);
  }, [data?.runs, data?.selected_run_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const openClaim = async (id) => {
    setError('');
    try {
      const result = await getEvidenceClaim(projectId, id);
      setSelected(result.claim); setDecision(result.claim.reviews?.[0]?.decision || result.claim.assessment); setReason('');
    } catch (err) { setError(err?.message || 'Failed to open the claim.'); }
  };

  const openMatrixDetail = async (row, publisher) => {
    setMatrixDetail({ claim: row, publisher, evidence: [] });
    setMatrixDetailLoading(true); setError('');
    try {
      const result = await getEvidenceClaim(projectId, row.claim_id);
      setMatrixDetail({
        claim: result.claim,
        publisher,
        evidence: (result.claim?.evidence || []).filter((item) => evidencePublisher(item) === publisher),
      });
    } catch (err) { setError(err?.message || 'Failed to open the source evidence.'); }
    finally { setMatrixDetailLoading(false); }
  };

  const saveReview = async () => {
    if (!selected || !reason.trim()) return;
    setSaving(true);
    try {
      const result = await reviewEvidenceClaim(projectId, selected.id, { decision, reason });
      setSelected(result.claim); setReason(''); await load();
    } catch (err) { setError(err?.message || 'Failed to save the review.'); }
    finally { setSaving(false); }
  };

  const saveProvenanceReview = async () => {
    if (!provenanceTarget || !provenanceReason.trim()) return;
    try {
      await reviewEvidenceProvenance(projectId, provenanceTarget.article_id, { status: provenanceDecision, reason: provenanceReason });
      setProvenanceTarget(null); setProvenanceReason('');
      await openClaim(selected.id); await load();
    } catch (err) { setError(err?.message || 'Failed to review provenance.'); }
  };

  const retry = async () => {
    if (!data?.selected_run_id) return;
    setRetrying(true);
    try {
      await retryEvidenceRun(projectId, data.selected_run_id); await load();
      window.setTimeout(() => load(), 1200);
    }
    catch (err) { setError(err?.message || 'Failed to rebuild evidence.'); }
    finally { setRetrying(false); }
  };

  const defaultCompareBase = useMemo(() => {
    const runs = data?.runs || [];
    const targetIndex = runs.findIndex((run) => String(run.id) === String(data?.selected_run_id));
    return String(runs[targetIndex + 1]?.id || runs.find((run) => String(run.id) !== String(data?.selected_run_id))?.id || '');
  }, [data?.runs, data?.selected_run_id]);

  const runComparison = async () => {
    const baseRunId = compareBase || defaultCompareBase;
    if (!baseRunId || !data?.selected_run_id) return;
    setComparing(true); setError('');
    try {
      const result = await compareEvidenceRuns(projectId, {
        base_run_id: baseRunId, target_run_id: data.selected_run_id,
      });
      setComparison(result.comparison);
    } catch (err) { setError(err?.message || 'Failed to compare evidence runs.'); }
    finally { setComparing(false); }
  };

  const overview = data?.overview || {};
  const assessmentCards = useMemo(() => Object.entries(overview.assessment_counts || {}), [overview.assessment_counts]);
  const matrix = data?.source_matrix || { publishers: [], rows: [] };
  const matrixTotal = Number(data?.total_filtered || 0);
  const matrixPageCount = Math.max(1, Math.ceil(matrixTotal / MATRIX_PAGE_SIZE));
  const matrixSafePage = Math.min(matrixPage, matrixPageCount - 1);
  const matrixFirst = matrixTotal ? matrixSafePage * MATRIX_PAGE_SIZE + 1 : 0;
  const matrixLast = Math.min(matrixFirst + matrix.rows.length - 1, matrixTotal);
  const matrixCoverage = useMemo(() => Object.fromEntries(
    (matrix.publishers || []).map((publisher) => [publisher, (matrix.rows || []).filter((row) => (
      row.sources.some((item) => item.publisher === publisher && item.citation_valid && item.qualifies)
    )).length]),
  ), [matrix.publishers, matrix.rows]);
  const matrixPresence = useMemo(() => Object.fromEntries(
    (matrix.publishers || []).map((publisher) => [publisher, (matrix.rows || []).filter((row) => (
      row.sources.some((item) => item.publisher === publisher)
    )).length]),
  ), [matrix.publishers, matrix.rows]);
  const activeMatrixPublishers = (matrix.publishers || []).filter((publisher) => matrixPresence[publisher] > 0);
  const visibleMatrixPublishers = matrixSourceMode === 'all' ? (matrix.publishers || []) : activeMatrixPublishers;
  const hiddenMatrixPublishers = Math.max(0, (matrix.publishers || []).length - activeMatrixPublishers.length);
  const matrixQuickFilter = coverageFilter === 'single_source' ? 'single_source'
    : coverageFilter === 'conflicting' ? 'conflicting'
      : reviewFilter === 'needs_attention' ? 'needs_review'
        : assessmentFilter === 'supported' ? 'supported' : 'all';
  const setMatrixQuickFilter = (key) => {
    const next = { assessment: '', review_status: '', coverage: '' };
    if (key === 'supported') next.assessment = 'supported';
    if (key === 'conflicting') next.coverage = 'conflicting';
    if (key === 'needs_review') next.review_status = 'needs_attention';
    if (key === 'single_source') next.coverage = 'single_source';
    updateFilters(next);
  };
  const changeMatrixPage = (page) => {
    setMatrixDetail(null);
    setMatrixPage(Math.max(0, Math.min(matrixPageCount - 1, page)));
  };
  const matrixPagination = (position) => <nav className="evidence-matrix-pagination" aria-label={`${position} claim matrix pagination`}>
    <button type="button" aria-label="Previous claim page" disabled={matrixSafePage === 0 || loading} onClick={() => changeMatrixPage(matrixSafePage - 1)}><ChevronLeft size={15} /> Previous</button>
    <span>Page {matrixSafePage + 1} of {matrixPageCount}</span>
    <button type="button" aria-label="Next claim page" disabled={matrixSafePage + 1 >= matrixPageCount || loading} onClick={() => changeMatrixPage(matrixSafePage + 1)}>Next <ChevronRight size={15} /></button>
  </nav>;
  const selectedClaimTab = reviewFilter === 'needs_attention' ? 'needs_review'
    : CLAIM_TABS.find((item) => item.assessment === assessmentFilter)?.key || 'all';
  const claimTabCount = (tab) => {
    if (tab.key === 'all') return overview.total_claims || 0;
    if (tab.key === 'needs_review') return overview.needs_review_claims || 0;
    return overview.assessment_counts?.[tab.assessment] || 0;
  };
  const setClaimTab = (tab) => updateFilters({
    assessment: tab.assessment || '',
    review_status: tab.key === 'needs_review' ? 'needs_attention' : '',
    coverage: '',
  });
  const claimTotal = Number(data?.total_filtered || 0);
  const claimPage = Math.floor(offset / CLAIM_PAGE_SIZE);
  const claimPageCount = Math.max(1, Math.ceil(claimTotal / CLAIM_PAGE_SIZE));
  const claimFirst = claimTotal ? offset + 1 : 0;
  const claimLast = Math.min(offset + (data?.claims?.length || 0), claimTotal);
  const changeClaimPage = (page) => updateFilters({ offset: Math.max(0, Math.min(claimPageCount - 1, page)) * CLAIM_PAGE_SIZE });
  const claimPagination = (position) => <nav className="evidence-claim-pagination" aria-label={`${position} claims pagination`}>
    <button type="button" disabled={claimPage === 0 || loading} onClick={() => changeClaimPage(claimPage - 1)}><ChevronLeft size={15} /> Previous</button>
    <span>Page <strong>{claimPage + 1}</strong> of <strong>{claimPageCount}</strong></span>
    <button type="button" disabled={claimPage + 1 >= claimPageCount || loading} onClick={() => changeClaimPage(claimPage + 1)}>Next <ChevronRight size={15} /></button>
  </nav>;

  return (
    <div className="admin-page-shell evidence-page">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker"><ShieldCheck size={14} /> Evidence workspace</div>
          <h1 className="admin-page-title">{project?.name || 'Project evidence'}</h1>
          <p className="admin-page-subtitle">Inspect what each run supports, what remains uncertain, and the exact imported passages behind every assessment.</p>
        </div>
        <div className="admin-page-toolbar">
          <Link className="btn-secondary" to={`/projects/${projectId}`}><ArrowLeft size={15} /> Project</Link>
          {canRetry && data?.selected_run_id ? <button className="btn-secondary" onClick={retry} disabled={retrying}><RefreshCw size={15} className={retrying ? 'spin' : ''} /> Rebuild evidence</button> : null}
        </div>
      </div>

      <div className="evidence-scope-note">
        <ShieldCheck size={18} />
        <div><strong>Evidence from this run’s saved documents</strong><span>Assessments use the frozen text captured for this run. No website is fetched while you review this page.</span></div>
      </div>

      <div className="glass-card evidence-filters">
        <label>Analysis run<select value={data?.selected_run_id || runId} onChange={(event) => updateFilters({ run_id: event.target.value, topic: '' })}>
          {(data?.runs || []).map((run) => <option key={run.id} value={run.id}>Run {run.run_number} · {formatDateTime(run.created_at)} · {run.claim_count} claims · {run.document_count} documents</option>)}
        </select></label>
        <label>Topic<select value={topic} onChange={(event) => updateFilters({ topic: event.target.value })}>
          <option value="">All topics</option>{(data?.topics || []).map((item) => <option key={item.topic} value={item.topic}>{item.topic} ({item.count})</option>)}
        </select></label>
        <label>Search<input value={searchText} onChange={(event) => updateFilters({ search: event.target.value })} placeholder="Claim or explanation" /></label>
        <label>Assessment<select value={assessmentFilter} onChange={(event) => updateFilters({ assessment: event.target.value })}>
          <option value="">All assessments</option>{Object.entries(LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <button type="button" className="evidence-more-filters" onClick={() => setShowAdvanced((current) => !current)}><Filter size={14} /> {showAdvanced ? 'Hide filters' : 'More filters'} <ChevronDown size={14} className={showAdvanced ? 'open' : ''} /></button>
        {showAdvanced ? <div className="evidence-advanced-filters"><label>Claim type<select value={typeFilter} onChange={(event) => updateFilters({ claim_type: event.target.value })}>
          <option value="">All types</option>{['factual_assertion', 'attributed_statement', 'forecast', 'opinion', 'causal_explanation'].map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
        </select></label>
        <label>Publisher<select value={publisherFilter} onChange={(event) => updateFilters({ publisher: event.target.value })}>
          <option value="">All publishers</option>{(data?.filter_options?.publishers || []).map((value) => <option key={value} value={value}>{value}</option>)}
        </select></label>
        <label>Analyst review<select value={reviewFilter} onChange={(event) => updateFilters({ review_status: event.target.value })}>
          <option value="">Any status</option><option value="needs_attention">Needs attention</option><option value="unreviewed">Not reviewed by analyst</option><option value="reviewed">Reviewed</option>
        </select></label>
        <label>Origin review<select value={provenanceFilter} onChange={(event) => updateFilters({ provenance_status: event.target.value })}>
          <option value="">Any status</option><option value="unassessed">Unassessed</option><option value="verified">Verified</option><option value="rejected">Rejected</option>
        </select></label></div> : null}
      </div>

      {error ? <div className="evidence-error">{error}</div> : null}
      {data?.runs?.find((run) => String(run.id) === String(data.selected_run_id))?.evidence_status === 'failed'
        ? <div className="evidence-error">Evidence processing failed: {data.runs.find((run) => String(run.id) === String(data.selected_run_id))?.evidence_error || 'Unknown error'}. Use Rebuild evidence to retry safely.</div>
        : null}
      {loading && !data ? <div className="glass-card evidence-empty">Loading evidence…</div> : null}
      {!loading && !(data?.runs || []).length ? <div className="glass-card evidence-empty"><FileSearch size={24} /><strong>No evidence run yet</strong><span>Complete an analysis run to freeze the project evidence and extract claims.</span></div> : null}

      {(data?.runs || []).length ? <>
        <div className="evidence-overview">
          <div className="glass-card evidence-stat"><span>Total claims</span><strong>{overview.total_claims || 0}</strong><small>Extracted from this run</small></div>
          <div className="glass-card evidence-stat positive"><span>Corroborated</span><strong>{overview.corroborated_claims || 0}</strong><small>Two or more independent origins</small></div>
          <div className="glass-card evidence-stat"><span>Single source</span><strong>{overview.single_source_claims || 0}</strong><small>Useful, but not independently confirmed</small></div>
          <div className={`glass-card evidence-stat ${(overview.needs_review_claims || 0) ? 'attention' : ''}`}><span>Needs review</span><strong>{overview.needs_review_claims || 0}</strong><small>Quotation or source needs attention</small></div>
          {assessmentCards.map(([key, value]) => <button type="button" className={`glass-card ${assessmentFilter === key ? 'active' : ''}`} key={key} onClick={() => updateFilters({ assessment: assessmentFilter === key ? '' : key })}><span>{LABELS[key] || key}</span><strong>{value}</strong></button>)}
        </div>

        {(data?.runs || []).length > 1 ? <div className="glass-card evidence-comparison">
          <div><strong>Compare runs</strong><span>See evidence changes separately from rules-only reprocessing.</span></div>
          <select value={compareBase || defaultCompareBase} onChange={(event) => { setCompareBase(event.target.value); setComparison(null); }}>
            {(data?.runs || []).filter((run) => String(run.id) !== String(data.selected_run_id)).map((run) => <option key={run.id} value={run.id}>{formatDate(run.created_at)} · {run.claim_count} claims</option>)}
          </select>
          <button className="btn-secondary" onClick={runComparison} disabled={comparing || !(compareBase || defaultCompareBase)}>{comparing ? 'Comparing…' : 'Compare'}</button>
          {comparison ? <div className="evidence-change-list">
            {!comparison.changes.length ? <span>No claim or evidence-count changes between these runs.</span> : comparison.changes.map((change) => <button type="button" key={change.fingerprint} onClick={() => change.target?.id && openClaim(change.target.id)}>
              <span className="panel-chip">{change.change_type.replaceAll('_', ' ')}</span>
              <strong>{change.claim_text}</strong>
              <small>{change.base?.assessment ? LABELS[change.base.assessment] : 'Not present'} → {change.target?.assessment ? LABELS[change.target.assessment] : 'Not present'}</small>
              <p>{change.cause}</p>
            </button>)}
          </div> : null}
        </div> : null}

        <div className="evidence-view-switch" role="tablist" aria-label="Evidence view">
          <button type="button" role="tab" aria-selected={view === 'review'} className={view === 'review' ? 'active' : ''} onClick={() => { if (coverageFilter) updateFilters({ coverage: '' }); setView('review'); }}><Quote size={15} /> Review claims</button>
          <button type="button" role="tab" aria-selected={view === 'matrix'} className={view === 'matrix' ? 'active' : ''} onClick={() => { setMatrixPage(0); setView('matrix'); }}><BarChart3 size={15} /> Compare sources</button>
        </div>

        {view === 'matrix' ? <div className={`glass-card evidence-matrix-card ${matrixDetail ? 'has-detail' : ''}`}>
          <div className="evidence-matrix-heading">
            <div><div className="evidence-matrix-title"><strong>Claims by source</strong><span className="panel-chip">5 per page</span><span className="panel-chip muted">{activeMatrixPublishers.length} on this page</span>{loading ? <span className="panel-chip loading">Updating…</span> : null}</div><span>Compare source agreement and open any filled cell to inspect its exact saved passage.</span></div>
            <div className="evidence-matrix-legend">{Object.entries(MATRIX_STATES).map(([key, state]) => <span className={key} key={key}><b><MatrixStateIcon stateKey={key} size={13} /></b>{state.label}</span>)}</div>
          </div>
          <div className="evidence-matrix-controls">
            <div className="evidence-matrix-quick-filters" aria-label="Quick claim filters">
              {[['all', 'All claims'], ['supported', 'Supported'], ['conflicting', 'Conflicting'], ['needs_review', 'Needs review'], ['single_source', 'Single source']].map(([key, label]) => <button type="button" key={key} aria-pressed={matrixQuickFilter === key} className={matrixQuickFilter === key ? 'active' : ''} onClick={() => setMatrixQuickFilter(key)}>{label}</button>)}
            </div>
            <div className="evidence-source-toggle" aria-label="Source columns"><button type="button" className={matrixSourceMode === 'active' ? 'active' : ''} aria-pressed={matrixSourceMode === 'active'} onClick={() => setMatrixSourceMode('active')}>Sources on page</button><button type="button" className={matrixSourceMode === 'all' ? 'active' : ''} aria-pressed={matrixSourceMode === 'all'} onClick={() => setMatrixSourceMode('all')}>All sources</button></div>
          </div>
          <div className="evidence-matrix-truth-note"><ShieldCheck size={15} /><span><strong>“Supported” means supported by qualifying passages in the saved documents.</strong> It does not independently prove the claim is true in the real world.</span></div>
          {matrix.rows.length && visibleMatrixPublishers.length ? <>
            <div className="evidence-matrix-topline"><span>Showing <strong>{matrixFirst}–{matrixLast}</strong> of <strong>{matrixTotal}</strong> claims{matrixSourceMode === 'active' && hiddenMatrixPublishers ? ` · ${hiddenMatrixPublishers} unrelated source${hiddenMatrixPublishers === 1 ? '' : 's'} hidden` : ''}</span>{matrixPagination('Top')}</div>
            <div className="evidence-matrix-scroll"><table className="evidence-matrix"><thead><tr><th><span>Claim</span><small>{matrixTotal} in this view</small></th>{visibleMatrixPublishers.map((publisher) => <th key={publisher} title={publisher}><span>{shortSourceName(publisher)}</span><small>{matrixCoverage[publisher] ? `${matrixCoverage[publisher]} qualified` : 'No qualifying passage'}</small></th>)}</tr></thead><tbody>
              {matrix.rows.map((row, rowIndex) => <tr key={row.claim_id}><th><button type="button" onClick={() => { openClaim(row.claim_id); setView('review'); }}><span className="evidence-matrix-claim-number">{matrixFirst + rowIndex}</span><span className={`evidence-status ${row.assessment}`}>{LABELS[row.assessment] || row.assessment}</span><strong>{row.claim_text}</strong><small>{row.topic}</small></button></th>{visibleMatrixPublishers.map((publisher) => {
                const { items, stateKey, state } = matrixCellState(row, publisher);
                return <td key={publisher}><button type="button" disabled={!items.length} onClick={() => openMatrixDetail(row, publisher)} className={`evidence-matrix-cell ${stateKey}`} aria-label={`${publisher}: ${state.label}${items.length ? '. Open evidence.' : ''}`} title={`${publisher}: ${state.label}`}><MatrixStateIcon stateKey={stateKey} /><span>{state.label}</span></button></td>;
              })}</tr>)}
            </tbody></table></div>
            <div className="evidence-matrix-mobile">{matrix.rows.map((row, rowIndex) => <article key={row.claim_id} className="evidence-matrix-mobile-card"><button type="button" className="evidence-matrix-mobile-claim" onClick={() => { openClaim(row.claim_id); setView('review'); }}><span className="evidence-matrix-claim-number">{matrixFirst + rowIndex}</span><span className={`evidence-status ${row.assessment}`}>{LABELS[row.assessment] || row.assessment}</span><strong>{row.claim_text}</strong><small>{row.topic}</small></button><div>{activeMatrixPublishers.map((publisher) => {
              const { items, stateKey, state } = matrixCellState(row, publisher);
              if (!items.length) return null;
              return <button type="button" key={publisher} className={`evidence-matrix-mobile-source ${stateKey}`} onClick={() => openMatrixDetail(row, publisher)}><span title={publisher}>{shortSourceName(publisher)}</span><b><MatrixStateIcon stateKey={stateKey} /> {state.label}</b></button>;
            })}</div></article>)}</div>
            <div className="evidence-matrix-footer"><span>Showing <strong>{matrixFirst}–{matrixLast}</strong> of <strong>{matrixTotal}</strong> claims</span>{matrixPagination('Bottom')}</div>
          </> : <div className="evidence-empty"><FileSearch size={22} /><span>No source evidence matches these filters.</span></div>}
          {matrixDetail ? <aside className="evidence-matrix-detail" aria-label="Source evidence detail">
            <header><div><span>Evidence detail</span><strong title={matrixDetail.publisher}>{shortSourceName(matrixDetail.publisher)}</strong></div><button type="button" aria-label="Close evidence detail" onClick={() => setMatrixDetail(null)}><PanelRightClose size={18} /></button></header>
            <div className="evidence-matrix-detail-claim"><span className={`evidence-status ${matrixDetail.claim.assessment}`}>{LABELS[matrixDetail.claim.assessment] || matrixDetail.claim.assessment}</span><strong>{matrixDetail.claim.claim_text}</strong></div>
            {matrixDetailLoading ? <div className="evidence-empty">Loading exact passages…</div> : <div className="evidence-matrix-detail-items">{matrixDetail.evidence.map((item) => {
              const meta = sourceMeta(item); const provenance = item.current_provenance || meta.provenance || {}; const stateKey = item.citation_valid && item.qualifies ? item.relationship : 'review';
              return <article key={item.id}><div><span className={`evidence-matrix-cell ${stateKey}`}><MatrixStateIcon stateKey={stateKey} /><span>{MATRIX_STATES[stateKey]?.label || 'Review'}</span></span>{!item.qualifies ? <span className="panel-chip warning">Does not qualify</span> : null}</div><blockquote>{item.passage}</blockquote><dl><div><dt>Publisher</dt><dd>{provenance.publisher || meta.source || matrixDetail.publisher}</dd></div><div><dt>Published</dt><dd>{formatDate(meta.published_at)}</dd></div><div><dt>Locator</dt><dd>{item.passage_locator || 'Unavailable'}</dd></div></dl>{meta.qualification_reason ? <p className={`evidence-qualification ${item.qualifies ? 'qualified' : 'unqualified'}`}>{meta.qualification_reason}</p> : null}{(provenance.original_url || meta.url)?.startsWith('http') ? <a href={provenance.original_url || meta.url} target="_blank" rel="noreferrer">Open source <ExternalLink size={12} /></a> : null}</article>;
            })}{!matrixDetail.evidence.length ? <div className="evidence-empty">No saved passage is available for this source.</div> : null}</div>}
            <button type="button" className="btn-primary evidence-matrix-open-review" onClick={() => { setSelected(matrixDetail.claim); setMatrixDetail(null); setView('review'); }}>Open full claim review</button>
          </aside> : null}
        </div> : <div className="evidence-layout">
          <div className="glass-card evidence-claims">
            <div className="evidence-claims-heading"><div><strong>Claims</strong><span className="panel-chip">{claimTotal}</span></div><small>Choose a status to focus the review queue.</small></div>
            <div className="evidence-claim-tabs" role="tablist" aria-label="Claim status">
              {CLAIM_TABS.map((tab) => <button type="button" role="tab" aria-selected={selectedClaimTab === tab.key} className={selectedClaimTab === tab.key ? 'active' : ''} key={tab.key} onClick={() => setClaimTab(tab)}><span>{tab.label}</span><b>{claimTabCount(tab)}</b></button>)}
            </div>
            <div className="evidence-claim-page-summary"><span>Showing <strong>{claimFirst}–{claimLast}</strong> of <strong>{claimTotal}</strong></span>{claimPagination('Top')}</div>
            {(data?.claims || []).map((claim) => {
              const effective = claim.review_decision || claim.assessment;
              return <button type="button" className={`evidence-claim ${selected?.id === claim.id ? 'active' : ''}`} key={claim.id} onClick={() => openClaim(claim.id)}>
                <div><span className={`evidence-status ${effective}`}>{LABELS[effective] || effective}</span><span className="panel-chip muted">{claim.topic}</span>{claim.needs_review ? <span className="panel-chip warning">Needs review</span> : null}</div>
                <strong>{claim.claim_text}</strong>
                <small>{claim.distinct_origins} origin{claim.distinct_origins === 1 ? '' : 's'} · {claim.supporting_count} supporting · {claim.contradicting_count} conflicting{claim.review_count ? ` · reviewed` : ''}</small>
              </button>;
            })}
            {!(data?.claims || []).length ? <div className="evidence-empty">No claims match this topic.</div> : null}
            <div className="evidence-claim-page-summary bottom"><span>Showing <strong>{claimFirst}–{claimLast}</strong> of <strong>{claimTotal}</strong></span>{claimPagination('Bottom')}</div>
          </div>

          <div className="glass-card evidence-detail">
            {!selected ? <div className="evidence-empty"><FileSearch size={22} /><span>Select a claim to inspect its evidence.</span></div> : <>
              <div><span className={`evidence-status ${selected.assessment}`}>Automated: {LABELS[selected.assessment]}</span>{selected.reviews?.[0] ? <span className={`evidence-status ${selected.reviews[0].decision}`}>Analyst: {LABELS[selected.reviews[0].decision]}</span> : null}<span className="panel-chip muted">{selected.claim_type?.replaceAll('_', ' ')}</span></div>
              <h2>{selected.claim_text}</h2>
              <p>{selected.explanation}</p><p className="evidence-limit">{selected.limitations}</p>
              <div className="evidence-method"><span>Assessment method: {selected.rules_version || 'Unknown'}</span><span>Independent qualifying origins: {selected.independent_origin_count || 0}</span><span>Exact quotations checked: {selected.citation_checked_count || 0}</span>{selected.time_scope ? <span>Time scope: {selected.time_scope}</span> : null}{selected.quantities?.length ? <span>Quantities: {selected.quantities.join(', ')}</span> : null}</div>
              <h3>Evidence passages</h3>
              <div className="evidence-items">{(selected.evidence || []).map((item) => {
                const meta = sourceMeta(item); const provenance = item.current_provenance || meta.provenance || {};
                return <article key={item.id} className={`evidence-item ${item.relationship}`}>
                  <div><span className={`evidence-status ${item.relationship}`}>{item.relationship}</span>{item.citation_valid ? <span title="Exact passage found in frozen document"><CheckCircle2 size={14} /> exact quotation</span> : <span title="No exact document passage"><XCircle size={14} /> quotation unavailable</span>}{!item.qualifies ? <span className="panel-chip warning">Does not qualify</span> : null}</div>
                  <blockquote>{item.passage}</blockquote>
                  <div className="evidence-source"><strong>{provenance.publisher || meta.source || 'Unknown source'}</strong><span>Published: {formatDate(meta.published_at)}</span><span>Locator: {item.passage_locator || 'Unavailable'}</span><span>Content type: {item.quote_source || provenance.source_type || 'Unknown'}</span><span>Analysis: {meta.analysis_source === 'run' ? 'Produced in this run' : 'Reused frozen analysis'}</span><span>Origin review: {item.provenance_review?.status || provenance.verification_status || 'unassessed'}</span>{Number.isFinite(Number(meta.passage_match_score)) ? <span>Passage match: {Math.round(Number(meta.passage_match_score) * 100)}%</span> : null}{item.provenance_review ? <span>{item.provenance_review.reviewer_name}: {item.provenance_review.reason}</span> : null}</div>
                  {meta.qualification_reason ? <p className={`evidence-qualification ${item.qualifies ? 'qualified' : 'unqualified'}`}>{meta.qualification_reason}</p> : null}
                  <div className="evidence-item-actions">{(provenance.original_url || meta.url)?.startsWith('http') ? <a href={provenance.original_url || meta.url} target="_blank" rel="noreferrer">Open source <ExternalLink size={12} /></a> : <span>Stored article #{item.article_id}</span>}{canReview ? <button onClick={() => { setProvenanceTarget(item); setProvenanceDecision('verified'); setProvenanceReason(''); }}>Review origin</button> : null}</div>
                  {provenanceTarget?.id === item.id ? <div className="evidence-provenance-form"><label>Origin decision<select value={provenanceDecision} onChange={(event) => setProvenanceDecision(event.target.value)}><option value="verified">Verified</option><option value="rejected">Rejected</option><option value="unassessed">Return to unassessed</option></select></label><label>Reason<textarea rows="2" value={provenanceReason} onChange={(event) => setProvenanceReason(event.target.value)} placeholder="Record what you checked and why…" /></label><div><button className="btn-primary" onClick={saveProvenanceReview} disabled={!provenanceReason.trim()}>Save origin review</button><button className="btn-secondary" onClick={() => setProvenanceTarget(null)}>Cancel</button></div></div> : null}
                </article>;
              })}</div>
              {canReview ? <div className="evidence-review"><h3>Analyst review</h3><select value={decision} onChange={(event) => setDecision(event.target.value)}>{Object.entries(LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain the evidence and the limits of this decision…"/><button className="btn-primary" onClick={saveReview} disabled={saving || !reason.trim()}>{saving ? 'Saving…' : 'Save review'}</button></div> : null}
              {selected.reviews?.length ? <div><h3>Review history</h3>{selected.reviews.map((review) => <div className="evidence-history" key={review.id}><strong>{LABELS[review.decision]}</strong><span>{review.reviewer_name || 'Reviewer'} · {formatDate(review.created_at)}</span><p>{review.reason}</p></div>)}</div> : null}
            </>}
          </div>
        </div>}
      </> : null}
    </div>
  );
}
