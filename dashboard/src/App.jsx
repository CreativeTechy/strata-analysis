import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import StatsOverview from './components/StatsOverview';
import FeedsPage from './components/FeedsPage';
import EventsPage from './components/EventsPage';
import IntelligencePage from './components/IntelligencePage';
import WorkflowPage from './components/WorkflowPage';
import PipelineRunsPage from './components/PipelineRunsPage';
import SpiderPage from './components/SpiderPage';
import BrandSentimentPage from './components/BrandSentimentPage';
import ArticlesPage from './components/ArticlesPage';
import { RefreshCw, MessageSquare, GitMerge, Rss, Newspaper, CalendarDays } from 'lucide-react';
import { motion } from 'framer-motion';
import { supabase } from './supabaseClient';

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

  const [events, setEvents] = useState([]);
  const [reportStats, setReportStats] = useState({ total: 0, positive: 0, negative: 0, neutral: 0 });
  const [workflowArticles, setWorkflowArticles] = useState([]);
  const [isScraping, setIsScraping] = useState(false);
  const [feeds, setFeeds] = useState([]);
  const [feedSource, setFeedSource] = useState('supabase');
  const [isLoadingFeeds, setIsLoadingFeeds] = useState(false);
  const [isLoadingEvents, setIsLoadingEvents] = useState(false);
  const [isLoadingReportStats, setIsLoadingReportStats] = useState(true);
  const [selectedEventId, setSelectedEventId] = useState(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('strata.selectedEventId') : null;
    return stored ? Number(stored) : null;
  });
  const [crawlCount, setCrawlCount] = useState(null);
  const pollIntervalRef = useRef(null);

  const selectedEvent = useMemo(
    () => events.find((event) => Number(event.id) === Number(selectedEventId)) || null,
    [events, selectedEventId]
  );

  const selectedEventFeedIds = useMemo(
    () => (selectedEvent?.feed_ids || []).map(Number),
    [selectedEvent]
  );

  const selectedEventFeeds = useMemo(
    () => feeds.filter((feed) => selectedEventFeedIds.includes(Number(feed.id))),
    [feeds, selectedEventFeedIds]
  );

  const feedUrls = useMemo(() => selectedEventFeeds.map((feed) => feed.url).filter(Boolean), [selectedEventFeeds]);

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const loadCrawlCount = async () => {
    try {
      const { count } = await supabase
        .from('crawl_pages')
        .select('*', { count: 'exact', head: true });
      setCrawlCount(count ?? 0);
    } catch {
      setCrawlCount(0);
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

  const refreshFeeds = async () => {
    setIsLoadingFeeds(true);
    try {
      const res = await fetch('/api/feeds');
      if (!res.ok) return;
      const data = await res.json();
      setFeeds(Array.isArray(data?.feeds) ? data.feeds : []);
      setFeedSource(data?.source || 'supabase');
    } catch {
      setFeeds([]);
      setFeedSource('supabase');
    } finally {
      setIsLoadingFeeds(false);
    }
  };

  const loadReportStats = async (eventId = selectedEventId) => {
    setIsLoadingReportStats(true);
    try {
      const params = new URLSearchParams();
      if (eventId != null) {
        params.set('event_id', String(eventId));
      }
      const scopedRes = await fetch(`/api/articles/stats${params.toString() ? `?${params.toString()}` : ''}`);
      if (!scopedRes.ok) throw new Error(`Stats request failed: ${scopedRes.status}`);
      const data = await scopedRes.json();
      setReportStats({
        total: Number(data?.total) || 0,
        positive: Number(data?.positive) || 0,
        negative: Number(data?.negative) || 0,
        neutral: Number(data?.neutral) || 0,
      });
    } catch (error) {
      console.error('Failed to load report stats', error);
      setReportStats({ total: 0, positive: 0, negative: 0, neutral: 0 });
    } finally {
      setIsLoadingReportStats(false);
    }
  };

  const loadWorkflowArticles = async (eventId = selectedEventId) => {
    try {
      const params = new URLSearchParams({
        limit: '100',
        offset: '0',
        sort: 'published.desc',
      });
      if (eventId != null) {
        params.set('event_id', String(eventId));
      }
      const res = await fetch(`/api/articles${params.toString() ? `?${params.toString()}` : ''}`);
      if (!res.ok) throw new Error(`Articles request failed: ${res.status}`);
      const data = await res.json();
      setWorkflowArticles(Array.isArray(data?.articles) ? data.articles : []);
    } catch (error) {
      console.error('Failed to load workflow articles', error);
      setWorkflowArticles([]);
    }
  };

  useEffect(() => {
    refreshFeeds();
    refreshEvents();
    loadCrawlCount();
    return () => stopPolling();
  }, []);

  useEffect(() => {
    if (events.length === 0) {
      if (selectedEventId != null) {
        setSelectedEventId(null);
      }
      return;
    }

    const currentExists = events.some((event) => Number(event.id) === Number(selectedEventId));
    if (selectedEventId != null && !currentExists) {
      setSelectedEventId(null);
    }
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
    if (pathname === '/dashboard' || pathname === '/') {
      loadReportStats(selectedEventId);
    }

    if (pathname === '/workflow') {
      loadWorkflowArticles(selectedEventId);
    }
  }, [pathname, selectedEventId]);

  const runScraper = async (eventId = selectedEventId) => {
    if (eventId == null) return;
    stopPolling();
    setIsScraping(true);
    try {
      const res = await fetch('/scrape', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId }),
      });
      if (!res.ok) throw new Error(`Scrape request failed: ${res.status}`);
      await res.json().catch(() => ({}));

      let polls = 0;
      const maxPolls = 30;
      pollIntervalRef.current = setInterval(async () => {
        polls += 1;
        await loadWorkflowArticles(eventId);
        await loadReportStats(eventId);
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

  const createFeed = async (payload) => {
    try {
      const res = await fetch('/api/feeds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to add feed (${res.status})`);
      await refreshFeeds();
      await refreshEvents();
      return data?.feed ?? null;
    } catch (error) {
      console.error('Failed to add feed:', error);
      throw error;
    }
  };

  const updateFeed = async (feedId, payload) => {
    try {
      const res = await fetch(`/api/feeds/${feedId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to update feed (${res.status})`);
      await refreshFeeds();
      await refreshEvents();
      return data?.feed ?? null;
    } catch (error) {
      console.error('Failed to update feed:', error);
      throw error;
    }
  };

  const deleteFeed = async (feedId) => {
    try {
      const res = await fetch(`/api/feeds/${feedId}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to delete feed (${res.status})`);
      await refreshFeeds();
      await refreshEvents();
      return true;
    } catch (error) {
      console.error('Failed to remove feed:', error);
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
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to add event (${res.status})`);
      await refreshEvents();
      await refreshFeeds();
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
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to update event (${res.status})`);
      await refreshEvents();
      await refreshFeeds();
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
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to delete event (${res.status})`);
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
        onToggleFeed={(feed) => updateFeed(feed.id, { ...feed, enabled: !feed.enabled })}
      />

      <main className="main-content">
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '10px', gap: '15px', flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ fontSize: '1.8rem', color: 'var(--text-dark)' }}>Reports</h2>
            <p className="subtitle">
              Overview metrics and pipeline health{selectedEvent ? ` for ${selectedEvent.name}` : ' - all events'}
            </p>
          </div>

          <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap' }}>
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
            <Link to="/articles" className="btn-secondary" style={dashboardHeaderButtonStyle}>
              <Newspaper size={16} /> Open Articles
            </Link>
            <Link to="/feeds" className="btn-secondary" style={dashboardHeaderButtonStyle}>
              <Rss size={16} /> Manage Feeds
            </Link>
            <Link to="/events" className="btn-secondary" style={dashboardHeaderButtonStyle}>
              <CalendarDays size={16} /> Manage Events
            </Link>
            <Link to="/workflow" className="btn-secondary" style={dashboardHeaderButtonStyle}>
              <GitMerge size={16} /> Open Workflow Board
            </Link>
            <Link to="/intelligence" className="btn-primary" style={dashboardHeaderButtonStyle}>
              <MessageSquare size={16} /> Open Intelligence Copilot
            </Link>
            <button className="btn-secondary" onClick={loadReportStats}>
              <RefreshCw size={16} /> Refresh Reports
            </button>
          </div>
        </header>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
          {(isLoadingReportStats || isLoadingEvents || isLoadingFeeds) ? (
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
            crawlCount={crawlCount}
            scopeLabel={selectedEvent ? selectedEvent.name : 'all events'}
            loading={isLoadingReportStats || crawlCount == null}
          />
        </motion.div>
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
        feeds={feedUrls}
        event={selectedEvent}
      />
    </div>
  );

  const renderFeedsRoute = () => (
    <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
      <FeedsPage
        feeds={feeds}
        events={events}
        feedsSource={feedSource}
        onCreateFeed={createFeed}
        onUpdateFeed={updateFeed}
        onDeleteFeed={deleteFeed}
        isLoadingFeeds={isLoadingFeeds}
      />
    </RouteShell>
  );

  const renderEventsRoute = () => (
    <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
      <EventsPage
        events={events}
        feeds={feeds}
        onCreateEvent={createEvent}
        onUpdateEvent={updateEvent}
        onDeleteEvent={deleteEvent}
        isLoadingEvents={isLoadingEvents}
      />
    </RouteShell>
  );

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={renderDashboardView()} />
      <Route path="/articles" element={<RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}><ArticlesPage event={selectedEvent} eventId={selectedEventId} events={events} /></RouteShell>} />
      <Route path="/pipeline-runs" element={<RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}><PipelineRunsPage /></RouteShell>} />
      <Route path="/feeds" element={renderFeedsRoute()} />
      <Route path="/events" element={renderEventsRoute()} />
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
            <IntelligencePage event={selectedEvent} eventId={selectedEventId} />
          </RouteShell>
        )}
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
