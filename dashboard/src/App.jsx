import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import StatsOverview from './components/StatsOverview';
import SourcesPage from './components/SourcesPage';
import EventsPage from './components/EventsPage';
import EventDetailPage from './components/EventDetailPage';
import IntelligencePage from './components/IntelligencePage';
import WorkflowPage from './components/WorkflowPage';
import PipelineRunsPage from './components/PipelineRunsPage';
import SpiderPage from './components/SpiderPage';
import BrandSentimentPage from './components/BrandSentimentPage';
import ArticlesPage from './components/ArticlesPage';
import { RefreshCw, MessageSquare, GitMerge, Rss, Newspaper, CalendarDays } from 'lucide-react';
import { motion } from 'framer-motion';

function RouteShell({ children, backTo, backLabel, backStyle }) {
  return (
    <div style={{ position: 'relative' }}>
      <div style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000 }}>
        <Link to={backTo} className="btn-secondary" style={{ ...backStyle, textDecoration: 'none' }}>
          {backLabel}
        </Link>
      </div>
      {children}
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const pathname = location.pathname;
  const workflowSelectionStorageKey = 'strata.workflowSelectedEventIds';

  const [events, setEvents] = useState([]);
  const [reportStats, setReportStats] = useState({
    total: 0,
    positive: 0,
    negative: 0,
    neutral: 0,
    article_category_breakdown: [],
    insights: {},
  });
  const [workflowArticles, setWorkflowArticles] = useState([]);
  const [isScraping, setIsScraping] = useState(false);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [sources, setSources] = useState([]);
  const [sourcesProvenance, setSourcesProvenance] = useState('supabase');
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [isLoadingEvents, setIsLoadingEvents] = useState(false);
  const [isLoadingReportStats, setIsLoadingReportStats] = useState(true);
  const [workflowSelectedEventIds, setWorkflowSelectedEventIds] = useState(() => {
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
    const selected = typeof window !== 'undefined' ? window.localStorage.getItem('strata.selectedEventId') : null;
    return selected ? [Number(selected)] : [];
  });
  const [selectedEventId, setSelectedEventId] = useState(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('strata.selectedEventId') : null;
    return stored ? Number(stored) : null;
  });
  const [appNow, setAppNow] = useState(() => new Date());
  const pollIntervalRef = useRef(null);
  const pipelineRunsPollRef = useRef(null);

  const selectedEvent = useMemo(
    () => events.find((event) => Number(event.id) === Number(selectedEventId)) || null,
    [events, selectedEventId]
  );

  const selectedEventSourceIds = useMemo(
    () => (selectedEvent?.source_ids || []).map(Number),
    [selectedEvent]
  );

  const selectedEventSources = useMemo(
    () => sources.filter((source) => selectedEventSourceIds.includes(Number(source.id))),
    [sources, selectedEventSourceIds]
  );

  const workflowSelectedEvents = useMemo(() => {
    const selectedIds = new Set(workflowSelectedEventIds.map((id) => Number(id)));
    return events.filter((event) => selectedIds.has(Number(event.id)));
  }, [events, workflowSelectedEventIds]);

  const workflowSelectedSourceUrls = useMemo(() => {
    const urls = new Set();
    workflowSelectedEvents.forEach((event) => {
      (event.source_ids || []).forEach((sourceId) => {
        const source = sources.find((item) => Number(item.id) === Number(sourceId));
        if (source?.url) urls.add(source.url);
      });
    });
    return [...urls];
  }, [sources, workflowSelectedEvents]);

  const isTerminalPipelineStatus = (status) => ['success', 'failed'].includes(String(status || '').toLowerCase());
  const activePipelineRun = useMemo(
    () => pipelineRuns.find((run) => String(run?.status || '').toLowerCase() === 'running' && String(run?.pipeline || 'scrape').toLowerCase() === 'scrape') || null,
    [pipelineRuns]
  );
  const activePipelineStartedAt = activePipelineRun?.started_at || activePipelineRun?.created_at || null;

  const coerceEventId = (value) => {
    if (value == null) return null;
    if (Array.isArray(value)) return coerceEventId(value[0]);
    if (typeof value === 'object') {
      if ('id' in value) return coerceEventId(value.id);
      return null;
    }
    const normalized = Number(value);
    return Number.isFinite(normalized) ? normalized : null;
  };

  const normalizeWorkflowSelection = (ids, sourceEvents = events) => {
    const availableIds = new Set(sourceEvents.map((event) => Number(event.id)));
    const normalized = [...new Set((ids || []).map((id) => Number(id)).filter((id) => Number.isFinite(id) && availableIds.has(id)))];
    if (normalized.length) return normalized;
    if (sourceEvents.length) return [Number(sourceEvents[0].id)];
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

  const refreshEvents = async () => {
    setIsLoadingEvents(true);
    try {
      const res = await fetch('/api/events');
      if (!res.ok) return;
      const data = await res.json();
      setEvents(Array.isArray(data?.events) ? data.events : []);
    } catch {
      setEvents([]);
    } finally {
      setIsLoadingEvents(false);
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

  const formatApiError = (data, fallback) => {
    const parts = [data?.error, data?.detail].filter(Boolean);
    if (parts.length > 0) {
      return parts.join(' - ');
    }
    return fallback;
  };

  const loadReportStats = async (eventId = selectedEventId) => {
    const scopedEventId = coerceEventId(eventId);
    setIsLoadingReportStats(true);
    try {
      const params = new URLSearchParams();
      if (scopedEventId != null) {
        params.set('event_id', String(scopedEventId));
      }
      const scopedRes = await fetch(`/api/articles/stats${params.toString() ? `?${params.toString()}` : ''}`);
      if (!scopedRes.ok) throw new Error(`Stats request failed: ${scopedRes.status}`);
      const data = await scopedRes.json();
      setReportStats({
        total: Number(data?.total) || 0,
        positive: Number(data?.positive) || 0,
        negative: Number(data?.negative) || 0,
        neutral: Number(data?.neutral) || 0,
        article_category_breakdown: Array.isArray(data?.article_category_breakdown) ? data.article_category_breakdown : [],
        insights: data?.insights && typeof data.insights === 'object' ? data.insights : {},
      });
    } catch (error) {
      console.error('Failed to load report stats', error);
      setReportStats({ total: 0, positive: 0, negative: 0, neutral: 0, article_category_breakdown: [], insights: {} });
    } finally {
      setIsLoadingReportStats(false);
    }
  };

  const loadWorkflowArticles = async (eventId = selectedEventId) => {
    try {
      const eventIds = (Array.isArray(eventId) ? eventId : [eventId])
        .map((value) => coerceEventId(value))
        .filter((value) => value != null);
      if (eventIds.length === 0) {
        setWorkflowArticles([]);
        return;
      }

      const params = new URLSearchParams({
        limit: '100',
        offset: '0',
        sort: 'published.desc',
      });
      const requests = eventIds.map(async (singleEventId) => {
        const scopedParams = new URLSearchParams(params);
        scopedParams.set('event_id', String(singleEventId));
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
    refreshSources();
    refreshEvents();
    return () => stopPolling();
  }, []);

  useEffect(() => {
    loadPipelineRuns();
    pipelineRunsPollRef.current = setInterval(loadPipelineRuns, 5000);
    return () => stopPipelineRunsPolling();
  }, []);

  useEffect(() => {
    if (events.length === 0) {
      if (selectedEventId != null) {
        setSelectedEventId(null);
      }
      setWorkflowSelectedEventIds([]);
      return;
    }

    const currentExists = events.some((event) => Number(event.id) === Number(selectedEventId));
    if (selectedEventId != null && !currentExists) {
      setSelectedEventId(null);
    }

    setWorkflowSelectedEventIds((current) => normalizeWorkflowSelection(current, events));
  }, [events, selectedEventId]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (selectedEventId == null) {
        window.localStorage.removeItem('strata.selectedEventId');
      } else {
        window.localStorage.setItem('strata.selectedEventId', String(selectedEventId));
      }
    }
  }, [selectedEventId]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (workflowSelectedEventIds.length === 0) {
        window.localStorage.removeItem(workflowSelectionStorageKey);
      } else {
        window.localStorage.setItem(workflowSelectionStorageKey, JSON.stringify(workflowSelectedEventIds));
      }
    }
  }, [workflowSelectedEventIds]);

  useEffect(() => {
    if (pathname === '/dashboard' || pathname === '/') {
      loadReportStats(selectedEventId);
    }

    if (pathname === '/workflow') {
      loadWorkflowArticles(workflowSelectedEventIds);
    }
  }, [pathname, selectedEventId, workflowSelectedEventIds]);

  const runScraper = async (eventIds = workflowSelectedEventIds) => {
    const normalizedEventIds = normalizeWorkflowSelection(Array.isArray(eventIds) ? eventIds : [eventIds]);
    if (normalizedEventIds.length === 0) return;
    stopPolling();
    setIsScraping(true);
    try {
      const runIds = [];
      for (const eventId of normalizedEventIds) {
        const res = await fetch('/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_id: eventId }),
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
            : runs.filter((run) => normalizedEventIds.includes(Number(run.event_id)));
          const allDone = trackedRuns.length > 0 && trackedRuns.every((run) => isTerminalPipelineStatus(run.status));
          if (allDone) {
            stopPolling();
            setIsScraping(false);
            await loadWorkflowArticles(normalizedEventIds);
            return;
          }
        } catch (error) {
          console.error('Failed to poll pipeline runs:', error);
        }

        await loadWorkflowArticles(normalizedEventIds);
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

  const dashboardHeaderButtonStyle = {
    textDecoration: 'none',
  };

  useEffect(() => {
    const timer = setInterval(() => setAppNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatElapsed = (startedAt, now) => {
    if (!startedAt) return '00:00:00';
    const started = new Date(startedAt);
    if (Number.isNaN(started.getTime())) return '00:00:00';
    const totalSeconds = Math.max(0, Math.floor((now.getTime() - started.getTime()) / 1000));
    const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
    const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
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
      await refreshEvents();
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
      await refreshEvents();
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
      await refreshEvents();
      return true;
    } catch (error) {
      console.error('Failed to remove source:', error);
      throw error;
    }
  };

  const createEvent = async (payload) => {
    try {
      const res = await fetch('/api/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to add event (${res.status})`));
      await refreshEvents();
      await refreshSources();
      return data ?? null;
    } catch (error) {
      console.error('Failed to add event:', error);
      throw error;
    }
  };

  const updateEvent = async (eventId, payload) => {
    try {
      const res = await fetch(`/api/events/${eventId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to update event (${res.status})`));
      await refreshEvents();
      await refreshSources();
      return data ?? null;
    } catch (error) {
      console.error('Failed to update event:', error);
      throw error;
    }
  };

  const deleteEvent = async (eventId) => {
    try {
      const res = await fetch(`/api/events/${eventId}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(formatApiError(data, `Failed to delete event (${res.status})`));
      await refreshEvents();
      if (Number(selectedEventId) === Number(eventId)) {
        setSelectedEventId(null);
      }
      return true;
    } catch (error) {
      console.error('Failed to remove event:', error);
      throw error;
    }
  };

  const renderDashboardView = () => (
    <div className="layout">
      <div className="bg-pattern"></div>

      <Sidebar
        onToggleSource={(source) => updateSource(source.id, { ...source, enabled: !source.enabled })}
      />

      <main className="main-content">
        <div className="content-shell">
          <header className="dashboard-hero">
            <div>
              <h2 style={{ fontSize: '1.8rem', color: 'var(--text-dark)' }}>Reports</h2>
              <p className="subtitle">
                Overview metrics and pipeline health{selectedEvent ? ` for ${selectedEvent.name}` : ' - all events'}
              </p>
            </div>

            <div className="dashboard-hero-actions">
              <select
                className="filter-select"
                value={selectedEventId ?? ''}
                onChange={(e) => setSelectedEventId(e.target.value ? Number(e.target.value) : null)}
                disabled={isLoadingEvents || events.length === 0}
                style={{ minWidth: '220px' }}
              >
                <option value="">{events.length ? 'all events' : 'No events yet'}</option>
                {events.map((event) => (
                  <option key={event.id} value={event.id}>
                    {event.name} ({event.status || 'draft'})
                  </option>
                ))}
              </select>
              <Link to="/articles" className="btn-secondary toolbar-button" style={dashboardHeaderButtonStyle}>
                <Newspaper size={16} /> Open Articles
              </Link>
              <Link to="/sources" className="btn-secondary toolbar-button" style={dashboardHeaderButtonStyle}>
                <Rss size={16} /> Manage Sources
              </Link>
              <Link to="/events" className="btn-secondary toolbar-button" style={dashboardHeaderButtonStyle}>
                <CalendarDays size={16} /> Manage Events
              </Link>
              <Link to="/workflow" className="btn-secondary toolbar-button" style={dashboardHeaderButtonStyle}>
                <GitMerge size={16} /> Open Workflow Board
              </Link>
              <Link to="/intelligence" className="btn-primary toolbar-button toolbar-button-primary" style={dashboardHeaderButtonStyle}>
                <MessageSquare size={16} /> Open Intelligence Copilot
              </Link>
              <button className="btn-secondary toolbar-button" onClick={loadReportStats}>
                <RefreshCw size={16} /> Refresh Reports
              </button>
            </div>
          </header>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
            {(isLoadingReportStats || isLoadingEvents || isLoadingSources) ? (
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
              scopeLabel={selectedEvent ? selectedEvent.name : 'all events'}
              loading={isLoadingReportStats}
            />
          </motion.div>
        </div>
      </main>
    </div>
  );

  const renderWorkflowRoute = () => (
    <div style={{ position: 'relative' }}>
      <div style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        <Link to="/dashboard" className="btn-secondary" style={{ background: 'white', textDecoration: 'none' }}>
          To Dashboard
        </Link>
      </div>

      <WorkflowPage
        articles={workflowArticles}
        isScraping={isScraping}
        onRunScraper={runScraper}
        sources={workflowSelectedSourceUrls}
        events={events}
        selectedEvents={workflowSelectedEvents}
        selectedEventIds={workflowSelectedEventIds}
        onChangeSelectedEventIds={setWorkflowSelectedEventIds}
      />
    </div>
  );

  return (
    <div>
      <div
        style={{
          position: 'fixed',
          top: 14,
          right: 14,
          zIndex: 2000,
          padding: '10px 14px',
          borderRadius: 999,
          background: 'rgba(15, 23, 42, 0.92)',
          color: 'white',
          boxShadow: '0 10px 24px rgba(15, 23, 42, 0.18)',
          backdropFilter: 'blur(12px)',
          fontSize: '0.8rem',
          display: 'flex',
          gap: 10,
          alignItems: 'center',
        }}
      >
        <span style={{ opacity: 0.72, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Live timer</span>
        <strong>{formatElapsed(activePipelineStartedAt, appNow)}</strong>
      </div>

      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={renderDashboardView()} />
        <Route path="/articles" element={<RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}><ArticlesPage event={selectedEvent} eventId={selectedEventId} events={events} /></RouteShell>} />
        <Route path="/pipeline-runs" element={<RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}><PipelineRunsPage /></RouteShell>} />
        <Route
          path="/sources"
          element={(
            <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
              <SourcesPage
                sources={sources}
                events={events}
                sourcesSource={sourcesProvenance}
                onCreateSource={createSource}
                onUpdateSource={updateSource}
                onDeleteSource={deleteSource}
                isLoadingSources={isLoadingSources}
              />
            </RouteShell>
          )}
        />
        <Route
          path="/sources/new"
          element={(
            <RouteShell backTo="/sources" backLabel="Back to Sources" backStyle={{ background: 'white' }}>
              <SourcesPage
                sources={sources}
                events={events}
                sourcesSource={sourcesProvenance}
                onCreateSource={createSource}
                onUpdateSource={updateSource}
                onDeleteSource={deleteSource}
                isLoadingSources={isLoadingSources}
              />
            </RouteShell>
          )}
        />
        <Route
          path="/sources/:sourceId/edit"
          element={(
            <RouteShell backTo="/sources" backLabel="Back to Sources" backStyle={{ background: 'white' }}>
              <SourcesPage
                sources={sources}
                events={events}
                sourcesSource={sourcesProvenance}
                onCreateSource={createSource}
                onUpdateSource={updateSource}
                onDeleteSource={deleteSource}
                isLoadingSources={isLoadingSources}
              />
            </RouteShell>
          )}
        />
        <Route
          path="/events"
          element={(
            <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
              <EventsPage
                events={events}
                sources={sources}
                onCreateEvent={createEvent}
                onUpdateEvent={updateEvent}
                isLoadingEvents={isLoadingEvents}
              />
            </RouteShell>
          )}
        />
        <Route
          path="/events/new"
          element={(
            <RouteShell backTo="/events" backLabel="Back to Events" backStyle={{ background: 'white' }}>
              <EventsPage
                events={events}
                sources={sources}
                onCreateEvent={createEvent}
                onUpdateEvent={updateEvent}
                onCreateSource={createSource}
                isLoadingEvents={isLoadingEvents}
              />
            </RouteShell>
          )}
        />
        <Route
          path="/events/:eventId/edit"
          element={(
            <RouteShell backTo="/events" backLabel="Back to Events" backStyle={{ background: 'white' }}>
              <EventsPage
                events={events}
                sources={sources}
                onCreateEvent={createEvent}
                onUpdateEvent={updateEvent}
                isLoadingEvents={isLoadingEvents}
              />
            </RouteShell>
          )}
        />
        <Route
          path="/events/:eventId"
          element={(
            <RouteShell backTo="/events" backLabel="Back to Events" backStyle={{ background: 'white' }}>
              <EventDetailPage
                events={events}
                sources={sources}
                onDeleteEvent={deleteEvent}
              />
            </RouteShell>
          )}
        />
        <Route path="/workflow" element={renderWorkflowRoute()} />
        <Route
          path="/spider"
          element={(
            <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
              <SpiderPage />
            </RouteShell>
          )}
        />
        <Route
          path="/sentiment"
          element={(
            <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
              <BrandSentimentPage />
            </RouteShell>
          )}
        />
        <Route
          path="/intelligence"
          element={(
            <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
              <IntelligencePage key={selectedEventId ?? 'all'} event={selectedEvent} eventId={selectedEventId} />
            </RouteShell>
          )}
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </div>
  );
}
