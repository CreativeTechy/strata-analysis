import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import StatsOverview from './components/StatsOverview';
import FeedView from './components/FeedView';
import IntelligencePage from './components/IntelligencePage';
import WorkflowPage from './components/WorkflowPage';
import { RefreshCw, MessageSquare, GitMerge } from 'lucide-react';
import { motion } from 'framer-motion';

export default function App() {
  const [articles, setArticles] = useState([]);
  const [isScraping, setIsScraping] = useState(false);
  const [activeTab, setActiveTab] = useState('workflow'); // 'dashboard', 'intelligence', 'workflow'
  
  const [feeds, setFeeds] = useState([
    "https://www.motor1.com/rss/news/all/",
    "https://www.carscoops.com/feed/",
    "https://www.autoblog.com/rss.xml",
    "https://www.bmwblog.com/feed/"
  ]);

  const loadArticles = async () => {
    try {
      const res = await fetch('/data.json');
      if (res.ok) {
        const data = await res.json();
        setArticles(data);
      }
    } catch (e) {
      console.error("Failed to load articles", e);
    }
  };

  useEffect(() => {
    loadArticles();
  }, []);

  const runScraper = async () => {
    setIsScraping(true);
    await new Promise(r => setTimeout(r, 3000));
    await loadArticles();
    setIsScraping(false);
  };

  if (activeTab === 'intelligence') {
    return (
      <div style={{ position: 'relative' }}>
        <button 
          onClick={() => setActiveTab('dashboard')} 
          className="btn-secondary" 
          style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, background: 'white' }}
        >
          ← Back to Dashboard
        </button>
        <IntelligencePage />
      </div>
    );
  }

  if (activeTab === 'workflow') {
    return (
      <div style={{ position: 'relative' }}>
        <div style={{ position: 'absolute', top: '20px', left: '20px', zIndex: 1000, display: 'flex', gap: '10px' }}>
          <button onClick={() => setActiveTab('dashboard')} className="btn-secondary" style={{ background: 'white' }}>
            ← To Dashboard
          </button>
          <button onClick={() => setActiveTab('intelligence')} className="btn-primary">
            <MessageSquare size={16} /> Intelligence Copilot
          </button>
        </div>
        <WorkflowPage articles={articles} />
      </div>
    );
  }

  return (
    <div className="layout">
      <div className="bg-pattern"></div>
      
      <Sidebar 
        feeds={feeds} 
        setFeeds={setFeeds} 
        onRunScraper={runScraper} 
        isScraping={isScraping} 
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
          <StatsOverview articles={articles} />
          <FeedView articles={articles} isScraping={isScraping} />
        </motion.div>
      </main>
    </div>
  );
}
