import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, ExternalLink, FileSearch, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
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

function formatDate(value) {
  if (!value) return 'Unknown date';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString();
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

  const load = async (signal) => {
    setLoading(true); setError('');
    try {
      const result = await getEvidenceWorkspace(projectId, { run_id: runId, topic }, signal);
      setData(result);
      if (!runId && result.selected_run_id) setSearch({ run_id: result.selected_run_id }, { replace: true });
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
  }, [projectId, runId, topic]); // eslint-disable-line react-hooks/exhaustive-deps

  const openClaim = async (id) => {
    setError('');
    try {
      const result = await getEvidenceClaim(projectId, id);
      setSelected(result.claim); setDecision(result.claim.reviews?.[0]?.decision || result.claim.assessment); setReason('');
    } catch (err) { setError(err?.message || 'Failed to open the claim.'); }
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

  const verifyOrigin = async (item, status) => {
    const note = window.prompt(`Reason for marking this origin ${status}:`);
    if (!note?.trim()) return;
    try {
      await reviewEvidenceProvenance(projectId, item.article_id, { status, reason: note });
      await openClaim(selected.id); await load();
    } catch (err) { setError(err?.message || 'Failed to review provenance.'); }
  };

  const retry = async () => {
    if (!data?.selected_run_id) return;
    setRetrying(true);
    try { await retryEvidenceRun(projectId, data.selected_run_id); await load(); }
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

      <div className="glass-card evidence-filters">
        <label>Analysis run<select value={data?.selected_run_id || runId} onChange={(event) => setSearch({ run_id: event.target.value })}>
          {(data?.runs || []).map((run) => <option key={run.id} value={run.id}>{formatDate(run.created_at)} · {run.status} · {run.claim_count} claims</option>)}
        </select></label>
        <label>Topic<select value={topic} onChange={(event) => setSearch({ run_id: data?.selected_run_id || runId, ...(event.target.value ? { topic: event.target.value } : {}) })}>
          <option value="">All topics</option>{(data?.topics || []).map((item) => <option key={item.topic} value={item.topic}>{item.topic} ({item.count})</option>)}
        </select></label>
      </div>

      {error ? <div className="evidence-error">{error}</div> : null}
      {data?.runs?.find((run) => String(run.id) === String(data.selected_run_id))?.evidence_status === 'failed'
        ? <div className="evidence-error">Evidence processing failed: {data.runs.find((run) => String(run.id) === String(data.selected_run_id))?.evidence_error || 'Unknown error'}. Use Rebuild evidence to retry safely.</div>
        : null}
      {loading ? <div className="glass-card evidence-empty">Loading evidence…</div> : null}
      {!loading && !(data?.runs || []).length ? <div className="glass-card evidence-empty"><FileSearch size={24} /><strong>No evidence run yet</strong><span>Complete an analysis run to freeze the project evidence and extract claims.</span></div> : null}

      {!loading && (data?.runs || []).length ? <>
        <div className="evidence-overview">
          <div className="glass-card"><span>Claims</span><strong>{overview.total_claims || 0}</strong></div>
          <div className="glass-card"><span>Recorded origins</span><strong>{overview.known_origins || 0}</strong></div>
          <div className="glass-card"><span>Unassessed citations</span><strong>{overview.unassessed_items || 0}</strong></div>
          {assessmentCards.map(([key, value]) => <div className="glass-card" key={key}><span>{LABELS[key] || key}</span><strong>{value}</strong></div>)}
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

        <div className="evidence-layout">
          <div className="glass-card evidence-claims">
            <div className="panel-header-tight"><strong>Claims</strong><span className="panel-chip">{(data?.claims || []).length}</span></div>
            {(data?.claims || []).map((claim) => {
              const effective = claim.review_decision || claim.assessment;
              return <button type="button" className={`evidence-claim ${selected?.id === claim.id ? 'active' : ''}`} key={claim.id} onClick={() => openClaim(claim.id)}>
                <div><span className={`evidence-status ${effective}`}>{LABELS[effective] || effective}</span><span className="panel-chip muted">{claim.topic}</span></div>
                <strong>{claim.claim_text}</strong>
                <small>{claim.distinct_origins} origin{claim.distinct_origins === 1 ? '' : 's'} · {claim.supporting_count} supporting · {claim.contradicting_count} conflicting{claim.review_count ? ` · reviewed` : ''}</small>
              </button>;
            })}
            {!(data?.claims || []).length ? <div className="evidence-empty">No claims match this topic.</div> : null}
          </div>

          <div className="glass-card evidence-detail">
            {!selected ? <div className="evidence-empty"><FileSearch size={22} /><span>Select a claim to inspect its evidence.</span></div> : <>
              <div><span className={`evidence-status ${selected.assessment}`}>{LABELS[selected.assessment]}</span><span className="panel-chip muted">{selected.claim_type?.replaceAll('_', ' ')}</span></div>
              <h2>{selected.claim_text}</h2>
              <p>{selected.explanation}</p><p className="evidence-limit">{selected.limitations}</p>
              <div className="evidence-method"><span>Assessment method: {selected.rules_version || 'Unknown'}</span><span>Model confidence: {selected.model ? 'Recorded by model' : 'Not assessed'}</span>{selected.time_scope ? <span>Time scope: {selected.time_scope}</span> : null}{selected.quantities?.length ? <span>Quantities: {selected.quantities.join(', ')}</span> : null}</div>
              <h3>Evidence passages</h3>
              <div className="evidence-items">{(selected.evidence || []).map((item) => {
                const meta = sourceMeta(item); const provenance = item.current_provenance || meta.provenance || {};
                return <article key={item.id} className={`evidence-item ${item.relationship}`}>
                  <div><span className={`evidence-status ${item.relationship}`}>{item.relationship}</span>{item.citation_valid ? <span title="Passage validated"><CheckCircle2 size={14} /></span> : <span title="Citation invalid"><XCircle size={14} /></span>}</div>
                  <blockquote>{item.passage}</blockquote>
                  <div className="evidence-source"><strong>{provenance.publisher || meta.source || 'Unknown source'}</strong><span>Published: {formatDate(meta.published_at)}</span><span>Collected: {formatDate(provenance.collected_at)}</span><span>Speaker/author: {provenance.original_attribution || meta.author || 'Unknown'}</span><span>Origin: {provenance.source_type || 'Unknown'}</span><span>Relationship: {provenance.relationship_to_subject || 'Unknown'}</span><span>Verification: {provenance.verification_status || 'unassessed'}</span>{item.provenance_review ? <span>{item.provenance_review.reviewer_name}: {item.provenance_review.reason}</span> : null}</div>
                  <div className="evidence-item-actions">{(provenance.original_url || meta.url)?.startsWith('http') ? <a href={provenance.original_url || meta.url} target="_blank" rel="noreferrer">Original <ExternalLink size={12} /></a> : <span>Stored article #{item.article_id}</span>}{canReview ? <><button onClick={() => verifyOrigin(item, 'verified')}>Verify origin</button><button onClick={() => verifyOrigin(item, 'rejected')}>Reject origin</button></> : null}</div>
                </article>;
              })}</div>
              {canReview ? <div className="evidence-review"><h3>Analyst review</h3><select value={decision} onChange={(event) => setDecision(event.target.value)}>{Object.entries(LABELS).filter(([key]) => key !== 'assessment_unavailable').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain why the evidence supports this decision…"/><button className="btn-primary" onClick={saveReview} disabled={saving || !reason.trim()}>{saving ? 'Saving…' : 'Save review'}</button></div> : null}
              {selected.reviews?.length ? <div><h3>Review history</h3>{selected.reviews.map((review) => <div className="evidence-history" key={review.id}><strong>{LABELS[review.decision]}</strong><span>{review.reviewer_name || 'Reviewer'} · {formatDate(review.created_at)}</span><p>{review.reason}</p></div>)}</div> : null}
            </>}
          </div>
        </div>
      </> : null}
    </div>
  );
}
