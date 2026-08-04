/**
 * Competitor study onboarding.
 *
 * Four steps, in the order the information actually becomes available:
 *
 *   1. Your business  — name + website. The website is what makes the rest work,
 *                       so it is asked for first and its scrape is shown honestly.
 *   2. Market context — the AI's reading of the site, editable. Shown rather than
 *                       hidden because everything downstream is judged against it.
 *   3. Competitors    — manual-first: add competitors and their sources directly,
 *                       and they are valid and scrape-ready immediately, no
 *                       confirmation step needed. "Suggest with AI" is an optional
 *                       action on the same screen; AI-suggested competitors and
 *                       their channels still need a quick review before they're
 *                       trusted the same way a manual entry already is.
 *   4. Schedule       — how often confirmed sources get re-scraped, then finish.
 *
 * Long steps (scrape, discovery) run tens of seconds, so each shows staged
 * progress instead of an indeterminate spinner.
 */

import { useMemo, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Building2, CalendarClock, Check, CheckCircle2, ChevronRight,
  Globe, Link2, Loader2, Plus, Radar, Search, Sparkles, Trash2, X,
} from 'lucide-react';
import {
  PLATFORM_LABELS, SIZE_TIER_LABELS, addAccount, addCompetitorManual, avatarGradient, buildProfile,
  createStudy, discoverCompetitors, initials, listAccounts, listCompetitors, pollDiscoveryRun,
  saveProfile, setCompetitorStatus, setSchedule, validateAccount,
} from '../competitorApi.js';
import { COUNTRIES, countryLabel } from '../constants/countries.js';
import { AddCompetitorForm, AddSourceRow } from './CompetitorSourceEditor.jsx';
import '../styles/Competitors.css';

const STEPS = [
  { id: 1, label: 'Your business', icon: Building2 },
  { id: 2, label: 'Market context', icon: Sparkles },
  { id: 3, label: 'Competitors', icon: Radar },
  { id: 4, label: 'Schedule', icon: CalendarClock },
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

/** Fixed-list country multi-select: type to filter, click a match to add,
 *  selected countries render as removable pills. Modeled on ListEditor above,
 *  since free text would let "USA" and "United States" reach the discovery
 *  prompt as different values. */
function CountryPicker({ label, hint, values, onChange }) {
  const [query, setQuery] = useState('');
  const selected = Array.isArray(values) ? values : [];
  const matches = query.trim()
    ? COUNTRIES.filter(
        (c) =>
          !selected.includes(c.code) &&
          (c.name.toLowerCase().includes(query.trim().toLowerCase()) ||
            c.code.toLowerCase() === query.trim().toLowerCase()),
      ).slice(0, 8)
    : [];

  const add = (code) => {
    if (!selected.includes(code)) onChange([...selected, code]);
    setQuery('');
  };

  return (
    <div className="cs-field">
      <label className="cs-label">
        {label}
        {hint ? <span className="cs-label-hint">{hint}</span> : null}
      </label>
      <div className="cs-pills" style={{ marginBottom: selected.length ? 9 : 0 }}>
        {selected.map((code) => (
          <span key={code} className="cs-pill">
            {countryLabel(code)}
            <button
              type="button"
              onClick={() => onChange(selected.filter((value) => value !== code))}
              aria-label={`Remove ${countryLabel(code)}`}
              style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'flex', color: 'inherit' }}
            >
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <div style={{ position: 'relative' }}>
        <input
          className="cs-input"
          value={query}
          placeholder="Search countries..."
          onChange={(event) => setQuery(event.target.value)}
        />
        {matches.length ? (
          <div className="cs-dropdown">
            {matches.map((c) => (
              <button key={c.code} type="button" className="cs-dropdown-item" onClick={() => add(c.code)}>
                {c.name}
              </button>
            ))}
          </div>
        ) : null}
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
  const [targetCountries, setTargetCountries] = useState([]);
  const [profile, setProfile] = useState(null);
  const [scrape, setScrape] = useState(null);

  const [competitors, setCompetitors] = useState([]);
  const [rejected, setRejected] = useState([]);
  const [addingManual, setAddingManual] = useState(false);
  const [discovering, setDiscovering] = useState(false);

  const [expandedChannels, setExpandedChannels] = useState(() => new Set());
  const [accountsByCompetitor, setAccountsByCompetitor] = useState({});
  const [sourceBusy, setSourceBusy] = useState({});

  const [scheduleDays, setScheduleDays] = useState(1);
  const [scheduleOn, setScheduleOn] = useState(true);

  const canLeaveStep1 = business.name.trim().length > 0;
  const trackedCompetitors = useMemo(
    () => competitors.filter((competitor) => competitor.status === 'tracked'),
    [competitors],
  );

  const refreshCompetitors = async () => {
    const result = await listCompetitors(studyId);
    setCompetitors(result.competitors || []);
  };

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
      const result = await buildProfile(id, { ...business, target_countries: targetCountries });
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

  // Step 2 -> 3: save any edits and move on. Competitors are added manually
  // from here; AI suggestion is an optional action on that screen, not a step.
  const submitContext = async () => {
    setError('');
    setBusy(true);
    try {
      const saved = await saveProfile(studyId, profile);
      setProfile(saved.profile);
      await refreshCompetitors();
      setStep(3);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  const handleAddManualCompetitor = async (payload) => {
    setError('');
    setAddingManual(true);
    try {
      const result = await addCompetitorManual(studyId, payload);
      await refreshCompetitors();
      setAccountsByCompetitor((current) => ({ ...current, [result.competitor.id]: result.accounts || [] }));
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAddingManual(false);
    }
  };

  const runAiSuggest = async () => {
    setError('');
    setDiscovering(true);
    try {
      const queued = await discoverCompetitors(studyId, { limit: 12, with_accounts: true });
      const run = await pollDiscoveryRun(studyId, queued.run_id);
      if (run.status === 'failed') {
        throw new Error(run.error || run.message || 'Competitor discovery failed.');
      }
      await refreshCompetitors();
      setRejected(run.rejected || []);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDiscovering(false);
    }
  };

  const toggleTracking = async (competitor) => {
    try {
      await setCompetitorStatus(competitor.id, competitor.status === 'tracked' ? 'ignored' : 'tracked');
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    }
  };

  const toggleChannels = async (competitorId) => {
    setExpandedChannels((current) => {
      const next = new Set(current);
      if (next.has(competitorId)) next.delete(competitorId);
      else next.add(competitorId);
      return next;
    });
    if (accountsByCompetitor[competitorId]) return;
    try {
      const result = await listAccounts(competitorId);
      setAccountsByCompetitor((current) => ({ ...current, [competitorId]: result.accounts || [] }));
    } catch (caught) {
      setError(caught.message);
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
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    }
  };

  const addSourceToCompetitor = async (competitorId, source) => {
    setSourceBusy((current) => ({ ...current, [competitorId]: true }));
    try {
      const result = await addAccount(competitorId, { ...source, validation_status: 'valid', confidence: 1 });
      setAccountsByCompetitor((current) => ({
        ...current,
        [competitorId]: [...(current[competitorId] || []), result.account],
      }));
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSourceBusy((current) => ({ ...current, [competitorId]: false }));
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

  return (
    <div className="cs-page cs-wizard">
      <div className="cs-head">
        <div>
          <h1>New competitor study</h1>
          <p>
            Strata reads your website to understand your market, then lets you add competitors
            yourself — sources you enter are trusted right away. AI suggestions are available if you
            want a head start, but nothing about tracking a competitor requires them.
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

          <CountryPicker
            label="Target countries"
            hint="optional — leave blank to search globally"
            values={targetCountries}
            onChange={setTargetCountries}
          />

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

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(1)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <button type="button" className="cs-btn cs-btn-primary" onClick={submitContext} disabled={busy}>
                {busy ? <span className="cs-spinner" /> : <ArrowRight size={15} />}
                {busy ? 'Saving...' : 'Continue to competitors'}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {/* ---------------- Step 3: competitors ---------------- */}
      {step === 3 ? (
        <>
          <div className="cs-panel">
            <h2 className="cs-panel-title"><Building2 size={16} /> Add your competitors</h2>
            <p className="cs-panel-hint">
              Add the companies you compete with directly. Sources you enter here are trusted
              immediately and start scraping right away — no confirmation step needed.
            </p>
            <AddCompetitorForm onSubmit={handleAddManualCompetitor} busy={addingManual} />
          </div>

          <div className="cs-panel">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <h2 className="cs-panel-title" style={{ marginBottom: 4 }}>
                  <Sparkles size={16} /> Not sure who else to add?
                </h2>
                <p className="cs-panel-hint" style={{ marginBottom: 0 }}>
                  Optional — AI compares your profile against the market and suggests competitors to
                  review. Their channels still need a quick check before they count as valid.
                </p>
              </div>
              <button type="button" className="cs-btn" onClick={runAiSuggest} disabled={discovering}>
                {discovering ? <span className="cs-spinner" /> : <Sparkles size={15} />}
                {discovering ? 'Suggesting...' : 'Suggest competitors with AI'}
              </button>
            </div>

            {discovering ? (
              <div className="cs-panel" style={{ marginTop: 14, background: '#fcfdff' }}>
                <StageList stages={DISCOVERY_STAGES} />
              </div>
            ) : null}

            {rejected.length ? (
              <details style={{ marginTop: 16 }}>
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
          </div>

          <div className="cs-panel">
            <h2 className="cs-panel-title"><Radar size={16} /> Your competitors</h2>
            <p className="cs-panel-hint">
              <strong>{trackedCompetitors.length}</strong> tracked. Manual sources are valid
              immediately; AI-suggested channels need a quick check before they are used.
            </p>

            {!competitors.length ? (
              <div className="cs-empty">
                <div className="cs-empty-icon"><Search size={20} /></div>
                <h3>No competitors yet</h3>
                <p>Add one above, or suggest some with AI.</p>
              </div>
            ) : (
              <div className="cs-rows">
                {competitors.map((competitor) => {
                  const channelsOpen = expandedChannels.has(competitor.id);
                  const accounts = accountsByCompetitor[competitor.id];
                  const isManual = competitor.discovery_source === 'manual';
                  const tracked = competitor.status === 'tracked';
                  return (
                    <div key={competitor.id}>
                      <div className={`cs-row${tracked ? ' cs-row-selected' : ''}`}>
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
                            {competitor.description || competitor.size_signals?.why_competitor || competitor.domain || '—'}
                          </div>
                        </div>
                        <div className="cs-row-side">
                          <span className={`cs-pill ${isManual ? 'cs-pill-manual' : 'cs-pill-ai'}`}>
                            {isManual ? 'Manual' : 'AI suggested'}
                          </span>
                          {competitor.country ? (
                            <span className="cs-pill cs-pill-signal">{countryLabel(competitor.country)}</span>
                          ) : null}
                          <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                            {SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}
                          </span>
                          <button type="button" className="cs-btn cs-btn-sm" onClick={() => toggleChannels(competitor.id)}>
                            <Link2 size={13} /> {channelsOpen ? 'Hide sources' : 'Sources'}
                          </button>
                          <button
                            type="button"
                            className={`cs-btn cs-btn-sm${tracked ? ' cs-btn-primary' : ''}`}
                            onClick={() => toggleTracking(competitor)}
                          >
                            {tracked ? <><Check size={13} /> Tracking</> : 'Track'}
                          </button>
                        </div>
                      </div>

                      {channelsOpen ? (
                        <div className="cs-rows" style={{ marginLeft: 30, marginBottom: 14 }}>
                          {!accounts ? (
                            <div className="cs-row-desc" style={{ padding: '8px 0' }}>Loading sources...</div>
                          ) : (
                            accounts.map((account) => (
                              <div key={account.id} className="cs-row">
                                <div className="cs-row-main">
                                  <div className="cs-row-name">
                                    {PLATFORM_LABELS[account.platform] || account.platform}
                                    {account.handle ? <span style={{ fontWeight: 400, color: 'var(--text-light)' }}> @{account.handle}</span> : null}
                                  </div>
                                  <div className="cs-row-desc">{account.url}</div>
                                </div>
                                <div className="cs-row-side">
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
                            ))
                          )}
                          <AddSourceRow
                            busy={Boolean(sourceBusy[competitor.id])}
                            onSubmit={(source) => addSourceToCompetitor(competitor.id, source)}
                          />
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(2)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <button
                type="button"
                className="cs-btn cs-btn-primary"
                onClick={() => setStep(4)}
                disabled={busy || !trackedCompetitors.length}
              >
                <ArrowRight size={15} />
                Continue with {trackedCompetitors.length} competitor{trackedCompetitors.length === 1 ? '' : 's'}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {/* ---------------- Step 4: schedule + finish ---------------- */}
      {step === 4 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Globe size={16} /> Keep it current</h2>
          <p className="cs-panel-hint">
            {trackedCompetitors.length} competitor{trackedCompetitors.length === 1 ? '' : 's'} ready to
            track. Re-scrape their sources on a schedule, using the same pipeline scheduler as the
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
            <button type="button" className="cs-btn cs-btn-primary" onClick={finish} disabled={busy}>
              {busy ? <span className="cs-spinner" /> : <CheckCircle2 size={15} />} Open workspace
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
