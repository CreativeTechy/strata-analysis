import React, { useState, useEffect } from 'react';
import { supabase } from '../supabaseClient';
import '../Intelligence.css';
import { Send, Bot, User, X, FileText, ChevronRight, Filter } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function IntelligencePage() {
  const [articles, setArticles] = useState([]);
  const [filteredArticles, setFilteredArticles] = useState([]);
  
  // Filters
  const [selectedSites, setSelectedSites] = useState([]);
  const [selectedSentiments, setSelectedSentiments] = useState([]);
  const [selectedCategories, setSelectedCategories] = useState([]);

  // Chat
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([
    { role: 'bot', text: "Hello! I am your Intelligence Copilot. I've indexed all the latest scraped car news. You can use the filters on the left to narrow down the articles, and ask me to analyze them, summarize key trends, or draft a social media report." }
  ]);

  // Article preview
  const [selectedArticle, setSelectedArticle] = useState(null);

  // Fetch data
  useEffect(() => {
    async function fetchData() {
      // For now, load from local data.json or fallback to supabase if wired
      try {
        const { data, error } = await supabase.from('articles').select('*').order('published', { ascending: false });
        if (data && data.length > 0) {
          setArticles(data);
        } else {
          // Fallback to local
          const res = await fetch('/data.json');
          if (res.ok) {
            const localData = await res.json();
            setArticles(localData);
          }
        }
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
      result = result.filter(a => selectedSites.includes(a.source));
    }
    if (selectedSentiments.length > 0) {
      result = result.filter(a => selectedSentiments.includes(a.sentiment?.toLowerCase() || 'neutral'));
    }
    if (selectedCategories.length > 0) {
      result = result.filter(a => selectedCategories.includes(a.category));
    }
    setFilteredArticles(result);
  }, [articles, selectedSites, selectedSentiments, selectedCategories]);

  // Derived filter options
  const sites = [...new Set(articles.map(a => a.source).filter(Boolean))];
  const categories = [...new Set(articles.map(a => a.category).filter(Boolean))];
  const sentiments = ['positive', 'negative', 'neutral'];

  const toggleFilter = (setFn, currentList, value) => {
    if (currentList.includes(value)) {
      setFn(currentList.filter(v => v !== value));
    } else {
      setFn([...currentList, value]);
    }
  };

  const handleSendMessage = () => {
    if (!chatInput.trim()) return;
    
    // Add user message
    const newHistory = [...chatHistory, { role: 'user', text: chatInput }];
    setChatHistory(newHistory);
    setChatInput('');

    // Mock AI response
    setTimeout(() => {
      setChatHistory([
        ...newHistory, 
        { role: 'bot', text: `I've analyzed the ${filteredArticles.length} filtered articles regarding your request. Based on the selected data, the overall sentiment indicates a shift in market perception. (This is a mocked AI response - wire this up to DeepSeek or Claude API in your backend!)` }
      ]);
    }, 1500);
  };

  return (
    <div className="intelligence-layout">
      {/* Background elements */}
      <div className="bg-pattern"></div>
      
      {/* LEFT: Filters */}
      <div className="intell-sidebar">
        <h2 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Filter size={18} /> Filters
        </h2>
        
        <div className="filter-group">
          <h4>By Site</h4>
          {sites.map(site => (
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
          {sentiments.map(sent => (
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
          <h4>By Category</h4>
          {categories.map(cat => (
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
        <div style={{ padding: '20px 40px', borderBottom: '1px solid rgba(0,0,0,0.05)', background: 'rgba(255,255,255,0.4)', backdropFilter: 'blur(10px)' }}>
          <h2 className="title" style={{ fontSize: '1.5rem' }}>Strata Intelligence Copilot</h2>
          <p className="subtitle" style={{ fontSize: '0.9rem' }}>Chatting with context of {filteredArticles.length} articles</p>
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
                {msg.role === 'bot' ? <Bot size={18} style={{ marginTop: '2px', color: 'var(--primary-color)' }} /> : <User size={18} style={{ marginTop: '2px' }} />}
                <div>{msg.text}</div>
              </div>
            </motion.div>
          ))}
        </div>

        <div className="chat-input-container">
          <div className="chat-input-box">
            <input 
              type="text" 
              placeholder={`Ask about the ${filteredArticles.length} filtered articles...`}
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
            />
            <button className="chat-send-btn" onClick={handleSendMessage}>
              <Send size={18} />
            </button>
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '15px', justifyContent: 'center' }}>
             <button className="btn-secondary" style={{ fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.6)' }}>✨ Summarize Sentiment</button>
             <button className="btn-secondary" style={{ fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.6)' }}>📄 Draft Event Report</button>
          </div>
        </div>
      </div>

      {/* RIGHT: Previews */}
      <div className="intell-preview">
        <h3 style={{ fontSize: '1.1rem', marginBottom: '10px', color: 'var(--text-light)' }}>
          Matches ({filteredArticles.length})
        </h3>
        
        {filteredArticles.map(article => (
          <motion.div 
            key={article.url} 
            layout
            className="preview-card"
            onClick={() => setSelectedArticle(article)}
          >
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
            <button 
              className="btn-secondary" 
              style={{ alignSelf: 'flex-end', padding: '8px' }}
              onClick={() => setSelectedArticle(null)}
            >
              <X size={20} /> Close
            </button>
            
            <div style={{ maxWidth: '800px', margin: '0 auto', width: '100%' }}>
              <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
                <span className="badge category">{selectedArticle.category}</span>
                <span className={`badge ${selectedArticle.sentiment?.toLowerCase() || 'neutral'}`}>{selectedArticle.sentiment}</span>
                <span className="badge score">Score: {selectedArticle.relevance_score}/10</span>
              </div>
              
              <h1 style={{ fontSize: '2rem', marginBottom: '10px' }}>{selectedArticle.title}</h1>
              <div style={{ color: 'var(--text-light)', marginBottom: '30px', display: 'flex', gap: '15px' }}>
                <span>{selectedArticle.source}</span>
                <span>{new Date(selectedArticle.published).toLocaleDateString()}</span>
                {selectedArticle.author && <span>By {selectedArticle.author}</span>}
              </div>

              <div style={{ background: 'rgba(46, 134, 222, 0.05)', padding: '20px', borderRadius: '12px', borderLeft: '4px solid var(--secondary-color)', marginBottom: '30px' }}>
                <h3 style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Bot size={18} /> AI Summary
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
