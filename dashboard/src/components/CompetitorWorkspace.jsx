/**
 * Competitor reports — the card grid.
 *
 * Each card answers the same three questions in the same order, so the eye learns
 * the shape once: what they're up to, how it affects us, what to do. Cards are
 * ordered by impact then competitor size, because the point of the screen is to
 * put the thing worth acting on first rather than the most recent thing.
 *
 * Clicking a card opens the full report. The card is a genuine <button> so it is
 * keyboard-reachable, since the whole surface is the click target.
 *
 * Managing who's tracked lives on the Competitors page; editing the study and
 * its business profile lives on the Full edit page - this screen is just the
 * evidence and the action to (re)generate it.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, BarChart3, CalendarClock, Check, ChevronRight,
  Layers, LayoutGrid, Lightbulb, List, Pencil, Radar, Search,
  Sparkles, Target, TrendingUp, Upload, X,
} from 'lucide-react';
import {
  IMPACT_LABELS, SIZE_TIER_LABELS, avatarGradient, getStudy,
  initials, listCompetitors, listFindings,
} from '../api/competitorApi.js';
import { formatDate, formatRelativeTime, formatTime } from '../lib/i18nFormat.js';
import { useAuth } from '../auth/useAuth.js';
import {
  RunAnalysisButton, RunAnalysisChoiceModal, RunAnalysisLog,
} from './CompetitorRunAnalysis.jsx';
import { useRunAnalysis } from '../useRunAnalysis.js';
import '../styles/Competitors.css';

function impactLabel(t, level) {
  return t(`labels.impact.${level}`, { defaultValue: IMPACT_LABELS[level] || level });
}

function sizeTierLabel(t, tier) {
  return t(`labels.sizeTier.${tier}`, { defaultValue: SIZE_TIER_LABELS[tier] || tier });
}

/** Localized replacement for useRunAnalysis.js's analysisRunTitle() - same
 *  shape ("Analysis #N: <date> <time>"), but translated and using the shared
 *  locale-aware date formatters instead of an implicit browser locale.
 *  useRunAnalysis.js isn't owned by this pass, so this stays local rather
 *  than changing that shared export. */
function analysisRunTitle(t, locale, run) {
  const value = run?.finished_at || run?.started_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return t('workspace.analysisRunFallback');
  const formatted = `${formatDate(date, locale, { month: 'short', day: 'numeric' })} ${formatTime(date, locale)}`;
  return t('workspace.analysisRunLabel', { number: run?.sequence_number ?? '?', date: formatted });
}

function FindingCard({ finding, onOpen, t, locale }) {
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
              <p className="cs-card-name" dir="auto">{finding.competitor_name}</p>
              <p className="cs-card-domain" dir="auto">
                {finding.competitor_domain || '-'}
                {finding.size_tier ? ` · ${sizeTierLabel(t, finding.size_tier)}` : ''}
              </p>
            </div>
          </div>
          <span className={`cs-pill cs-pill-${finding.impact_level}`}>
            {impactLabel(t, finding.impact_level)}
          </span>
        </div>

        <h3 className="cs-card-headline" dir="auto">{finding.headline}</h3>

        <div className="cs-answer">
          <span className="cs-answer-label"><Activity size={11} /> {t('shared.whatTheyreUpTo')}</span>
          <p className="cs-answer-text cs-answer-clamp" dir="auto">{finding.whats_up}</p>
        </div>

        <div className="cs-answer">
          <span className="cs-answer-label"><Target size={11} /> {t('shared.howItAffectsUs')}</span>
          <p className="cs-answer-text cs-answer-clamp" dir="auto">{finding.impact}</p>
        </div>

        {actions.length ? (
          <div className="cs-answer">
            <span className="cs-answer-label"><Lightbulb size={11} /> {t('shared.suggestedActions')}</span>
            <ul className="cs-actions-preview">
              {actions.slice(0, 2).map((item, index) => (
                <li key={index} dir="auto">{item.action}</li>
              ))}
            </ul>
            {actions.length > 2 ? (
              <span style={{ fontSize: '0.79rem', color: 'var(--text-light)', paddingLeft: 17 }}>
                {t('workspace.moreActions', { count: actions.length - 2 })}
              </span>
            ) : null}
          </div>
        ) : null}

        {signals.length ? (
          <div className="cs-pills">
            {signals.slice(0, 4).map((signal) => (
              <span key={signal} className="cs-pill cs-pill-signal" dir="auto">{signal}</span>
            ))}
          </div>
        ) : null}

        <div className="cs-card-foot">
          <span>
            {t('workspace.sourceCount', { count: finding.story_count })}
            {evidence.length ? ` · ${t('workspace.citedCount', { count: evidence.length })}` : ''}
            {finding.generated_at ? ` · ${formatRelativeTime(finding.generated_at, locale)}` : ''}
          </span>
          <span className="cs-card-foot-open">{t('workspace.fullReport')} <ChevronRight size={13} className="rtl-mirror" /></span>
        </div>
      </div>
    </button>
  );
}

function FindingRow({ finding, onOpen, t, locale }) {
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];

  return (
    <button type="button" className="cs-finding-row" onClick={() => onOpen(finding.id)}>
      <span className={`cs-pill cs-pill-${finding.impact_level}`}>
        {impactLabel(t, finding.impact_level)}
      </span>
      <span className="cs-avatar cs-finding-row-avatar" style={{ background: avatarGradient(finding.competitor_name) }} aria-hidden="true">
        {initials(finding.competitor_name)}
      </span>
      <span className="cs-finding-row-main">
        <span className="cs-finding-row-name" dir="auto">{finding.competitor_name}</span>
        <span className="cs-finding-row-headline" dir="auto">{finding.headline}</span>
      </span>
      <span className="cs-finding-row-meta">
        {t('workspace.sourceCount', { count: finding.story_count })}
        {evidence.length ? ` · ${t('workspace.citedCount', { count: evidence.length })}` : ''}
        {finding.generated_at ? ` · ${formatRelativeTime(finding.generated_at, locale)}` : ''}
      </span>
      <ChevronRight size={15} className="cs-finding-row-chevron rtl-mirror" />
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
  const { t, i18n } = useTranslation('competitors');
  const locale = i18n.language;
  const { studyId } = useParams();
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canManage = hasPermission('competitors.manage');

  const IMPACT_FILTERS = [
    { key: '', label: t('workspace.impactFilters.all') },
    { key: 'high', label: t('workspace.impactFilters.high') },
    { key: 'medium', label: t('workspace.impactFilters.medium') },
    { key: 'low', label: t('workspace.impactFilters.low') },
  ];

  const VIEW_MODES = [
    { value: 'card', label: t('shared.viewModes.card'), icon: LayoutGrid },
    { value: 'list', label: t('shared.viewModes.list'), icon: List },
  ];

  const [study, setStudy] = useState(null);
  const [profile, setProfile] = useState(null);
  const [competitors, setCompetitors] = useState([]);
  const [findings, setFindings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(null);
  const [impact, setImpact] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  // Filters the reports list by which analysis run generated the evidence -
  // separate from the scope picker in the run-analysis modal, which picks
  // what a *new* analysis run should read. Not defaulted to the latest run:
  // unlike starting a fresh analysis, opening the reports list should show
  // everything already on file until the user asks to narrow it.
  const [findingsRunId, setFindingsRunId] = useState(null);
  const [findingsLoading, setFindingsLoading] = useState(false);
  const [viewMode, setViewMode] = useState(() => {
    try {
      return window.localStorage.getItem('competitors-view-mode') === 'list' ? 'list' : 'card';
    } catch {
      return 'card';
    }
  });

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

  // Debounce the free-text search the same way ArticlesPage does, so every
  // keystroke doesn't fire its own request.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Findings are fetched separately from the study/competitors load above so
  // that changing a filter never has to re-fetch all of those too.
  useEffect(() => {
    if (!studyId) return undefined;
    let cancelled = false;
    (async () => {
      setFindingsLoading(true);
      try {
        const result = await listFindings(studyId, {
          impact: impact || undefined,
          search: search || undefined,
          // Mutually exclusive on the server too: a specific run already
          // names a fixed set of evidence, so a date box layered on top
          // would just silently narrow it further.
          date_from: findingsRunId ? undefined : (dateFrom || undefined),
          date_to: findingsRunId ? undefined : (dateTo || undefined),
          analysis_run_id: findingsRunId || undefined,
        });
        if (!cancelled) setFindings(result.findings || []);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setFindingsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId, impact, search, dateFrom, dateTo, findingsRunId]);

  const hasFindingFilters = Boolean(impact || search || dateFrom || dateTo || findingsRunId);

  const clearFindingFilters = () => {
    setImpact('');
    setSearchInput('');
    setSearch('');
    setDateFrom('');
    setDateTo('');
    setFindingsRunId(null);
  };

  const changeViewMode = (mode) => {
    setViewMode(mode);
    try {
      window.localStorage.setItem('competitors-view-mode', mode);
    } catch {
      // ignore - persistence is a nicety, not a requirement
    }
  };

  const run = useRunAnalysis(studyId, {
    onSuccess: (result) => {
      setFindings(result.findings || []);
      const validation = result.validation || {};
      setNotice({
        generated: result.generated,
        scanned: validation.scanned || 0,
        // From the run, not the picker: reports how many documents this run
        // actually read, which stays right even if the scope choice is
        // changed afterwards.
        documentCount: validation.document_ids?.length || null,
        skipped: result.skipped || [],
        reasons: validation.rejection_reasons || {},
      });
      clearFindingFilters();
    },
    onError: (message) => setError(message),
  });

  const stats = useMemo(() => {
    const tracked = competitors.filter((item) => item.status === 'tracked');
    const highImpact = findings.filter((item) => item.impact_level === 'high').length;
    return { tracked: tracked.length, highImpact };
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
            <ChevronRight size={14} className="rtl-mirror" style={{ transform: 'rotate(180deg)' }} /> {t('workspace.backToAllStudies')}
          </Link>
          <h1 dir="auto">{study?.name || t('shared.competitorStudyFallback')}</h1>
          <p>
            {profile?.name ? (
              <>
                {t('workspace.measuredAgainstPrefix')} <strong dir="auto">{profile.name}</strong>
                {profile.market ? t('workspace.inMarket', { market: profile.market }) : ''}
                {t('workspace.measuredAgainstSuffix')}
              </>
            ) : (
              t('workspace.noProfileHint')
            )}
          </p>
        </div>
        <div className="cs-head-actions">
          <RunAnalysisButton run={run} label={t('runAnalysis.runAnalysisLabel')} />
          <Link to={`/competitors/${studyId}/manage`} className="cs-btn">
            <Layers size={15} /> {t('workspace.competitorCount', { count: competitors.length })}
          </Link>
          {canManage ? (
            <Link to={`/competitors/${studyId}/documents`} className="cs-btn">
              <Upload size={15} /> {t('workspace.addDocuments')}
            </Link>
          ) : null}
          {canManage ? (
            <Link to={`/competitors/${studyId}/edit`} className="cs-btn">
              <Pencil size={15} /> {t('shared.fullEdit')}
            </Link>
          ) : null}
        </div>
      </div>

      <RunAnalysisLog run={run} />

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span dir="auto">{error}</span>
        </div>
      ) : null}

      {notice ? (
        <div className="cs-alert cs-alert-info">
          <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            {t('workspace.notice.reportsGenerated', { count: notice.generated })}{' '}
            {t('workspace.notice.fromArticles', { count: notice.scanned })}
            {notice.documentCount ? ` ${t('workspace.notice.acrossDocuments', { count: notice.documentCount })}` : ''}.
            {Object.keys(notice.reasons || {}).length ? (
              <>
                {' '}{t('workspace.notice.filteredOutPrefix')}{' '}
                {Object.entries(notice.reasons)
                  .map(([reason, count]) => `${count} ${reason.replace(/_/g, ' ')}`)
                  .join(', ')}
                .
              </>
            ) : null}
            {notice.skipped?.length ? (
              <> {t('workspace.notice.skipped', { count: notice.skipped.length })} —{' '}
                {notice.skipped.map((item) => `${item.name}: ${item.reason}`).join(' ')}</>
            ) : null}
          </span>
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 20 }}>
        <StatTile icon={Radar} label={t('workspace.stats.tracked')} value={stats.tracked} />
        <StatTile icon={BarChart3} label={t('workspace.stats.reports')} value={findings.length} />
        <StatTile icon={TrendingUp} label={t('workspace.stats.highImpact')} value={stats.highImpact}
          tone={stats.highImpact ? '#b91c1c' : undefined} />
        <StatTile icon={CalendarClock} label={t('workspace.stats.lastRun')}
          value={study?.last_run_at ? formatRelativeTime(study.last_run_at, locale) : t('workspace.stats.never')} />
      </div>

      {(findings.length > 0 || hasFindingFilters) ? (
        <>
          <div className="cs-panel cs-findings-toolbar">
            <label className="cs-search-field">
              <Search size={16} />
              <input
                type="text"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t('workspace.searchPlaceholder')}
              />
            </label>

            <select className="cs-select" value={impact} onChange={(event) => setImpact(event.target.value)}
              aria-label={t('workspace.filterByImpactAria')}>
              {IMPACT_FILTERS.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
            </select>

            <div className="filter-tabs-shell" style={{ margin: 0 }}>
              <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label={t('workspace.filterReportsByAria')}>
                <button type="button" role="tab" aria-selected={!findingsRunId}
                  className={`source-type-tab ${!findingsRunId ? 'active' : ''}`}
                  onClick={() => setFindingsRunId(null)}>
                  {t('workspace.dateRangeTab')}
                </button>
                {run.analysisRuns.length > 0 ? (
                  <button type="button" role="tab" aria-selected={!!findingsRunId}
                    className={`source-type-tab ${findingsRunId ? 'active' : ''}`}
                    onClick={() => setFindingsRunId(findingsRunId || run.analysisRuns[0].id)}>
                    {t('workspace.analysisRunTab')}
                  </button>
                ) : null}
              </div>
            </div>

            {findingsRunId ? (
              run.analysisRuns.length > 3 ? (
                <select className="cs-select filter-run-select" value={findingsRunId}
                  onChange={(event) => setFindingsRunId(event.target.value)}
                  aria-label={t('workspace.filterByAnalysisRunAria')}>
                  {run.analysisRuns.map((analysisRun) => (
                    <option key={analysisRun.id} value={analysisRun.id}>{analysisRunTitle(t, locale, analysisRun)}</option>
                  ))}
                </select>
              ) : (
                <div className="filter-tab-buttons scrollable" role="tablist" aria-label={t('workspace.filterByAnalysisRunAria')}>
                  {run.analysisRuns.map((analysisRun, index) => (
                    <span key={analysisRun.id} className="filter-tab-run-item">
                      {index > 0 ? <ChevronRight size={14} className="filter-tab-arrow rtl-mirror" aria-hidden="true" /> : null}
                      <button type="button" role="tab" aria-selected={findingsRunId === analysisRun.id}
                        className={`source-type-tab ${findingsRunId === analysisRun.id ? 'active' : ''}`}
                        onClick={() => setFindingsRunId(analysisRun.id)}>
                        {analysisRunTitle(t, locale, analysisRun)}
                      </button>
                    </span>
                  ))}
                </div>
              )
            ) : (
              <div className="cs-date-range">
                <input type="date" className="cs-input" value={dateFrom}
                  onChange={(event) => setDateFrom(event.target.value)} aria-label={t('workspace.fromDateAria')} />
                <span>{t('shared.to')}</span>
                <input type="date" className="cs-input" value={dateTo}
                  onChange={(event) => setDateTo(event.target.value)} aria-label={t('workspace.toDateAria')} />
              </div>
            )}

            {hasFindingFilters ? (
              <button type="button" className="cs-btn cs-btn-sm" onClick={clearFindingFilters}>
                <X size={13} /> {t('shared.clearFilters')}
              </button>
            ) : null}

            <div className="cs-view-tabs" role="tablist" aria-label={t('workspace.switchReportViewAria')}>
              {VIEW_MODES.map((mode) => {
                const Icon = mode.icon;
                const isActive = viewMode === mode.value;
                return (
                  <button key={mode.value} type="button" role="tab" aria-selected={isActive}
                    className={`cs-view-tab${isActive ? ' active' : ''}`} onClick={() => changeViewMode(mode.value)}>
                    <Icon size={14} /> {mode.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div style={{ opacity: findingsLoading ? 0.6 : 1, transition: 'opacity 0.15s ease' }}>
            {findings.length ? (
              viewMode === 'list' ? (
                <div className="cs-finding-list">
                  {findings.map((finding) => (
                    <FindingRow key={finding.id} finding={finding} t={t} locale={locale}
                      onOpen={(id) => navigate(`/competitors/${studyId}/reports/${id}`)} />
                  ))}
                </div>
              ) : (
                <div className="cs-card-grid">
                  {findings.map((finding) => (
                    <FindingCard key={finding.id} finding={finding} t={t} locale={locale}
                      onOpen={(id) => navigate(`/competitors/${studyId}/reports/${id}`)} />
                  ))}
                </div>
              )
            ) : (
              <div className="cs-empty">
                <div className="cs-empty-icon"><Search size={20} /></div>
                <h3>{t('workspace.noMatchTitle')}</h3>
                <p>{t('workspace.noMatchBody')}</p>
                <button type="button" className="cs-btn" onClick={clearFindingFilters}>
                  <X size={15} /> {t('shared.clearFilters')}
                </button>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="cs-empty">
          <div className="cs-empty-icon"><Sparkles size={20} /></div>
          <h3>{t('workspace.emptyTitle')}</h3>
          <p>
            {stats.tracked
              ? t('workspace.emptyTrackedBody')
              : t('workspace.emptyNoCompetitorsBody')}
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            {stats.tracked ? (
              <RunAnalysisButton run={run} label={t('runAnalysis.runAnalysisLabel')} />
            ) : (
              <Link to={`/competitors/${studyId}/manage`} className="cs-btn cs-btn-primary">
                <Layers size={15} /> {t('workspace.goToCompetitors')}
              </Link>
            )}
          </div>
        </div>
      )}

      <RunAnalysisChoiceModal run={run} lastRunAt={study?.last_run_at} />
    </div>
  );
}
