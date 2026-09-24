import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft, CheckCircle2, ExternalLink, FileText, Lightbulb, Loader2,
  Pencil, Plus, RefreshCw, Scale, Trash2, UserRound,
} from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import {
  createIdeaComparisonFact, deleteIdeaComparisonFact, getIdeaComparison,
  regenerateIdeaComparison, updateIdeaComparisonFact,
} from '../api/projectsApi.js';
import '../styles/IdeaComparisonDetail.css';

const EMPTY_FACT = { fact_text: '', reference_label: '', reference_url: '', stated_value: '', observed_at: '' };

export default function IdeaComparisonDetailPage() {
  const { projectId, clusterId } = useParams();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('run_id') || undefined;
  const location = useLocation();
  const { hasPermission } = useAuth();
  const canManage = hasPermission('projects.update');
  const backTo = location.state?.from || '/dashboard';
  const [comparison, setComparison] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [editingFactId, setEditingFactId] = useState(null);
  const [form, setForm] = useState(EMPTY_FACT);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const load = useCallback(async (signal) => {
    setLoading(true);
    setError('');
    try {
      const data = await getIdeaComparison(projectId, clusterId, { run_id: runId }, signal);
      setComparison(data?.comparison || null);
    } catch (err) {
      if (err?.name !== 'AbortError') setError(err?.message || 'Failed to load this comparison.');
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectId, clusterId, runId]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => load(controller.signal), 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [load]);

  const closeForm = () => {
    setFormOpen(false);
    setEditingFactId(null);
    setForm(EMPTY_FACT);
  };

  const openEdit = (fact) => {
    setEditingFactId(fact.id);
    setForm({
      fact_text: fact.fact_text || '', reference_label: fact.reference_label || '',
      reference_url: fact.reference_url || '', stated_value: fact.stated_value || '',
      observed_at: fact.observed_at || '',
    });
    setFormOpen(true);
    setMessage('');
  };

  const regenerate = async () => {
    setRegenerating(true);
    setMessage('');
    try {
      const data = await regenerateIdeaComparison(projectId, clusterId, { run_id: runId });
      setComparison(data?.comparison || null);
      setMessage('Executive summary regenerated with the latest evidence.');
      return true;
    } catch (err) {
      setMessage(`${err?.message || 'Summary regeneration failed.'} Your fact changes were saved; retry when the model is available.`);
      await load();
      return false;
    } finally {
      setRegenerating(false);
    }
  };

  const saveAndRegenerate = async (event) => {
    event.preventDefault();
    if (!form.fact_text.trim() || saving) return;
    setSaving(true);
    setMessage('');
    try {
      if (editingFactId) await updateIdeaComparisonFact(projectId, clusterId, editingFactId, form);
      else await createIdeaComparisonFact(projectId, clusterId, form);
      closeForm();
      await regenerate();
    } catch (err) {
      setMessage(err?.message || 'Failed to save the fact.');
    } finally {
      setSaving(false);
    }
  };

  const removeFact = async (fact) => {
    if (!window.confirm('Delete this user-provided fact? The current summary will be marked outdated.')) return;
    setMessage('');
    try {
      await deleteIdeaComparisonFact(projectId, clusterId, fact.id);
      await load();
      setMessage('Fact deleted. Regenerate the summary to apply the change.');
    } catch (err) {
      setMessage(err?.message || 'Failed to delete the fact.');
    }
  };

  if (loading) return <div className="admin-page-shell comparison-detail-state"><Loader2 className="spin" /> Loading comparison…</div>;
  if (error || !comparison) return (
    <div className="admin-page-shell comparison-detail-state">
      <p>{error || 'Idea comparison not found.'}</p>
      <Link className="btn-secondary" to={backTo}><ArrowLeft size={15} /> Back to dashboard</Link>
    </div>
  );

  return (
    <div className="admin-page-shell comparison-detail-page">
      <Link className="comparison-detail-back" to={backTo}><ArrowLeft size={15} /> Back to dashboard</Link>
      <header className="comparison-detail-header">
        <div>
          <span className="admin-page-kicker"><Lightbulb size={14} /> Idea comparison</span>
          <h1 className="admin-page-title">{comparison.idea}</h1>
          <div className={`comparison-detail-status ${comparison.diverges ? 'diverges' : 'agrees'}`}>
            {comparison.diverges ? <Scale size={14} /> : <CheckCircle2 size={14} />}
            {comparison.diverges ? 'Evidence differs' : 'Evidence aligns'}
          </div>
        </div>
        {canManage ? (
          <button type="button" className="btn-secondary" onClick={regenerate} disabled={regenerating}>
            {regenerating ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} Regenerate summary
          </button>
        ) : null}
      </header>

      {message ? <div className="comparison-detail-message" role="status">{message}</div> : null}

      <section className="glass-card comparison-summary-card">
        <div className="comparison-section-heading">
          <div><span>Executive summary</span><small>Generated from document claims and user-provided facts</small></div>
          {comparison.summary_stale ? <strong>Needs regeneration</strong> : null}
        </div>
        <p>{comparison.summary || 'No summary has been generated yet.'}</p>
      </section>

      <section className="comparison-evidence-grid">
        <article className="glass-card comparison-evidence-card">
          <div className="comparison-section-heading">
            <div><span>Document evidence</span><small>{comparison.sources.length} source{comparison.sources.length === 1 ? '' : 's'}</small></div>
          </div>
          <div className="comparison-evidence-list">
            {comparison.sources.map((source, index) => (
              <div className="comparison-evidence-row" key={`${source.article_id || 'source'}-${index}`}>
                <div className="comparison-evidence-number">{index + 1}</div>
                <div className="comparison-evidence-content">
                  <div><FileText size={14} /><strong>{source.source_label}</strong></div>
                  <h3>{source.title || 'Untitled source'}</h3>
                  {source.excerpt ? <p>{source.excerpt}</p> : null}
                  <dl><dt>Stated figure</dt><dd>{source.value || 'Not stated'}</dd></dl>
                </div>
                {source.url ? <a href={source.url} target="_blank" rel="noreferrer" aria-label={`Open ${source.source_label}`}><ExternalLink size={16} /></a> : null}
              </div>
            ))}
          </div>
        </article>

        <article className="glass-card comparison-evidence-card">
          <div className="comparison-section-heading">
            <div><span>User-provided facts</span><small>Additional context supplied by your team</small></div>
            {canManage ? <button type="button" className="btn-secondary" onClick={() => { closeForm(); setFormOpen(true); }}><Plus size={14} /> Add fact</button> : null}
          </div>
          {formOpen ? (
            <form className="comparison-fact-form" onSubmit={saveAndRegenerate}>
              <label className="comparison-fact-wide">Fact <textarea required maxLength={4000} rows={4} value={form.fact_text} onChange={(e) => setForm({ ...form, fact_text: e.target.value })} placeholder="State the fact and enough context to compare it with the claims." /></label>
              <label>Reference label <input value={form.reference_label} onChange={(e) => setForm({ ...form, reference_label: e.target.value })} placeholder="Internal research, annual report…" /></label>
              <label>Stated figure <input value={form.stated_value} onChange={(e) => setForm({ ...form, stated_value: e.target.value })} placeholder="e.g. 42%, $120, 3 days" /></label>
              <label>Reference URL <input type="url" value={form.reference_url} onChange={(e) => setForm({ ...form, reference_url: e.target.value })} placeholder="https://…" /></label>
              <label>Date <input type="date" value={form.observed_at} onChange={(e) => setForm({ ...form, observed_at: e.target.value })} /></label>
              <div className="comparison-fact-actions">
                <button type="button" className="btn-secondary" onClick={closeForm} disabled={saving}>Cancel</button>
                <button type="submit" className="btn-primary" disabled={saving || regenerating || !form.fact_text.trim()}>
                  {saving || regenerating ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
                  Save and regenerate
                </button>
              </div>
            </form>
          ) : null}
          {comparison.facts.length ? (
            <div className="comparison-facts-list">
              {comparison.facts.map((fact) => (
                <div className="comparison-fact" key={fact.id}>
                  <div className="comparison-fact-icon"><UserRound size={16} /></div>
                  <div>
                    <span>User-provided fact{fact.reference_label ? ` · ${fact.reference_label}` : ''}</span>
                    <p>{fact.fact_text}</p>
                    <small>{[fact.stated_value, fact.observed_at, fact.created_by_name && `Added by ${fact.created_by_name}`].filter(Boolean).join(' · ')}</small>
                    {fact.reference_url ? <a href={fact.reference_url} target="_blank" rel="noreferrer">Open reference <ExternalLink size={12} /></a> : null}
                  </div>
                  {canManage ? <div className="comparison-fact-row-actions"><button type="button" onClick={() => openEdit(fact)} aria-label="Edit fact"><Pencil size={14} /></button><button type="button" onClick={() => removeFact(fact)} aria-label="Delete fact"><Trash2 size={14} /></button></div> : null}
                </div>
              ))}
            </div>
          ) : <p className="comparison-empty-facts">No user-provided facts yet.</p>}
        </article>
      </section>
    </div>
  );
}
