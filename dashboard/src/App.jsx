import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import StatsOverview from './components/StatsOverview';
import FeedView from './components/FeedView';
import FeedsPage from './components/FeedsPage';
import IntelligencePage from './components/IntelligencePage';
import WorkflowPage from './components/WorkflowPage';
import SpiderPage from './components/SpiderPage';
import BrandSentimentPage from './components/BrandSentimentPage';
import { RefreshCw, MessageSquare, GitMerge, Bug, BarChart3, Rss } from 'lucide-react';
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
  const [articles, setArticles] = useState([]);
  const [isScraping, setIsScraping] = useState(false);
  const [feeds, setFeeds] = useState([]);
  const [feedSource, setFeedSource] = useState('supabase');
  const [isLoadingFeeds, setIsLoadingFeeds] = useState(false);
  const [crawlCount, setCrawlCount] = useState(null);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const pollIntervalRef = useRef(null);

  const feedUrls = useMemo(() => feeds.map((feed) => feed.url).filter(Boolean), [feeds]);

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

  const loadArticles = async () => {
    try {
      const { data, error } = await supabase
        .from('articles')
        .select('*')
        .order('published', { ascending: false });

      if (error) throw error;
      if (data) setArticles(data);
    } catch (e) {
      console.error('Failed to load articles', e);
    }
  };

  const loadPipelineRuns = async () => {
    try {
      const res = await fetch('/api/pipeline-runs?limit=6');
      if (!res.ok) return;
      const data = await res.json();
      setPipelineRuns(Array.isArray(data?.runs) ? data.runs : []);
    } catch {
      setPipelineRuns([]);
    }
  };

  useEffect(() => {
    loadArticles();
    refreshFeeds();
    loadCrawlCount();
    loadPipelineRuns();
    return () => stopPolling();
  }, []);

  const runScraper = async () => {
    stopPolling();
    setIsScraping(true);
    try {
      const res = await fetch('/scrape', { method: 'POST' });
      if (!res.ok) throw new Error(`Scrape request failed: ${res.status}`);
      await res.json().catch(() => ({}));
      await loadPipelineRuns();

      let polls = 0;
      const maxPolls = 30;
      pollIntervalRef.current = setInterval(async () => {
        polls += 1;
        await loadArticles();
        await loadPipelineRuns();
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
      return true;
    } catch (error) {
      console.error('Failed to remove feed:', error);
      throw error;
    }
  };

  const renderDashboardView = () => (
    <div className="layout">
      <div className="bg-pattern"></div>

      <Sidebar
        feeds={feeds}
        onToggleFeed={(feed) => updateFeed(feed.id, { ...feed, enabled: !feed.enabled })}
        onRunScraper={runScraper}
        isScraping={isScraping}
      />

      <main className="main-content">
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '10px', gap: '15px', flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ fontSize: '1.8rem', color: 'var(--text-dark)' }}>Data Feed</h2>
            <p className="subtitle">Real-time automotive insights and sentiment</p>
          </div>

          <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap' }}>
            <Link to="/feeds" className="btn-secondary" style={dashboardHeaderButtonStyle}>
              <Rss size={16} /> Manage Feeds
            </Link>
            <Link to="/workflow" className="btn-secondary" style={dashboardHeaderButtonStyle}>
              <GitMerge size={16} /> Open Workflow Board
            </Link>
            <Link to="/intelligence" className="btn-primary" style={dashboardHeaderButtonStyle}>
              <MessageSquare size={16} /> Open Intelligence Copilot
            </Link>
            <button className="btn-secondary" onClick={loadArticles}>
              <RefreshCw size={16} /> Refresh Feeds
            </button>
          </div>
        </header>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <StatsOverview articles={articles} crawlCount={crawlCount} />
          <FeedView articles={articles} isScraping={isScraping} />
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
        articles={articles}
        isScraping={isScraping}
        onRunScraper={runScraper}
        feeds={feedUrls}
        pipelineRuns={pipelineRuns}
      />
    </div>
  );

  const renderFeedsRoute = () => (
    <RouteShell backTo="/dashboard" backLabel="Back to Dashboard" backStyle={{ background: 'white' }}>
      <FeedsPage
        feeds={feeds}
        feedsSource={feedSource}
        onCreateFeed={createFeed}
        onUpdateFeed={updateFeed}
        onDeleteFeed={deleteFeed}
        isLoadingFeeds={isLoadingFeeds}
      />
    </RouteShell>
  );

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={renderDashboardView()} />
      <Route path="/feeds" element={renderFeedsRoute()} />
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
            <IntelligencePage />
          </RouteShell>
        )}
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
