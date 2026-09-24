import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft, CheckCircle2, ExternalLink, FileText, Lightbulb, Loader2,
  Minus, Pencil, Plus, RefreshCw, Scale, Trash2, TrendingDown, TrendingUp, UserRound, X,
} from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { useAuth } from '../auth/useAuth.js';
import {
  createIdeaComparisonFact, deleteIdeaComparisonFact, getIdeaComparison,
  regenerateIdeaComparison, updateIdeaComparisonFact,
} from '../api/projectsApi.js';
import '../styles/IdeaComparisonDetail.css';

const emptyObservation = (metric = '') => ({ metric, numeric_value: '', unit: '', period_label: '', value_kind: 'unknown' });
const emptyFact = () => ({ fact_text: '', reference_label: '', reference_url: '', observed_at: '', observations: [] });

const compactNumber = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });

function NumericEvidence({ evidence }) {
  if (!evidence?.groups?.length) return null;
  return (
    <section className="glass-card comparison-numeric-card">
      <div className="comparison-section-heading">
        <div><span>Numbers at a glance</span><small>Shown only for comparable figures found in this idea</small></div>
      </div>
      <div className="comparison-numeric-groups">
        {evidence.groups.map((group) => {
          const chartData = group.observations.map((item) => ({
            ...item,
            label: group.display_type === 'trend' ? item.period_label : item.source_label,
            actual: item.value_kind === 'actual' ? item.numeric_value : null,
            forecast: item.value_kind === 'forecast' || item.value_kind === 'target' ? item.numeric_value : null,
            estimate: !['actual', 'forecast', 'target'].includes(item.value_kind) ? item.numeric_value : null,
          }));
          const DirectionIcon = group.direction === 'up' ? TrendingUp : group.direction === 'down' ? TrendingDown : Minus;
          return (
            <article className="comparison-numeric-group" key={group.id}>
              <div className="comparison-numeric-title">
                <div><h2>{group.metric}</h2><span>{group.unit}</span></div>
                {group.direction ? (
                  <strong className={`comparison-direction ${group.direction}`}>
                    <DirectionIcon size={15} /> {compactNumber(Math.abs(group.change))} {group.unit}
                    {group.change_percent != null ? ` (${Math.abs(group.change_percent).toFixed(1)}%)` : ''}
                  </strong>
                ) : null}
              </div>
              {group.display_type === 'single' ? (
                <a className="comparison-single-value" href={`#${group.observations[0].evidence_id}`}>
                  <strong>{group.observations[0].display_value}</strong>
                  <span>{group.observations[0].source_label}</span>
                </a>
              ) : (
                <div className="comparison-chart" role="img" aria-label={`${group.metric} ${group.display_type} chart`}>
                  <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 48)}>
                    {group.display_type === 'trend' ? (
                      <LineChart data={chartData} margin={{ top: 12, right: 18, bottom: 8, left: 4 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 12 }} width={58} />
                        <Tooltip formatter={(value) => [`${compactNumber(value)} ${group.unit}`, 'Value']} />
                        <Legend />
                        <Line type="monotone" dataKey="numeric_value" name="Direction" stroke="#94a3b8" strokeWidth={2} dot={false} />
                        <Line type="monotone" dataKey="actual" name="Actual" stroke="#2563eb" strokeWidth={3} connectNulls />
                        <Line type="monotone" dataKey="estimate" name="Estimate" stroke="#7c3aed" strokeWidth={3} strokeDasharray="5 4" connectNulls />
                        <Line type="monotone" dataKey="forecast" name="Forecast / target" stroke="#f97316" strokeWidth={3} strokeDasharray="5 4" connectNulls />
                      </LineChart>
                    ) : (
                      <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 28, bottom: 4, left: 18 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 12 }} />
                        <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(value) => [`${compactNumber(value)} ${group.unit}`, 'Value']} />
                        <Bar dataKey="numeric_value" radius={[0, 6, 6, 0]}>
                          {chartData.map((item) => <Cell key={item.id} fill={item.origin === 'user' ? '#f97316' : '#2563eb'} />)}
                        </Bar>
                      </BarChart>
                    )}
                  </ResponsiveContainer>
                </div>
              )}
              {group.observations.length > 1 ? (
                <div className="comparison-number-table">
                  {group.observations.map((item) => (
                    <a href={`#${item.evidence_id}`} key={item.id}>
                      <span><i className={`comparison-origin-dot ${item.origin}`} />{item.source_label}</span>
                      <strong>{item.display_value}</strong>
                      <small>{[item.period_label, item.value_kind !== 'unknown' && item.value_kind].filter(Boolean).join(' · ') || 'Period not specified'}</small>
                    </a>
                  ))}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

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
  const [form, setForm] = useState(emptyFact);
  const [includeNumbers, setIncludeNumbers] = useState(false);
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
    setForm(emptyFact());
    setIncludeNumbers(false);
  };

  const openEdit = (fact) => {
    setEditingFactId(fact.id);
    const observations = fact.observations || [];
    setForm({
      fact_text: fact.fact_text || '', reference_label: fact.reference_label || '',
      reference_url: fact.reference_url || '', observed_at: fact.observed_at || '',
      observations: observations.map((item) => ({ ...item, numeric_value: String(item.numeric_value) })),
    });
    setIncludeNumbers(observations.length > 0);
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
      const payload = { ...form, observations: includeNumbers ? form.observations : [] };
      if (editingFactId) await updateIdeaComparisonFact(projectId, clusterId, editingFactId, payload);
      else await createIdeaComparisonFact(projectId, clusterId, payload);
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

      <NumericEvidence evidence={comparison.numeric_evidence} />

      <section className="comparison-evidence-grid">
        <article className="glass-card comparison-evidence-card">
          <div className="comparison-section-heading">
            <div><span>Document evidence</span><small>{comparison.sources.length} source{comparison.sources.length === 1 ? '' : 's'}</small></div>
          </div>
          <div className="comparison-evidence-list">
            {comparison.sources.map((source, index) => (
              <div className="comparison-evidence-row" id={`document-evidence-${index}`} key={`${source.article_id || 'source'}-${index}`}>
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
              <label>Reference URL <input type="url" value={form.reference_url} onChange={(e) => setForm({ ...form, reference_url: e.target.value })} placeholder="https://…" /></label>
              <label>Date <input type="date" value={form.observed_at} onChange={(e) => setForm({ ...form, observed_at: e.target.value })} /></label>
              <label className="comparison-number-toggle">
                <input type="checkbox" checked={includeNumbers} onChange={(e) => {
                  const checked = e.target.checked;
                  setIncludeNumbers(checked);
                  if (checked && !form.observations.length) setForm({ ...form, observations: [emptyObservation(comparison.idea)] });
                }} />
                <span><strong>Include numbers</strong><small>Add structured values when this fact contains a measurable figure.</small></span>
              </label>
              {includeNumbers ? (
                <div className="comparison-observations">
                  {form.observations.map((observation, index) => (
                    <div className="comparison-observation-row" key={index}>
                      <label>Metric <input required value={observation.metric} onChange={(e) => setForm({ ...form, observations: form.observations.map((item, itemIndex) => itemIndex === index ? { ...item, metric: e.target.value } : item) })} placeholder="Oil production" /></label>
                      <label>Value <input required inputMode="decimal" value={observation.numeric_value} onChange={(e) => setForm({ ...form, observations: form.observations.map((item, itemIndex) => itemIndex === index ? { ...item, numeric_value: e.target.value } : item) })} placeholder="1.10" /></label>
                      <label>Unit <input required value={observation.unit} onChange={(e) => setForm({ ...form, observations: form.observations.map((item, itemIndex) => itemIndex === index ? { ...item, unit: e.target.value } : item) })} placeholder="million bpd" /></label>
                      <label>Period <input value={observation.period_label} onChange={(e) => setForm({ ...form, observations: form.observations.map((item, itemIndex) => itemIndex === index ? { ...item, period_label: e.target.value } : item) })} placeholder="2026 Q4" /></label>
                      <label>Type <select value={observation.value_kind} onChange={(e) => setForm({ ...form, observations: form.observations.map((item, itemIndex) => itemIndex === index ? { ...item, value_kind: e.target.value } : item) })}><option value="unknown">Unspecified</option><option value="actual">Actual</option><option value="estimate">Estimate</option><option value="forecast">Forecast</option><option value="target">Target</option></select></label>
                      <button type="button" onClick={() => setForm({ ...form, observations: form.observations.filter((_, itemIndex) => itemIndex !== index) })} aria-label="Remove number"><X size={15} /></button>
                    </div>
                  ))}
                  <button type="button" className="comparison-add-observation" onClick={() => setForm({ ...form, observations: [...form.observations, emptyObservation(comparison.idea)] })}><Plus size={14} /> Add another number</button>
                </div>
              ) : null}
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
                <div className="comparison-fact" id={`user-fact-${fact.id}`} key={fact.id}>
                  <div className="comparison-fact-icon"><UserRound size={16} /></div>
                  <div>
                    <span>User-provided fact{fact.reference_label ? ` · ${fact.reference_label}` : ''}</span>
                    <p>{fact.fact_text}</p>
                    {fact.observations?.length ? <div className="comparison-fact-values">{fact.observations.map((item) => <span key={item.id}>{item.display_value}{item.period_label ? ` · ${item.period_label}` : ''}</span>)}</div> : null}
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
