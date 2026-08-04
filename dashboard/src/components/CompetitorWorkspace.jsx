/**
 * Competitor workspace — the card grid.
 *
 * Each card answers the same three questions in the same order, so the eye learns
 * the shape once: what they're up to, how it affects us, what to do. Cards are
 * ordered by impact then competitor size, because the point of the screen is to
 * put the thing worth acting on first rather than the most recent thing.
 *
 * Clicking a card opens the full report. The card is a genuine <button> so it is
 * keyboard-reachable, since the whole surface is the click target.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, BarChart3, CalendarClock, Check, ChevronRight, Filter,
  Layers, Lightbulb, Link2, Plus, Radar, RefreshCw, Search, ShieldCheck, Sparkles, Target, Trash2, TrendingUp, X,
} from 'lucide-react';
import {
  IMPACT_LABELS, PLATFORM_LABELS, SIZE_TIER_LABELS, addAccount, addCompetitorManual, analyze,
  avatarGradient, discoverAccounts, discoverCompetitors, getStudy, initials, listAccounts,
  listCompetitors, listFindings, pollDiscoveryRun, relativeTime, setCompetitorStatus,
  syncSources, validateAccount,
} from '../competitorApi.js';
import { countryLabel } from '../constants/countries.js';
import { AddCompetitorForm, AddSourceRow } from './CompetitorSourceEditor.jsx';
import '../styles/Competitors.css';

const IMPACT_FILTERS = [
  { key: '', label: 'All impact' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
];

function FindingCard({ finding, onOpen }) {
  const actions = Array.isArray(finding.actions) ? finding.actions : [];
  const signals = Array.isArray(finding.signals) ? finding.signals : [];
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];

  return (
    <button type="button" className="cs-card" onClick={() => onOpen(finding.id)}>
      <span className={`cs-card-spine cs-card-spine-${finding.impact_level}`} aria-hidden="true" />
      <div className="cs-card-body">
        <div className="cs-card-top">
          <div className="cs-card-competitor">
            <span className="cs-avatar" style={{ background: avatarGradient(finding.competitor_name) }} aria-hidden="true">
              {initials(finding.competitor_name)}
            </span>
            <div style={{ minWidth: 0 }}>
              <p className="cs-card-name">{finding.competitor_name}</p>
              <p className="cs-card-domain">
                {finding.competitor_domain || '-'}
                {finding.size_tier ? ` · ${SIZE_TIER_LABELS[finding.size_tier] || finding.size_tier}` : ''}
              </p>
            </div>
          </div>
          <span className={`cs-pill cs-pill-${finding.impact_level}`}>
            {IMPACT_LABELS[finding.impact_level] || finding.impact_level}
          </span>
        </div>

        <h3 className="cs-card-headline">{finding.headline}</h3>

        <div className="cs-answer">
          <span className="cs-answer-label"><Activity size={11} /> What they&rsquo;re up to</span>
          <p className="cs-answer-text cs-answer-clamp">{finding.whats_up}</p>
        </div>

        <div className="cs-answer">
          <span className="cs-answer-label"><Target size={11} /> How it affects us</span>
          <p className="cs-answer-text cs-answer-clamp">{finding.impact}</p>
        </div>

        {actions.length ? (
          <div className="cs-answer">
            <span className="cs-answer-label"><Lightbulb size={11} /> Suggested actions</span>
            <ul className="cs-actions-preview">
              {actions.slice(0, 2).map((item, index) => (
                <li key={index}>{item.action}</li>
              ))}
            </ul>
            {actions.length > 2 ? (
              <span style={{ fontSize: '0.79rem', color: 'var(--text-light)', paddingLeft: 17 }}>
                +{actions.length - 2} more
              </span>
            ) : null}
          </div>
        ) : null}

        {signals.length ? (
          <div className="cs-pills">
            {signals.slice(0, 4).map((signal) => (
              <span key={signal} className="cs-pill cs-pill-signal">{signal}</span>
            ))}
          </div>
        ) : null}

        <div className="cs-card-foot">
          <span>
            {finding.story_count} source{finding.story_count === 1 ? '' : 's'}
            {evidence.length ? ` · ${evidence.length} cited` : ''}
            {finding.generated_at ? ` · ${relativeTime(finding.generated_at)}` : ''}
          </span>
          <span className="cs-card-foot-open">Full report <ChevronRight size={13} /></span>
        </div>
      </div>
    </button>
  );
}

function StatTile({ icon: Icon, label, value, tone }) {
  return (
    <div className="cs-panel" style={{ padding: '15px 17px', flex: '1 1 150px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--text-light)', fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        <Icon size={13} /> {label}
      </div>
      <div style={{ fontSize: '1.5rem', fontWeight: 680, marginTop: 6, color: tone || 'var(--text-dark)', letterSpacing: '-0.02em' }}>
        {value}
      </div>
    </div>
  );
}

export default function CompetitorWorkspace() {
  const { studyId } = useParams();
  const navigate = useNavigate();

  const [study, setStudy] = useState(null);
  const [profile, setProfile] = useState(null);
  const [competitors, setCompetitors] = useState([]);
  const [findings, setFindings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [runMode, setRunMode] = useState(null); // 'scrape' | 'direct' - which choice is currently running
  const [showRunChoice, setShowRunChoice] = useState(false);
  const [notice, setNotice] = useState(null);
  const [impact, setImpact] = useState('');
  const [showCompetitors, setShowCompetitors] = useState(false);
  const [expandedChannels, setExpandedChannels] = useState(() => new Set());
  const [accountsByCompetitor, setAccountsByCompetitor] = useState({});
  const [channelBusy, setChannelBusy] = useState({});
  const [showAddCompetitor, setShowAddCompetitor] = useState(false);
  const [addingManual, setAddingManual] = useState(false);
  const [discoveringCompetitors, setDiscoveringCompetitors] = useState(false);
  const [discoveryNotice, setDiscoveryNotice] = useState(null);

  // Fetch inside the effect with a cancel guard, so switching studies mid-request
  // cannot resolve into the newly-selected study's state.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [detail, competitorList] = await Promise.all([
          getStudy(studyId),
          listCompetitors(studyId),
        ]);
        if (cancelled) return;
        setStudy(detail.study);
        setProfile(detail.profile);
        setFindings(detail.findings || []);
        setCompetitors(competitorList.competitors || []);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId]);

  const applyFilter = async (next) => {
    setImpact(next);
    try {
      const result = await listFindings(studyId, { impact: next || undefined });
      setFindings(result.findings || []);
    } catch (caught) {
      setError(caught.message);
    }
  };

  // Never scraped before - hint which choice to lead with in the run dialog.
  const likelyNeedsScrape = !study?.last_run_at;

  const runAnalysis = async (scrapeFirst) => {
    setShowRunChoice(false);
    setRunMode(scrapeFirst ? 'scrape' : 'direct');
    setAnalyzing(true);
    setError('');
    setNotice(null);
    try {
      await syncSources(studyId);
      const result = await analyze(studyId, { period_days: 30, scrape: scrapeFirst });
      setFindings(result.findings || []);
      const validation = result.validation || {};
      const reasons = validation.rejection_reasons || {};
      setNotice({
        generated: result.generated,
        scanned: validation.scanned || 0,
        skipped: result.skipped || [],
        reasons,
        scrapedFirst: Boolean(result.scrape_run),
        scrapeRun: result.scrape_run || null,
      });
      setImpact('');
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const toggleTracking = async (competitor) => {
    try {
      await setCompetitorStatus(competitor.id, competitor.status === 'tracked' ? 'ignored' : 'tracked');
      const result = await listCompetitors(studyId);
      setCompetitors(result.competitors || []);
    } catch (caught) {
      setError(caught.message);
    }
  };

  // Confirmed/valid, pending, and account_count are aggregate counts on the
  // competitor row itself - refetch them after any channel action so the
  // "N pending" banner and per-row counts stay in sync with what was just done.
  const refreshCompetitorCounts = async () => {
    try {
      const result = await listCompetitors(studyId);
      setCompetitors(result.competitors || []);
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
      await refreshCompetitorCounts();
    } catch (caught) {
      setError(caught.message);
    }
  };

  const findChannels = async (competitorId) => {
    setChannelBusy((current) => ({ ...current, [competitorId]: true }));
    try {
      const result = await discoverAccounts(competitorId);
      setAccountsByCompetitor((current) => ({ ...current, [competitorId]: result.accounts || [] }));
      await refreshCompetitorCounts();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setChannelBusy((current) => ({ ...current, [competitorId]: false }));
    }
  };

  const addSourceToCompetitor = async (competitorId, source) => {
    setChannelBusy((current) => ({ ...current, [competitorId]: true }));
    try {
      const result = await addAccount(competitorId, { ...source, validation_status: 'valid', confidence: 1 });
      setAccountsByCompetitor((current) => ({
        ...current,
        [competitorId]: [...(current[competitorId] || []), result.account],
      }));
      await refreshCompetitorCounts();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setChannelBusy((current) => ({ ...current, [competitorId]: false }));
    }
  };

  const handleAddManualCompetitor = async (payload) => {
    setError('');
    setAddingManual(true);
    try {
      await addCompetitorManual(studyId, payload);
      await refreshCompetitorCounts();
      setShowAddCompetitor(false);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAddingManual(false);
    }
  };

  // Optional, from the workspace rather than onboarding - runs the same
  // background discovery job and merges results into the existing list.
  const runDiscovery = async () => {
    setError('');
    setDiscoveryNotice(null);
    setDiscoveringCompetitors(true);
    try {
      const queued = await discoverCompetitors(studyId, { limit: 12, with_accounts: true });
      const run = await pollDiscoveryRun(studyId, queued.run_id);
      if (run.status === 'failed') {
        throw new Error(run.error || run.message || 'Competitor discovery failed.');
      }
      await refreshCompetitorCounts();
      setShowCompetitors(true);
      setDiscoveryNotice({ discovered: run.discovered || 0, rejected: run.rejected || [] });
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDiscoveringCompetitors(false);
    }
  };

  const stats = useMemo(() => {
    const tracked = competitors.filter((item) => item.status === 'tracked');
    const pendingChannels = competitors.reduce((sum, item) => sum + (item.pending_account_count || 0), 0);
    const highImpact = findings.filter((item) => item.impact_level === 'high').length;
    return { tracked: tracked.length, pendingChannels, highImpact };
  }, [competitors, findings]);

  if (loading) {
    return (
      <div className="cs-page">
        <div className="cs-skeleton" style={{ height: 34, width: 280, marginBottom: 12 }} />
        <div className="cs-skeleton" style={{ height: 18, width: 460, marginBottom: 28 }} />
        <div className="cs-card-grid">
          {[0, 1, 2].map((key) => (
            <div key={key} className="cs-skeleton" style={{ height: 300 }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="cs-page">
      <div className="cs-head">
        <div>
          <Link to="/competitors" className="cs-link-back">
            <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> All studies
          </Link>
          <h1>{study?.name || 'Competitor study'}</h1>
          <p>
            {profile?.name ? (
              <>
                Measured against <strong>{profile.name}</strong>
                {profile.market ? ` in ${profile.market}` : ''}. Each card is one competitor: what
                they are doing, what it means for you, and what to do about it.
              </>
            ) : (
              'Add your business profile so competitor activity can be judged against it.'
            )}
          </p>
        </div>
        <div className="cs-head-actions">
          <button type="button" className="cs-btn" onClick={() => setShowCompetitors((value) => !value)}>
            <Layers size={15} /> {competitors.length} competitor{competitors.length === 1 ? '' : 's'}
          </button>
          <button type="button" className="cs-btn" onClick={runDiscovery} disabled={discoveringCompetitors}>
            {discoveringCompetitors ? <span className="cs-spinner" /> : <Radar size={15} />}
            {discoveringCompetitors ? 'Discovering...' : 'Discover with AI'}
          </button>
          <button type="button" className="cs-btn cs-btn-primary" onClick={() => setShowRunChoice(true)} disabled={analyzing}>
            {analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />}
            {analyzing ? (runMode === 'scrape' ? 'Scraping & analysing...' : 'Analysing...') : 'Run analysis'}
          </button>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{error}</span>
        </div>
      ) : null}

      {discoveryNotice ? (
        <div className="cs-alert cs-alert-info">
          <Sparkles size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            Discovered {discoveryNotice.discovered} competitor{discoveryNotice.discovered === 1 ? '' : 's'}.
            {discoveryNotice.rejected.length
              ? ` ${discoveryNotice.rejected.length} suggestion${discoveryNotice.rejected.length === 1 ? '' : 's'} dropped during checking.`
              : ''}
            {' '}Review them in the competitors list below.
          </span>
        </div>
      ) : null}

      {stats.pendingChannels > 0 ? (
        <div className="cs-alert cs-alert-warn">
          <ShieldCheck size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            {stats.pendingChannels} channel{stats.pendingChannels === 1 ? '' : 's'} still awaiting
            confirmation. Unconfirmed channels are not scraped, so their activity is missing from
            these reports.{' '}
            <button type="button" onClick={() => setShowCompetitors(true)}
              style={{ background: 'none', border: 'none', padding: 0, color: 'inherit', fontWeight: 700, textDecoration: 'underline', cursor: 'pointer' }}>
              Review them
            </button>
          </span>
        </div>
      ) : null}

      {notice ? (
        <div className="cs-alert cs-alert-info">
          <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            {notice.scrapedFirst ? (
              <>
                This study had no articles yet, so we scraped and enriched its sources first
                {notice.scrapeRun?.articles_saved ? ` (${notice.scrapeRun.articles_saved} saved)` : ''}, then{' '}
              </>
            ) : null}
            Generated {notice.generated} report{notice.generated === 1 ? '' : 's'} from{' '}
            {notice.scanned} scanned article{notice.scanned === 1 ? '' : 's'}.
            {Object.keys(notice.reasons).length ? (
              <>
                {' '}Filtered out:{' '}
                {Object.entries(notice.reasons)
                  .map(([reason, count]) => `${count} ${reason.replace(/_/g, ' ')}`)
                  .join(', ')}
                .
              </>
            ) : null}
            {notice.skipped.length ? (
              <> {notice.skipped.length} competitor{notice.skipped.length === 1 ? '' : 's'} had no
                usable evidence this period.</>
            ) : null}
          </span>
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 20 }}>
        <StatTile icon={Radar} label="Tracked" value={stats.tracked} />
        <StatTile icon={BarChart3} label="Reports" value={findings.length} />
        <StatTile icon={TrendingUp} label="High impact" value={stats.highImpact}
          tone={stats.highImpact ? '#b91c1c' : undefined} />
        <StatTile icon={CalendarClock} label="Last run"
          value={study?.last_run_at ? relativeTime(study.last_run_at) : 'Never'} />
      </div>

      {showCompetitors ? (
        <div className="cs-panel" style={{ marginBottom: 20 }}>
          <h2 className="cs-panel-title"><Layers size={16} /> Competitors</h2>
          <p className="cs-panel-hint">
            Only tracked competitors are scraped and analysed. Ranked by size.
          </p>

          <div style={{ marginBottom: 18, paddingBottom: 18, borderBottom: '1px solid #eef1f6' }}>
            {showAddCompetitor ? (
              <AddCompetitorForm onSubmit={handleAddManualCompetitor} busy={addingManual} />
            ) : (
              <button type="button" className="cs-btn cs-btn-sm" onClick={() => setShowAddCompetitor(true)}>
                <Plus size={13} /> Add competitor manually
              </button>
            )}
          </div>

          <div className="cs-rows">
            {competitors.map((competitor) => {
              const channelsOpen = expandedChannels.has(competitor.id);
              const accounts = accountsByCompetitor[competitor.id];
              return (
                <div key={competitor.id}>
                  <div className="cs-row">
                    <span className="cs-row-rank">{competitor.size_rank ?? '-'}</span>
                    <div className="cs-avatar" style={{ background: avatarGradient(competitor.name), width: 30, height: 30, fontSize: '0.72rem' }} aria-hidden="true">
                      {initials(competitor.name)}
                    </div>
                    <div className="cs-row-main">
                      <div className="cs-row-name">{competitor.name}</div>
                      <div className="cs-row-desc">
                        {competitor.valid_account_count}/{competitor.account_count} channels confirmed
                        {competitor.pending_account_count ? ` · ${competitor.pending_account_count} pending` : ''}
                        {competitor.finding_count ? ` · ${competitor.finding_count} report(s)` : ''}
                      </div>
                    </div>
                    <div className="cs-row-side">
                      {competitor.country ? (
                        <span className="cs-pill cs-pill-signal">{countryLabel(competitor.country)}</span>
                      ) : null}
                      <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                        {SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}
                      </span>
                      <button type="button" className="cs-btn cs-btn-sm" onClick={() => toggleChannels(competitor.id)}>
                        <Link2 size={13} /> {channelsOpen ? 'Hide channels' : 'Channels'}
                      </button>
                      <button type="button" className={`cs-btn cs-btn-sm${competitor.status === 'tracked' ? ' cs-btn-primary' : ''}`}
                        onClick={() => toggleTracking(competitor)}>
                        {competitor.status === 'tracked' ? <><Check size={13} /> Tracking</> : 'Track'}
                      </button>
                    </div>
                  </div>

                  {channelsOpen ? (
                    <div className="cs-rows" style={{ marginLeft: 30, marginBottom: 14 }}>
                      {!accounts ? (
                        <div className="cs-row-desc" style={{ padding: '8px 0' }}>Loading channels...</div>
                      ) : !accounts.length ? (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0' }}>
                          <span className="cs-row-desc">No channels found yet.</span>
                          <button type="button" className="cs-btn cs-btn-sm"
                            onClick={() => findChannels(competitor.id)} disabled={channelBusy[competitor.id]}>
                            {channelBusy[competitor.id] ? <span className="cs-spinner" /> : <Search size={13} />} Find channels
                          </button>
                        </div>
                      ) : null}
                      {accounts?.length ? (
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
                        ))
                      ) : null}
                      {Array.isArray(accounts) ? (
                        <AddSourceRow
                          busy={Boolean(channelBusy[competitor.id])}
                          onSubmit={(source) => addSourceToCompetitor(competitor.id, source)}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {findings.length ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 15, flexWrap: 'wrap' }}>
            <Filter size={14} style={{ color: 'var(--text-light)' }} />
            {IMPACT_FILTERS.map((option) => (
              <button key={option.key} type="button"
                className={`cs-btn cs-btn-sm${impact === option.key ? ' cs-btn-primary' : ''}`}
                onClick={() => applyFilter(option.key)} aria-pressed={impact === option.key}>
                {option.label}
              </button>
            ))}
          </div>

          <div className="cs-card-grid">
            {findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding}
                onOpen={(id) => navigate(`/competitors/${studyId}/reports/${id}`)} />
            ))}
          </div>
        </>
      ) : (
        <div className="cs-empty">
          <div className="cs-empty-icon"><Sparkles size={20} /></div>
          <h3>No reports yet</h3>
          <p>
            {stats.tracked
              ? 'Competitors are tracked but nothing has been analysed. Run the analysis to scrape fresh evidence or read what is already on file.'
              : 'Track at least one competitor, confirm their channels, then run the analysis.'}
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            {stats.tracked ? (
              <button type="button" className="cs-btn cs-btn-primary" onClick={() => setShowRunChoice(true)} disabled={analyzing}>
                {analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />}
                {analyzing ? (runMode === 'scrape' ? 'Scraping & analysing...' : 'Analysing...') : 'Run analysis'}
              </button>
            ) : (
              <button type="button" className="cs-btn cs-btn-primary" onClick={() => setShowCompetitors(true)}>
                <Layers size={15} /> Choose competitors
              </button>
            )}
          </div>
        </div>
      )}

      {showRunChoice ? (
        <div className="confirm-modal-backdrop" role="presentation" onClick={() => setShowRunChoice(false)}>
          <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="run-analysis-title"
            aria-describedby="run-analysis-message" onClick={(event) => event.stopPropagation()}>
            <div className="confirm-modal-header">
              <h2 id="run-analysis-title" className="confirm-modal-title">Run analysis</h2>
              <button type="button" className="confirm-modal-close" onClick={() => setShowRunChoice(false)} aria-label="Close dialog">
                <X size={18} />
              </button>
            </div>

            <p id="run-analysis-message" className="confirm-modal-message">
              Scrape this study&rsquo;s sources for fresh articles first, or analyse the evidence already on file?
              {' '}{study?.last_run_at ? `Last scraped ${relativeTime(study.last_run_at)}.` : 'This study has never been scraped.'}
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '4px 0 6px' }}>
              <button type="button" onClick={() => runAnalysis(true)}
                className={`cs-btn${likelyNeedsScrape ? ' cs-btn-primary' : ''}`}
                style={{ justifyContent: 'flex-start', width: '100%' }}>
                <RefreshCw size={15} />
                <span style={{ textAlign: 'left', flex: 1 }}>Scrape &amp; analyze</span>
                {likelyNeedsScrape ? <span style={{ fontSize: '0.72rem', opacity: 0.85 }}>Recommended</span> : null}
              </button>
              <button type="button" onClick={() => runAnalysis(false)}
                className={`cs-btn${likelyNeedsScrape ? '' : ' cs-btn-primary'}`}
                style={{ justifyContent: 'flex-start', width: '100%' }}>
                <Sparkles size={15} />
                <span style={{ textAlign: 'left', flex: 1 }}>Analyze existing articles</span>
                {likelyNeedsScrape ? null : <span style={{ fontSize: '0.72rem', opacity: 0.85 }}>Recommended</span>}
              </button>
            </div>

            <div className="confirm-modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowRunChoice(false)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
