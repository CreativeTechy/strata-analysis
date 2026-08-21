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

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, BarChart3, Building2, CalendarClock, Check, ChevronRight,
  ExternalLink, Layers, LayoutGrid, Lightbulb, Link2, List, Pencil, Plus, Radar, RefreshCw, Search,
  ShieldCheck, Sparkles, Target, Trash2, TrendingUp, X,
} from 'lucide-react';
import {
  IMPACT_LABELS, PLATFORM_LABELS, SIZE_TIER_LABELS, addAccount, addCompetitorManual, analyze,
  avatarGradient, deleteStudy, discoverAccounts, discoverCompetitors, discoverTrackedAccounts,
  getSchedule, getStudy, initials, listAccounts, listCompetitors, listFindings, pollAnalysisRun,
  pollDiscoveryRun, relativeTime, saveProfile, setCompetitorStatus, setSchedule, syncSources,
  updateCompetitor, updateStudy, validateAccount,
} from '../competitorApi.js';
import { countryLabel } from '../constants/countries.js';
import { useAuth } from '../auth/useAuth.js';
import ConfirmModal from './ConfirmModal';
import { AddCompetitorForm, AddSourceRow } from './CompetitorSourceEditor.jsx';
import { DiscoveryLog, ListEditor } from './CompetitorOnboarding.jsx';
import '../styles/Competitors.css';

const STUDY_STATUS_OPTIONS = ['draft', 'active', 'archived'];
const SCHEDULE_UNIT_OPTIONS = [
  { value: 'minutes', label: 'minute(s)' },
  { value: 'hours', label: 'hour(s)' },
  { value: 'days', label: 'day(s)' },
];

const IMPACT_FILTERS = [
  { key: '', label: 'All impact' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
];

/** Alternate names a competitor is published under, edited as a comma-separated
 *  list. Evidence attribution otherwise only matches the company name and its
 *  domain label, so a company reported on in another language or script, or
 *  trading under a different retail brand, is never matched at all. It is also
 *  the way to make a competitor whose name is an ordinary word analyzable:
 *  those are dropped as automatic matchers, but an alias typed here is
 *  trusted. */
function AliasEditor({ competitor, onSave }) {
  const stored = Array.isArray(competitor.aliases) ? competitor.aliases : [];
  const [value, setValue] = useState(stored.join(', '));
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  // Re-syncing from props is handled by remounting on a key of the stored
  // aliases (see the call site), not by an effect that writes state.
  const dirty = value !== stored.join(', ');

  const save = async () => {
    setBusy(true);
    try {
      await onSave(value.split(',').map((item) => item.trim()).filter(Boolean));
      setSaved(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cs-alias-editor">
      <label className="cs-label" htmlFor={`cs-aliases-${competitor.id}`}>Other names</label>
      <div className="cs-alias-editor-row">
        <input
          id={`cs-aliases-${competitor.id}`}
          className="cs-input"
          value={value}
          placeholder="e.g. Younes Bros, قهوة يونس"
          onChange={(event) => { setValue(event.target.value); setSaved(false); }}
        />
        <button type="button" className="cs-btn cs-btn-sm" onClick={save} disabled={busy || !dirty}>
          {busy ? <span className="cs-spinner" /> : null} {saved && !dirty ? 'Saved' : 'Save'}
        </button>
      </div>
      <small className="cs-row-desc">
        Comma separated. Articles naming any of these count as evidence for this competitor.
      </small>
    </div>
  );
}

// How far back analysis looks for evidence. The backend accepts 1-365 and
// stamps the chosen window on every card as period_start/period_end.
// 30 stays the default: a card answers "what changed", and over a longer
// window a move from six months ago sits beside one from last week with
// nothing to tell them apart. Longer windows are for competitors that are
// simply covered rarely.
const ANALYSIS_PERIODS = [
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 180, label: 'Last 6 months' },
  { days: 365, label: 'Last 12 months' },
];

// Same run-labeling convention as Dashboard/Reports (DashboardOverview.jsx,
// App.jsx's renderReportsView) - "Pipeline #N: <date>" - so a run means the
// same thing wherever it's picked from.
function formatPipelineRunLabel(run) {
  const value = run?.finished_at || run?.created_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return 'Run';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function pipelineRunTitle(run, index) {
  const number = run?.sequence_number ?? (index + 1);
  return `Pipeline #${number}: ${formatPipelineRunLabel(run)}`;
}

const VIEW_MODES = [
  { value: 'card', label: 'Cards', icon: LayoutGrid },
  { value: 'list', label: 'List', icon: List },
];

const WORKSPACE_TABS = [
  { value: 'reports', label: 'Reports', icon: BarChart3 },
  { value: 'sources', label: 'Sources', icon: Link2 },
];

// The unfiltered "All sources" list spans every account across every tracked
// and suggested competitor - easily well past a screenful for a study with
// many competitors, so it's paged rather than rendered all at once.
const SOURCES_PAGE_SIZE = 20;

// Fixed identity -> colour mapping for the sources chart, in the order the
// chart always draws them (never re-ordered by count, so a colour always
// means the same platform group). The three hues are a validated-passing
// subset of the standard categorical order (run
// dataviz/scripts/validate_palette.js "#1baf7a,#2a78d6,#4a3aa7" to reproduce);
// "Other" stays neutral gray rather than a fourth hue, and none of the three
// overlap the green/amber/red already reserved for validation-status pills
// elsewhere on this page.
const SOURCE_GROUPS = [
  { key: 'content', label: 'Owned content', platforms: new Set(['news', 'web', 'website', 'blog', 'rss']), color: '#1baf7a' },
  { key: 'x', label: 'X accounts', platforms: new Set(['x']), color: '#2a78d6' },
  { key: 'hashtag', label: 'Hashtags', platforms: new Set(['hashtag']), color: '#4a3aa7' },
  { key: 'other', label: 'Other', platforms: new Set(), color: '#94a3b8' },
];
const SOURCE_GROUP_BY_KEY = Object.fromEntries(SOURCE_GROUPS.map((group) => [group.key, group]));

function sourceGroupKey(platform) {
  const found = SOURCE_GROUPS.find((group) => group.platforms.has(platform));
  return found ? found.key : 'other';
}

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

const SOURCE_STATUS_FILTERS = [
  { key: '', label: 'All statuses' },
  { key: 'valid', label: 'Valid' },
  { key: 'pending', label: 'Pending' },
  { key: 'rejected', label: 'Rejected' },
];

/** Bar-per-group chart, always in SOURCE_GROUPS order regardless of count -
 *  a group's colour never changes as filters change which ones have data. */
function SourceGroupChart({ groupCounts }) {
  const rows = SOURCE_GROUPS.map((group) => ({ ...group, count: groupCounts[group.key] || 0 }));
  const max = Math.max(1, ...rows.map((row) => row.count));

  return (
    <div className="cs-panel" style={{ marginBottom: 20 }}>
      <h2 className="cs-panel-title"><BarChart3 size={16} /> Sources by channel</h2>
      <p className="cs-panel-hint">Every discovered or manually-added source across all competitors, by channel type.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
        {rows.map((row) => (
          <div key={row.key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ width: 128, flexShrink: 0, fontSize: '0.8rem', color: 'var(--text-dark)', fontWeight: 560 }}>
              {row.label}
            </span>
            <div style={{ flex: 1, height: 16, borderRadius: 8, background: '#f1f5f9', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${(row.count / max) * 100}%`,
                  minWidth: row.count ? 4 : 0,
                  borderRadius: 8,
                  background: row.color,
                  transition: 'width 0.2s ease',
                }}
              />
            </div>
            <span style={{ width: 28, flexShrink: 0, textAlign: 'right', fontSize: '0.82rem', fontWeight: 650, color: 'var(--text-dark)' }}>
              {row.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** All sources (competitor accounts) across the study in one place - the
 *  per-competitor "Sources" drawer shows the same data scoped to one company;
 *  this is the aggregate view across the whole study. */
function SourcesPanel({
  sources, filteredTotal, total, groupCounts, search, onSearch, groupFilter, onGroupFilter,
  statusFilter, onStatusFilter, onChooseCompetitors, page, totalPages, onPageChange,
}) {
  return (
    <>
      <SourceGroupChart groupCounts={groupCounts} />

      <div className="cs-panel">
        <h2 className="cs-panel-title"><Link2 size={16} /> All sources</h2>
        <p className="cs-panel-hint">
          {total} source{total === 1 ? '' : 's'} across every tracked and suggested competitor.
        </p>

        {total ? (
          <>
            <div className="cs-panel cs-findings-toolbar" style={{ marginTop: 14 }}>
              <label className="cs-search-field">
                <Search size={16} />
                <input
                  type="text"
                  value={search}
                  onChange={(event) => onSearch(event.target.value)}
                  placeholder="Search competitor, handle, or URL..."
                />
              </label>

              <select className="cs-select" value={groupFilter} onChange={(event) => onGroupFilter(event.target.value)}
                aria-label="Filter by channel">
                <option value="">All channels</option>
                {SOURCE_GROUPS.map((group) => (
                  <option key={group.key} value={group.key}>{group.label}</option>
                ))}
              </select>

              <select className="cs-select" value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}
                aria-label="Filter by validation status">
                {SOURCE_STATUS_FILTERS.map((option) => (
                  <option key={option.key} value={option.key}>{option.label}</option>
                ))}
              </select>
            </div>

            {filteredTotal ? (
              <div className="cs-rows" style={{ marginTop: 4 }}>
                {sources.map((source) => {
                  const group = SOURCE_GROUP_BY_KEY[sourceGroupKey(source.platform)];
                  return (
                    <div key={source.id} className="cs-row">
                      <span
                        aria-hidden="true"
                        style={{ width: 8, height: 8, borderRadius: 4, background: group.color, flexShrink: 0 }}
                      />
                      <div
                        className="cs-avatar"
                        style={{ background: avatarGradient(source.competitor_name), width: 28, height: 28, fontSize: '0.68rem' }}
                        aria-hidden="true"
                      >
                        {initials(source.competitor_name)}
                      </div>
                      <div className="cs-row-main">
                        <div className="cs-row-name">
                          {source.competitor_name}
                          <span style={{ fontWeight: 400, color: 'var(--text-light)' }}>
                            {' '}· {PLATFORM_LABELS[source.platform] || source.platform}
                            {source.handle ? ` @${source.handle}` : ''}
                          </span>
                        </div>
                        <div className="cs-row-desc">
                          <a href={source.url} target="_blank" rel="noopener noreferrer"
                            style={{ color: 'inherit', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            {source.url} <ExternalLink size={11} />
                          </a>
                        </div>
                      </div>
                      <div className="cs-row-side">
                        {typeof source.confidence === 'number' ? (
                          <span className="cs-pill cs-pill-signal">{Math.round(source.confidence * 100)}% confidence</span>
                        ) : null}
                        <span className={`cs-pill cs-pill-${source.validation_status}`}>{source.validation_status}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="cs-empty">
                <div className="cs-empty-icon"><Search size={20} /></div>
                <h3>No matching sources</h3>
                <p>Try a different search term or clear the channel/status filters.</p>
              </div>
            )}

            {filteredTotal ? (
              <div className="cs-pagination">
                <div className="cs-pagination-info">
                  Showing {(page - 1) * SOURCES_PAGE_SIZE + 1}-{Math.min(page * SOURCES_PAGE_SIZE, filteredTotal)} of {filteredTotal}
                </div>
                <div className="cs-pagination-controls">
                  <button
                    type="button"
                    className="cs-btn cs-btn-sm"
                    onClick={() => onPageChange(Math.max(1, page - 1))}
                    disabled={page <= 1}
                  >
                    Previous
                  </button>
                  <span className="cs-pill cs-pill-signal">Page {page} of {totalPages}</span>
                  <button
                    type="button"
                    className="cs-btn cs-btn-sm"
                    onClick={() => onPageChange(Math.min(totalPages, page + 1))}
                    disabled={page >= totalPages}
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </>
        ) : (
          <div className="cs-empty">
            <div className="cs-empty-icon"><Link2 size={20} /></div>
            <h3>No sources yet</h3>
            <p>Track a competitor and confirm or discover its channels to see them here.</p>
            <button type="button" className="cs-btn cs-btn-primary" onClick={onChooseCompetitors}>
              <Layers size={15} /> Choose competitors
            </button>
          </div>
        )}
      </div>
    </>
  );
}

export default function CompetitorWorkspace() {
  const { studyId } = useParams();
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canManage = hasPermission('competitors.manage');

  const [study, setStudy] = useState(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [profile, setProfile] = useState(null);
  const [competitors, setCompetitors] = useState([]);
  const [findings, setFindings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [runMode, setRunMode] = useState(null); // 'scrape' | 'direct' - which choice is currently running
  const [showRunChoice, setShowRunChoice] = useState(false);
  const [periodDays, setPeriodDays] = useState(ANALYSIS_PERIODS[0].days);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [pipelineRunId, setPipelineRunId] = useState(null);
  const pipelineRunDefaultedRef = useRef(new Set());
  const [notice, setNotice] = useState(null);
  const [impact, setImpact] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  // Filters the reports list by which pipeline run generated the evidence -
  // separate from pipelineRunId above, which picks what a *new* analysis run
  // should use. Not defaulted to the latest run: unlike starting a fresh
  // analysis, opening the reports list should show everything already on
  // file until the user asks to narrow it.
  const [findingsRunId, setFindingsRunId] = useState(null);
  const [findingsLoading, setFindingsLoading] = useState(false);
  const [viewMode, setViewMode] = useState(() => {
    try {
      return window.localStorage.getItem('competitors-view-mode') === 'list' ? 'list' : 'card';
    } catch {
      return 'card';
    }
  });
  const [showCompetitors, setShowCompetitors] = useState(false);
  const [activeTab, setActiveTab] = useState('reports');
  const [sourceSearch, setSourceSearch] = useState('');
  const [sourceGroupFilter, setSourceGroupFilter] = useState('');
  const [sourceStatusFilter, setSourceStatusFilter] = useState('');
  const [sourcePage, setSourcePage] = useState(1);
  const [expandedChannels, setExpandedChannels] = useState(() => new Set());
  const [accountsByCompetitor, setAccountsByCompetitor] = useState({});
  const [channelBusy, setChannelBusy] = useState({});
  const [trackingBusy, setTrackingBusy] = useState({});
  const [unverified, setUnverified] = useState({});
  const [showAddCompetitor, setShowAddCompetitor] = useState(false);
  const [addingManual, setAddingManual] = useState(false);
  const [discoveringCompetitors, setDiscoveringCompetitors] = useState(false);
  const [discoveryNotice, setDiscoveryNotice] = useState(null);
  const [discoveringChannels, setDiscoveringChannels] = useState(false);
  const [discoveryLogs, setDiscoveryLogs] = useState([]);
  const [analysisLogs, setAnalysisLogs] = useState([]);

  const [editOpen, setEditOpen] = useState(false);
  const [editDraft, setEditDraft] = useState({ name: '', description: '', status: 'active' });
  const [savingEdit, setSavingEdit] = useState(false);

  const [schedule, setScheduleState] = useState(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleDraft, setScheduleDraft] = useState({
    repeat_enabled: false, repeat_interval_value: 1, repeat_interval_unit: 'days',
  });
  const [savingSchedule, setSavingSchedule] = useState(false);

  const [profileOpen, setProfileOpen] = useState(false);
  const [profileDraft, setProfileDraft] = useState(null);
  const [savingProfile, setSavingProfile] = useState(false);

  // Fetch inside the effect with a cancel guard, so switching studies mid-request
  // cannot resolve into the newly-selected study's state.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [detail, competitorList, scheduleDetail] = await Promise.all([
          getStudy(studyId),
          listCompetitors(studyId),
          getSchedule(studyId),
        ]);
        if (cancelled) return;
        setStudy(detail.study);
        setProfile(detail.profile);
        setCompetitors(competitorList.competitors || []);
        setScheduleState(scheduleDetail.schedule || null);
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

  // A study is a project, so it has the same pipeline_runs rows any project's
  // scrapes write - fetched here so "Run analysis" can offer analyzing one
  // specific past run instead of only a date window, same choice Dashboard/
  // Reports give over `articles.pipeline_run_id`. Defaults to the latest
  // completed run the first time this study is opened (tracked per study id
  // so it doesn't fight a choice the user already made); after that, only an
  // explicit pick changes it.
  useEffect(() => {
    if (!studyId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/pipeline-runs?project_id=${studyId}&limit=500`);
        if (!res.ok) return;
        const data = await res.json().catch(() => ({}));
        const runs = Array.isArray(data?.runs) ? data.runs : [];
        const completed = runs
          .filter((run) => run?.finished_at)
          .sort((a, b) => new Date(b.finished_at).getTime() - new Date(a.finished_at).getTime());
        if (cancelled) return;
        setPipelineRuns(completed);
        if (!pipelineRunDefaultedRef.current.has(studyId)) {
          pipelineRunDefaultedRef.current.add(studyId);
          if (completed.length > 0) setPipelineRunId(completed[0].id);
        }
      } catch {
        if (!cancelled) setPipelineRuns([]);
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

  // Findings are fetched separately from the study/competitors/schedule load
  // above so that changing a filter never has to re-fetch all of those too.
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
          pipeline_run_id: findingsRunId || undefined,
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

  // Never scraped before - hint which choice to lead with in the run dialog.
  const likelyNeedsScrape = !study?.last_run_at;

  const runAnalysis = async (scrapeFirst) => {
    // Picking a specific past run means "analyze exactly what it gathered" -
    // a fresh scrape would just be a different, not-yet-selected run.
    const runFilter = pipelineRunId;
    const willScrapeFirst = scrapeFirst && !runFilter;
    setShowRunChoice(false);
    setRunMode(willScrapeFirst ? 'scrape' : 'direct');
    setAnalyzing(true);
    setError('');
    setNotice(null);
    setAnalysisLogs([]);
    try {
      await syncSources(studyId);
      // Queued, not awaited: a scrape plus one LLM call per competitor runs for
      // minutes. Poll for progress so the log renders live instead of leaving
      // the user on a spinner with no idea what stage it reached.
      const queued = await analyze(studyId, {
        period_days: periodDays,
        pipeline_run_id: runFilter || undefined,
        scrape: willScrapeFirst,
      });
      const run = await pollAnalysisRun(studyId, queued.run_id, (r) => setAnalysisLogs(r.logs || []));
      if (run.status === 'failed') throw new Error(run.error || 'Analysis failed.');

      setFindings(run.findings || []);
      const validation = run.validation || {};
      setNotice({
        generated: run.generated,
        scanned: validation.scanned || 0,
        // From the run, not the picker: reports the window actually analyzed,
        // which stays right even if the selector is changed afterwards.
        periodDays: validation.period_days || null,
        pipelineRunId: validation.pipeline_run_id || null,
        skipped: run.skipped || [],
        reasons: validation.rejection_reasons || {},
        scrapedFirst: Boolean(run.scrape_run),
        scrapeRun: run.scrape_run || null,
      });
      clearFindingFilters();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDeleteStudy = async () => {
    setDeleting(true);
    try {
      await deleteStudy(studyId);
      navigate('/competitors');
    } catch (caught) {
      setError(caught.message);
      setDeleting(false);
      setDeleteOpen(false);
    }
  };

  const openEdit = () => {
    setEditDraft({
      name: study?.name || '',
      description: study?.description || '',
      status: study?.status || 'active',
    });
    setEditOpen(true);
  };

  const handleSaveEdit = async () => {
    setSavingEdit(true);
    setError('');
    try {
      const result = await updateStudy(studyId, editDraft);
      setStudy((prev) => ({ ...prev, ...result.study }));
      setEditOpen(false);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSavingEdit(false);
    }
  };

  const openSchedule = () => {
    setScheduleDraft({
      repeat_enabled: Boolean(schedule?.repeat_enabled),
      repeat_interval_value: schedule?.repeat_interval_value || 1,
      repeat_interval_unit: schedule?.repeat_interval_unit || 'days',
    });
    setScheduleOpen(true);
  };

  const handleSaveSchedule = async () => {
    setSavingSchedule(true);
    setError('');
    try {
      const result = await setSchedule(studyId, {
        repeat_enabled: scheduleDraft.repeat_enabled,
        repeat_interval_value: Math.max(1, Number(scheduleDraft.repeat_interval_value) || 1),
        repeat_interval_unit: scheduleDraft.repeat_interval_unit,
      });
      setScheduleState(result.schedule || null);
      setStudy((prev) => (prev ? { ...prev, ...result.schedule } : prev));
      setScheduleOpen(false);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSavingSchedule(false);
    }
  };

  const openProfile = () => {
    setProfileDraft({
      industry: profile?.industry || '',
      market: profile?.market || '',
      positioning: profile?.positioning || '',
      offerings: profile?.offerings || [],
      audience: profile?.audience || [],
      differentiators: profile?.differentiators || [],
      context_summary: profile?.context_summary || '',
    });
    setProfileOpen(true);
  };

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    setError('');
    try {
      const result = await saveProfile(studyId, profileDraft);
      setProfile(result.profile || null);
      setProfileOpen(false);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSavingProfile(false);
    }
  };

  const saveAliases = async (competitorId, aliases) => {
    try {
      await updateCompetitor(competitorId, { aliases });
      const result = await listCompetitors(studyId);
      setCompetitors(result.competitors || []);
    } catch (caught) {
      setError(caught.message);
    }
  };

  const toggleTracking = async (competitor) => {
    const nextStatus = competitor.status === 'tracked' ? 'ignored' : 'tracked';
    setTrackingBusy((current) => ({ ...current, [competitor.id]: true }));
    try {
      // Phase 2: tracking an AI-suggested competitor for the first time
      // triggers a live web check server-side, so this call can take a beat
      // longer than a plain status flip — the button shows a spinner for it.
      const statusResult = await setCompetitorStatus(competitor.id, nextStatus);
      if (statusResult.verification) {
        setUnverified((current) => ({ ...current, [competitor.id]: !statusResult.verification.verified }));
      }
      const result = await listCompetitors(studyId);
      setCompetitors(result.competitors || []);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setTrackingBusy((current) => ({ ...current, [competitor.id]: false }));
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
    setDiscoveryLogs([]);
    try {
      const queued = await discoverCompetitors(studyId, { limit: 12, with_accounts: false });
      const run = await pollDiscoveryRun(studyId, queued.run_id, (r) => setDiscoveryLogs(r.logs || []));
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

  // Phase 3: find channels for every tracked competitor that doesn't have one
  // yet, in one shot, instead of clicking "Find channels" per competitor.
  const runChannelDiscovery = async () => {
    setError('');
    setDiscoveringChannels(true);
    setDiscoveryLogs([]);
    try {
      const queued = await discoverTrackedAccounts(studyId);
      if (queued.run_id) {
        const run = await pollDiscoveryRun(studyId, queued.run_id, (r) => setDiscoveryLogs(r.logs || []));
        if (run.status === 'failed') {
          throw new Error(run.error || run.message || 'Channel discovery failed.');
        }
        // Cached per-competitor account lists are now stale for whichever
        // competitors just got new channels - drop the cache so re-expanding
        // "Sources" re-fetches instead of showing the old (empty) list.
        setAccountsByCompetitor({});
        await refreshCompetitorCounts();
      }
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDiscoveringChannels(false);
    }
  };

  const stats = useMemo(() => {
    const tracked = competitors.filter((item) => item.status === 'tracked');
    const pendingChannels = competitors.reduce((sum, item) => sum + (item.pending_account_count || 0), 0);
    const highImpact = findings.filter((item) => item.impact_level === 'high').length;
    const channellessTracked = tracked.filter((item) => !item.account_count).length;
    return { tracked: tracked.length, pendingChannels, highImpact, channellessTracked };
  }, [competitors, findings]);

  // Every competitor already carries its full `accounts` list from
  // listCompetitors() (see loadAll below) - no extra request needed to see
  // every source across the study at once.
  const allSources = useMemo(
    () => competitors.flatMap((competitor) => (competitor.accounts || []).map((account) => ({
      ...account,
      competitor_id: competitor.id,
      competitor_name: competitor.name,
    }))),
    [competitors],
  );

  const sourceGroupCounts = useMemo(() => {
    const counts = Object.fromEntries(SOURCE_GROUPS.map((group) => [group.key, 0]));
    for (const source of allSources) counts[sourceGroupKey(source.platform)] += 1;
    return counts;
  }, [allSources]);

  const sourceStats = useMemo(() => ({
    total: allSources.length,
    valid: allSources.filter((source) => source.validation_status === 'valid').length,
    pending: allSources.filter((source) => source.validation_status === 'pending').length,
    rejected: allSources.filter((source) => source.validation_status === 'rejected').length,
  }), [allSources]);

  const filteredSources = useMemo(() => {
    const query = sourceSearch.trim().toLowerCase();
    return allSources.filter((source) => {
      if (sourceGroupFilter && sourceGroupKey(source.platform) !== sourceGroupFilter) return false;
      if (sourceStatusFilter && source.validation_status !== sourceStatusFilter) return false;
      if (query) {
        const haystack = `${source.competitor_name} ${source.handle || ''} ${source.url || ''}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }, [allSources, sourceGroupFilter, sourceStatusFilter, sourceSearch]);

  // A new search/filter should land back on page 1, not wherever the user was
  // scrolled to on the old result set - adjusted during render (React's
  // documented pattern for this) rather than an effect, so it takes effect in
  // the same render as the filter change instead of one tick later.
  const sourceFilterKey = `${sourceSearch}|${sourceGroupFilter}|${sourceStatusFilter}`;
  const [prevSourceFilterKey, setPrevSourceFilterKey] = useState(sourceFilterKey);
  if (sourceFilterKey !== prevSourceFilterKey) {
    setPrevSourceFilterKey(sourceFilterKey);
    setSourcePage(1);
  }

  const sourceTotalPages = Math.max(1, Math.ceil(filteredSources.length / SOURCES_PAGE_SIZE));
  const sourceSafePage = Math.min(sourcePage, sourceTotalPages);
  const pagedSources = useMemo(
    () => filteredSources.slice((sourceSafePage - 1) * SOURCES_PAGE_SIZE, sourceSafePage * SOURCES_PAGE_SIZE),
    [filteredSources, sourceSafePage],
  );

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
          {stats.channellessTracked > 0 && (
            <button type="button" className="cs-btn" onClick={runChannelDiscovery} disabled={discoveringChannels}>
              {discoveringChannels ? <span className="cs-spinner" /> : <Search size={15} />}
              {discoveringChannels ? 'Finding channels...' : `Find channels (${stats.channellessTracked})`}
            </button>
          )}
          <button type="button" className="cs-btn cs-btn-primary" onClick={() => setShowRunChoice(true)} disabled={analyzing}>
            {analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />}
            {analyzing ? (runMode === 'scrape' ? 'Scraping & analysing...' : 'Analysing...') : 'Run analysis'}
          </button>
          {canManage && (
            <>
              <button type="button" className="cs-btn" onClick={openProfile}>
                <Building2 size={15} /> {profile ? 'Edit profile' : 'Add profile'}
              </button>
              <button type="button" className="cs-btn" onClick={openSchedule}>
                <CalendarClock size={15} />
                {schedule?.repeat_enabled ? `Every ${schedule.repeat_interval_value} ${schedule.repeat_interval_unit}` : 'Tracking off'}
              </button>
              <button type="button" className="cs-btn" onClick={openEdit}>
                <Pencil size={15} /> Edit study
              </button>
              <button
                type="button"
                className="cs-btn"
                onClick={() => setDeleteOpen(true)}
                style={{ color: '#ff4757' }}
              >
                <Trash2 size={15} /> Delete study
              </button>
            </>
          )}
        </div>
      </div>

      {(discoveringCompetitors || discoveringChannels) ? (
        <DiscoveryLog logs={discoveryLogs} active={discoveringCompetitors || discoveringChannels} />
      ) : null}

      {analyzing || analysisLogs.length ? (
        <DiscoveryLog logs={analysisLogs} active={analyzing} />
      ) : null}

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
            {notice.scanned} scanned article{notice.scanned === 1 ? '' : 's'}
            {notice.pipelineRunId
              ? ' from the selected pipeline run'
              : notice.periodDays ? ` in the last ${notice.periodDays} days` : ''}.
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
              <> {notice.skipped.length} competitor{notice.skipped.length === 1 ? '' : 's'} skipped —{' '}
                {notice.skipped.map((item) => `${item.name}: ${item.reason}`).join(' ')}</>
            ) : null}
          </span>
        </div>
      ) : null}

      <div className="cs-view-tabs" role="tablist" aria-label="Switch workspace tab" style={{ marginBottom: 16 }}>
        {WORKSPACE_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.value;
          return (
            <button key={tab.value} type="button" role="tab" aria-selected={isActive}
              className={`cs-view-tab${isActive ? ' active' : ''}`} onClick={() => setActiveTab(tab.value)}>
              <Icon size={14} /> {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === 'sources' ? (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 20 }}>
          <StatTile icon={Link2} label="Total sources" value={sourceStats.total} />
          <StatTile icon={ShieldCheck} label="Valid" value={sourceStats.valid} />
          <StatTile icon={RefreshCw} label="Pending" value={sourceStats.pending}
            tone={sourceStats.pending ? '#a16207' : undefined} />
          <StatTile icon={X} label="Rejected" value={sourceStats.rejected} />
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 20 }}>
          <StatTile icon={Radar} label="Tracked" value={stats.tracked} />
          <StatTile icon={BarChart3} label="Reports" value={findings.length} />
          <StatTile icon={TrendingUp} label="High impact" value={stats.highImpact}
            tone={stats.highImpact ? '#b91c1c' : undefined} />
          <StatTile icon={CalendarClock} label="Last run"
            value={study?.last_run_at ? relativeTime(study.last_run_at) : 'Never'} />
        </div>
      )}

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
                        <span className="cs-pill cs-pill-signal" title="Where this company is headquartered">
                          Based in {countryLabel(competitor.country)}
                        </span>
                      ) : null}
                      {Array.isArray(competitor.operates_in_countries) && competitor.operates_in_countries.length ? (
                        <span
                          className="cs-pill cs-pill-signal"
                          title="Where this competitor actually competes with your business"
                        >
                          Competes in {competitor.operates_in_countries.map(countryLabel).join(', ')}
                        </span>
                      ) : null}
                      <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                        {SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}
                      </span>
                      {competitor.status === 'tracked' && unverified[competitor.id] ? (
                        <span
                          className="cs-pill cs-pill-signal"
                          title="Tracked, but a live web check couldn't confirm this company exists — worth a manual look."
                        >
                          Couldn’t verify
                        </span>
                      ) : null}
                      <button type="button" className="cs-btn cs-btn-sm" onClick={() => toggleChannels(competitor.id)}>
                        <Link2 size={13} /> {channelsOpen ? 'Hide channels' : 'Channels'}
                      </button>
                      <button
                        type="button"
                        className={`cs-btn cs-btn-sm${competitor.status === 'tracked' ? ' cs-btn-primary' : ''}`}
                        onClick={() => toggleTracking(competitor)}
                        disabled={Boolean(trackingBusy[competitor.id])}
                      >
                        {trackingBusy[competitor.id] ? (
                          <span className="cs-spinner" />
                        ) : competitor.status === 'tracked' ? (
                          <><Check size={13} /> Tracking</>
                        ) : (
                          'Track'
                        )}
                      </button>
                    </div>
                  </div>

                  {channelsOpen ? (
                    <div className="cs-rows" style={{ marginLeft: 30, marginBottom: 14 }}>
                      <AliasEditor
                        key={(competitor.aliases || []).join('|')}
                        competitor={competitor}
                        onSave={(aliases) => saveAliases(competitor.id, aliases)}
                      />
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

      {activeTab === 'sources' ? (
        <SourcesPanel
          sources={pagedSources}
          filteredTotal={filteredSources.length}
          total={allSources.length}
          groupCounts={sourceGroupCounts}
          search={sourceSearch}
          onSearch={setSourceSearch}
          groupFilter={sourceGroupFilter}
          onGroupFilter={setSourceGroupFilter}
          statusFilter={sourceStatusFilter}
          onStatusFilter={setSourceStatusFilter}
          onChooseCompetitors={() => setShowCompetitors(true)}
          page={sourceSafePage}
          totalPages={sourceTotalPages}
          onPageChange={setSourcePage}
        />
      ) : (findings.length > 0 || hasFindingFilters) ? (
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
                {pipelineRuns.length > 0 ? (
                  <button type="button" role="tab" aria-selected={!!findingsRunId}
                    className={`source-type-tab ${findingsRunId ? 'active' : ''}`}
                    onClick={() => setFindingsRunId(findingsRunId || pipelineRuns[0].id)}>
                    Pipeline run
                  </button>
                ) : null}
              </div>
            </div>

            {findingsRunId ? (
              pipelineRuns.length > 3 ? (
                <select className="cs-select filter-run-select" value={findingsRunId}
                  onChange={(event) => setFindingsRunId(event.target.value)}
                  aria-label="Filter by pipeline run">
                  {pipelineRuns.map((run, index) => (
                    <option key={run.id} value={run.id}>{pipelineRunTitle(run, index)}</option>
                  ))}
                </select>
              ) : (
                <div className="filter-tab-buttons scrollable" role="tablist" aria-label="Filter by pipeline run">
                  {pipelineRuns.map((run, index) => (
                    <span key={run.id} className="filter-tab-run-item">
                      {index > 0 ? <ChevronRight size={14} className="filter-tab-arrow" aria-hidden="true" /> : null}
                      <button type="button" role="tab" aria-selected={findingsRunId === run.id}
                        className={`source-type-tab ${findingsRunId === run.id ? 'active' : ''}`}
                        onClick={() => setFindingsRunId(run.id)}>
                        {pipelineRunTitle(run, index)}
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

            <div className="cs-run-period" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="filter-tabs-shell" style={{ margin: 0 }}>
                <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label="Evidence source">
                  <button type="button" role="tab" aria-selected={!pipelineRunId}
                    className={`source-type-tab ${!pipelineRunId ? 'active' : ''}`}
                    onClick={() => setPipelineRunId(null)}>
                    Date range
                  </button>
                  {pipelineRuns.length > 0 ? (
                    <button type="button" role="tab" aria-selected={!!pipelineRunId}
                      className={`source-type-tab ${pipelineRunId ? 'active' : ''}`}
                      onClick={() => setPipelineRunId(pipelineRunId || pipelineRuns[0].id)}>
                      Pipeline run
                    </button>
                  ) : null}
                </div>
              </div>

              {pipelineRunId ? (
                <select className="cs-select filter-run-select" value={pipelineRunId}
                  onChange={(event) => setPipelineRunId(event.target.value)}
                  aria-label="Pipeline run to analyze">
                  {pipelineRuns.map((run, index) => (
                    <option key={run.id} value={run.id}>{pipelineRunTitle(run, index)}</option>
                  ))}
                </select>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <label htmlFor="cs-analysis-period">Look back over</label>
                  <select id="cs-analysis-period" className="cs-select" style={{ flex: 1 }} value={periodDays}
                    onChange={(event) => setPeriodDays(Number(event.target.value))}>
                    {ANALYSIS_PERIODS.map((option) => (
                      <option key={option.days} value={option.days}>{option.label}</option>
                    ))}
                  </select>
                </div>
              )}

              <small>
                {pipelineRunId
                  ? 'Only the articles that specific pipeline run gathered are used as evidence - no new scrape runs.'
                  : (<>
                      Evidence outside this window is ignored, and each report says which window it covers.
                      Pages scraped from a competitor&rsquo;s own site are dated by when they were fetched, so
                      a longer window mainly helps with competitors the news covers rarely.
                    </>)}
              </small>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '4px 0 6px' }}>
              {pipelineRunId ? (
                <button type="button" onClick={() => runAnalysis(false)}
                  className="cs-btn cs-btn-primary"
                  style={{ justifyContent: 'flex-start', width: '100%' }}>
                  <Sparkles size={15} />
                  <span style={{ textAlign: 'left', flex: 1 }}>Analyze this pipeline run</span>
                </button>
              ) : (
                <>
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
                </>
              )}
            </div>

            <div className="confirm-modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowRunChoice(false)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmModal
        open={editOpen}
        title="Edit study"
        confirmLabel={savingEdit ? 'Saving...' : 'Save changes'}
        cancelLabel="Cancel"
        onClose={() => setEditOpen(false)}
        onConfirm={handleSaveEdit}
      >
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-study-name">Name</label>
          <input id="cs-study-name" className="cs-input" value={editDraft.name}
            onChange={(event) => setEditDraft({ ...editDraft, name: event.target.value })} />
        </div>
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-study-description">Description</label>
          <textarea id="cs-study-description" className="cs-textarea" style={{ minHeight: 80 }}
            value={editDraft.description}
            onChange={(event) => setEditDraft({ ...editDraft, description: event.target.value })} />
        </div>
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-study-status">Status</label>
          <select id="cs-study-status" className="cs-input" value={editDraft.status}
            onChange={(event) => setEditDraft({ ...editDraft, status: event.target.value })}>
            {STUDY_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </div>
      </ConfirmModal>

      <ConfirmModal
        open={scheduleOpen}
        title="Tracking schedule"
        message="Automatically re-scrape and re-analyse this study's competitors on a recurring interval."
        confirmLabel={savingSchedule ? 'Saving...' : 'Save schedule'}
        cancelLabel="Cancel"
        onClose={() => setScheduleOpen(false)}
        onConfirm={handleSaveSchedule}
      >
        <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.88rem', marginBottom: 14 }}>
          <input type="checkbox" checked={scheduleDraft.repeat_enabled}
            onChange={(event) => setScheduleDraft({ ...scheduleDraft, repeat_enabled: event.target.checked })} />
          Scrape and re-analyse automatically
        </label>
        {scheduleDraft.repeat_enabled ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: '0.88rem' }}>
            <span>Every</span>
            <input className="cs-input" type="number" min="1" style={{ width: 78 }}
              value={scheduleDraft.repeat_interval_value}
              onChange={(event) => setScheduleDraft({ ...scheduleDraft, repeat_interval_value: event.target.value })} />
            <select className="cs-input" style={{ width: 130 }} value={scheduleDraft.repeat_interval_unit}
              onChange={(event) => setScheduleDraft({ ...scheduleDraft, repeat_interval_unit: event.target.value })}>
              {SCHEDULE_UNIT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
        ) : null}
      </ConfirmModal>

      <ConfirmModal
        open={profileOpen}
        title="Business profile"
        message="This is the description competitors get matched against, and what every “how does this affect us” judgement is measured by."
        confirmLabel={savingProfile ? 'Saving...' : 'Save profile'}
        cancelLabel="Cancel"
        onClose={() => setProfileOpen(false)}
        onConfirm={handleSaveProfile}
      >
        {profileDraft ? (
          <div style={{ maxHeight: '60vh', overflowY: 'auto', paddingRight: 4 }}>
            <div className="cs-grid-2">
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-p-industry">Industry</label>
                <input id="cs-p-industry" className="cs-input" value={profileDraft.industry}
                  onChange={(event) => setProfileDraft({ ...profileDraft, industry: event.target.value })} />
              </div>
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-p-market">Market you compete in</label>
                <input id="cs-p-market" className="cs-input" value={profileDraft.market}
                  onChange={(event) => setProfileDraft({ ...profileDraft, market: event.target.value })} />
              </div>
            </div>

            <div className="cs-field">
              <label className="cs-label" htmlFor="cs-p-positioning">Positioning</label>
              <input id="cs-p-positioning" className="cs-input" value={profileDraft.positioning}
                onChange={(event) => setProfileDraft({ ...profileDraft, positioning: event.target.value })} />
            </div>

            <ListEditor label="What you offer" values={profileDraft.offerings}
              placeholder="demand forecasting"
              onChange={(offerings) => setProfileDraft({ ...profileDraft, offerings })} />
            <ListEditor label="Who buys it" values={profileDraft.audience}
              placeholder="operations directors"
              onChange={(audience) => setProfileDraft({ ...profileDraft, audience })} />
            <ListEditor label="What sets you apart" hint="used to judge competitor moves"
              values={profileDraft.differentiators} placeholder="implementation in under 30 days"
              onChange={(differentiators) => setProfileDraft({ ...profileDraft, differentiators })} />

            <div className="cs-field">
              <label className="cs-label" htmlFor="cs-p-context">Market context</label>
              <textarea id="cs-p-context" className="cs-textarea" style={{ minHeight: 110 }}
                value={profileDraft.context_summary}
                onChange={(event) => setProfileDraft({ ...profileDraft, context_summary: event.target.value })} />
            </div>
          </div>
        ) : null}
      </ConfirmModal>

      <ConfirmModal
        open={deleteOpen}
        title={`Delete study "${study?.name || ''}"?`}
        message="This will permanently remove the study, its business profile, tracked competitors, and findings."
        confirmLabel={deleting ? 'Deleting...' : 'Delete study'}
        cancelLabel="Keep study"
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDeleteStudy}
      />
    </div>
  );
}
