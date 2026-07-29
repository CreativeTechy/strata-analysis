/**
 * Competitor study onboarding.
 *
 * Four steps, in the order the information actually becomes available:
 *
 *   1. Your business  — name + website. The website is what makes the rest work,
 *                       so it is asked for first and its scrape is shown honestly.
 *   2. Market context — the AI's reading of the site, editable. Shown rather than
 *                       hidden because everything downstream is judged against it,
 *                       and a wrong market here produces wrong competitors.
 *   3. Competitors    — discovered and ranked by size. The user picks who to track;
 *                       nothing is tracked on the model's word alone.
 *   4. Channels       — the accounts found for each tracked competitor, each
 *                       needing confirmation before it is scraped.
 *
 * Long steps (scrape, discovery) run tens of seconds, so each shows staged
 * progress instead of an indeterminate spinner.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Building2, Check, CheckCircle2, ChevronRight,
  Globe, Info, Link2, Loader2, Plus, Radar, Search, Sparkles, Trash2, X,
} from 'lucide-react';
import {
  SIZE_TIER_LABELS, addCompetitor, buildProfile, createStudy, discoverCompetitors,
  getDiscoveryStatus, initials, avatarGradient, listCompetitors, saveProfile,
  setCompetitorStatus, setSchedule, validateAccount,
} from '../competitorApi.js';
import '../styles/Competitors.css';

const STEPS = [
  { id: 1, label: 'Your business', icon: Building2 },
  { id: 2, label: 'Market context', icon: Sparkles },
  { id: 3, label: 'Competitors', icon: Radar },
  { id: 4, label: 'Channels', icon: Link2 },
];

const SCRAPE_STAGES = [
  'Fetching your website',
  'Extracting page text',
  'Reading how you position yourself',
  'Writing your market context',
];

const DISCOVERY_STAGES = [
  'Comparing your profile against the market',
  'Naming candidate competitors',
  'Checking each company actually exists',
  'Ranking them by size',
  'Locating their channels',
];

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

const DISCOVERY_POLL_MS = 2500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Discovery runs as a backend job that can take minutes (LLM call + live web
 *  corroboration + per-competitor account lookups), so it's queued rather than
 *  awaited directly - poll until it reaches a terminal status. */
async function pollDiscoveryRun(studyId, runId) {
  for (;;) {
    const { run } = await getDiscoveryStatus(studyId, runId);
    if (run.status === 'success' || run.status === 'failed') return run;
    await sleep(DISCOVERY_POLL_MS);
  }
}

function ListEditor({ label, hint, values, onChange, placeholder }) {
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
  const [busy, setBusy] = useState(false);

  const [studyName, setStudyName] = useState('');
  const [studyId, setStudyId] = useState(null);

  const [business, setBusiness] = useState({ name: '', website: '', description: '' });
  const [profile, setProfile] = useState(null);
  const [scrape, setScrape] = useState(null);

  const [competitors, setCompetitors] = useState([]);
  const [rejected, setRejected] = useState([]);
  const [tracked, setTracked] = useState(() => new Set());
  const [manual, setManual] = useState({ name: '', website: '' });

  const [accountsByCompetitor, setAccountsByCompetitor] = useState({});
  const [scheduleDays, setScheduleDays] = useState(1);
  const [scheduleOn, setScheduleOn] = useState(true);

  const canLeaveStep1 = business.name.trim().length > 0;
  const trackedCompetitors = useMemo(
    () => competitors.filter((competitor) => tracked.has(competitor.id)),
    [competitors, tracked],
  );

  // Step 1 -> 2: create the study, scrape the site, derive the market context.
  const submitBusiness = async () => {
    setError('');
    setBusy(true);
    try {
      let id = studyId;
      if (!id) {
        const created = await createStudy({
          name: studyName.trim() || `${business.name.trim()} - competitor study`,
        });
        id = created.study.id;
        setStudyId(id);
      }
      const result = await buildProfile(id, business);
      setProfile(result.profile);
      setScrape(result.scrape);
      if (!result.ai_derived) {
        setError(
          'The site was read but the market context could not be generated. Fill it in below and continue.',
        );
      }
      setStep(2);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  // Step 2 -> 3: save any edits, then discover and rank competitors.
  const submitContext = async () => {
    setError('');
    setBusy(true);
    try {
      const saved = await saveProfile(studyId, profile);
      setProfile(saved.profile);

      const queued = await discoverCompetitors(studyId, { limit: 12, with_accounts: true });
      const run = await pollDiscoveryRun(studyId, queued.run_id);
      if (run.status === 'failed') {
        throw new Error(run.error || run.message || 'Competitor discovery failed.');
      }

      const result = await listCompetitors(studyId);
      const discovered = result.competitors || [];
      setCompetitors(discovered);
      setRejected(run.rejected || []);
      // Pre-select the top five by size: the ranking is the recommendation, but
      // the user still confirms it before anything gets scraped.
      setTracked(new Set(discovered.slice(0, 5).map((item) => item.id)));
      setStep(3);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  // Step 3 -> 4: persist track/ignore for every competitor, then load channels.
  const submitCompetitors = async () => {
    setError('');
    setBusy(true);
    try {
      await Promise.all(
        competitors.map((competitor) =>
          setCompetitorStatus(competitor.id, tracked.has(competitor.id) ? 'tracked' : 'ignored'),
        ),
      );
      const result = await listCompetitors(studyId);
      const map = {};
      (result.competitors || [])
        .filter((competitor) => tracked.has(competitor.id))
        .forEach((competitor) => {
          map[competitor.id] = competitor.accounts || [];
        });
      setAccountsByCompetitor(map);
      setStep(4);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  const decideAccount = async (competitorId, accountId, status) => {
    try {
      const result = await validateAccount(accountId, status);
      setAccountsByCompetitor((current) => ({
        ...current,
        [competitorId]: (current[competitorId] || []).map((account) =>
          account.id === accountId ? result.account : account,
        ),
      }));
    } catch (caught) {
      setError(caught.message);
    }
  };

  const finish = async () => {
    setError('');
    setBusy(true);
    try {
      await setSchedule(studyId, {
        repeat_enabled: scheduleOn,
        repeat_interval_value: Math.max(1, Number(scheduleDays) || 1),
        repeat_interval_unit: 'days',
      });
      navigate(`/competitors/${studyId}`);
    } catch (caught) {
      setError(caught.message);
      setBusy(false);
    }
  };

  const addManualCompetitor = async () => {
    if (!manual.name.trim()) return;
    try {
      const result = await addCompetitor(studyId, {
        name: manual.name.trim(),
        website: manual.website.trim() || null,
        status: 'tracked',
      });
      const refreshed = await listCompetitors(studyId);
      setCompetitors(refreshed.competitors || []);
      setTracked((current) => new Set([...current, result.competitor.id]));
      setManual({ name: '', website: '' });
    } catch (caught) {
      setError(caught.message);
    }
  };

  const validAccountCount = useMemo(
    () =>
      Object.values(accountsByCompetitor)
        .flat()
        .filter((account) => account.validation_status === 'valid').length,
    [accountsByCompetitor],
  );

  return (
    <div className="cs-page cs-wizard">
      <div className="cs-head">
        <div>
          <h1>New competitor study</h1>
          <p>
            Strata reads your website to understand your market, finds who you compete with, then
            tracks what they do and what it means for you. This is separate from sentiment and
            opinion tracking.
          </p>
        </div>
      </div>

      <div className="cs-steps" role="list">
        {STEPS.map((item, index) => {
          const state = step === item.id ? ' cs-step-active' : step > item.id ? ' cs-step-done' : '';
          const Icon = item.icon;
          return (
            <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div className={`cs-step${state}`} role="listitem" aria-current={step === item.id}>
                <span className="cs-step-num">
                  {step > item.id ? <Check size={12} /> : item.id}
                </span>
                <Icon size={14} />
                <span>{item.label}</span>
              </div>
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

      {/* ---------------- Step 1: business ---------------- */}
      {step === 1 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Building2 size={16} /> Tell us about your business</h2>
          <p className="cs-panel-hint">
            The website matters most — we read it to work out which market you are in and how you
            position yourself. Everything after this is judged against that, so a real site gives
            much better competitors than a description alone.
          </p>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-biz-name">Business name</label>
            <input
              id="cs-biz-name"
              className="cs-input"
              value={business.name}
              placeholder="Northwind Analytics"
              onChange={(event) => setBusiness({ ...business, name: event.target.value })}
            />
          </div>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-biz-site">
              Website<span className="cs-label-hint">strongly recommended</span>
            </label>
            <input
              id="cs-biz-site"
              className="cs-input"
              value={business.website}
              placeholder="northwind.com"
              onChange={(event) => setBusiness({ ...business, website: event.target.value })}
            />
          </div>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-biz-desc">
              Anything else<span className="cs-label-hint">optional</span>
            </label>
            <textarea
              id="cs-biz-desc"
              className="cs-textarea"
              value={business.description}
              placeholder="What you sell, who buys it, which markets you care about."
              onChange={(event) => setBusiness({ ...business, description: event.target.value })}
            />
          </div>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-study-name">
              Study name<span className="cs-label-hint">defaults to your business name</span>
            </label>
            <input
              id="cs-study-name"
              className="cs-input"
              value={studyName}
              placeholder={business.name ? `${business.name} - competitor study` : 'Q3 competitor study'}
              onChange={(event) => setStudyName(event.target.value)}
            />
          </div>

          {busy ? (
            <div className="cs-panel" style={{ marginTop: 18, background: '#fcfdff' }}>
              <StageList stages={SCRAPE_STAGES} />
            </div>
          ) : null}

          <div className="cs-wizard-foot">
            <span style={{ fontSize: '0.8rem', color: 'var(--text-light)' }}>
              This takes about 20-40 seconds.
            </span>
            <button type="button" className="cs-btn cs-btn-primary" onClick={submitBusiness} disabled={!canLeaveStep1 || busy}>
              {busy ? <Loader2 size={15} className="cs-spin" /> : <ArrowRight size={15} />}
              {busy ? 'Reading your site...' : 'Read my site'}
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 2: market context ---------------- */}
      {step === 2 && profile ? (
        <>
          {scrape ? (
            <div className={`cs-alert ${scrape.status === 'success' ? 'cs-alert-info' : 'cs-alert-warn'}`}>
              {scrape.status === 'success' ? <Globe size={16} style={{ flexShrink: 0 }} /> : <AlertTriangle size={16} style={{ flexShrink: 0 }} />}
              <span>
                {scrape.status === 'success'
                  ? `Read ${scrape.pages.length} page${scrape.pages.length === 1 ? '' : 's'} from your site (${scrape.chars.toLocaleString()} characters). Check the context below — competitors are found from it.`
                  : `Could not read your website${scrape.error ? `: ${scrape.error}` : '.'} Fill the fields in below so discovery still has something to work from.`}
              </span>
            </div>
          ) : null}

          <div className="cs-panel">
            <h2 className="cs-panel-title"><Sparkles size={16} /> What we understood</h2>
            <p className="cs-panel-hint">
              Edit anything that is off. This is the description competitors get matched against and
              that every &ldquo;how does this affect us&rdquo; judgement is measured by.
            </p>

            <div className="cs-grid-2">
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-industry">Industry</label>
                <input id="cs-industry" className="cs-input" value={profile.industry || ''}
                  onChange={(event) => setProfile({ ...profile, industry: event.target.value })} />
              </div>
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-market">Market you compete in</label>
                <input id="cs-market" className="cs-input" value={profile.market || ''}
                  onChange={(event) => setProfile({ ...profile, market: event.target.value })} />
              </div>
            </div>

            <div className="cs-field">
              <label className="cs-label" htmlFor="cs-positioning">Positioning</label>
              <input id="cs-positioning" className="cs-input" value={profile.positioning || ''}
                onChange={(event) => setProfile({ ...profile, positioning: event.target.value })} />
            </div>

            <ListEditor label="What you offer" values={profile.offerings}
              placeholder="demand forecasting"
              onChange={(offerings) => setProfile({ ...profile, offerings })} />
            <ListEditor label="Who buys it" values={profile.audience}
              placeholder="operations directors"
              onChange={(audience) => setProfile({ ...profile, audience })} />
            <ListEditor label="What sets you apart" hint="used to judge competitor moves"
              values={profile.differentiators} placeholder="implementation in under 30 days"
              onChange={(differentiators) => setProfile({ ...profile, differentiators })} />

            <div className="cs-field">
              <label className="cs-label" htmlFor="cs-context">Market context</label>
              <textarea id="cs-context" className="cs-textarea" style={{ minHeight: 110 }}
                value={profile.context_summary || ''}
                onChange={(event) => setProfile({ ...profile, context_summary: event.target.value })} />
            </div>

            {busy ? (
              <div className="cs-panel" style={{ marginTop: 4, background: '#fcfdff' }}>
                <StageList stages={DISCOVERY_STAGES} />
              </div>
            ) : null}

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(1)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <button type="button" className="cs-btn cs-btn-primary" onClick={submitContext} disabled={busy}>
                {busy ? <span className="cs-spinner" /> : <Radar size={15} />}
                {busy ? 'Finding competitors...' : 'Find my competitors'}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {/* ---------------- Step 3: competitors ---------------- */}
      {step === 3 ? (
        <>
          <div className="cs-panel">
            <h2 className="cs-panel-title"><Radar size={16} /> Who you compete with</h2>
            <p className="cs-panel-hint">
              Ranked by size, largest first — incumbents move the market you are in. Pick who to
              track; only tracked competitors get scraped and analysed.
              {' '}<strong>{tracked.size}</strong> selected.
            </p>

            <div className="cs-rows">
              {competitors.map((competitor) => {
                const on = tracked.has(competitor.id);
                const basis = competitor.size_signals?.basis || [];
                return (
                  <div key={competitor.id} className={`cs-row${on ? ' cs-row-selected' : ''}`}>
                    <span className="cs-row-rank">{competitor.size_rank ?? '-'}</span>
                    <div
                      className="cs-avatar"
                      style={{ background: avatarGradient(competitor.name), width: 30, height: 30, fontSize: '0.72rem' }}
                      aria-hidden="true"
                    >
                      {initials(competitor.name)}
                    </div>
                    <div className="cs-row-main">
                      <div className="cs-row-name">{competitor.name}</div>
                      <div className="cs-row-desc">
                        {competitor.description || competitor.size_signals?.why_competitor || competitor.domain}
                      </div>
                      {basis.length ? (
                        <div className="cs-pills" style={{ marginTop: 6 }}>
                          {basis.slice(0, 3).map((signal) => (
                            <span key={signal} className="cs-pill cs-pill-signal">{signal}</span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="cs-row-side">
                      <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                        {SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}
                      </span>
                      <button
                        type="button"
                        className={`cs-btn cs-btn-sm${on ? ' cs-btn-primary' : ''}`}
                        onClick={() =>
                          setTracked((current) => {
                            const next = new Set(current);
                            if (next.has(competitor.id)) next.delete(competitor.id);
                            else next.add(competitor.id);
                            return next;
                          })
                        }
                        aria-pressed={on}
                      >
                        {on ? <><Check size={13} /> Tracking</> : 'Track'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {!competitors.length ? (
              <div className="cs-empty">
                <div className="cs-empty-icon"><Search size={20} /></div>
                <h3>No competitors found</h3>
                <p>Nothing could be corroborated for this market. Add one by hand below.</p>
              </div>
            ) : null}

            <div style={{ marginTop: 20, paddingTop: 18, borderTop: '1px solid #eef1f6' }}>
              <label className="cs-label">Add one we missed</label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <input className="cs-input" style={{ flex: '1 1 180px' }} placeholder="Company name"
                  value={manual.name} onChange={(event) => setManual({ ...manual, name: event.target.value })} />
                <input className="cs-input" style={{ flex: '1 1 180px' }} placeholder="website.com"
                  value={manual.website} onChange={(event) => setManual({ ...manual, website: event.target.value })} />
                <button type="button" className="cs-btn" onClick={addManualCompetitor} disabled={!manual.name.trim()}>
                  <Plus size={14} /> Add
                </button>
              </div>
            </div>

            {rejected.length ? (
              <details style={{ marginTop: 18 }}>
                <summary style={{ cursor: 'pointer', fontSize: '0.82rem', color: 'var(--text-light)' }}>
                  {rejected.length} suggestion{rejected.length === 1 ? '' : 's'} dropped during checking
                </summary>
                <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {rejected.map((item) => (
                    <div key={item.name} style={{ fontSize: '0.81rem', color: 'var(--text-light)' }}>
                      <strong style={{ color: 'var(--text-dark)' }}>{item.name}</strong> — {item.reason}
                    </div>
                  ))}
                </div>
              </details>
            ) : null}

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(2)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <button type="button" className="cs-btn cs-btn-primary" onClick={submitCompetitors} disabled={busy || !tracked.size}>
                {busy ? <span className="cs-spinner" /> : <ArrowRight size={15} />}
                Confirm {tracked.size} competitor{tracked.size === 1 ? '' : 's'}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {/* ---------------- Step 4: channels + schedule ---------------- */}
      {step === 4 ? (
        <>
          <div className="cs-alert cs-alert-info">
            <Info size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              Confirm each channel before we scrape it. Handles are found automatically and are
              sometimes wrong — an account belonging to another company would put their activity
              into your reports, so nothing is scraped until you approve it.
            </span>
          </div>

          {trackedCompetitors.map((competitor) => {
            const accounts = accountsByCompetitor[competitor.id] || [];
            return (
              <div key={competitor.id} className="cs-panel">
                <h2 className="cs-panel-title">
                  <span className="cs-avatar" style={{ background: avatarGradient(competitor.name), width: 26, height: 26, fontSize: '0.66rem' }} aria-hidden="true">
                    {initials(competitor.name)}
                  </span>
                  {competitor.name}
                </h2>
                {!accounts.length ? (
                  <p className="cs-panel-hint" style={{ marginBottom: 0 }}>
                    No channels found. You can add them later from the workspace.
                  </p>
                ) : (
                  <div className="cs-rows">
                    {accounts.map((account) => (
                      <div key={account.id} className="cs-row">
                        <div className="cs-row-main">
                          <div className="cs-row-name" style={{ textTransform: 'capitalize' }}>
                            {account.platform}
                            {account.handle ? <span style={{ fontWeight: 400, color: 'var(--text-light)' }}> @{account.handle}</span> : null}
                          </div>
                          <div className="cs-row-desc">{account.url}</div>
                        </div>
                        <div className="cs-row-side">
                          {account.confidence != null ? (
                            <span className="cs-pill cs-pill-signal">
                              {Math.round(Number(account.confidence) * 100)}% sure
                            </span>
                          ) : null}
                          <span className={`cs-pill cs-pill-${account.validation_status}`}>
                            {account.validation_status}
                          </span>
                          {account.validation_status !== 'valid' ? (
                            <button type="button" className="cs-btn cs-btn-sm"
                              onClick={() => decideAccount(competitor.id, account.id, 'valid')}>
                              <Check size={13} /> Confirm
                            </button>
                          ) : null}
                          {account.validation_status !== 'rejected' ? (
                            <button type="button" className="cs-btn cs-btn-sm cs-btn-danger"
                              onClick={() => decideAccount(competitor.id, account.id, 'rejected')}>
                              <Trash2 size={13} /> Not theirs
                            </button>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          <div className="cs-panel">
            <h2 className="cs-panel-title"><Globe size={16} /> Keep it current</h2>
            <p className="cs-panel-hint">
              Re-scrape confirmed channels on a schedule, using the same pipeline scheduler as the
              rest of Strata.
            </p>
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.88rem', marginBottom: 14 }}>
              <input type="checkbox" checked={scheduleOn} onChange={(event) => setScheduleOn(event.target.checked)} />
              Scrape competitors automatically
            </label>
            {scheduleOn ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: '0.88rem' }}>
                <span>Every</span>
                <input className="cs-input" type="number" min="1" style={{ width: 78 }}
                  value={scheduleDays} onChange={(event) => setScheduleDays(event.target.value)} />
                <span>day(s)</span>
              </div>
            ) : null}

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(3)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-light)' }}>
                  {validAccountCount} channel{validAccountCount === 1 ? '' : 's'} confirmed
                </span>
                <button type="button" className="cs-btn cs-btn-primary" onClick={finish} disabled={busy}>
                  {busy ? <span className="cs-spinner" /> : <CheckCircle2 size={15} />} Open workspace
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
