import { useEffect, useMemo, useState } from 'react';
import '../styles/Intelligence.css';
import {
  Send,
  Bot,
  User,
  X,
  FileText,
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  Filter,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { computeOverallTone } from '../lib/tone.js';
import { listArticles, sendChatMessage } from '../api/articlesApi.js';

const MATCHES_PAGE_SIZE = 4;

// Local-date helpers for the date-range filter. Using local (not UTC)
// components keeps `YYYY-MM-DD` strings round-tripping consistently between
// the <input type="date"> values, the week/month presets, and the filter.
function formatLocalDate(d) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseLocalDate(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

// Backend error codes (see backend/llm_client.py) mapped to short, friendly,
// provider-neutral copy. Never surface raw provider/stack trace text here.
const LLM_ERROR_MESSAGES = {
  llm_config_error: "The AI assistant isn't set up yet. Please contact your administrator.",
  llm_auth_error: "The AI assistant isn't configured correctly. Please contact your administrator.",
  llm_rate_limited: 'The assistant is busy right now. Please wait a moment and try again.',
  llm_timeout: 'The assistant took too long to respond. Please try again.',
  llm_unavailable: 'The assistant service is temporarily unavailable. Please try again shortly.',
  llm_bad_request: "That request couldn't be processed. Try rephrasing your question.",
  llm_invalid_response: "The assistant couldn't produce a usable answer. Try rephrasing your question.",
  llm_provider_error: 'The assistant hit an unexpected error. Please try again.',
  network_error: "Can't reach the Copilot service right now. Please check your connection and try again.",
};

const DEFAULT_ERROR_MESSAGE = 'Something went wrong. Please try again.';

export default function IntelligencePage({ project = null, projectId = null, projects = [] }) {
  const normalizedProjectId = useMemo(() => {
    if (projectId == null) return null;
    if (typeof projectId === 'object') {
      const nestedId = Number(projectId?.id);
      return Number.isFinite(nestedId) ? nestedId : null;
    }
    const parsed = Number(projectId);
    return Number.isFinite(parsed) ? parsed : null;
  }, [projectId]);
  const [articles, setArticles] = useState([]);
  const [matchesPage, setMatchesPage] = useState(1);

  const [selectedSites, setSelectedSites] = useState([]);
  const [selectedSentiments, setSelectedSentiments] = useState([]);
  const [selectedCategories, setSelectedCategories] = useState([]);

  // Route-scoped project filter, following the same pattern as ArticlesPage:
  // seeded from the dashboard's selected project but overridable on this page.
  const [projectFilter, setProjectFilter] = useState(() => (normalizedProjectId != null ? String(normalizedProjectId) : 'all'));
  const activeProject = useMemo(() => {
    if (projectFilter === 'all') return null;
    return projects.find((item) => String(item.id) === String(projectFilter)) || project;
  }, [projects, projectFilter, project]);

  // Each filter section collapses independently; matches panel collapses as a whole.
  // All start collapsed.
  const [openSections, setOpenSections] = useState({ site: false, sentiment: false, topic: false, date: false });
  const toggleSection = (key) => setOpenSections((current) => ({ ...current, [key]: !current[key] }));
  const [matchesCollapsed, setMatchesCollapsed] = useState(true);

  const [dateStart, setDateStart] = useState('');
  const [dateEnd, setDateEnd] = useState('');
  const [datePreset, setDatePreset] = useState('');

  const [chatInput, setChatInput] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [chatHistory, setChatHistory] = useState([
    {
      role: 'bot',
      text: 'Hello! I am your Intelligence Copilot. Select a project or browse all projects, then ask me to summarize or analyze the articles.',
    },
  ]);

  const [selectedArticle, setSelectedArticle] = useState(null);
  // Below the 960px breakpoint the filters sidebar and matches preview become
  // slide-in drawers instead of permanent grid columns; null means both closed.
  const [mobilePanel, setMobilePanel] = useState(null); // 'filters' | 'matches' | null
  // On mobile the matches drawer always renders fully expanded; only the
  // desktop rail collapses (same pattern as the main app Sidebar).
  const showMatchesCollapsed = matchesCollapsed && mobilePanel !== 'matches';

  const formatMatchScore = (value) => {
    const score = Number(value);
    if (!Number.isFinite(score)) return '';
    return score.toFixed(2);
  };

  useEffect(() => {
    async function fetchData() {
      try {
        const data = await listArticles({
          limit: 100,
          offset: 0,
          sort: 'published.desc',
          project_id: projectFilter !== 'all' ? projectFilter : undefined,
        });

        const curated = (data.articles || []).map((a) => ({ ...a, origin: 'curated' }));
        setArticles(curated);
      } catch (e) {
        console.error(e);
        setArticles([]);
      }
    }
    fetchData();
  }, [projectFilter]);

  const filteredArticles = useMemo(() => {
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
    if (dateStart) {
      const startTime = parseLocalDate(dateStart).getTime();
      result = result.filter((a) => a.published && new Date(a.published).getTime() >= startTime);
    }
    if (dateEnd) {
      // Treat the end date as inclusive of the whole day.
      const endTime = parseLocalDate(dateEnd).getTime() + 24 * 60 * 60 * 1000 - 1;
      result = result.filter((a) => a.published && new Date(a.published).getTime() <= endTime);
    }
    return result;
  }, [articles, selectedSites, selectedSentiments, selectedCategories, dateStart, dateEnd]);

  const totalMatchesPages = Math.max(1, Math.ceil(filteredArticles.length / MATCHES_PAGE_SIZE));
  const safeMatchesPage = Math.min(matchesPage, totalMatchesPages);
  const pagedArticles = useMemo(
    () => filteredArticles.slice((safeMatchesPage - 1) * MATCHES_PAGE_SIZE, safeMatchesPage * MATCHES_PAGE_SIZE),
    [filteredArticles, safeMatchesPage]
  );

  const sites = [...new Set(articles.map((a) => a.source).filter(Boolean))];
  const categories = [...new Set(articles.map((a) => a.category).filter(Boolean))];
  const sentiments = ['positive', 'negative', 'neutral', 'mixed'];

  const toggleFilter = (setFn, currentList, value) => {
    if (currentList.includes(value)) {
      setFn(currentList.filter((v) => v !== value));
    } else {
      setFn([...currentList, value]);
    }
    setMatchesPage(1);
  };

  const applyDatePreset = (preset) => {
    const now = new Date();
    let start;
    let end;
    if (preset === 'week') {
      const daysSinceMonday = (now.getDay() + 6) % 7;
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysSinceMonday);
      end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6);
    } else if (preset === 'month') {
      start = new Date(now.getFullYear(), now.getMonth(), 1);
      end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    } else {
      setDatePreset('');
      setDateStart('');
      setDateEnd('');
      setMatchesPage(1);
      return;
    }
    setDatePreset(preset);
    setDateStart(formatLocalDate(start));
    setDateEnd(formatLocalDate(end));
    setMatchesPage(1);
  };

  const handleDateStartChange = (value) => {
    setDateStart(value);
    setDatePreset('');
    setMatchesPage(1);
  };

  const handleDateEndChange = (value) => {
    setDateEnd(value);
    setDatePreset('');
    setMatchesPage(1);
  };

  const handleSendMessage = async (presetText, { skipUserBubble = false } = {}) => {
    const question = (presetText ?? chatInput).trim();
    if (!question || isThinking) return;

    const baseHistory = skipUserBubble ? chatHistory : [...chatHistory, { role: 'user', text: question }];
    setChatHistory(baseHistory);
    if (!skipUserBubble) setChatInput('');
    setIsThinking(true);

    try {
      const { ok, data } = await sendChatMessage({
        question,
        total: filteredArticles.length,
        project: activeProject
          ? {
              id: activeProject.id,
              name: activeProject.name,
              status: activeProject.status,
              start_date: activeProject.start_date,
              end_date: activeProject.end_date,
              description: activeProject.description,
              location: activeProject.location,
              target_audience: activeProject.target_audience,
              hashtags: activeProject.hashtags,
              keywords: activeProject.keywords,
            }
          : null,
        project_id: activeProject ? activeProject.id : null,
        articles: filteredArticles.map((a) => ({
          source: a.source,
          sentiment: a.sentiment,
          category: a.category,
          article_category: a.article_category,
          writer_tone: a.writer_tone,
          article_tone: a.article_tone,
          title: a.title,
          summary: a.summary,
          insight_json: a.insight_json,
          relevance_score: a.relevance_score,
          project_similarity_score: a.project_similarity_score,
        })),
      });
      if (ok) {
        setChatHistory([...baseHistory, { role: 'bot', text: data.reply || 'No response.' }]);
      } else {
        const text = (data?.error_code && LLM_ERROR_MESSAGES[data.error_code]) || data?.error || DEFAULT_ERROR_MESSAGE;
        setChatHistory([...baseHistory, { role: 'bot', text, isError: true, retryText: question }]);
      }
    } catch {
      setChatHistory([
        ...baseHistory,
        { role: 'bot', text: LLM_ERROR_MESSAGES.network_error, isError: true, retryText: question },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  const handleRetry = (question) => {
    if (!question || isThinking) return;
    handleSendMessage(question, { skipUserBubble: true });
  };

  return (
    <div className={`intelligence-layout ${showMatchesCollapsed ? 'matches-collapsed' : ''}`}>
      <div className="bg-pattern"></div>

      {mobilePanel && <div className="intell-mobile-backdrop" onClick={() => setMobilePanel(null)} />}

      <div className={`intell-sidebar ${mobilePanel === 'filters' ? 'mobile-open' : ''}`}>
        <button type="button" className="intell-mobile-close" onClick={() => setMobilePanel(null)}>
          <X size={16} /> Close
        </button>
        <h2 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Filter size={18} /> Filters
        </h2>

        <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-light)', marginBottom: '16px' }}>
          Project
          <select
            className="filter-select"
            style={{ display: 'block', width: '100%', marginTop: '6px' }}
            value={projectFilter}
            onChange={(e) => {
              setProjectFilter(e.target.value);
              setMatchesPage(1);
            }}
          >
            <option value="all">All projects</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.status || 'draft'})
              </option>
            ))}
          </select>
        </label>

        <div className="filter-group">
          <button type="button" className="filter-group-header" onClick={() => toggleSection('site')}>
            <h4>By Document</h4>
            <ChevronDown size={16} className={`filter-group-chevron ${openSections.site ? 'open' : ''}`} />
          </button>
          {openSections.site && (
            <div className="filter-group-content">
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
          )}
        </div>

        <div className="filter-group">
          <button type="button" className="filter-group-header" onClick={() => toggleSection('sentiment')}>
            <h4>By Sentiment</h4>
            <ChevronDown size={16} className={`filter-group-chevron ${openSections.sentiment ? 'open' : ''}`} />
          </button>
          {openSections.sentiment && (
            <div className="filter-group-content">
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
          )}
        </div>

        <div className="filter-group">
          <button type="button" className="filter-group-header" onClick={() => toggleSection('topic')}>
            <h4>By Topic</h4>
            <ChevronDown size={16} className={`filter-group-chevron ${openSections.topic ? 'open' : ''}`} />
          </button>
          {openSections.topic && (
            <div className="filter-group-content">
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
          )}
        </div>

        <div className="filter-group">
          <button type="button" className="filter-group-header" onClick={() => toggleSection('date')}>
            <h4>By Date (published)</h4>
            <ChevronDown size={16} className={`filter-group-chevron ${openSections.date ? 'open' : ''}`} />
          </button>
          {openSections.date && (
            <div className="filter-group-content">
              <div className="date-filter-presets">
                <button
                  type="button"
                  className={`btn-secondary ${datePreset === 'week' ? 'active' : ''}`}
                  onClick={() => applyDatePreset(datePreset === 'week' ? '' : 'week')}
                >
                  This Week
                </button>
                <button
                  type="button"
                  className={`btn-secondary ${datePreset === 'month' ? 'active' : ''}`}
                  onClick={() => applyDatePreset(datePreset === 'month' ? '' : 'month')}
                >
                  This Month
                </button>
                {(dateStart || dateEnd) && (
                  <button type="button" className="btn-secondary" onClick={() => applyDatePreset('')}>
                    Clear
                  </button>
                )}
              </div>
              <div className="date-filter-inputs">
                <label>
                  From
                  <input
                    type="date"
                    className="filter-select date-input"
                    value={dateStart}
                    max={dateEnd || undefined}
                    onChange={(e) => handleDateStartChange(e.target.value)}
                  />
                </label>
                <label>
                  To
                  <input
                    type="date"
                    className="filter-select date-input"
                    value={dateEnd}
                    min={dateStart || undefined}
                    onChange={(e) => handleDateEndChange(e.target.value)}
                  />
                </label>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="intell-chat">
        <div className="intell-chat-header">
          <h2 className="title" style={{ fontSize: '1.5rem' }}>
            Strata Intelligence Copilot
          </h2>
          <p className="subtitle" style={{ fontSize: '0.9rem' }}>
            Chatting over {filteredArticles.length} articles
            {activeProject ? ` - ${activeProject.name}` : ' - all projects'}
          </p>

          <div className="intell-mobile-toggle-row">
            <button type="button" className="btn-secondary" onClick={() => setMobilePanel('filters')}>
              <Filter size={14} /> Filters
            </button>
            <button type="button" className="btn-secondary" onClick={() => setMobilePanel('matches')}>
              <FileText size={14} /> Matches ({filteredArticles.length})
            </button>
          </div>
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
                    {msg.isError && (
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{ marginTop: '8px', fontSize: '0.8rem', padding: '4px 10px' }}
                        disabled={isThinking}
                        onClick={() => handleRetry(msg.retryText)}
                      >
                        Retry
                      </button>
                    )}
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
              disabled={isThinking || filteredArticles.length === 0}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
            />
            <button className="chat-send-btn" onClick={() => handleSendMessage()} disabled={isThinking || filteredArticles.length === 0}>
              <Send size={18} />
            </button>
          </div>
          <div className="chat-quick-actions">
            <button
              className="btn-secondary"
              style={{ fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.6)' }}
              disabled={isThinking || filteredArticles.length === 0}
              onClick={() => handleSendMessage('Summarize the overall sentiment and the key themes across these articles.')}
            >
              Summarize Themes
            </button>
            <button
              className="btn-secondary"
              style={{ fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.6)' }}
              disabled={isThinking || filteredArticles.length === 0}
              onClick={() => handleSendMessage('Draft a short executive brief highlighting the most important signals in these articles.')}
            >
              Draft Brief
            </button>
          </div>
        </div>
      </div>

      <div
        className={`intell-preview ${mobilePanel === 'matches' ? 'mobile-open' : ''} ${showMatchesCollapsed ? 'intell-preview-collapsed' : ''}`}
      >
        <button type="button" className="intell-mobile-close" onClick={() => setMobilePanel(null)}>
          <X size={16} /> Close
        </button>

        <div className="matches-panel-header">
          <button
            type="button"
            className="matches-collapse-btn"
            onClick={() => setMatchesCollapsed((value) => !value)}
            title={matchesCollapsed ? 'Expand matches panel' : 'Collapse matches panel'}
            aria-label={matchesCollapsed ? 'Expand matches panel' : 'Collapse matches panel'}
          >
            {showMatchesCollapsed ? <ChevronsLeft size={18} /> : <ChevronsRight size={18} />}
          </button>
          {!showMatchesCollapsed && (
            <h3 style={{ fontSize: '1.1rem', color: 'var(--text-light)', margin: 0 }}>
              Matches ({filteredArticles.length})
            </h3>
          )}
        </div>

        {showMatchesCollapsed && (
          <span className="matches-collapsed-count" title={`${filteredArticles.length} matches`}>
            {filteredArticles.length}
          </span>
        )}

        {!showMatchesCollapsed && (
        <>
        {pagedArticles.length === 0 ? (
          <div className="preview-empty">No matching articles for the current filters.</div>
        ) : (
          pagedArticles.map((article) => (
            <motion.div
              key={article.url}
              layout
              className="preview-card"
              onClick={() => {
                setSelectedArticle(article);
                setMobilePanel(null);
              }}
            >
              <div className="preview-meta">
                <span style={{ color: 'var(--secondary-color)', fontWeight: '500' }}>{article.source}</span>
                <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`} style={{ padding: '2px 6px', fontSize: '0.65rem' }}>
                  {article.sentiment || 'Neutral'}
                </span>
                <span className="badge category" style={{ padding: '2px 6px', fontSize: '0.65rem' }} title="Writer tone">
                  Writer: {article.writer_tone || 'neutral'}
                </span>
                <span className="badge category" style={{ padding: '2px 6px', fontSize: '0.65rem' }} title="Article tone">
                  Article: {article.article_tone || 'neutral'}
                </span>
                <span className="badge category" style={{ padding: '2px 6px', fontSize: '0.65rem' }} title="Overall tone (derived from writer + article tone)">
                  Overall: {computeOverallTone(article.article_tone, article.writer_tone)}
                </span>
                {article.project_similarity_score != null && (
                  <span className="badge score" style={{ padding: '2px 6px', fontSize: '0.65rem' }}>
                    Match: {formatMatchScore(article.project_similarity_score)}
                  </span>
                )}
              </div>
              <div className="preview-title">{article.title}</div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', fontSize: '0.8rem', color: 'var(--primary-color)' }}>
                View Details <ChevronRight size={14} />
              </div>
            </motion.div>
          ))
        )}

        {filteredArticles.length > MATCHES_PAGE_SIZE && (
          <div className="matches-pagination">
            <div className="matches-pagination-meta">
              Showing {(safeMatchesPage - 1) * MATCHES_PAGE_SIZE + 1}-{Math.min(safeMatchesPage * MATCHES_PAGE_SIZE, filteredArticles.length)} of {filteredArticles.length}
            </div>
            <div className="matches-pagination-controls">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setMatchesPage((value) => Math.max(1, value - 1))}
                disabled={safeMatchesPage <= 1}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                <ChevronLeft size={14} /> Previous
              </button>
              <span className="matches-pagination-chip">
                Page {safeMatchesPage} of {totalMatchesPages}
              </span>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setMatchesPage((value) => Math.min(totalMatchesPages, value + 1))}
                disabled={safeMatchesPage >= totalMatchesPages}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
        </>
        )}
      </div>

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

            <div className="content-shell">
              <div className="article-meta-badges">
                <span className="badge category">{selectedArticle.article_category || selectedArticle.category || 'Topic'}</span>
                <span className={`badge ${selectedArticle.sentiment?.toLowerCase() || 'neutral'}`}>{selectedArticle.sentiment}</span>
                <span className="badge category" title="Writer tone">Writer tone: {selectedArticle.writer_tone || 'neutral'}</span>
                <span className="badge category" title="Article tone">Article tone: {selectedArticle.article_tone || 'neutral'}</span>
                <span className="badge category" title="Overall tone (derived from writer + article tone)">
                  Overall tone: {computeOverallTone(selectedArticle.article_tone, selectedArticle.writer_tone)}
                </span>
                <span className="badge score">Score: {selectedArticle.relevance_score}/10</span>
                {selectedArticle.project_similarity_score != null && (
                  <span className="badge score">Project match: {formatMatchScore(selectedArticle.project_similarity_score)}</span>
                )}
              </div>

              <h1 style={{ fontSize: '2rem', marginBottom: '10px' }}>{selectedArticle.title}</h1>
              <div className="article-byline">
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
                <p style={{ lineHeight: '1.6' }}>{selectedArticle.insight_json?.summary || selectedArticle.summary}</p>
                {selectedArticle.insight_json?.frequent_ideas?.length ? (
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>
                    {selectedArticle.insight_json.frequent_ideas.slice(0, 4).map((item) => (
                      <span key={item.idea} className="badge score" style={{ textTransform: 'none' }}>
                        {item.idea}
                      </span>
                    ))}
                  </div>
                ) : null}
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
