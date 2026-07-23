import { useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import AppShell from './components/AppShell';
import StatsOverview from './components/StatsOverview';
import SourcesPage from './components/SourcesPage';
import ProjectsPage from './components/ProjectsPage';
import ProjectDetailPage from './components/ProjectDetailPage';
import IntelligencePage from './components/IntelligencePage';
import WorkflowPage from './components/WorkflowPage';
import PipelineRunsPage from './components/PipelineRunsPage';
import ArticlesPage from './components/ArticlesPage';
import LoginPage from './components/LoginPage';
import UsersPage from './components/UsersPage';
import RolesListPage from './components/RolesListPage';
import RoleCreatePage from './components/RoleCreatePage';
import RoleEditPage from './components/RoleEditPage';
import ProjectLinkageListPage from './components/ProjectLinkageListPage';
import ProjectLinkageDetailPage from './components/ProjectLinkageDetailPage';
import ProjectLinkageEditPage from './components/ProjectLinkageEditPage';
import { useAuth } from './auth/useAuth.js';
import { RefreshCw, FolderKanban, Database, CalendarClock, Activity, CheckCircle2, AlertCircle, BarChart3 } from 'lucide-react';
import { motion } from 'framer-motion';

const PIPELINE_STATUS_COLORS = {
  success: '#2ed573',
  failed: '#ff4757',
  running: '#ffb13b',
  queued: '#9aa0aa',
  cancelled: '#9aa0aa',
};

const SENTIMENT_COLORS = {
  positive: '#16a34a',
  negative: '#e11d48',
  neutral: '#64748b',
  mixed: '#f59e0b',
};

function dominantSentimentFromStats(stats) {
  const total = Number(stats?.total) || 0;
  if (!total) {
    return { label: 'No data yet', color: 'var(--text-light)', pct: 0 };
  }
  const entries = [
    { label: 'Positive', key: 'positive', value: Number(stats.positive) || 0 },
    { label: 'Negative', key: 'negative', value: Number(stats.negative) || 0 },
    { label: 'Neutral', key: 'neutral', value: Number(stats.neutral) || 0 },
    { label: 'Mixed', key: 'mixed', value: Number(stats.mixed) || 0 },
  ].sort((a, b) => b.value - a.value);
  const top = entries[0];
  const pct = Math.round((top.value / total) * 100);
  return { label: `${top.label} - ${pct}%`, color: SENTIMENT_COLORS[top.key] };
}

const REPORT_PERIODS = [
  { key: '7d', label: 'Last 7 days', days: 7 },
  { key: '30d', label: 'Last 30 days', days: 30 },
  { key: 'all', label: 'All time', days: null },
];

// Non-overlapping, back-to-back windows: offsetWindows=0 is "now minus N
// days through now", offsetWindows=1 is the equal-length window right
// before that - what "compare to previous period" diffs against.
function reportPeriodWindow(periodKey, offsetWindows = 0) {
  const period = REPORT_PERIODS.find((entry) => entry.key === periodKey);
  if (!period?.days) return { dateFrom: null, dateTo: null };
  const windowMs = period.days * 24 * 60 * 60 * 1000;
  const to = Date.now() - offsetWindows * windowMs;
  const from = to - windowMs;
  return { dateFrom: new Date(from).toISOString(), dateTo: new Date(to).toISOString() };
}

function timeAgo(dateString) {
  if (!dateString) return null;
  const diffMs = Date.now() - new Date(dateString).getTime();
  if (!Number.isFinite(diffMs)) return null;
  if (diffMs < 60000) return 'just now';
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function findNextScheduledRun(projects) {
  const now = Date.now();
  const candidates = projects
    .filter((project) => project.repeat_enabled && project.next_run_at)
    .map((project) => ({ project, nextRunAt: new Date(project.next_run_at).getTime() }))
    .filter(({ nextRunAt }) => Number.isFinite(nextRunAt) && nextRunAt > now)
    .sort((a, b) => a.nextRunAt - b.nextRunAt);
  return candidates[0] || null;
}

function formatCountdown(targetMs) {
  const diffMs = targetMs - Date.now();
  if (diffMs <= 0) return 'starting shortly';
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return 'in under a minute';
  if (minutes === 1) return 'in 1 minute';
  if (minutes < 60) return `in ${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h ${minutes % 60}m`;
  const days = Math.floor(hours / 24);
  return `in ${days}d ${hours % 24}h`;
}

function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        Loading...
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

function RequirePermission({ permissions, children }) {
  const { hasPermission } = useAuth();
  if (!hasPermission(...permissions)) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <h2>Access denied</h2>
        <p className="subtitle">You don't have permission to view this page.</p>
      </div>
    );
  }
  return children;
}

export default function App() {
  const location = useLocation();
  const pathname = location.pathname;
  const workflowSelectionStorageKey = 'strata.workflowSelectedProjectIds';
  const { user, loading: authLoading } = useAuth();
  // App mounts once at the router root and never unmounts across login/logout,
  // so data-loading effects must key off this (not `[]`) or they run before the
  // session cookie is confirmed and never refetch once auth resolves.
  const isAuthenticated = !authLoading && !!user;

  const [projects, setProjects] = useState([]);
  const [reportStats, setReportStats] = useState({
    total: 0,
    positive: 0,
    negative: 0,
    neutral: 0,
    mixed: 0,
    article_category_breakdown: [],
    insights: {},
  });
  const [workflowArticles, setWorkflowArticles] = useState([]);
  const [isScraping, setIsScraping] = useState(false);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [sources, setSources] = useState([]);
  const [sourcesProvenance, setSourcesProvenance] = useState('supabase');
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [isLoadingReportStats, setIsLoadingReportStats] = useState(true);
  const [reportStatsError, setReportStatsError] = useState(null);
  const [lastReportSyncAt, setLastReportSyncAt] = useState(null);
  const [reportPeriod, setReportPeriod] = useState('all');
  const [reportCompareEnabled, setReportCompareEnabled] = useState(false);
  const [reportCompareStats, setReportCompareStats] = useState(null);
  const [workflowSelectedProjectIds, setWorkflowSelectedProjectIds] = useState(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem(workflowSelectionStorageKey) : null;
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          const ids = parsed.map((value) => Number(value)).filter((value) => Number.isFinite(value));
          if (ids.length) return [...new Set(ids)];
        }
      } catch {
        // Ignore malformed localStorage and fall back to an empty selection.
      }
    }
    const selected = typeof window !== 'undefined' ? window.localStorage.getItem('strata.selectedProjectId') : null;
    return selected ? [Number(selected)] : [];
  });
  const [selectedProjectId, setSelectedProjectId] = useState(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('strata.selectedProjectId') : null;
    return stored ? Number(stored) : null;
  });
  const pollIntervalRef = useRef(null);
  const pipelineRunsPollRef = useRef(null);

  const selectedProject = useMemo(
    () => projects.find((project) => Number(project.id) === Number(selectedProjectId)) || null,
    [projects, selectedProjectId]
  );

  const selectedProjectSourceIds = useMemo(
    () => (selectedProject?.source_ids || []).map(Number),
    [selectedProject]
  );

  const selectedProjectSources = useMemo(
    () => sources.filter((source) => selectedProjectSourceIds.includes(Number(source.id))),
    [sources, selectedProjectSourceIds]
  );

  const workflowSelectedProjects = useMemo(() => {
    const selectedIds = new Set(workflowSelectedProjectIds.map((id) => Number(id)));
    return projects.filter((project) => selectedIds.has(Number(project.id)));
  }, [projects, workflowSelectedProjectIds]);

  const workflowSelectedSourceUrls = useMemo(() => {
    const urls = new Set();
    workflowSelectedProjects.forEach((project) => {
      (project.source_ids || []).forEach((sourceId) => {
        const source = sources.find((item) => Number(item.id) === Number(sourceId));
        if (source?.url) urls.add(source.url);
      });
    });
    return [...urls];
  }, [sources, workflowSelectedProjects]);

  const isTerminalPipelineStatus = (status) => ['success', 'failed', 'cancelled'].includes(String(status || '').toLowerCase());
  const activePipelineRun = useMemo(
    () => pipelineRuns.find((run) => String(run?.status || '').toLowerCase() === 'running' && String(run?.pipeline || 'scrape').toLowerCase() === 'scrape') || null,
    [pipelineRuns]
  );

  const pipelineHealth = useMemo(() => {
    const sorted = [...pipelineRuns].sort(
      (a, b) => new Date(b?.created_at || 0).getTime() - new Date(a?.created_at || 0).getTime()
    );
    const counts = { queued: 0, running: 0, success: 0, failed: 0, cancelled: 0 };
    pipelineRuns.forEach((run) => {
      const status = String(run?.status || '').toLowerCase();
      if (status in counts) counts[status] += 1;
    });
    const lastFinished = sorted.find((run) => run?.finished_at) || null;
    return { lastRun: sorted[0] || null, counts, lastFinished };
  }, [pipelineRuns]);

  const nextScheduledRun = useMemo(() => findNextScheduledRun(projects), [projects]);

  const coerceProjectId = (value) => {
    if (value == null) return null;
    if (Array.isArray(value)) return coerceProjectId(value[0]);
    if (typeof value === 'object') {
      if ('id' in value) return coerceProjectId(value.id);
      return null;
    }
    const normalized = Number(value);
    return Number.isFinite(normalized) ? normalized : null;
  };

  const normalizeWorkflowSelection = (ids, sourceProjects = projects) => {
    const availableIds = new Set(sourceProjects.map((project) => Number(project.id)));
    const normalized = [...new Set((ids || []).map((id) => Number(id)).filter((id) => Number.isFinite(id) && availableIds.has(id)))];
    if (normalized.length) return normalized;
    if (sourceProjects.length) return [Number(sourceProjects[0].id)];
    return [];
  };

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const stopPipelineRunsPolling = () => {
    if (pipelineRunsPollRef.current) {
      clearInterval(pipelineRunsPollRef.current);
      pipelineRunsPollRef.current = null;
    }
  };

  const loadPipelineRuns = async () => {
    try {
      const res = await fetch('/api/pipeline-runs?limit=25');
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      setPipelineRuns(Array.isArray(data?.runs) ? data.runs : []);
    } catch {
      setPipelineRuns([]);
    }
  };

  const refreshProjects = async () => {
    setIsLoadingProjects(true);
    try {
      const res = await fetch('/api/projects');
      if (!res.ok) return;
      const data = await res.json();
      setProjects(Array.isArray(data?.projects) ? data.projects : []);
    } catch {
      setProjects([]);
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const refreshSources = async () => {
    setIsLoadingSources(true);
    try {
      const res = await fetch('/api/sources');
      if (!res.ok) return;
      const data = await res.json();
      setSources(Array.isArray(data?.sources) ? data.sources : []);
      setSourcesProvenance(data?.source || 'supabase');
    } catch {
      setSources([]);
      setSourcesProvenance('supabase');
    } finally {
      setIsLoadingSources(false);
    }
  };

  const refreshUsers = async () => {
    setIsLoadingUsers(true);
    try {
      const res = await fetch('/api/users/linkable');
      if (!res.ok) return;
      const data = await res.json();
      setUsers(Array.isArray(data?.users) ? data.users : []);
    } catch {
      setUsers([]);
    } finally {
      setIsLoadingUsers(false);
    }
  };

  const formatApiError = (data, fallback) => {
    const parts = [data?.error, data?.detail].filter(Boolean);
    if (parts.length > 0) {
      return parts.join(' - ');
    }
    return fallback;
  };

  const fetchReportStatsForRange = async (scopedProjectId, { dateFrom, dateTo } = {}) => {
    const params = new URLSearchParams();
    if (scopedProjectId != null) {
      params.set('project_id', String(scopedProjectId));
    }
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const res = await fetch(`/api/articles/stats${params.toString() ? `?${params.toString()}` : ''}`);
    if (!res.ok) throw new Error(`Stats request failed: ${res.status}`);
    const data = await res.json();
    return {
      total: Number(data?.total) || 0,
      positive: Number(data?.positive) || 0,
      negative: Number(data?.negative) || 0,
      neutral: Number(data?.neutral) || 0,
      mixed: Number(data?.mixed) || 0,
      article_category_breakdown: Array.isArray(data?.article_category_breakdown) ? data.article_category_breakdown : [],
      insights: data?.insights && typeof data.insights === 'object' ? data.insights : {},
    };
  };

  const loadReportStats = async (projectId = selectedProjectId) => {
    const scopedProjectId = coerceProjectId(projectId);
    setIsLoadingReportStats(true);
    setReportStatsError(null);
    const shouldCompare = reportCompareEnabled && reportPeriod !== 'all';
    try {
      // Fetched independently of the (optional) compare request below: a
      // failure comparing against the previous period shouldn't cost the
      // user the primary numbers they actually asked to see.
      const current = await fetchReportStatsForRange(scopedProjectId, reportPeriodWindow(reportPeriod, 0));
      setReportStats(current);
      setLastReportSyncAt(new Date().toISOString());

      if (shouldCompare) {
        try {
          const previous = await fetchReportStatsForRange(scopedProjectId, reportPeriodWindow(reportPeriod, 1));
          setReportCompareStats(previous);
        } catch (compareError) {
          console.error('Failed to load comparison period stats', compareError);
          setReportCompareStats(null);
        }
      } else {
        setReportCompareStats(null);
      }
    } catch (error) {
      // Deliberately leave reportStats/reportCompareStats untouched: keeping
      // the last known-good numbers on screen alongside a clear error state
      // reads better than blanking the report to a misleading "0 articles".
      console.error('Failed to load report stats', error);
      setReportStatsError(error?.message || 'Failed to load reports');
    } finally {
      setIsLoadingReportStats(false);
    }
  };

  const loadWorkflowArticles = async (projectId = selectedProjectId) => {
    try {
      const projectIds = (Array.isArray(projectId) ? projectId : [projectId])
        .map((value) => coerceProjectId(value))
        .filter((value) => value != null);
      if (projectIds.length === 0) {
        setWorkflowArticles([]);
        return;
      }

      const params = new URLSearchParams({
        limit: '100',
        offset: '0',
        sort: 'published.desc',
      });
      const requests = projectIds.map(async (singleProjectId) => {
        const scopedParams = new URLSearchParams(params);
        scopedParams.set('project_id', String(singleProjectId));
        const res = await fetch(`/api/articles?${scopedParams.toString()}`);
        if (!res.ok) throw new Error(`Articles request failed: ${res.status}`);
        const data = await res.json();
        return Array.isArray(data?.articles) ? data.articles : [];
      });
      const results = await Promise.allSettled(requests);
      const articles = results.flatMap((result) => (result.status === 'fulfilled' ? result.value : []));
      const seen = new Set();
      const deduped = articles.filter((article) => {
        const key = article?.url || article?.title || JSON.stringify(article);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      }).sort((a, b) => {
        const left = new Date(a?.published || a?.created_at || a?.fetched_at || 0).getTime();
        const right = new Date(b?.published || b?.created_at || b?.fetched_at || 0).getTime();
        return right - left;
      });
      setWorkflowArticles(deduped);
    } catch (error) {
      console.error('Failed to load workflow articles', error);
      setWorkflowArticles([]);
    }
  };

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    refreshSources();
    refreshProjects();
    refreshUsers();
    return () => stopPolling();
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    loadPipelineRuns();
    pipelineRunsPollRef.current = setInterval(loadPipelineRuns, 5000);
    return () => stopPipelineRunsPolling();
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated || pathname !== '/pipeline-runs') return undefined;
    // Keeps repeat schedules (next_run_at) fresh so the upcoming-run placeholder
    // stays accurate while this page is open, without polling project data elsewhere.
    const interval = setInterval(refreshProjects, 15000);
    return () => clearInterval(interval);
  }, [isAuthenticated, pathname]);

  useEffect(() => {
    if (projects.length === 0) {
      if (selectedProjectId != null) {
        setSelectedProjectId(null);
      }
      setWorkflowSelectedProjectIds([]);
      return;
    }

    const currentExists = projects.some((project) => Number(project.id) === Number(selectedProjectId));
    if (selectedProjectId != null && !currentExists) {
      setSelectedProjectId(null);
    }

    setWorkflowSelectedProjectIds((current) => normalizeWorkflowSelection(current, projects));
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (selectedProjectId == null) {
        window.localStorage.removeItem('strata.selectedProjectId');
      } else {
        window.localStorage.setItem('strata.selectedProjectId', String(selectedProjectId));
      }
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (workflowSelectedProjectIds.length === 0) {
        window.localStorage.removeItem(workflowSelectionStorageKey);
      } else {
        window.localStorage.setItem(workflowSelectionStorageKey, JSON.stringify(workflowSelectedProjectIds));
      }
    }
  }, [workflowSelectedProjectIds]);

  useEffect(() => {
    if (!isAuthenticated || pathname !== '/reports') return;

    // Reports is project-scoped only (no "all projects" aggregate), so pick a
    // default project as soon as one is available instead of showing an empty state.
    if (selectedProjectId == null && projects.length > 0) {
      setSelectedProjectId(Number(projects[0].id));
      return;
    }

    loadReportStats(selectedProjectId);
  }, [isAuthenticated, pathname, selectedProjectId, projects, reportPeriod, reportCompareEnabled]);

  useEffect(() => {
    if (!isAuthenticated || pathname !== '/workflow') return;
    loadWorkflowArticles(workflowSelectedProjectIds);
  }, [isAuthenticated, pathname, workflowSelectedProjectIds]);

  const runScraper = async (projectIds = workflowSelectedProjectIds) => {
    const normalizedProjectIds = normalizeWorkflowSelection(Array.isArray(projectIds) ? projectIds : [projectIds]);
    if (normalizedProjectIds.length === 0) return;
    stopPolling();
    setIsScraping(true);
    try {
      const runIds = [];
      for (const projectId of normalizedProjectIds) {
        const res = await fetch('/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: projectId }),
        });
        if (!res.ok) throw new Error(`Scrape request failed: ${res.status}`);
        const data = await res.json().catch(() => ({}));
        if (data?.run_id) {
          runIds.push(String(data.run_id));
        }
      }

      let polls = 0;
      const maxPolls = 90;
      pollIntervalRef.current = setInterval(async () => {
        polls += 1;
        try {
          const res = await fetch('/api/pipeline-runs?limit=25');
          const data = await res.json().catch(() => ({}));
          const runs = Array.isArray(data?.runs) ? data.runs : [];
          const trackedRuns = runIds.length
            ? runs.filter((run) => runIds.includes(String(run.id)))
            : runs.filter((run) => normalizedProjectIds.includes(Number(run.project_id)));
          const allDone = trackedRuns.length > 0 && trackedRuns.every((run) => isTerminalPipelineStatus(run.status));
          if (allDone) {
            stopPolling();
            setIsScraping(false);
            await loadWorkflowArticles(normalizedProjectIds);
            return;
          }
        } catch (error) {
          console.error('Failed to poll pipeline runs:', error);
        }

        await loadWorkflowArticles(normalizedProjectIds);
        if (polls >= maxPolls) {
          stopPolling();
          setIsScraping(false);
        }
      }, 8000);
    } catch (error) {
      console.error('Failed to start scraper:', error);
      stopPolling();
      setIsScraping(false);
    }
  };

  const stopPipelineRun = async (runId) => {
    if (!runId) return null;
    try {
      const res = await fetch(`/api/pipeline-runs/${runId}/stop`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiError(data, `Failed to stop pipeline run (${res.status})`));
      stopPolling();
      setIsScraping(false);
      await loadPipelineRuns();
      return data;
    } catch (error) {
      console.error('Failed to stop pipeline run:', error);
      throw error;
    }
  };

  const createSource = async (payload) => {
    try {
      const res = await fetch('/api/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to add source (${res.status})`);
      await refreshSources();
      await refreshProjects();
      return data?.source ?? null;
    } catch (error) {
      console.error('Failed to add source:', error);
      throw error;
    }
  };

  const updateSource = async (sourceId, payload) => {
    try {
      const res = await fetch(`/api/sources/${sourceId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to update source (${res.status})`);
      await refreshSources();
      await refreshProjects();
      return data?.source ?? null;
    } catch (error) {
      console.error('Failed to update source:', error);
      throw error;
    }
  };

  const deleteSource = async (sourceId) => {
    try {
      const res = await fetch(`/api/sources/${sourceId}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to delete source (${res.status})`));
      await refreshSources();
      await refreshProjects();
      return true;
    } catch (error) {
      console.error('Failed to remove source:', error);
      throw error;
    }
  };

  // The backend echoes back the fully-normalized project (including resolved
  // source_ids/user_ids), so we can patch it into local state directly instead
  // of waiting on a full projects refetch. Sources themselves only need a
  // refetch if the save referenced a source_id we haven't seen yet.
  const hasUnknownSourceIds = (sourceIds) => {
    if (!Array.isArray(sourceIds) || sourceIds.length === 0) return false;
    const known = new Set(sources.map((source) => Number(source.id)));
    return sourceIds.some((id) => !known.has(Number(id)));
  };

  const createProject = async (payload) => {
    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to add project (${res.status})`));
      const created = data?.project ?? null;
      if (created) {
        setProjects((prev) => [...prev, created]);
      } else {
        refreshProjects();
      }
      if (hasUnknownSourceIds(payload?.source_ids)) {
        refreshSources();
      }
      return data ?? null;
    } catch (error) {
      console.error('Failed to add project:', error);
      throw error;
    }
  };

  const updateProject = async (projectId, payload) => {
    try {
      const res = await fetch(`/api/projects/${projectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to update project (${res.status})`));
      const updated = data?.project ?? null;
      if (updated) {
        setProjects((prev) => prev.map((project) => (Number(project.id) === Number(projectId) ? updated : project)));
      } else {
        refreshProjects();
      }
      if (hasUnknownSourceIds(payload?.source_ids)) {
        refreshSources();
      }
      return data ?? null;
    } catch (error) {
      console.error('Failed to update project:', error);
      throw error;
    }
  };

  const setProjectUsers = async (projectId, userIds) => {
    try {
      const res = await fetch(`/api/projects/${projectId}/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_ids: userIds }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to update linked users (${res.status})`));
      await refreshProjects();
      return data;
    } catch (error) {
      console.error('Failed to update linked users:', error);
      throw error;
    }
  };

  const deleteProject = async (projectId) => {
    try {
      const res = await fetch(`/api/projects/${projectId}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to delete project (${res.status})`));
      await refreshProjects();
      if (Number(selectedProjectId) === Number(projectId)) {
        setSelectedProjectId(null);
      }
      return true;
    } catch (error) {
      console.error('Failed to remove project:', error);
      throw error;
    }
  };

  const renderDashboardView = () => (
    <div className="content-shell">
      <header className="dashboard-hero">
        <div>
          <h2 style={{ fontSize: '1.8rem', color: 'var(--text-dark)' }}>Dashboard</h2>
          <p className="subtitle">Quick snapshot of your workspace</p>
        </div>
      </header>

      <section className="stats-grid" style={{ marginTop: 28 }}>
        <motion.article
          className="glass-card stat-card"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <div className="stat-icon">
            <FolderKanban size={24} />
          </div>
          <div className="stat-info">
            <h4>Total Projects</h4>
            <p>{isLoadingProjects ? '—' : projects.length.toLocaleString()}</p>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Across your workspace</span>
          </div>
        </motion.article>

        <motion.article
          className="glass-card stat-card"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <div
            className="stat-icon"
            style={{ background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(56, 189, 248, 0.1))', color: '#6366f1' }}
          >
            <Database size={24} />
          </div>
          <div className="stat-info">
            <h4>Pipeline Health</h4>
            <p style={{ color: pipelineHealth.lastRun ? PIPELINE_STATUS_COLORS[String(pipelineHealth.lastRun.status || '').toLowerCase()] : 'var(--text-dark)' }}>
              {pipelineHealth.lastRun
                ? pipelineHealth.lastRun.status.charAt(0).toUpperCase() + pipelineHealth.lastRun.status.slice(1)
                : 'No runs yet'}
            </p>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>
              {pipelineHealth.lastFinished
                ? `Last completed ${timeAgo(pipelineHealth.lastFinished.finished_at)}`
                : 'No completed runs yet'}
            </span>
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <span className="panel-chip success">{pipelineHealth.counts.success} success</span>
              <span className="panel-chip warning">{pipelineHealth.counts.running + pipelineHealth.counts.queued} running</span>
              <span className="panel-chip" style={{ background: 'rgba(255, 71, 87, 0.14)', color: '#ff4757' }}>
                {pipelineHealth.counts.failed} failed
              </span>
            </div>
          </div>
        </motion.article>

        <motion.article
          className="glass-card stat-card"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div
            className="stat-icon"
            style={{ background: 'linear-gradient(135deg, rgba(255, 107, 53, 0.1), rgba(255, 159, 67, 0.1))', color: '#ff6b35' }}
          >
            <CalendarClock size={24} />
          </div>
          <div className="stat-info">
            <h4>Next Run</h4>
            <p style={{ fontSize: '1.4rem' }}>
              {nextScheduledRun
                ? nextScheduledRun.project.name || `Project #${nextScheduledRun.project.id}`
                : 'None scheduled'}
            </p>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>
              {nextScheduledRun
                ? `Runs ${formatCountdown(nextScheduledRun.nextRunAt)} - ${new Date(nextScheduledRun.nextRunAt).toLocaleString()}`
                : 'Enable a repeat schedule on a project to see it here'}
            </span>
          </div>
        </motion.article>
      </section>
    </div>
  );

  const renderReportsView = () => {
    const hasProjects = projects.length > 0;
    const dominantSentiment = dominantSentimentFromStats(reportStats);
    const totalArticles = Number(reportStats.total) || 0;

    let syncStatus;
    if (reportStatsError) {
      syncStatus = {
        tone: 'error',
        icon: <AlertCircle size={13} />,
        label: 'Sync failed',
        detail: reportStatsError,
      };
    } else if (isLoadingReportStats) {
      syncStatus = {
        tone: 'loading',
        icon: <RefreshCw size={13} className="spin" />,
        label: 'Syncing',
        detail: 'Fetching latest data...',
      };
    } else {
      syncStatus = {
        tone: 'success',
        icon: <CheckCircle2 size={13} />,
        label: 'Up to date',
        detail: lastReportSyncAt ? `Updated ${timeAgo(lastReportSyncAt)}` : 'Not synced yet',
      };
    }

    return (
      <div className="content-shell">
        <header className="report-header">
          <div className="report-header-top">
            <div className="report-heading">
              <span className="report-kicker">
                <BarChart3 size={13} /> Reports
              </span>
              <h2 className="report-title">
                {selectedProject ? selectedProject.name : 'Select a project'}
              </h2>
              <p className="subtitle">
                Sentiment, categories, and audience insights generated from analyzed articles.
              </p>
            </div>

            <div className="report-header-actions">
              <div className="report-project-control">
                <label className="report-project-control-label" htmlFor="reports-project-select">
                  <FolderKanban size={13} /> Project scope
                </label>
                <div className="report-project-select-wrap">
                  <FolderKanban size={16} aria-hidden="true" />
                  <select
                    id="reports-project-select"
                    className="filter-select report-project-select"
                    value={selectedProjectId ?? ''}
                    onChange={(e) => setSelectedProjectId(e.target.value ? Number(e.target.value) : null)}
                    disabled={isLoadingProjects || !hasProjects}
                    aria-label="Project scope for this report"
                  >
                    {hasProjects ? (
                      projects.map((project) => (
                        <option key={project.id} value={project.id}>
                          {project.name} ({project.status || 'draft'})
                        </option>
                      ))
                    ) : (
                      <option value="">No projects yet</option>
                    )}
                  </select>
                </div>
              </div>

              <button
                type="button"
                className="btn-secondary toolbar-button report-refresh-btn"
                onClick={() => loadReportStats()}
                disabled={isLoadingReportStats || !hasProjects}
                aria-busy={isLoadingReportStats}
              >
                <RefreshCw size={16} className={isLoadingReportStats ? 'spin' : ''} />
                {isLoadingReportStats ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
          </div>

          <div className="report-filter-row">
            <div className="source-type-tabs" role="tablist" aria-label="Report date range">
              {REPORT_PERIODS.map((period) => (
                <button
                  key={period.key}
                  type="button"
                  role="tab"
                  aria-selected={reportPeriod === period.key}
                  className={`source-type-tab ${reportPeriod === period.key ? 'active' : ''}`}
                  onClick={() => setReportPeriod(period.key)}
                >
                  {period.label}
                </button>
              ))}
            </div>

            <label className={`report-compare-toggle ${reportPeriod === 'all' ? 'disabled' : ''}`}>
              <input
                type="checkbox"
                checked={reportCompareEnabled}
                disabled={reportPeriod === 'all'}
                onChange={(e) => setReportCompareEnabled(e.target.checked)}
              />
              Compare to previous period
            </label>
          </div>

          <ul className="report-summary-chips" aria-label="Report summary">
            <li className="report-chip">
              <FolderKanban size={13} aria-hidden="true" />
              <span className="report-chip-label">Project</span>
              <strong>{selectedProject ? selectedProject.name : 'None selected'}</strong>
            </li>
            <li className="report-chip">
              <Activity size={13} aria-hidden="true" />
              <span className="report-chip-label">Articles analyzed</span>
              <strong>{totalArticles.toLocaleString()}</strong>
            </li>
            <li className="report-chip">
              <BarChart3 size={13} aria-hidden="true" style={{ color: dominantSentiment.color }} />
              <span className="report-chip-label">Dominant sentiment</span>
              <strong style={{ color: dominantSentiment.color }}>{dominantSentiment.label}</strong>
            </li>
            <li className="report-chip">
              <CalendarClock size={13} aria-hidden="true" />
              <span className="report-chip-label">Range</span>
              <strong>
                {REPORT_PERIODS.find((period) => period.key === reportPeriod)?.label}
                {reportCompareEnabled && reportPeriod !== 'all' ? ' (compared)' : ''}
              </strong>
            </li>
            <li
              className={`report-chip report-sync-chip report-sync-${syncStatus.tone}`}
              role="status"
              aria-live="polite"
            >
              {syncStatus.icon}
              <span className="report-chip-label">{syncStatus.label}</span>
              <strong>{syncStatus.detail}</strong>
            </li>
          </ul>
        </header>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <StatsOverview
            stats={reportStats}
            compareStats={reportCompareEnabled && reportPeriod !== 'all' ? reportCompareStats : null}
            comparePeriodLabel={(() => {
              const period = REPORT_PERIODS.find((entry) => entry.key === reportPeriod);
              return period?.days ? `${period.days}-day period` : null;
            })()}
            scopeLabel={selectedProject ? selectedProject.name : 'no project selected'}
            loading={isLoadingReportStats}
            error={reportStatsError}
            onRetry={() => loadReportStats()}
          />
        </motion.div>
      </div>
    );
  };

  const renderWorkflowRoute = () => (
    <WorkflowPage
      articles={workflowArticles}
      isScraping={isScraping}
      onRunScraper={runScraper}
      sources={workflowSelectedSourceUrls}
      projects={projects}
      selectedProjects={workflowSelectedProjects}
      selectedProjectIds={workflowSelectedProjectIds}
      onChangeSelectedProjectIds={setWorkflowSelectedProjectIds}
      activeRun={activePipelineRun}
      onStopRun={stopPipelineRun}
    />
  );

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={renderDashboardView()} />
          <Route path="/reports" element={renderReportsView()} />
          <Route path="/articles" element={<ArticlesPage project={selectedProject} projectId={selectedProjectId} projects={projects} />} />
          <Route path="/pipeline-runs" element={<PipelineRunsPage projects={projects} />} />
          <Route
            path="/sources"
            element={(
              <SourcesPage
                sources={sources}
                projects={projects}
                sourcesSource={sourcesProvenance}
                onCreateSource={createSource}
                onUpdateSource={updateSource}
                onDeleteSource={deleteSource}
                isLoadingSources={isLoadingSources}
              />
            )}
          />
          <Route
            path="/sources/new"
            element={(
              <RequirePermission permissions={['sources.create']}>
                <SourcesPage
                  sources={sources}
                  projects={projects}
                  sourcesSource={sourcesProvenance}
                  onCreateSource={createSource}
                  onUpdateSource={updateSource}
                  onDeleteSource={deleteSource}
                  isLoadingSources={isLoadingSources}
                />
              </RequirePermission>
            )}
          />
          <Route
            path="/sources/:sourceId/edit"
            element={(
              <RequirePermission permissions={['sources.update']}>
                <SourcesPage
                  sources={sources}
                  projects={projects}
                  sourcesSource={sourcesProvenance}
                  onCreateSource={createSource}
                  onUpdateSource={updateSource}
                  onDeleteSource={deleteSource}
                  isLoadingSources={isLoadingSources}
                />
              </RequirePermission>
            )}
          />
          <Route
            path="/projects"
            element={(
              <ProjectsPage
                projects={projects}
                sources={sources}
                users={users}
                onCreateProject={createProject}
                onUpdateProject={updateProject}
                isLoadingProjects={isLoadingProjects}
              />
            )}
          />
          <Route
            path="/projects/new"
            element={(
              <RequirePermission permissions={['projects.create']}>
                <ProjectsPage
                  projects={projects}
                  sources={sources}
                  users={users}
                  onCreateProject={createProject}
                  onUpdateProject={updateProject}
                  onCreateSource={createSource}
                  onRefreshSources={refreshSources}
                  isLoadingProjects={isLoadingProjects}
                />
              </RequirePermission>
            )}
          />
          <Route
            path="/projects/:projectId/edit"
            element={(
              <RequirePermission permissions={['projects.update']}>
                <ProjectsPage
                  projects={projects}
                  sources={sources}
                  users={users}
                  onCreateProject={createProject}
                  onUpdateProject={updateProject}
                  onCreateSource={createSource}
                  onRefreshSources={refreshSources}
                  isLoadingProjects={isLoadingProjects}
                />
              </RequirePermission>
            )}
          />
          <Route
            path="/projects/:projectId"
            element={(
              <ProjectDetailPage
                projects={projects}
                sources={sources}
                users={users}
                onDeleteProject={deleteProject}
              />
            )}
          />
          <Route path="/workflow" element={renderWorkflowRoute()} />
          <Route
            path="/intelligence"
            element={<IntelligencePage key={selectedProjectId ?? 'all'} project={selectedProject} projectId={selectedProjectId} />}
          />
          <Route
            path="/admin/users"
            element={(
              <RequirePermission permissions={['users.view']}>
                <UsersPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/admin/roles"
            element={(
              <RequirePermission permissions={['roles.view']}>
                <RolesListPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/admin/roles/new"
            element={(
              <RequirePermission permissions={['roles.create']}>
                <RoleCreatePage />
              </RequirePermission>
            )}
          />
          <Route
            path="/admin/roles/:roleId/edit"
            element={(
              <RequirePermission permissions={['roles.update']}>
                <RoleEditPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/admin/project-linkage"
            element={(
              <RequirePermission permissions={['projects.link_users']}>
                <ProjectLinkageListPage
                  projects={projects}
                  users={users}
                  isLoadingProjects={isLoadingProjects}
                  isLoadingUsers={isLoadingUsers}
                />
              </RequirePermission>
            )}
          />
          <Route
            path="/admin/project-linkage/:projectId"
            element={(
              <RequirePermission permissions={['projects.link_users']}>
                <ProjectLinkageDetailPage projects={projects} users={users} />
              </RequirePermission>
            )}
          />
          <Route
            path="/admin/project-linkage/:projectId/edit"
            element={(
              <RequirePermission permissions={['projects.link_users']}>
                <ProjectLinkageEditPage projects={projects} users={users} onSetProjectUsers={setProjectUsers} />
              </RequirePermission>
            )}
          />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
