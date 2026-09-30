import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, BarChart3, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, FileSearch, Filter, Minus, PanelRightClose, Quote, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import {
  compareEvidenceRuns, getEvidenceClaim, getEvidenceWorkspace, retryEvidenceRun,
  reviewEvidenceArticleScreening, reviewEvidenceClaim, reviewEvidenceProvenance,
  reviewEvidenceRelevance, updateEvidenceScope,
} from '../api/projectsApi.js';
import i18n from '../i18n/index.js';
import { formatDate as formatDateIntl, formatDateTime as formatDateTimeIntl, formatPercent } from '../lib/i18nFormat.js';
import '../styles/Evidence.css';

// These label maps are DB enum values (never translate the object key, only
// the displayed value - see CLAUDE.md's source-trust note on keeping
// `unknown` distinct from `untrusted`; the same "don't blur the codes"
// principle applies to claim assessment/relevance codes here). Built from
// `t` rather than kept as module-level constants so the labels re-render in
// the active locale.
function buildLabels(t) {
  return {
    supported: t('sources:evidence.labels.supported'),
    contradicted: t('sources:evidence.labels.contradicted'),
    mixed_evidence: t('sources:evidence.labels.mixedEvidence'),
    insufficient_evidence: t('sources:evidence.labels.insufficientEvidence'),
    not_yet_verifiable: t('sources:evidence.labels.notYetVerifiable'),
    assessment_unavailable: t('sources:evidence.labels.assessmentUnavailable'),
  };
}

function buildRelevanceLabels(t) {
  return {
    direct: t('sources:evidence.relevanceLabels.direct'),
    contextual: t('sources:evidence.relevanceLabels.contextual'),
    unrelated: t('sources:evidence.relevanceLabels.unrelated'),
    uncertain: t('sources:evidence.relevanceLabels.uncertain'),
    unclassified: t('sources:evidence.relevanceLabels.unclassified'),
  };
}

function buildClaimTabs(t, labels) {
  return [
    { key: 'all', label: t('sources:evidence.claimTabs.all') },
    { key: 'needs_review', label: t('sources:evidence.claimTabs.needsReview') },
    { key: 'supported', label: labels.supported, assessment: 'supported' },
    { key: 'contradicted', label: labels.contradicted, assessment: 'contradicted' },
    { key: 'mixed_evidence', label: t('sources:evidence.claimTabs.mixed'), assessment: 'mixed_evidence' },
    { key: 'insufficient_evidence', label: t('sources:evidence.claimTabs.insufficient'), assessment: 'insufficient_evidence' },
    { key: 'not_yet_verifiable', label: labels.not_yet_verifiable, assessment: 'not_yet_verifiable' },
    { key: 'assessment_unavailable', label: t('sources:evidence.claimTabs.unavailable'), assessment: 'assessment_unavailable' },
  ];
}

function buildMatrixStates(t) {
  return {
    supporting: { label: t('sources:evidence.matrixStates.supporting') },
    contradicting: { label: t('sources:evidence.matrixStates.contradicting') },
    contextual: { label: t('sources:evidence.matrixStates.contextual') },
    review: { label: t('sources:evidence.matrixStates.review') },
    missing: { label: t('common:misc.none') },
  };
}

function buildClaimTypeLabels(t) {
  return {
    factual_assertion: t('sources:evidence.claimType.factual_assertion'),
    attributed_statement: t('sources:evidence.claimType.attributed_statement'),
    forecast: t('sources:evidence.claimType.forecast'),
    opinion: t('sources:evidence.claimType.opinion'),
    causal_explanation: t('sources:evidence.claimType.causal_explanation'),
  };
}

function buildProvenanceStatusLabels(t) {
  return {
    unassessed: t('sources:evidence.provenanceStatus.unassessed'),
    verified: t('sources:evidence.provenanceStatus.verified'),
    rejected: t('sources:evidence.provenanceStatus.rejected'),
  };
}

function buildGenerationStatusLabels(t) {
  return {
    queued: t('sources:evidence.generationStatus.queued'),
    running: t('sources:evidence.generationStatus.running'),
    pending: t('sources:evidence.generationStatus.pending'),
    success: t('sources:evidence.generationStatus.success'),
    failed: t('sources:evidence.generationStatus.failed'),
  };
}

const MATRIX_PAGE_SIZE = 5;
const CLAIM_PAGE_SIZE = 5;

function MatrixStateIcon({ stateKey, size = 14 }) {
  if (stateKey === 'supporting') return <CheckCircle2 size={size} />;
  if (stateKey === 'contradicting') return <XCircle size={size} />;
  if (stateKey === 'contextual') return <Quote size={size} />;
  if (stateKey === 'review') return <AlertTriangle size={size} />;
  return <Minus size={size} />;
}

// Known real-world organization names kept as literal proper nouns
// regardless of locale (not translated - see CLAUDE.md's "don't touch
// canonical data"); only the "Unknown source" fallback below is UI text.
function shortSourceName(value) {
  const source = String(value || i18n.t('sources:evidence.detail.unknownSource'));
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
  return provenance.publisher || meta.source || i18n.t('sources:evidence.detail.unknownSource');
}

function matrixCellState(row, publisher, matrixStates) {
  const items = row.sources.filter((item) => item.publisher === publisher);
  const qualifiedItems = items.filter((item) => item.citation_valid && item.qualifies);
  const relationship = qualifiedItems.find((item) => item.relationship === 'contradicting')?.relationship
    || qualifiedItems.find((item) => item.relationship === 'supporting')?.relationship
    || qualifiedItems[0]?.relationship;
  const qualified = items.some((item) => item.citation_valid && item.qualifies);
  const stateKey = qualified && relationship ? relationship : items.length ? 'review' : 'missing';
  return { items, stateKey, state: matrixStates[stateKey] || matrixStates.missing };
}

// Module-level (not component-scoped) since these are called from plain
// helper functions above as well as from deep inside JSX below - both read
// the current i18next locale straight off the shared singleton rather than
// threading a `t`/`locale` prop through every call site. The component
// re-renders on a language change (useTranslation subscribes to it), so this
// still recomputes with the right locale every time it's actually read.
function formatDate(value) {
  if (!value) return i18n.t('sources:evidence.unknownDate');
  const formatted = formatDateIntl(value, i18n.language);
  return formatted || String(value);
}

function formatDateTime(value) {
  if (!value) return i18n.t('sources:evidence.unknownTime');
  const formatted = formatDateTimeIntl(value, i18n.language);
  return formatted || String(value);
}

function sourceMeta(item) {
  return item?.source_snapshot || {};
}

export default function EvidenceWorkspacePage({ projects = [] }) {
  const { t } = useTranslation(['sources', 'common']);
  const LABELS = buildLabels(t);
  const RELEVANCE_LABELS = buildRelevanceLabels(t);
  const CLAIM_TABS = buildClaimTabs(t, LABELS);
  const MATRIX_STATES = buildMatrixStates(t);
  const CLAIM_TYPE_LABELS = buildClaimTypeLabels(t);
  const PROVENANCE_STATUS_LABELS = buildProvenanceStatusLabels(t);
  const GENERATION_STATUS_LABELS = buildGenerationStatusLabels(t);
  const relevanceFallbackUnclassified = t('sources:evidence.detail.relevanceFallbackUnclassified');

  const { projectId } = useParams();
  const [search, setSearch] = useSearchParams();
  const { hasPermission } = useAuth();
  const canReview = hasPermission('projects.update');
  const canRetry = hasPermission('pipeline.run');
  const project = projects.find((item) => Number(item.id) === Number(projectId));
  const runId = search.get('run_id') || '';
  const generation = search.get('generation') || '';
  const topic = search.get('topic') || '';
  const searchText = search.get('search') || '';
  const assessmentFilter = search.get('assessment') || '';
  const typeFilter = search.get('claim_type') || '';
  const publisherFilter = search.get('publisher') || '';
  const reviewFilter = search.get('review_status') || '';
  const provenanceFilter = search.get('provenance_status') || '';
  const coverageFilter = search.get('coverage') || '';
  const relevanceFilter = search.get('relevance') || 'focused';
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
  const [scopeDraft, setScopeDraft] = useState(null);
  const [editingScope, setEditingScope] = useState(false);
  const [savingScope, setSavingScope] = useState(false);
  const [relevanceDecision, setRelevanceDecision] = useState('direct');
  const [relevanceReason, setRelevanceReason] = useState('');
  const [savingRelevance, setSavingRelevance] = useState(false);
  const [sourceReviewTarget, setSourceReviewTarget] = useState(null);
  const [sourceReviewDecision, setSourceReviewDecision] = useState('include');
  const [sourceReviewReason, setSourceReviewReason] = useState('');
  const [savingSourceReview, setSavingSourceReview] = useState(false);
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

  const load = async (signal, generationOverride = generation) => {
    setLoading(true); setError('');
    try {
      const result = await getEvidenceWorkspace(projectId, {
        run_id: runId, generation: generationOverride, topic, search: searchText, assessment: assessmentFilter,
        claim_type: typeFilter, publisher: publisherFilter, review_status: reviewFilter,
        provenance_status: provenanceFilter, coverage: coverageFilter,
        relevance: relevanceFilter,
        limit: view === 'matrix' ? MATRIX_PAGE_SIZE : CLAIM_PAGE_SIZE,
        offset: view === 'matrix' ? matrixPage * MATRIX_PAGE_SIZE : offset,
      }, signal);
      setData(result);
      if (!runId && result.selected_run_id) updateFilters({ run_id: result.selected_run_id });
    } catch (err) {
      if (err?.name !== 'AbortError') setError(err?.message || t('sources:evidence.errors.loadFailed'));
    } finally { setLoading(false); }
  };

  useEffect(() => {
    const controller = new AbortController();
    // load owns the request lifecycle and the abort signal prevents stale updates.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load(controller.signal);
    return () => controller.abort();
  }, [projectId, runId, generation, topic, searchText, assessmentFilter, typeFilter, publisherFilter, reviewFilter, provenanceFilter, coverageFilter, relevanceFilter, offset, view, matrixPage]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // This clears details that belong to the previous URL-scoped claim set.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected(null); setComparison(null); setProvenanceTarget(null); setMatrixDetail(null);
  }, [runId, generation, topic, assessmentFilter, typeFilter, publisherFilter, reviewFilter, provenanceFilter, coverageFilter, relevanceFilter]);

  useEffect(() => {
    if (!data?.scope || editingScope) return;
    // Keep the form aligned with the selected run's frozen scope.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setScopeDraft({ ...data.scope, keywords: (data.scope.keywords || []).join(', ') });
  }, [data?.scope, editingScope]);

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
      setRelevanceDecision(result.claim.effective_relevance === 'unclassified' ? 'uncertain' : (result.claim.effective_relevance || 'uncertain'));
      setRelevanceReason('');
    } catch (err) { setError(err?.message || t('sources:evidence.errors.openClaimFailed')); }
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
    } catch (err) { setError(err?.message || t('sources:evidence.errors.openSourceFailed')); }
    finally { setMatrixDetailLoading(false); }
  };

  const saveReview = async () => {
    if (!selected || !reason.trim()) return;
    setSaving(true);
    try {
      const result = await reviewEvidenceClaim(projectId, selected.id, { decision, reason });
      setSelected(result.claim); setReason(''); await load();
    } catch (err) { setError(err?.message || t('sources:evidence.errors.saveReviewFailed')); }
    finally { setSaving(false); }
  };

  const saveRelevanceReview = async () => {
    if (!selected || !relevanceReason.trim()) return;
    setSavingRelevance(true);
    try {
      const result = await reviewEvidenceRelevance(projectId, selected.id, { decision: relevanceDecision, reason: relevanceReason });
      setSelected(result.claim); setRelevanceReason(''); await load();
    } catch (err) { setError(err?.message || t('sources:evidence.errors.saveRelevanceFailed')); }
    finally { setSavingRelevance(false); }
  };

  const saveSourceReview = async () => {
    if (!sourceReviewTarget || !sourceReviewReason.trim() || !data?.selected_run_id) return;
    setSavingSourceReview(true); setError('');
    try {
      await reviewEvidenceArticleScreening(projectId, data.selected_run_id, sourceReviewTarget.article_id, {
        decision: sourceReviewDecision, reason: sourceReviewReason,
      });
      setSourceReviewTarget(null); setSourceReviewReason(''); await load();
    } catch (err) { setError(err?.message || t('sources:evidence.errors.saveSourceReviewFailed')); }
    finally { setSavingSourceReview(false); }
  };

  const saveScope = async () => {
    if (!data?.selected_run_id || !scopeDraft) return;
    setSavingScope(true); setError('');
    try {
      await updateEvidenceScope(projectId, data.selected_run_id, {
        ...scopeDraft,
        keywords: String(scopeDraft.keywords || '').split(',').map((item) => item.trim()).filter(Boolean),
      });
      setEditingScope(false); await load();
    } catch (err) { setError(err?.message || t('sources:evidence.errors.saveScopeFailed')); }
    finally { setSavingScope(false); }
  };

  const saveProvenanceReview = async () => {
    if (!provenanceTarget || !provenanceReason.trim()) return;
    try {
      await reviewEvidenceProvenance(projectId, provenanceTarget.article_id, { status: provenanceDecision, reason: provenanceReason });
      setProvenanceTarget(null); setProvenanceReason('');
      await openClaim(selected.id); await load();
    } catch (err) { setError(err?.message || t('sources:evidence.errors.provenanceReviewFailed')); }
  };

  const retry = async () => {
    if (!data?.selected_run_id) return;
    setRetrying(true);
    try {
      await retryEvidenceRun(projectId, data.selected_run_id);
      updateFilters({ generation: '' });
      await load(undefined, '');
      window.setTimeout(() => load(undefined, ''), 1200);
    }
    catch (err) { setError(err?.message || t('sources:evidence.errors.rebuildFailed')); }
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
    } catch (err) { setError(err?.message || t('sources:evidence.errors.compareFailed')); }
    finally { setComparing(false); }
  };

  const overview = data?.overview || {};
  const selectedRunRecord = (data?.runs || []).find(
    (run) => String(run.id) === String(data?.selected_run_id),
  );
  const selectedRunActive = ['queued', 'running'].includes(selectedRunRecord?.status);
  const selectedGeneration = data?.selected_generation_status;
  const selectedGenerationPublished = Boolean(data?.is_selected_generation_published);
  const evidenceButtonLabel = selectedRunRecord?.evidence_status
    ? t('sources:evidence.header.rebuildEvidence')
    : t('sources:evidence.header.buildEvidence');
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
  const matrixPagination = (position) => {
    const positionLabel = position === 'Top' ? t('sources:evidence.matrix.positionTop') : t('sources:evidence.matrix.positionBottom');
    return <nav className="evidence-matrix-pagination" aria-label={t('sources:evidence.matrix.paginationNavLabel', { position: positionLabel })}>
      <button type="button" aria-label={t('sources:evidence.matrix.previousPage')} disabled={matrixSafePage === 0 || loading} onClick={() => changeMatrixPage(matrixSafePage - 1)}><ChevronLeft size={15} className="rtl-mirror" /> {t('common:actions.previous')}</button>
      <span>{t('common:pagination.pageOfTotal', { page: matrixSafePage + 1, totalPages: matrixPageCount })}</span>
      <button type="button" aria-label={t('sources:evidence.matrix.nextPage')} disabled={matrixSafePage + 1 >= matrixPageCount || loading} onClick={() => changeMatrixPage(matrixSafePage + 1)}>{t('common:actions.next')} <ChevronRight size={15} className="rtl-mirror" /></button>
    </nav>;
  };
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
  const claimPagination = (position) => {
    const positionLabel = position === 'Top' ? t('sources:evidence.matrix.positionTop') : t('sources:evidence.matrix.positionBottom');
    return <nav className="evidence-claim-pagination" aria-label={t('sources:evidence.claims.paginationAriaLabel', { position: positionLabel })}>
      <button type="button" disabled={claimPage === 0 || loading} onClick={() => changeClaimPage(claimPage - 1)}><ChevronLeft size={15} className="rtl-mirror" /> {t('common:actions.previous')}</button>
      <span>{t('common:pagination.pageOfTotal', { page: claimPage + 1, totalPages: claimPageCount })}</span>
      <button type="button" disabled={claimPage + 1 >= claimPageCount || loading} onClick={() => changeClaimPage(claimPage + 1)}>{t('common:actions.next')} <ChevronRight size={15} className="rtl-mirror" /></button>
    </nav>;
  };

  return (
    <div className="admin-page-shell evidence-page">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker"><ShieldCheck size={14} /> {t('sources:evidence.header.kicker')}</div>
          <h1 className="admin-page-title" dir="auto">{project?.name || t('sources:evidence.header.titleFallback')}</h1>
          <p className="admin-page-subtitle">{t('sources:evidence.header.subtitle')}</p>
        </div>
        <div className="admin-page-toolbar">
          <Link className="btn-secondary" to={`/projects/${projectId}`}><ArrowLeft size={15} className="rtl-mirror" /> {t('sources:evidence.header.projectLink')}</Link>
          {canRetry && data?.selected_run_id ? <button className="btn-secondary" onClick={retry} disabled={retrying || selectedRunActive} title={selectedRunActive ? t('sources:evidence.header.waitTitle') : undefined}><RefreshCw size={15} className={retrying ? 'spin' : ''} /> {retrying ? t('sources:evidence.header.starting') : selectedRunActive ? t('sources:evidence.header.analysisRunning') : evidenceButtonLabel}</button> : null}
        </div>
      </div>

      <div className="evidence-scope-note">
        <ShieldCheck size={18} />
        <div><strong>{t('sources:evidence.scopeNote.title')}</strong><span>{t('sources:evidence.scopeNote.body')}</span></div>
      </div>

      {data?.requires_rebuild ? <p role="status" className="evidence-scope-note">{t('sources:evidence.requiresRebuild')}</p> : null}
      {data?.scope ? <section className="glass-card evidence-research-scope">
        <header><div><strong>{t('sources:evidence.scope.frozenTitle')}</strong><span>{data.scope.source === 'explicit_override' ? t('sources:evidence.scope.editedForRun') : t('sources:evidence.scope.capturedFromSettings')}</span></div>{canReview ? <button type="button" className="btn-secondary" onClick={() => setEditingScope((value) => !value)}>{editingScope ? t('common:actions.cancel') : t('sources:evidence.scope.editScope')}</button> : null}</header>
        {editingScope && scopeDraft ? <div className="evidence-scope-form">
          <label>{t('sources:evidence.scope.questionLabel')}<input value={scopeDraft.name || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, name: event.target.value })} /></label>
          <label>{t('sources:evidence.scope.descriptionLabel')}<textarea rows="2" value={scopeDraft.description || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, description: event.target.value })} /></label>
          <label>{t('sources:evidence.scope.locationLabel')}<input value={scopeDraft.location || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, location: event.target.value })} /></label>
          <label>{t('sources:evidence.scope.keywordsLabel')}<input value={scopeDraft.keywords || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, keywords: event.target.value })} placeholder={t('sources:evidence.scope.keywordsPlaceholder')} /></label>
          <label>{t('sources:evidence.scope.directRelevanceLabel')}<textarea rows="2" value={scopeDraft.direct_relevance || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, direct_relevance: event.target.value })} /></label>
          <label>{t('sources:evidence.scope.allowedContextLabel')}<textarea rows="2" value={scopeDraft.contextual_relevance || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, contextual_relevance: event.target.value })} /></label>
          <label>{t('sources:evidence.scope.exclusionsLabel')}<textarea rows="2" value={scopeDraft.exclusions || ''} onChange={(event) => setScopeDraft({ ...scopeDraft, exclusions: event.target.value })} /></label>
          <div><button type="button" className="btn-primary" onClick={saveScope} disabled={savingScope}>{savingScope ? t('common:status.saving') : t('sources:evidence.scope.saveScope')}</button><span>{t('sources:evidence.scope.saveHint')}</span></div>
        </div> : <div className="evidence-scope-summary"><strong dir="auto">{data.scope.name}</strong>{data.scope.description ? <p dir="auto">{data.scope.description}</p> : null}<dl><div><dt>{t('sources:evidence.scope.geography')}</dt><dd>{data.scope.location || t('sources:evidence.scope.noGeoLimit')}</dd></div><div><dt>{t('sources:evidence.scope.keywordsDt')}</dt><dd>{(data.scope.keywords || []).join(', ') || t('sources:evidence.scope.noKeywordGuidance')}</dd></div><div><dt>{t('sources:evidence.scope.relevantContext')}</dt><dd>{data.scope.contextual_relevance}</dd></div><div><dt>{t('sources:evidence.scope.exclude')}</dt><dd>{data.scope.exclusions}</dd></div></dl></div>}
      </section> : null}

      <div className="glass-card evidence-filters">
        <label>{t('sources:evidence.filters.analysisRun')}<select value={data?.selected_run_id || runId} onChange={(event) => updateFilters({ run_id: event.target.value, generation: '', topic: '' })}>
          {(data?.runs || []).map((run) => <option key={run.id} value={run.id}>{t('sources:evidence.filters.runOption', {
            number: run.run_number,
            date: formatDateTime(run.created_at),
            claims: t('sources:evidence.count.claims', { count: run.claim_count }),
            documents: t('sources:evidence.count.documents', { count: run.document_count }),
          })}</option>)}
        </select></label>
        <label>{t('sources:evidence.filters.topic')}<select value={topic} onChange={(event) => updateFilters({ topic: event.target.value })}>
          <option value="">{t('sources:evidence.filters.allTopics')}</option>{(data?.topics || []).map((item) => <option key={item.topic} value={item.topic} dir="auto">{item.topic} ({item.count})</option>)}
        </select></label>
        <label>{t('common:actions.search')}<input value={searchText} onChange={(event) => updateFilters({ search: event.target.value })} placeholder={t('sources:evidence.filters.searchPlaceholder')} /></label>
        <label>{t('sources:evidence.filters.assessment')}<select value={assessmentFilter} onChange={(event) => updateFilters({ assessment: event.target.value })}>
          <option value="">{t('sources:evidence.filters.allAssessments')}</option>{Object.entries(LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <button type="button" className="evidence-more-filters" onClick={() => setShowAdvanced((current) => !current)}><Filter size={14} /> {showAdvanced ? t('sources:evidence.filters.hideFilters') : t('sources:evidence.filters.moreFilters')} <ChevronDown size={14} className={showAdvanced ? 'open' : ''} /></button>
        {showAdvanced ? <div className="evidence-advanced-filters"><label>{t('sources:evidence.filters.claimType')}<select value={typeFilter} onChange={(event) => updateFilters({ claim_type: event.target.value })}>
          <option value="">{t('sources:evidence.filters.allTypes')}</option>{['factual_assertion', 'attributed_statement', 'forecast', 'opinion', 'causal_explanation'].map((value) => <option key={value} value={value}>{CLAIM_TYPE_LABELS[value]}</option>)}
        </select></label>
        <label>{t('sources:evidence.filters.publisher')}<select value={publisherFilter} onChange={(event) => updateFilters({ publisher: event.target.value })}>
          <option value="">{t('sources:evidence.filters.allPublishers')}</option>{(data?.filter_options?.publishers || []).map((value) => <option key={value} value={value} dir="auto">{value}</option>)}
        </select></label>
        <label>{t('sources:evidence.filters.analystReview')}<select value={reviewFilter} onChange={(event) => updateFilters({ review_status: event.target.value })}>
          <option value="">{t('sources:evidence.filters.anyStatus')}</option><option value="needs_attention">{t('sources:evidence.filters.needsAttention')}</option><option value="unreviewed">{t('sources:evidence.filters.notReviewedByAnalyst')}</option><option value="reviewed">{t('sources:evidence.filters.reviewed')}</option>
        </select></label>
        <label>{t('sources:evidence.filters.originReview')}<select value={provenanceFilter} onChange={(event) => updateFilters({ provenance_status: event.target.value })}>
          <option value="">{t('sources:evidence.filters.anyStatus')}</option><option value="unassessed">{t('sources:evidence.provenanceFilter.unassessed')}</option><option value="verified">{t('sources:evidence.provenanceFilter.verified')}</option><option value="rejected">{t('sources:evidence.provenanceFilter.rejected')}</option>
        </select></label><label>{t('sources:evidence.filters.projectRelevance')}<select value={relevanceFilter} onChange={(event) => updateFilters({ relevance: event.target.value })}>
          <option value="focused">{t('sources:evidence.filters.relevantCurrent')}</option><option value="direct">{RELEVANCE_LABELS.direct}</option><option value="contextual">{RELEVANCE_LABELS.contextual}</option><option value="uncertain">{RELEVANCE_LABELS.uncertain}</option><option value="unrelated">{t('sources:evidence.filters.excludedAsUnrelated')}</option><option value="unclassified">{RELEVANCE_LABELS.unclassified}</option><option value="all">{t('sources:evidence.filters.allCandidates')}</option>
        </select></label></div> : null}
      </div>

      {(data?.generation_tabs || []).length ? <section className="glass-card evidence-generation-panel">
        <header><div><strong>{t('sources:evidence.generationTabs.title')}</strong><span>{t('sources:evidence.generationTabs.subtitle')}</span></div></header>
        <div className="evidence-generation-tabs" role="tablist" aria-label={t('sources:evidence.generationTabs.ariaLabel')}>
          {data.generation_tabs.map((item) => {
            const active = Number(data.selected_generation) === Number(item.generation);
            const relevant = Number(item.direct_count || 0) + Number(item.contextual_count || 0);
            return <button type="button" role="tab" aria-selected={active} className={active ? 'active' : ''} key={item.generation} onClick={() => updateFilters({ generation: item.generation })}>
              <span className={`evidence-generation-status ${item.status}`}>{GENERATION_STATUS_LABELS[item.status] || item.status}</span>
              <strong>{item.legacy ? t('sources:evidence.generationTabs.legacyEvidence') : t('sources:evidence.generationTabs.evidenceNumber', { number: item.generation })}</strong>
              <small>{formatDateTime(item.started_at || item.created_at)}{item.status === 'success' && !item.legacy ? ` · ${t('sources:evidence.count.relevantClaims', { count: relevant })} · ${t('sources:evidence.count.sourcesExcluded', { count: item.excluded_article_count || 0 })}` : ''}</small>
              {Number(data.active_generation) === Number(item.generation) ? <b>{t('sources:evidence.generationTabs.published')}</b> : null}
            </button>;
          })}
        </div>
      </section> : null}

      {error ? <div className="evidence-error" dir="auto">{error}</div> : null}
      {selectedRunRecord && !selectedRunRecord.evidence_status
        ? <div className="glass-card evidence-empty"><FileSearch size={22} /><strong>{t('sources:evidence.notBuilt.title')}</strong><span>{t('sources:evidence.notBuilt.body')}</span></div>
        : null}
      {selectedGeneration?.status === 'failed'
        ? <div className="evidence-error">{t('sources:evidence.failed.prefix', { error: selectedGeneration.error || t('sources:evidence.failed.unknownError') })}</div>
        : null}
      {selectedGeneration?.status === 'failed' && ((data?.excluded_articles || []).length || (data?.candidate_review || []).length)
        ? <details className="glass-card evidence-quality-review"><summary><span><strong>{t('sources:evidence.reviewFailedAttempt.summary')}</strong><small>{t('sources:evidence.reviewFailedAttempt.excludedSources', { count: data.excluded_articles?.length || 0 })} · {t('sources:evidence.reviewFailedAttempt.unsupportedCandidatesShown', { count: data.candidate_review?.length || 0 })}</small></span><ChevronDown size={17} /></summary><p>{t('sources:evidence.reviewFailedAttempt.intro')}</p><div className="evidence-quality-list">{(data.excluded_articles || []).map((item) => <article key={item.article_id}><div><strong dir="auto">{item.title || item.source || t('sources:evidence.articleFallback', { id: item.article_id })}</strong><span>{item.quality_code.replaceAll('_', ' ')}</span><p dir="auto">{item.reason}</p></div></article>)}{(data.candidate_review || []).map((item, index) => <article key={`${item.article_id}-${index}`}><div><strong dir="auto">{item.claim_text}</strong><span>{item.status.replaceAll('_', ' ')} · {item.source_title || t('sources:evidence.articleFallback', { id: item.article_id })}</span><p dir="auto">{item.reason}</p></div></article>)}</div></details>
        : null}
      {selectedGeneration?.status === 'running' || selectedGeneration?.status === 'pending'
        ? <div className="glass-card evidence-generation-progress"><RefreshCw size={18} className="spin" /><div><strong>{t('sources:evidence.running.title')}</strong><span>{selectedGeneration.candidate_count ? t('sources:evidence.running.progress', { classified: selectedGeneration.classified_count || 0, total: selectedGeneration.candidate_count }) : t('sources:evidence.running.preparing')}</span></div></div>
        : null}
      {loading && !data ? <div className="glass-card evidence-empty">{t('sources:evidence.loadingEvidence')}</div> : null}
      {!loading && !(data?.runs || []).length ? <div className="glass-card evidence-empty"><FileSearch size={24} /><strong>{t('sources:evidence.noRuns.title')}</strong><span>{t('sources:evidence.noRuns.body')}</span></div> : null}

      {(data?.runs || []).length ? <>
        {selectedGeneration?.status === 'success' ? <>
        <div className="evidence-relevance-summary"><span><strong>{(data.relevance_counts?.direct || 0) + (data.relevance_counts?.contextual || 0)}</strong> {t('sources:evidence.relevanceSummary.relevant')}</span><span><strong>{data.relevance_counts?.uncertain || 0}</strong> {t('sources:evidence.relevanceSummary.uncertain')}</span><span><strong>{data.relevance_counts?.unrelated || 0}</strong> {t('sources:evidence.relevanceSummary.excluded')}</span><span><strong>{data.relevance_counts?.unclassified || 0}</strong> {t('sources:evidence.relevanceSummary.legacy')}</span></div>
        <div className="evidence-overview">
          <div className="glass-card evidence-stat"><span>{t('sources:evidence.overview.totalClaims')}</span><strong>{overview.total_claims || 0}</strong><small>{t('sources:evidence.overview.extractedFromRun')}</small></div>
          <div className="glass-card evidence-stat positive"><span>{t('sources:evidence.overview.corroborated')}</span><strong>{overview.corroborated_claims || 0}</strong><small>{t('sources:evidence.overview.twoOrMoreOrigins')}</small></div>
          <div className="glass-card evidence-stat"><span>{t('sources:evidence.overview.singleSource')}</span><strong>{overview.single_source_claims || 0}</strong><small>{t('sources:evidence.overview.usefulNotConfirmed')}</small></div>
          <div className={`glass-card evidence-stat ${(overview.needs_review_claims || 0) ? 'attention' : ''}`}><span>{t('sources:evidence.overview.needsReview')}</span><strong>{overview.needs_review_claims || 0}</strong><small>{t('sources:evidence.overview.quotationNeedsAttention')}</small></div>
          {assessmentCards.map(([key, value]) => <button type="button" className={`glass-card ${assessmentFilter === key ? 'active' : ''}`} key={key} onClick={() => updateFilters({ assessment: assessmentFilter === key ? '' : key })}><span>{LABELS[key] || key}</span><strong>{value}</strong></button>)}
        </div>

        <details className="glass-card evidence-quality-review">
          <summary><span><strong>{t('sources:evidence.quality.title')}</strong><small>{t('sources:evidence.count.sourcesExcluded', { count: selectedGeneration?.excluded_article_count || 0 })} · {t('sources:evidence.quality.unsupportedCandidates', { count: selectedGeneration?.unsupported_candidate_count || 0 })} · {t('sources:evidence.quality.duplicateRecords', { count: selectedGeneration?.duplicate_article_count || 0 })}</small></span><ChevronDown size={17} /></summary>
          <p>{t('sources:evidence.quality.body')}</p>
          {(data.quality_summary || []).length ? <div className="evidence-quality-counts">{data.quality_summary.map((item) => <span key={`${item.decision}-${item.quality_code}`}><strong>{item.count}</strong> {item.decision.replaceAll('_', ' ')} · {item.quality_code.replaceAll('_', ' ')}</span>)}</div> : null}
          {(data.excluded_articles || []).length ? <div className="evidence-quality-list"><h4>{t('sources:evidence.quality.excludedOrPendingTitle')}</h4>{data.excluded_articles.map((item) => <article key={item.article_id}>
            <div><strong dir="auto">{item.title || item.source || t('sources:evidence.articleFallback', { id: item.article_id })}</strong><span>{item.decision.replaceAll('_', ' ')} · {item.quality_code.replaceAll('_', ' ')} · {item.decision_method.replaceAll('_', ' ')}</span><p dir="auto">{item.reason}</p>{item.best_passage ? <blockquote dir="auto">{item.best_passage}</blockquote> : null}{item.review_decision ? <small>{t('sources:evidence.quality.latestReview', { decision: item.review_decision, reason: item.review_reason })}</small> : null}</div>
            {canReview ? <button type="button" className="btn-secondary" onClick={() => { setSourceReviewTarget(item); setSourceReviewDecision('include'); setSourceReviewReason(''); }}>{t('sources:evidence.quality.review')}</button> : null}
            {sourceReviewTarget?.article_id === item.article_id ? <div className="evidence-quality-form"><select value={sourceReviewDecision} onChange={(event) => setSourceReviewDecision(event.target.value)}><option value="include">{t('sources:evidence.quality.includeNextRebuild')}</option><option value="exclude">{t('sources:evidence.quality.keepExcluded')}</option><option value="needs_review">{t('sources:evidence.quality.needsReviewOption')}</option></select><textarea value={sourceReviewReason} onChange={(event) => setSourceReviewReason(event.target.value)} placeholder={t('sources:evidence.quality.requiredReasonPlaceholder')} rows={2} /><button type="button" className="btn-primary" disabled={savingSourceReview || !sourceReviewReason.trim()} onClick={saveSourceReview}>{savingSourceReview ? t('common:status.saving') : t('sources:evidence.actions.saveReview')}</button></div> : null}
          </article>)}</div> : null}
          {(data.candidate_review || []).length ? <div className="evidence-quality-list"><h4>{t('sources:evidence.quality.unsupportedCandidatesTitle')}</h4>{data.candidate_review.map((item, index) => <article key={`${item.article_id}-${index}`}><div><strong dir="auto">{item.claim_text}</strong><span>{item.status.replaceAll('_', ' ')} · {item.topic} · {item.source_title || t('sources:evidence.articleFallback', { id: item.article_id })}</span><p dir="auto">{item.reason}</p>{item.passage ? <blockquote dir="auto">{item.passage}</blockquote> : null}</div></article>)}</div> : null}
        </details>

        {(data?.runs || []).length > 1 ? <div className="glass-card evidence-comparison">
          <div><strong>{t('sources:evidence.comparison.title')}</strong><span>{t('sources:evidence.comparison.subtitle')}</span></div>
          <select value={compareBase || defaultCompareBase} onChange={(event) => { setCompareBase(event.target.value); setComparison(null); }}>
            {(data?.runs || []).filter((run) => String(run.id) !== String(data.selected_run_id)).map((run) => <option key={run.id} value={run.id}>{formatDate(run.created_at)} · {t('sources:evidence.count.claims', { count: run.claim_count })}</option>)}
          </select>
          <button className="btn-secondary" onClick={runComparison} disabled={comparing || !(compareBase || defaultCompareBase)}>{comparing ? t('sources:evidence.comparison.comparing') : t('sources:evidence.comparison.compare')}</button>
          {comparison ? <div className="evidence-change-list">
            {!comparison.changes.length ? <span>{t('sources:evidence.comparison.noChanges')}</span> : comparison.changes.map((change) => <button type="button" key={change.fingerprint} onClick={() => change.target?.id && openClaim(change.target.id)}>
              <span className="panel-chip">{change.change_type.replaceAll('_', ' ')}</span>
              <strong dir="auto">{change.claim_text}</strong>
              <small>{t('sources:evidence.comparison.transition', {
                from: change.base?.assessment ? LABELS[change.base.assessment] : t('sources:evidence.comparison.notPresent'),
                to: change.target?.assessment ? LABELS[change.target.assessment] : t('sources:evidence.comparison.notPresent'),
              })}</small>
              <p dir="auto">{change.cause}</p>
            </button>)}
          </div> : null}
        </div> : null}

        <div className="evidence-view-switch" role="tablist" aria-label={t('sources:evidence.viewSwitch.ariaLabel')}>
          <button type="button" role="tab" aria-selected={view === 'review'} className={view === 'review' ? 'active' : ''} onClick={() => { if (coverageFilter) updateFilters({ coverage: '' }); setView('review'); }}><Quote size={15} /> {t('sources:evidence.viewSwitch.reviewClaims')}</button>
          <button type="button" role="tab" aria-selected={view === 'matrix'} className={view === 'matrix' ? 'active' : ''} onClick={() => { setMatrixPage(0); setView('matrix'); }}><BarChart3 size={15} /> {t('sources:evidence.viewSwitch.compareSources')}</button>
        </div>

        {view === 'matrix' ? <div className={`glass-card evidence-matrix-card ${matrixDetail ? 'has-detail' : ''}`}>
          <div className="evidence-matrix-heading">
            <div><div className="evidence-matrix-title"><strong>{t('sources:evidence.matrix.title')}</strong><span className="panel-chip">{t('sources:perPageOption', { count: MATRIX_PAGE_SIZE })}</span><span className="panel-chip muted">{t('sources:evidence.matrix.onThisPage', { count: activeMatrixPublishers.length })}</span>{loading ? <span className="panel-chip loading">{t('sources:evidence.matrix.updating')}</span> : null}</div><span>{t('sources:evidence.matrix.subtitle')}</span></div>
            <div className="evidence-matrix-legend">{Object.entries(MATRIX_STATES).map(([key, state]) => <span className={key} key={key}><b><MatrixStateIcon stateKey={key} size={13} /></b>{state.label}</span>)}</div>
          </div>
          <div className="evidence-matrix-controls">
            <div className="evidence-matrix-quick-filters" aria-label={t('sources:evidence.matrix.quickFiltersAriaLabel')}>
              {[['all', t('sources:evidence.claimTabs.all')], ['supported', LABELS.supported], ['conflicting', t('sources:evidence.matrix.quickFilters.conflicting')], ['needs_review', t('sources:evidence.claimTabs.needsReview')], ['single_source', t('sources:evidence.matrix.quickFilters.singleSource')]].map(([key, label]) => <button type="button" key={key} aria-pressed={matrixQuickFilter === key} className={matrixQuickFilter === key ? 'active' : ''} onClick={() => setMatrixQuickFilter(key)}>{label}</button>)}
            </div>
            <div className="evidence-source-toggle" aria-label={t('sources:evidence.matrix.sourceColumnsAriaLabel')}><button type="button" className={matrixSourceMode === 'active' ? 'active' : ''} aria-pressed={matrixSourceMode === 'active'} onClick={() => setMatrixSourceMode('active')}>{t('sources:evidence.matrix.sourceToggle.onPage')}</button><button type="button" className={matrixSourceMode === 'all' ? 'active' : ''} aria-pressed={matrixSourceMode === 'all'} onClick={() => setMatrixSourceMode('all')}>{t('sources:evidence.matrix.sourceToggle.allSources')}</button></div>
          </div>
          <div className="evidence-matrix-truth-note"><ShieldCheck size={15} /><span><strong>{t('sources:evidence.matrix.truthNoteStrong')}</strong> {t('sources:evidence.matrix.truthNoteText')}</span></div>
          {matrix.rows.length && visibleMatrixPublishers.length ? <>
            <div className="evidence-matrix-topline"><span>{t('sources:evidence.matrix.showingRange', { count: matrixTotal, first: matrixFirst, last: matrixLast, total: matrixTotal })}{matrixSourceMode === 'active' && hiddenMatrixPublishers ? t('sources:evidence.matrix.hiddenSources', { count: hiddenMatrixPublishers }) : ''}</span>{matrixPagination('Top')}</div>
            <div className="evidence-matrix-scroll"><table className="evidence-matrix"><thead><tr><th><span>{t('sources:evidence.matrix.claimHeader')}</span><small>{t('sources:evidence.matrix.inViewCount', { count: matrixTotal })}</small></th>{visibleMatrixPublishers.map((publisher) => <th key={publisher} title={publisher}><span dir="auto">{shortSourceName(publisher)}</span><small>{matrixCoverage[publisher] ? t('sources:evidence.matrix.qualifiedCount', { count: matrixCoverage[publisher] }) : t('sources:evidence.matrix.noQualifyingPassage')}</small></th>)}</tr></thead><tbody>
              {matrix.rows.map((row, rowIndex) => <tr key={row.claim_id}><th><button type="button" onClick={() => { openClaim(row.claim_id); setView('review'); }}><span className="evidence-matrix-claim-number">{matrixFirst + rowIndex}</span><span className={`evidence-status ${row.assessment}`}>{LABELS[row.assessment] || row.assessment}</span><strong dir="auto">{row.claim_text}</strong><small>{row.topic}</small></button></th>{visibleMatrixPublishers.map((publisher) => {
                const { items, stateKey, state } = matrixCellState(row, publisher, MATRIX_STATES);
                return <td key={publisher}><button type="button" disabled={!items.length} onClick={() => openMatrixDetail(row, publisher)} className={`evidence-matrix-cell ${stateKey}`} aria-label={`${publisher}: ${state.label}${items.length ? t('sources:evidence.matrix.openEvidenceSuffix') : ''}`} title={`${publisher}: ${state.label}`}><MatrixStateIcon stateKey={stateKey} /><span>{state.label}</span></button></td>;
              })}</tr>)}
            </tbody></table></div>
            <div className="evidence-matrix-mobile">{matrix.rows.map((row, rowIndex) => <article key={row.claim_id} className="evidence-matrix-mobile-card"><button type="button" className="evidence-matrix-mobile-claim" onClick={() => { openClaim(row.claim_id); setView('review'); }}><span className="evidence-matrix-claim-number">{matrixFirst + rowIndex}</span><span className={`evidence-status ${row.assessment}`}>{LABELS[row.assessment] || row.assessment}</span><strong dir="auto">{row.claim_text}</strong><small>{row.topic}</small></button><div>{activeMatrixPublishers.map((publisher) => {
              const { items, stateKey, state } = matrixCellState(row, publisher, MATRIX_STATES);
              if (!items.length) return null;
              return <button type="button" key={publisher} className={`evidence-matrix-mobile-source ${stateKey}`} onClick={() => openMatrixDetail(row, publisher)}><span title={publisher} dir="auto">{shortSourceName(publisher)}</span><b><MatrixStateIcon stateKey={stateKey} /> {state.label}</b></button>;
            })}</div></article>)}</div>
            <div className="evidence-matrix-footer"><span>{t('sources:evidence.matrix.showingRange', { count: matrixTotal, first: matrixFirst, last: matrixLast, total: matrixTotal })}</span>{matrixPagination('Bottom')}</div>
          </> : <div className="evidence-empty"><FileSearch size={22} /><span>{t('sources:evidence.matrix.noMatch')}</span></div>}
          {matrixDetail ? <aside className="evidence-matrix-detail" aria-label={t('sources:evidence.matrix.detailAriaLabel')}>
            <header><div><span>{t('sources:evidence.matrix.detailHeading')}</span><strong title={matrixDetail.publisher} dir="auto">{shortSourceName(matrixDetail.publisher)}</strong></div><button type="button" aria-label={t('sources:evidence.matrix.closeDetailAriaLabel')} onClick={() => setMatrixDetail(null)}><PanelRightClose size={18} /></button></header>
            <div className="evidence-matrix-detail-claim"><span className={`evidence-status ${matrixDetail.claim.assessment}`}>{LABELS[matrixDetail.claim.assessment] || matrixDetail.claim.assessment}</span><strong dir="auto">{matrixDetail.claim.claim_text}</strong></div>
            {matrixDetailLoading ? <div className="evidence-empty">{t('sources:evidence.matrix.loadingPassages')}</div> : <div className="evidence-matrix-detail-items">{matrixDetail.evidence.map((item) => {
              const meta = sourceMeta(item); const provenance = item.current_provenance || meta.provenance || {}; const stateKey = item.citation_valid && item.qualifies ? item.relationship : 'review';
              return <article key={item.id}><div><span className={`evidence-matrix-cell ${stateKey}`}><MatrixStateIcon stateKey={stateKey} /><span>{MATRIX_STATES[stateKey]?.label || t('sources:evidence.matrixStates.review')}</span></span>{!item.qualifies ? <span className="panel-chip warning">{t('sources:evidence.detail.doesNotQualify')}</span> : null}</div><blockquote dir="auto">{item.passage}</blockquote><dl><div><dt>{t('sources:evidence.matrix.dtPublisher')}</dt><dd dir="auto">{provenance.publisher || meta.source || matrixDetail.publisher}</dd></div><div><dt>{t('sources:evidence.matrix.dtPublished')}</dt><dd>{formatDate(meta.published_at)}</dd></div><div><dt>{t('sources:evidence.matrix.dtLocator')}</dt><dd>{item.passage_locator || t('sources:evidence.detail.unavailable')}</dd></div></dl>{meta.qualification_reason ? <p className={`evidence-qualification ${item.qualifies ? 'qualified' : 'unqualified'}`} dir="auto">{meta.qualification_reason}</p> : null}{(provenance.original_url || meta.url)?.startsWith('http') ? <a href={provenance.original_url || meta.url} target="_blank" rel="noreferrer">{t('sources:evidence.detail.openSource')} <ExternalLink size={12} /></a> : null}</article>;
            })}{!matrixDetail.evidence.length ? <div className="evidence-empty">{t('sources:evidence.matrix.noPassageAvailable')}</div> : null}</div>}
            <button type="button" className="btn-primary evidence-matrix-open-review" onClick={() => { setSelected(matrixDetail.claim); setMatrixDetail(null); setView('review'); }}>{t('sources:evidence.matrix.openFullReview')}</button>
          </aside> : null}
        </div> : <div className="evidence-layout">
          <div className="glass-card evidence-claims">
            <div className="evidence-claims-heading"><div><strong>{t('sources:evidence.claims.title')}</strong><span className="panel-chip">{claimTotal}</span></div><small>{t('sources:evidence.claims.subtitle')}</small></div>
            <div className="evidence-claim-tabs" role="tablist" aria-label={t('sources:evidence.claims.tabsAriaLabel')}>
              {CLAIM_TABS.map((tab) => <button type="button" role="tab" aria-selected={selectedClaimTab === tab.key} className={selectedClaimTab === tab.key ? 'active' : ''} key={tab.key} onClick={() => setClaimTab(tab)}><span>{tab.label}</span><b>{claimTabCount(tab)}</b></button>)}
            </div>
            <div className="evidence-claim-page-summary"><span>{t('sources:evidence.claims.showingRange', { first: claimFirst, last: claimLast, total: claimTotal })}</span>{claimPagination('Top')}</div>
            {(data?.claims || []).map((claim) => {
              const effective = claim.review_decision || claim.assessment;
              return <button type="button" className={`evidence-claim ${selected?.id === claim.id ? 'active' : ''}`} key={claim.id} onClick={() => openClaim(claim.id)}>
                <div><span className={`evidence-status ${effective}`}>{LABELS[effective] || effective}</span><span className={`evidence-relevance ${claim.effective_relevance || claim.relevance}`}>{RELEVANCE_LABELS[claim.effective_relevance || claim.relevance] || relevanceFallbackUnclassified}</span><span className="panel-chip muted">{claim.topic}</span>{claim.needs_review ? <span className="panel-chip warning">{t('sources:evidence.claimTabs.needsReview')}</span> : null}</div>
                <strong dir="auto">{claim.claim_text}</strong>
                <small>
                  {t('sources:evidence.claims.originsCount', { count: claim.distinct_origins })} · {t('sources:evidence.claims.supportingCount', { count: claim.supporting_count })} · {t('sources:evidence.claims.conflictingCount', { count: claim.contradicting_count })}{claim.review_count ? t('sources:evidence.claims.reviewedSuffix') : ''}
                </small>
              </button>;
            })}
            {!(data?.claims || []).length ? <div className="evidence-empty">{t('sources:evidence.claims.noMatch')}</div> : null}
            <div className="evidence-claim-page-summary bottom"><span>{t('sources:evidence.claims.showingRange', { first: claimFirst, last: claimLast, total: claimTotal })}</span>{claimPagination('Bottom')}</div>
          </div>

          <div className="glass-card evidence-detail">
            {!selected ? <div className="evidence-empty"><FileSearch size={22} /><span>{t('sources:evidence.detail.selectPrompt')}</span></div> : <>
              <div><span className={`evidence-status ${selected.assessment}`}>{t('sources:evidence.detail.automated', { label: LABELS[selected.assessment] })}</span>{selected.reviews?.[0] ? <span className={`evidence-status ${selected.reviews[0].decision}`}>{t('sources:evidence.detail.analyst', { label: LABELS[selected.reviews[0].decision] })}</span> : null}<span className={`evidence-relevance ${selected.effective_relevance || selected.relevance}`}>{RELEVANCE_LABELS[selected.effective_relevance || selected.relevance] || relevanceFallbackUnclassified}</span><span className="panel-chip muted">{CLAIM_TYPE_LABELS[selected.claim_type] || selected.claim_type?.replaceAll('_', ' ')}</span></div>
              <h2 dir="auto">{selected.claim_text}</h2>
              <div className="evidence-relevance-reason"><strong>{t('sources:evidence.detail.whyMatches')}</strong><p dir="auto">{selected.relevance_reviews?.[0]?.reason || selected.relevance_explanation || t('sources:evidence.detail.legacyNotClassified')}</p></div>
              <p dir="auto">{selected.explanation}</p><p className="evidence-limit" dir="auto">{selected.limitations}</p>
              <div className="evidence-method"><span>{t('sources:evidence.detail.assessmentMethod', { value: selected.rules_version || t('common:misc.unknown') })}</span><span>{t('sources:evidence.detail.independentOrigins', { count: selected.independent_origin_count || 0 })}</span><span>{t('sources:evidence.detail.quotationsChecked', { count: selected.citation_checked_count || 0 })}</span>{selected.time_scope ? <span>{t('sources:evidence.detail.timeScope', { value: selected.time_scope })}</span> : null}{selected.quantities?.length ? <span>{t('sources:evidence.detail.quantities', { value: selected.quantities.join(', ') })}</span> : null}</div>
              <h3>{t('sources:evidence.detail.evidencePassages')}</h3>
              <div className="evidence-items">{(selected.evidence || []).map((item) => {
                const meta = sourceMeta(item); const provenance = item.current_provenance || meta.provenance || {};
                return <article key={item.id} className={`evidence-item ${item.relationship}`}>
                  <div><span className={`evidence-status ${item.relationship}`}>{MATRIX_STATES[item.relationship]?.label || item.relationship}</span>{item.citation_valid ? <span title={t('sources:evidence.detail.exactQuotationTitle')}><CheckCircle2 size={14} /> {t('sources:evidence.detail.exactQuotation')}</span> : <span title={t('sources:evidence.detail.quotationUnavailableTitle')}><XCircle size={14} /> {t('sources:evidence.detail.quotationUnavailable')}</span>}{!item.qualifies ? <span className="panel-chip warning">{t('sources:evidence.detail.doesNotQualify')}</span> : null}</div>
                  <blockquote dir="auto">{item.passage}</blockquote>
                  <div className="evidence-source"><strong dir="auto">{provenance.publisher || meta.source || t('sources:evidence.detail.unknownSource')}</strong><span>{t('sources:evidence.detail.published', { date: formatDate(meta.published_at) })}</span><span>{t('sources:evidence.detail.locator', { value: item.passage_locator || t('sources:evidence.detail.unavailable') })}</span><span>{t('sources:evidence.detail.contentType', { value: item.quote_source || provenance.source_type || t('common:misc.unknown') })}</span><span>{t('sources:evidence.detail.analysis', { value: meta.analysis_source === 'run' ? t('sources:evidence.detail.producedInRun') : t('sources:evidence.detail.reusedFrozen') })}</span><span>{t('sources:evidence.detail.originReviewLabel', { value: PROVENANCE_STATUS_LABELS[item.provenance_review?.status || provenance.verification_status] || item.provenance_review?.status || provenance.verification_status || t('sources:evidence.provenanceStatus.unassessed') })}</span>{Number.isFinite(Number(meta.passage_match_score)) ? <span>{t('sources:evidence.detail.passageMatch', { percent: formatPercent(meta.passage_match_score, i18n.language) })}</span> : null}{item.provenance_review ? <span dir="auto">{item.provenance_review.reviewer_name}: {item.provenance_review.reason}</span> : null}</div>
                  {meta.qualification_reason ? <p className={`evidence-qualification ${item.qualifies ? 'qualified' : 'unqualified'}`} dir="auto">{meta.qualification_reason}</p> : null}
                  <div className="evidence-item-actions">{(provenance.original_url || meta.url)?.startsWith('http') ? <a href={provenance.original_url || meta.url} target="_blank" rel="noreferrer">{t('sources:evidence.detail.openSource')} <ExternalLink size={12} /></a> : <span>{t('sources:evidence.detail.storedArticle', { id: item.article_id })}</span>}{canReview && selectedGenerationPublished ? <button onClick={() => { setProvenanceTarget(item); setProvenanceDecision('verified'); setProvenanceReason(''); }}>{t('sources:evidence.detail.reviewOrigin')}</button> : null}</div>
                  {provenanceTarget?.id === item.id ? <div className="evidence-provenance-form"><label>{t('sources:evidence.provenanceForm.originDecision')}<select value={provenanceDecision} onChange={(event) => setProvenanceDecision(event.target.value)}><option value="verified">{t('sources:evidence.provenanceFilter.verified')}</option><option value="rejected">{t('sources:evidence.provenanceFilter.rejected')}</option><option value="unassessed">{t('sources:evidence.provenanceForm.returnToUnassessed')}</option></select></label><label>{t('sources:reasonLabel')}<textarea rows="2" value={provenanceReason} onChange={(event) => setProvenanceReason(event.target.value)} placeholder={t('sources:evidence.provenanceForm.reasonPlaceholder')} /></label><div><button className="btn-primary" onClick={saveProvenanceReview} disabled={!provenanceReason.trim()}>{t('sources:evidence.provenanceForm.saveOriginReview')}</button><button className="btn-secondary" onClick={() => setProvenanceTarget(null)}>{t('common:actions.cancel')}</button></div></div> : null}
                </article>;
              })}</div>
              {canReview && selectedGenerationPublished ? <div className="evidence-review"><h3>{t('sources:evidence.detail.analystReviewTitle')}</h3><select value={decision} onChange={(event) => setDecision(event.target.value)}>{Object.entries(LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t('sources:evidence.detail.explainEvidencePlaceholder')}/><button className="btn-primary" onClick={saveReview} disabled={saving || !reason.trim()}>{saving ? t('common:status.saving') : t('sources:evidence.actions.saveReview')}</button></div> : null}
              {canReview && selectedGenerationPublished ? <div className="evidence-review"><h3>{t('sources:evidence.detail.relevanceOverrideTitle')}</h3><select value={relevanceDecision} onChange={(event) => setRelevanceDecision(event.target.value)}>{Object.entries(RELEVANCE_LABELS).filter(([key]) => key !== 'unclassified').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><textarea rows="3" value={relevanceReason} onChange={(event) => setRelevanceReason(event.target.value)} placeholder={t('sources:evidence.detail.explainRelevancePlaceholder')}/><button className="btn-primary" onClick={saveRelevanceReview} disabled={savingRelevance || !relevanceReason.trim()}>{savingRelevance ? t('common:status.saving') : t('sources:evidence.detail.saveRelevanceOverride')}</button></div> : null}
              {selected.reviews?.length ? <div><h3>{t('sources:evidence.detail.reviewHistoryTitle')}</h3>{selected.reviews.map((review) => <div className="evidence-history" key={review.id}><strong>{LABELS[review.decision]}</strong><span>{review.reviewer_name || t('sources:evidence.detail.reviewerFallback')} · {formatDate(review.created_at)}</span><p dir="auto">{review.reason}</p></div>)}</div> : null}
            </>}
          </div>
        </div>}</> : null}
      </> : null}
    </div>
  );
}
