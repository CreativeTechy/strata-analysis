import React, { useEffect, useMemo, useState } from 'react';
import Sidebar from './components/Sidebar';
import StatsOverview from './components/StatsOverview';
import FeedView from './components/FeedView';
import IntelligencePage from './components/IntelligencePage';
import WorkflowPage from './components/WorkflowPage';
import SpiderPage from './components/SpiderPage';
import BrandSentimentPage from './components/BrandSentimentPage';
import { RefreshCw, MessageSquare, GitMerge, Bug, BarChart3 } from 'lucide-react';
import { motion } from 'framer-motion';
import { supabase } from './supabaseClient';

export default function App() {
  const [articles, setArticles] = useState([]);
  const [isScraping, setIsScraping] = useState(false);
  const [activeTab, setActiveTab] = useState('workflow');
  const [feeds, setFeeds] = useState([]);
  const [feedSource, setFeedSource] = useState('fallback');
  const [isLoadingFeeds, setIsLoadingFeeds] = useState(false);
  const [crawlCount, setCrawlCount] = useState(null);
  const [pipelineRuns, setPipelineRuns] = useState([]);

  const feedUrls = useMemo(() => feeds.map((feed) => feed.url).filter(Boolean), [feeds]);

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
      setFeedSource(data?.source || 'fallback');
    } catch {
      setFeeds([]);
      setFeedSource('fallback');
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

  const addFeed = async (payload) => {
    try {
      const res = await fetch('/api/feeds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to add feed (${res.status})`);
      await refreshFeeds();
    } catch (error) {
      console.error('Failed to add feed:', error);
    }
  };

  const toggleFeed = async (feed) => {
    if (!feed?.id) return;
    try {
      const res = await fetch(`/api/feeds/${feed.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...feed,
          enabled: !feed.enabled,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to update feed (${res.status})`);
      await refreshFeeds();
    } catch (error) {
      console.error('Failed to toggle feed:', error);
    }
  };

  const removeFeed = async (feed) => {
    if (!feed?.id) return;
    try {
      const res = await fetch(`/api/feeds/${feed.id}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) throw new Error(data?.error || `Failed to delete feed (${res.status})`);
      await refreshFeeds();
    } catch (error) {
      console.error('Failed to remove feed:', error);
    }
  };

  useEffect(() => {
    loadArticles();
    refreshFeeds();
    loadCrawlCount();
    loadPipelineRuns();
  }, []);

  const runScraper = async () => {
    setIsScraping(true);
    try {
      const res = await fetch('/scrape', { method: 'POST' });
      if (!res.ok) throw new Error(`Scrape request failed: ${res.status}`);
      await res.json().catch(() => ({}));
      await loadPipelineRuns();
      let polls = 0;
      const maxPolls = 30;
      const interval = setInterval(async () => {
        polls += 1;
        await loadArticles();
        await loadPipelineRuns();
        if (polls >= maxPolls) {
          clearInterval(interval);
          setIsScraping(false);
        }
      }, 8000);
    } catch (error) {
      console.error('Failed to start scraper:', error);
      setIsScraping(false);
    }
  };

  if (activeTab === 'intelligence') {
    return (
      <div style={{ position: 'relative' }}>
        <button
          onClick={() => setActiveTab('dashboard')}
          className="btn-secondary"
          style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, background: 'white' }}
        >
          Back to Dashboard
        </button>
        <IntelligencePage />
      </div>
    );
  }

  if (activeTab === 'spider') {
    return (
      <div style={{ position: 'relative' }}>
        <button
          onClick={() => setActiveTab('workflow')}
          className="btn-secondary"
          style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, background: 'white' }}
        >
          Back
        </button>
        <SpiderPage />
      </div>
    );
  }

  if (activeTab === 'sentiment') {
    return (
      <div style={{ position: 'relative' }}>
        <button
          onClick={() => setActiveTab('workflow')}
          className="btn-secondary"
          style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, background: 'white' }}
        >
          Back
        </button>
        <BrandSentimentPage />
      </div>
    );
  }

  if (activeTab === 'workflow') {
    return (
      <div style={{ position: 'relative' }}>
        <div style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, display: 'flex', gap: '10px' }}>
          <button onClick={() => setActiveTab('dashboard')} className="btn-secondary" style={{ background: 'white' }}>
            To Dashboard
          </button>
          <button onClick={() => setActiveTab('spider')} className="btn-secondary" style={{ background: '#1a1a1a', color: '#fff', borderColor: '#1a1a1a' }}>
            <Bug size={16} /> Spider Mode
          </button>
          <button onClick={() => setActiveTab('sentiment')} className="btn-secondary" style={{ background: '#1a1a1a', color: '#fff', borderColor: '#1a1a1a' }}>
            <BarChart3 size={16} /> Brand Sentiment
          </button>
          <button onClick={() => setActiveTab('intelligence')} className="btn-primary">
            <MessageSquare size={16} /> Intelligence Copilot
          </button>
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
  }

  return (
    <div className="layout">
      <div className="bg-pattern"></div>

      <Sidebar
        feeds={feeds}
        feedsSource={feedSource}
        onAddFeed={addFeed}
        onToggleFeed={toggleFeed}
        onRemoveFeed={removeFeed}
        onRunScraper={runScraper}
        isScraping={isScraping}
        isLoadingFeeds={isLoadingFeeds}
      />

      <main className="main-content">
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '10px' }}>
          <div>
            <h2 style={{ fontSize: '1.8rem', color: 'var(--text-dark)' }}>Data Feed</h2>
            <p className="subtitle">Real-time automotive insights and sentiment</p>
          </div>

          <div style={{ display: 'flex', gap: '15px' }}>
            <button className="btn-secondary" onClick={() => setActiveTab('workflow')} style={{ background: 'white' }}>
              <GitMerge size={16} /> Open Workflow Board
            </button>
            <button className="btn-primary" onClick={() => setActiveTab('intelligence')}>
              <MessageSquare size={16} /> Open Intelligence Copilot
            </button>
            <button className="btn-secondary" onClick={loadArticles}>
              <RefreshCw size={16} /> Refresh
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
}
