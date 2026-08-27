import { useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import AppShell from './components/AppShell';
import DashboardOverview from './components/DashboardOverview';
import ReportsView from './components/ReportsView';
import ProjectsPage from './components/ProjectsPage';
import ProjectDetailPage from './components/ProjectDetailPage';
import TopicDetailPage from './components/TopicDetailPage';
import IntelligencePage from './components/IntelligencePage';
import CompetitorStudiesPage from './components/CompetitorStudiesPage';
import CompetitorOnboarding from './components/CompetitorOnboarding';
import CompetitorWorkspace from './components/CompetitorWorkspace';
import CompetitorsPage from './components/CompetitorsPage';
import CompetitorEditPage from './components/CompetitorEditPage';
import CompetitorDocumentsPage from './components/CompetitorDocuments';
import CompetitorReportPage from './components/CompetitorReportPage';
import PipelineRunsPage from './components/PipelineRunsPage';
import PipelineRunDetailPage from './components/PipelineRunDetailPage';
import ArticlesPage from './components/ArticlesPage';
import AnalysisPage from './components/AnalysisPage';
import LoginPage from './components/LoginPage';
import UsersPage from './components/UsersPage';
import RolesListPage from './components/RolesListPage';
import RoleCreatePage from './components/RoleCreatePage';
import RoleEditPage from './components/RoleEditPage';
import ProjectLinkageListPage from './components/ProjectLinkageListPage';
import ProjectLinkageDetailPage from './components/ProjectLinkageDetailPage';
import ProjectLinkageEditPage from './components/ProjectLinkageEditPage';
import { useAuth } from './auth/useAuth.js';
import { RequireAuth, RequirePermission } from './routes/RouteGuards.jsx';

export default function App() {
  const location = useLocation();
  const pathname = location.pathname;
  const { user, loading: authLoading } = useAuth();
  // App mounts once at the router root and never unmounts across login/logout,
  // so data-loading effects must key off this (not `[]`) or they run before the
  // session cookie is confirmed and never refetch once auth resolves.
  const isAuthenticated = !authLoading && !!user;

  const [projects, setProjects] = useState([]);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [lastIntelligenceSyncAt, setLastIntelligenceSyncAt] = useState(null);
  const [reportPeriod, setReportPeriod] = useState('all');
  const [dashboardPeriod, setDashboardPeriod] = useState('30d');
  const [dashboardRunId, setDashboardRunId] = useState(null);
  const [reportRunId, setReportRunId] = useState(null);
  const [projectRuns, setProjectRuns] = useState([]);
  const [intelligence, setIntelligence] = useState(null);
  const [isLoadingIntelligence, setIsLoadingIntelligence] = useState(false);
  const [intelligenceError, setIntelligenceError] = useState(null);
  const [selectedProjectId, setSelectedProjectId] = useState(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('strata.selectedProjectId') : null;
    return stored ? Number(stored) : null;
  });
  const pipelineRunsPollRef = useRef(null);
  // Which (page, project) pairs have already had their pipeline-run default
  // applied - so picking a period tab (which clears the run selection) isn't
  // immediately overridden back to "the latest run" on the next fetch.
  const dashboardRunDefaultedRef = useRef(new Set());
  const reportRunDefaultedRef = useRef(new Set());

  const selectedProject = useMemo(
    () => projects.find((project) => Number(project.id) === Number(selectedProjectId)) || null,
    [projects, selectedProjectId]
  );

  // Competitor studies live in the same `projects` table (mode='competitor') but
  // have their own workspace under /competitors, so the Opinion Monitor page only
  // shows sentiment-mode projects.
  const opinionMonitorProjects = useMemo(
    () => projects.filter((project) => (project.mode || 'sentiment') !== 'competitor'),
    [projects]
  );


  const selectedPipelineHealth = useMemo(() => {
    const scoped = pipelineRuns
      .filter((run) => Number(run?.project_id) === Number(selectedProjectId))
      .sort((a, b) => new Date(b?.created_at || 0).getTime() - new Date(a?.created_at || 0).getTime());
    return {
      lastRun: scoped[0] || null,
      lastFinished: scoped.find((run) => run?.finished_at) || null,
    };
  }, [pipelineRuns, selectedProjectId]);


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

  const loadProjectRuns = async (projectId, page = null) => {
    const scopedProjectId = coerceProjectId(projectId);
    if (scopedProjectId == null) {
      setProjectRuns([]);
      return;
    }
    try {
      const res = await fetch(`/api/pipeline-runs?project_id=${scopedProjectId}&limit=500`);
      if (!res.ok) {
        setProjectRuns([]);
        return;
      }
      const data = await res.json().catch(() => ({}));
      const runs = Array.isArray(data?.runs) ? data.runs : [];
      const completed = runs
        .filter((run) => run?.finished_at)
        .sort((a, b) => new Date(b.finished_at).getTime() - new Date(a.finished_at).getTime());
      setProjectRuns(completed);

      // Default to the latest run the first time this project is viewed on
      // this page - after that, respect whatever the user picks (including
      // switching back to a period tab). A project with zero completed runs
      // has nothing to show in any recent window (Reports already starts at
      // 'all' - see reportPeriod's initial state above), so the Dashboard's
      // usual 'Last 30 days' default is switched to 'All time' instead of
      // implying a narrower time window would ever surface something.
      if (page) {
        const defaultedRef = page === 'dashboard' ? dashboardRunDefaultedRef : reportRunDefaultedRef;
        if (!defaultedRef.current.has(scopedProjectId)) {
          defaultedRef.current.add(scopedProjectId);
          if (completed.length > 0) {
            if (page === 'dashboard') setDashboardRunId(completed[0].id);
            else setReportRunId(completed[0].id);
          } else if (page === 'dashboard') {
            setDashboardPeriod('all');
          }
        }
      }
    } catch {
      setProjectRuns([]);
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

  const loadIntelligence = async (projectId = selectedProjectId, period = dashboardPeriod, runId = null) => {
    const scopedProjectId = coerceProjectId(projectId);
    if (scopedProjectId == null) {
      setIntelligence(null);
      return;
    }
    setIsLoadingIntelligence(true);
    setIntelligenceError(null);
    try {
      const params = new URLSearchParams({ period });
      if (runId) params.set('run_id', runId);
      const res = await fetch(`/api/projects/${scopedProjectId}/intelligence?${params.toString()}`);
      if (!res.ok) throw new Error(`Intelligence request failed: ${res.status}`);
      setIntelligence(await res.json());
      setLastIntelligenceSyncAt(new Date().toISOString());
    } catch (error) {
      console.error('Failed to load project intelligence', error);
      setIntelligenceError(error?.message || 'Failed to load project intelligence');
    } finally {
      setIsLoadingIntelligence(false);
    }
  };

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    refreshProjects();
    refreshUsers();
    return undefined;
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    loadPipelineRuns();
    pipelineRunsPollRef.current = setInterval(loadPipelineRuns, 5000);
    return () => stopPipelineRunsPolling();
  }, [isAuthenticated]);

  useEffect(() => {
    if (projects.length === 0) {
      if (selectedProjectId != null) {
        setSelectedProjectId(null);
      }
      return;
    }

    const currentExists = projects.some((project) => Number(project.id) === Number(selectedProjectId));
    if (selectedProjectId != null && !currentExists) {
      setSelectedProjectId(null);
    }
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

  // A selected analysis run belongs to exactly one project - carrying it over
  // to a newly-selected project would silently scope the intelligence fetch
  // to a run_id/project_id pair that can never match (see
  // intelligence.py's _fetch_project_rows, which ANDs both), showing an
  // empty "analysis run" tab strip instead of the period tabs below it.
  // Clearing the one-shot "already defaulted" markers too means switching
  // back into a project always re-applies its correct default (latest run,
  // or 'All time' for a project with none - see loadProjectRuns below)
  // rather than carrying over whatever was picked for a *different* project.
  useEffect(() => {
    if (selectedProjectId != null) {
      dashboardRunDefaultedRef.current.delete(selectedProjectId);
      reportRunDefaultedRef.current.delete(selectedProjectId);
    }
    setDashboardRunId(null);
    setReportRunId(null);
  }, [selectedProjectId]);

  useEffect(() => {
    if (!isAuthenticated || !['/dashboard', '/reports'].includes(pathname)) return;

    // Reports is project-scoped only (no "all projects" aggregate), so pick a
    // default project as soon as one is available instead of showing an empty state.
    if (selectedProjectId == null && projects.length > 0) {
      setSelectedProjectId(Number(projects[0].id));
      return;
    }

    const period = pathname === '/dashboard' ? dashboardPeriod : reportPeriod;
    const runId = pathname === '/dashboard' ? dashboardRunId : reportRunId;
    loadIntelligence(selectedProjectId, period, runId);
  }, [isAuthenticated, pathname, selectedProjectId, projects, dashboardPeriod, reportPeriod, dashboardRunId, reportRunId]);

  useEffect(() => {
    if (!isAuthenticated || !['/dashboard', '/reports'].includes(pathname) || selectedProjectId == null) return;
    // Deliberately keyed only on project/page, not on period or run
    // selection - otherwise picking a period tab (which clears the run
    // selection) would immediately re-trigger the "default to latest run"
    // logic inside loadProjectRuns and undo the user's choice.
    loadProjectRuns(selectedProjectId, pathname === '/dashboard' ? 'dashboard' : 'reports');
  }, [isAuthenticated, pathname, selectedProjectId]);

  // The backend echoes back the fully-normalized project (including resolved
  // user_ids), so we can patch it into local state directly instead of waiting
  // on a full projects refetch.
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
    <DashboardOverview
      projects={projects}
      selectedProjectId={selectedProjectId}
      onProjectChange={setSelectedProjectId}
      period={dashboardPeriod}
      onPeriodChange={(key) => { setDashboardPeriod(key); setDashboardRunId(null); }}
      runs={projectRuns}
      selectedRunId={dashboardRunId}
      onRunChange={setDashboardRunId}
      intelligence={intelligence}
      loading={isLoadingIntelligence}
      error={intelligenceError}
      pipelineHealth={selectedPipelineHealth}
    />
  );

  const renderReportsView = () => (
    <ReportsView
      projects={projects}
      isLoadingProjects={isLoadingProjects}
      selectedProject={selectedProject}
      selectedProjectId={selectedProjectId}
      onSelectedProjectIdChange={setSelectedProjectId}
      intelligence={intelligence}
      isLoadingIntelligence={isLoadingIntelligence}
      intelligenceError={intelligenceError}
      lastIntelligenceSyncAt={lastIntelligenceSyncAt}
      reportPeriod={reportPeriod}
      onReportPeriodChange={setReportPeriod}
      reportRunId={reportRunId}
      onReportRunIdChange={setReportRunId}
      projectRuns={projectRuns}
      onRefresh={() => loadIntelligence(selectedProjectId, reportPeriod, reportRunId)}
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
          <Route path="/pipeline-runs/:runId" element={<PipelineRunDetailPage projects={projects} />} />
          <Route path="/analysis" element={<AnalysisPage projects={projects} />} />
          <Route
            path="/projects"
            element={(
              <ProjectsPage
                projects={opinionMonitorProjects}
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
                  projects={opinionMonitorProjects}
                  users={users}
                  onCreateProject={createProject}
                  onUpdateProject={updateProject}
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
                  projects={opinionMonitorProjects}
                  users={users}
                  onCreateProject={createProject}
                  onUpdateProject={updateProject}
                  isLoadingProjects={isLoadingProjects}
                />
              </RequirePermission>
            )}
          />
          <Route
            path="/projects/:projectId"
            element={(
              <ProjectDetailPage
                projects={opinionMonitorProjects}
                users={users}
                onDeleteProject={deleteProject}
              />
            )}
          />
          <Route path="/projects/:projectId/topics" element={<TopicDetailPage />} />
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
          {/* Competitor study — a separate experience from the sentiment/opinion
              screens above, so it keeps its own routes and its own project scope
              (a study *is* a project, in competitor mode). */}
          <Route
            path="/competitors"
            element={(
              <RequirePermission permissions={['competitors.view']}>
                <CompetitorStudiesPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/competitors/new"
            element={(
              <RequirePermission permissions={['competitors.manage']}>
                <CompetitorOnboarding />
              </RequirePermission>
            )}
          />
          <Route
            path="/competitors/:studyId"
            element={(
              <RequirePermission permissions={['competitors.view']}>
                <CompetitorWorkspace />
              </RequirePermission>
            )}
          />
          <Route
            path="/competitors/:studyId/manage"
            element={(
              <RequirePermission permissions={['competitors.view']}>
                <CompetitorsPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/competitors/:studyId/documents"
            element={(
              <RequirePermission permissions={['competitors.manage']}>
                <CompetitorDocumentsPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/competitors/:studyId/edit"
            element={(
              <RequirePermission permissions={['competitors.manage']}>
                <CompetitorEditPage />
              </RequirePermission>
            )}
          />
          <Route
            path="/competitors/:studyId/reports/:findingId"
            element={(
              <RequirePermission permissions={['competitors.view']}>
                <CompetitorReportPage />
              </RequirePermission>
            )}
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
