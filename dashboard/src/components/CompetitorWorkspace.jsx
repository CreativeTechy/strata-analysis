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
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, BarChart3, CalendarClock, Check, ChevronRight,
  Layers, LayoutGrid, Lightbulb, List, Pencil, Radar, Search,
  Sparkles, Target, TrendingUp, Upload, X,
} from 'lucide-react';
import {
  IMPACT_LABELS, SIZE_TIER_LABELS, avatarGradient, getStudy,
  initials, listCompetitors, listFindings, relativeTime,
} from '../api/competitorApi.js';
import { useAuth } from '../auth/useAuth.js';
import {
  RunAnalysisButton, RunAnalysisChoiceModal, RunAnalysisLog,
} from './CompetitorRunAnalysis.jsx';
import { analysisRunTitle, useRunAnalysis } from '../useRunAnalysis.js';
import '../styles/Competitors.css';

const IMPACT_FILTERS = [
  { key: '', label: 'All impact' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
];

const VIEW_MODES = [
  { value: 'card', label: 'Cards', icon: LayoutGrid },
  { value: 'list', label: 'List', icon: List },
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

function FindingRow({ finding, onOpen }) {
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];

  return (
    <button type="button" className="cs-finding-row" onClick={() => onOpen(finding.id)}>
      <span className={`cs-pill cs-pill-${finding.impact_level}`}>
        {IMPACT_LABELS[finding.impact_level] || finding.impact_level}
      </span>
      <span className="cs-avatar cs-finding-row-avatar" style={{ background: avatarGradient(finding.competitor_name) }} aria-hidden="true">
        {initials(finding.competitor_name)}
      </span>
      <span className="cs-finding-row-main">
        <span className="cs-finding-row-name">{finding.competitor_name}</span>
        <span className="cs-finding-row-headline">{finding.headline}</span>
      </span>
      <span className="cs-finding-row-meta">
        {finding.story_count} source{finding.story_count === 1 ? '' : 's'}
        {evidence.length ? ` · ${evidence.length} cited` : ''}
        {finding.generated_at ? ` · ${relativeTime(finding.generated_at)}` : ''}
      </span>
      <ChevronRight size={15} className="cs-finding-row-chevron" />
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
  const { hasPermission } = useAuth();
  const canManage = hasPermission('competitors.manage');

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
          <RunAnalysisButton run={run} />
          <Link to={`/competitors/${studyId}/manage`} className="cs-btn">
            <Layers size={15} /> {competitors.length} competitor{competitors.length === 1 ? '' : 's'}
          </Link>
          {canManage ? (
            <Link to={`/competitors/${studyId}/documents`} className="cs-btn">
              <Upload size={15} /> Add documents
            </Link>
          ) : null}
          {canManage ? (
            <Link to={`/competitors/${studyId}/edit`} className="cs-btn">
              <Pencil size={15} /> Full edit
            </Link>
          ) : null}
        </div>
      </div>

      <RunAnalysisLog run={run} />

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{error}</span>
        </div>
      ) : null}

      {notice ? (
        <div className="cs-alert cs-alert-info">
          <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            Generated {notice.generated} report{notice.generated === 1 ? '' : 's'} from{' '}
            {notice.scanned} article{notice.scanned === 1 ? '' : 's'}
            {notice.documentCount
              ? ` across ${notice.documentCount} document${notice.documentCount === 1 ? '' : 's'}`
              : ''}.
            {Object.keys(notice.reasons || {}).length ? (
              <>
                {' '}Filtered out:{' '}
                {Object.entries(notice.reasons)
                  .map(([reason, count]) => `${count} ${reason.replace(/_/g, ' ')}`)
                  .join(', ')}
                .
              </>
            ) : null}
            {notice.skipped?.length ? (
              <> {notice.skipped.length} competitor{notice.skipped.length === 1 ? '' : 's'} skipped —{' '}
                {notice.skipped.map((item) => `${item.name}: ${item.reason}`).join(' ')}</>
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

      {(findings.length > 0 || hasFindingFilters) ? (
        <>
          <div className="cs-panel cs-findings-toolbar">
            <label className="cs-search-field">
              <Search size={16} />
              <input
                type="text"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search headline, summary, competitor..."
              />
            </label>

            <select className="cs-select" value={impact} onChange={(event) => setImpact(event.target.value)}
              aria-label="Filter by impact">
              {IMPACT_FILTERS.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
            </select>

            <div className="filter-tabs-shell" style={{ margin: 0 }}>
              <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label="Filter reports by">
                <button type="button" role="tab" aria-selected={!findingsRunId}
                  className={`source-type-tab ${!findingsRunId ? 'active' : ''}`}
                  onClick={() => setFindingsRunId(null)}>
                  Date range
                </button>
                {run.analysisRuns.length > 0 ? (
                  <button type="button" role="tab" aria-selected={!!findingsRunId}
                    className={`source-type-tab ${findingsRunId ? 'active' : ''}`}
                    onClick={() => setFindingsRunId(findingsRunId || run.analysisRuns[0].id)}>
                    Analysis run
                  </button>
                ) : null}
              </div>
            </div>

            {findingsRunId ? (
              run.analysisRuns.length > 3 ? (
                <select className="cs-select filter-run-select" value={findingsRunId}
                  onChange={(event) => setFindingsRunId(event.target.value)}
                  aria-label="Filter by analysis run">
                  {run.analysisRuns.map((analysisRun) => (
                    <option key={analysisRun.id} value={analysisRun.id}>{analysisRunTitle(analysisRun)}</option>
                  ))}
                </select>
              ) : (
                <div className="filter-tab-buttons scrollable" role="tablist" aria-label="Filter by analysis run">
                  {run.analysisRuns.map((analysisRun, index) => (
                    <span key={analysisRun.id} className="filter-tab-run-item">
                      {index > 0 ? <ChevronRight size={14} className="filter-tab-arrow" aria-hidden="true" /> : null}
                      <button type="button" role="tab" aria-selected={findingsRunId === analysisRun.id}
                        className={`source-type-tab ${findingsRunId === analysisRun.id ? 'active' : ''}`}
                        onClick={() => setFindingsRunId(analysisRun.id)}>
                        {analysisRunTitle(analysisRun)}
                      </button>
                    </span>
                  ))}
                </div>
              )
            ) : (
              <div className="cs-date-range">
                <input type="date" className="cs-input" value={dateFrom}
                  onChange={(event) => setDateFrom(event.target.value)} aria-label="From date" />
                <span>to</span>
                <input type="date" className="cs-input" value={dateTo}
                  onChange={(event) => setDateTo(event.target.value)} aria-label="To date" />
              </div>
            )}

            {hasFindingFilters ? (
              <button type="button" className="cs-btn cs-btn-sm" onClick={clearFindingFilters}>
                <X size={13} /> Clear filters
              </button>
            ) : null}

            <div className="cs-view-tabs" role="tablist" aria-label="Switch report view">
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
                    <FindingRow key={finding.id} finding={finding}
                      onOpen={(id) => navigate(`/competitors/${studyId}/reports/${id}`)} />
                  ))}
                </div>
              ) : (
                <div className="cs-card-grid">
                  {findings.map((finding) => (
                    <FindingCard key={finding.id} finding={finding}
                      onOpen={(id) => navigate(`/competitors/${studyId}/reports/${id}`)} />
                  ))}
                </div>
              )
            ) : (
              <div className="cs-empty">
                <div className="cs-empty-icon"><Search size={20} /></div>
                <h3>No matching reports</h3>
                <p>Try adjusting your search, impact, or date filters.</p>
                <button type="button" className="cs-btn" onClick={clearFindingFilters}>
                  <X size={15} /> Clear filters
                </button>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="cs-empty">
          <div className="cs-empty-icon"><Sparkles size={20} /></div>
          <h3>No reports yet</h3>
          <p>
            {stats.tracked
              ? 'Competitors are tracked but nothing has been analysed yet. Run the analysis over the evidence on file.'
              : 'No competitors are tracked yet. Head to the Competitors page to re-read documents and find the companies they are about.'}
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            {stats.tracked ? (
              <RunAnalysisButton run={run} />
            ) : (
              <Link to={`/competitors/${studyId}/manage`} className="cs-btn cs-btn-primary">
                <Layers size={15} /> Go to competitors
              </Link>
            )}
          </div>
        </div>
      )}

      <RunAnalysisChoiceModal run={run} lastRunAt={study?.last_run_at} />
    </div>
  );
}
