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
import { RefreshCw } from 'lucide-react';
import { motion } from 'framer-motion';

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

  const loadReportStats = async (projectId = selectedProjectId) => {
    const scopedProjectId = coerceProjectId(projectId);
    setIsLoadingReportStats(true);
    try {
      const params = new URLSearchParams();
      if (scopedProjectId != null) {
        params.set('project_id', String(scopedProjectId));
      }
      const scopedRes = await fetch(`/api/articles/stats${params.toString() ? `?${params.toString()}` : ''}`);
      if (!scopedRes.ok) throw new Error(`Stats request failed: ${scopedRes.status}`);
      const data = await scopedRes.json();
      setReportStats({
        total: Number(data?.total) || 0,
        positive: Number(data?.positive) || 0,
        negative: Number(data?.negative) || 0,
        neutral: Number(data?.neutral) || 0,
        mixed: Number(data?.mixed) || 0,
        article_category_breakdown: Array.isArray(data?.article_category_breakdown) ? data.article_category_breakdown : [],
        insights: data?.insights && typeof data.insights === 'object' ? data.insights : {},
      });
    } catch (error) {
      console.error('Failed to load report stats', error);
      setReportStats({ total: 0, positive: 0, negative: 0, neutral: 0, mixed: 0, article_category_breakdown: [], insights: {} });
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
    if (!isAuthenticated) return;

    if (pathname === '/dashboard' || pathname === '/') {
      loadReportStats(selectedProjectId);
    }

    if (pathname === '/workflow') {
      loadWorkflowArticles(workflowSelectedProjectIds);
    }
  }, [isAuthenticated, pathname, selectedProjectId, workflowSelectedProjectIds]);

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
          <h2 style={{ fontSize: '1.8rem', color: 'var(--text-dark)' }}>Reports</h2>
          <p className="subtitle">
            Overview metrics and pipeline health{selectedProject ? ` for ${selectedProject.name}` : ' - all projects'}
          </p>
        </div>

        <div className="dashboard-hero-actions">
          <select
            className="filter-select"
            value={selectedProjectId ?? ''}
            onChange={(e) => setSelectedProjectId(e.target.value ? Number(e.target.value) : null)}
            disabled={isLoadingProjects || projects.length === 0}
            style={{ minWidth: '220px' }}
          >
            <option value="">{projects.length ? 'all projects' : 'No projects yet'}</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name} ({project.status || 'draft'})
              </option>
            ))}
          </select>
          <button className="btn-secondary toolbar-button" onClick={loadReportStats}>
            <RefreshCw size={16} /> Refresh Reports
          </button>
        </div>
      </header>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
        {(isLoadingReportStats || isLoadingProjects || isLoadingSources) ? (
          <span className="panel-chip warning">
            <RefreshCw size={12} className="spin" />
            Loading dashboard
          </span>
        ) : (
          <span className="panel-chip success">Dashboard ready</span>
        )}
      </div>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <StatsOverview
          stats={reportStats}
          scopeLabel={selectedProject ? selectedProject.name : 'all projects'}
          loading={isLoadingReportStats}
        />
      </motion.div>
    </div>
  );

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
            element={
              <IntelligencePage
                key={selectedProjectId ?? 'all'}
                project={selectedProject}
                projectId={selectedProjectId}
                projects={projects}
              />
            }
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
