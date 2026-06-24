import React, { useState, useEffect } from 'react';
import { supabase } from '../supabaseClient';
import '../styles/Intelligence.css';
import { Send, Bot, User, X, FileText, ChevronRight, Filter } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function IntelligencePage() {
  const [articles, setArticles] = useState([]);
  const [filteredArticles, setFilteredArticles] = useState([]);

  // Filters
  const [selectedSites, setSelectedSites] = useState([]);
  const [selectedSentiments, setSelectedSentiments] = useState([]);
  const [selectedCategories, setSelectedCategories] = useState([]);

  // Chat
  const [chatInput, setChatInput] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [chatHistory, setChatHistory] = useState([
    {
      role: 'bot',
      text: "Hello! I am your Intelligence Copilot. I've indexed the latest scraped articles. Use the filters on the left to narrow the set, then ask me to analyze them, summarize key themes, or draft a concise brief.",
    },
  ]);

  // Article preview
  const [selectedArticle, setSelectedArticle] = useState(null);

  // Fetch BOTH datasets so the Copilot reasons over the curated feed AND the
  // spider's crawl volume. Interleaved so any context slice gets a mix of both.
  useEffect(() => {
    async function fetchData() {
      try {
        const [arts, crawl] = await Promise.all([
          supabase.from('articles').select('*').order('published', { ascending: false }),
          supabase.from('crawl_pages').select('url,source,title,text').order('created_at', { ascending: false }).limit(400),
        ]);

        const curated = (arts.data || []).map((a) => ({ ...a, origin: 'curated' }));
        const crawled = (crawl.data || []).map((c) => ({
          url: c.url,
          source: c.source,
          title: c.title,
          text: c.text,
          summary: (c.text || '').slice(0, 280),
          sentiment: null,
          category: 'crawl',
          relevance_score: null,
          origin: 'crawl',
        }));

        const combined = [];
        for (let i = 0; i < Math.max(curated.length, crawled.length); i++) {
          if (curated[i]) combined.push(curated[i]);
          if (crawled[i]) combined.push(crawled[i]);
        }
        setArticles(combined);
      } catch (e) {
        console.error(e);
      }
    }
    fetchData();
  }, []);

  // Filter logic
  useEffect(() => {
    let result = articles;
    if (selectedSites.length > 0) {
      result = result.filter((a) => selectedSites.includes(a.source));
    }
    if (selectedSentiments.length > 0) {
      result = result.filter((a) => selectedSentiments.includes(a.sentiment?.toLowerCase() || 'neutral'));
    }
    if (selectedCategories.length > 0) {
      result = result.filter((a) => selectedCategories.includes(a.category));
    }
    setFilteredArticles(result);
  }, [articles, selectedSites, selectedSentiments, selectedCategories]);

  // Derived filter options
  const sites = [...new Set(articles.map((a) => a.source).filter(Boolean))];
  const categories = [...new Set(articles.map((a) => a.category).filter(Boolean))];
  const sentiments = ['positive', 'negative', 'neutral'];

  const toggleFilter = (setFn, currentList, value) => {
    if (currentList.includes(value)) {
      setFn(currentList.filter((v) => v !== value));
    } else {
      setFn([...currentList, value]);
    }
  };

  const handleSendMessage = async (presetText) => {
    const question = (presetText ?? chatInput).trim();
    if (!question || isThinking) return;

    const newHistory = [...chatHistory, { role: 'user', text: question }];
    setChatHistory(newHistory);
    setChatInput('');
    setIsThinking(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          total: filteredArticles.length,
          articles: filteredArticles.map((a) => ({
            source: a.source,
            sentiment: a.sentiment,
            category: a.category,
            title: a.title,
            summary: a.summary,
            relevance_score: a.relevance_score,
          })),
        }),
      });
      const data = await res.json().catch(() => ({}));
      const text = res.ok
        ? (data.reply || 'No response.')
        : `Error: ${data.error || `Copilot request failed (${res.status}).`}`;
      setChatHistory([...newHistory, { role: 'bot', text }]);
    } catch {
      setChatHistory([
        ...newHistory,
        { role: 'bot', text: 'Error: Could not reach the Copilot backend. Is the Worker deployed with DEEPSEEK_API_KEY set?' },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  return (
    <div className="intelligence-layout">
      <div className="bg-pattern"></div>

      {/* LEFT: Filters */}
      <div className="intell-sidebar">
        <h2 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Filter size={18} /> Filters
        </h2>

        <div className="filter-group">
          <h4>By Site</h4>
          {sites.map((site) => (
            <label key={site} className="filter-option">
              <input
                type="checkbox"
                checked={selectedSites.includes(site)}
                onChange={() => toggleFilter(setSelectedSites, selectedSites, site)}
              />
              {site}
            </label>
          ))}
        </div>

        <div className="filter-group">
          <h4>By Sentiment</h4>
          {sentiments.map((sent) => (
            <label key={sent} className="filter-option">
              <input
                type="checkbox"
                checked={selectedSentiments.includes(sent)}
                onChange={() => toggleFilter(setSelectedSentiments, selectedSentiments, sent)}
              />
              <span style={{ textTransform: 'capitalize' }}>{sent}</span>
            </label>
          ))}
        </div>

        <div className="filter-group">
          <h4>By Topic</h4>
          {categories.map((cat) => (
            <label key={cat} className="filter-option">
              <input
                type="checkbox"
                checked={selectedCategories.includes(cat)}
                onChange={() => toggleFilter(setSelectedCategories, selectedCategories, cat)}
              />
              {cat}
            </label>
          ))}
        </div>
      </div>

      {/* MIDDLE: AI Chat */}
      <div className="intell-chat">
        <div
          style={{
            padding: '20px 40px',
            borderBottom: '1px solid rgba(0,0,0,0.05)',
            background: 'rgba(255,255,255,0.4)',
            backdropFilter: 'blur(10px)',
          }}
        >
          <h2 className="title" style={{ fontSize: '1.5rem' }}>
            Strata Intelligence Copilot
          </h2>
          <p className="subtitle" style={{ fontSize: '0.9rem' }}>
            Chatting over {filteredArticles.length} items -{' '}
            {filteredArticles.filter((a) => a.origin !== 'crawl').length} curated + {filteredArticles.filter((a) => a.origin === 'crawl').length} crawled
          </p>
        </div>

        <div className="chat-history">
          {chatHistory.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`chat-bubble ${msg.role}`}
            >
              <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                {msg.role === 'bot' ? (
                  <Bot size={18} style={{ marginTop: '2px', color: 'var(--primary-color)', flexShrink: 0 }} />
                ) : (
                  <User size={18} style={{ marginTop: '2px', flexShrink: 0 }} />
                )}
                {msg.role === 'bot' ? (
                  <div className="md-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                  </div>
                ) : (
                  <div style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                )}
              </div>
            </motion.div>
          ))}
          {isThinking && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="chat-bubble bot">
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <Bot size={18} style={{ color: 'var(--primary-color)' }} />
                <div style={{ color: 'var(--text-light)' }}>Analyzing {filteredArticles.length} articles...</div>
              </div>
            </motion.div>
          )}
        </div>

        <div className="chat-input-container">
          <div className="chat-input-box">
            <input
              type="text"
              placeholder={isThinking ? 'Thinking...' : `Ask about the ${filteredArticles.length} filtered articles...`}
              value={chatInput}
              disabled={isThinking}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
            />
            <button className="chat-send-btn" onClick={() => handleSendMessage()} disabled={isThinking}>
              <Send size={18} />
            </button>
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '15px', justifyContent: 'center' }}>
            <button
              className="btn-secondary"
              style={{ fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.6)' }}
              disabled={isThinking}
              onClick={() => handleSendMessage('Summarize the overall sentiment and the key themes across these articles.')}
            >
              Summarize Themes
            </button>
            <button
              className="btn-secondary"
              style={{ fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.6)' }}
              disabled={isThinking}
              onClick={() => handleSendMessage('Draft a short executive brief highlighting the most important signals in these articles.')}
            >
              Draft Brief
            </button>
          </div>
        </div>
      </div>

      {/* RIGHT: Previews */}
      <div className="intell-preview">
        <h3 style={{ fontSize: '1.1rem', marginBottom: '10px', color: 'var(--text-light)' }}>
          Matches ({filteredArticles.length})
        </h3>

        {filteredArticles.map((article) => (
          <motion.div key={article.url} layout className="preview-card" onClick={() => setSelectedArticle(article)}>
            <div className="preview-meta">
              <span style={{ color: 'var(--secondary-color)', fontWeight: '500' }}>{article.source}</span>
              <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`} style={{ padding: '2px 6px', fontSize: '0.65rem' }}>
                {article.sentiment || 'Neutral'}
              </span>
            </div>
            <div className="preview-title">{article.title}</div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', fontSize: '0.8rem', color: 'var(--primary-color)' }}>
              View Details <ChevronRight size={14} />
            </div>
          </motion.div>
        ))}
      </div>

      {/* Full Details Overlay */}
      <AnimatePresence>
        {selectedArticle && (
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 50 }}
            className="article-detail-overlay"
          >
            <button className="btn-secondary" style={{ alignSelf: 'flex-end', padding: '8px' }} onClick={() => setSelectedArticle(null)}>
              <X size={20} /> Close
            </button>

            <div style={{ maxWidth: '800px', margin: '0 auto', width: '100%' }}>
              <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
                <span className="badge category">{selectedArticle.category || 'Topic'}</span>
                <span className={`badge ${selectedArticle.sentiment?.toLowerCase() || 'neutral'}`}>{selectedArticle.sentiment}</span>
                <span className="badge score">Score: {selectedArticle.relevance_score}/10</span>
              </div>

              <h1 style={{ fontSize: '2rem', marginBottom: '10px' }}>{selectedArticle.title}</h1>
              <div style={{ color: 'var(--text-light)', marginBottom: '30px', display: 'flex', gap: '15px' }}>
                <span>{selectedArticle.source}</span>
                {selectedArticle.published && <span>{new Date(selectedArticle.published).toLocaleDateString()}</span>}
                {selectedArticle.author && <span>By {selectedArticle.author}</span>}
              </div>

              <div
                style={{
                  background: 'rgba(46, 134, 222, 0.05)',
                  padding: '20px',
                  borderRadius: '12px',
                  borderLeft: '4px solid var(--secondary-color)',
                  marginBottom: '30px',
                }}
              >
                <h3 style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Bot size={18} /> AI Analysis
                </h3>
                <p style={{ lineHeight: '1.6' }}>{selectedArticle.summary}</p>
              </div>

              <h3 style={{ marginBottom: '15px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileText size={18} /> Full Text
              </h3>
              <div style={{ lineHeight: '1.8', whiteSpace: 'pre-wrap', color: '#4a4a4a' }}>
                {selectedArticle.text}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
