import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ExternalLink, Calendar, CarFront, Tag, Search, ChevronLeft, ChevronRight, SlidersHorizontal, Trash2 } from 'lucide-react';

const SENTIMENTS = ['all', 'positive', 'negative', 'neutral'];
const CATEGORIES = ['all', 'review', 'event', 'recall', 'auction', 'race', 'tech', 'industry', 'other'];
const SORT_OPTIONS = [
  { value: 'published.desc', label: 'Newest first' },
  { value: 'published.asc', label: 'Oldest first' },
  { value: 'relevance_score.desc', label: 'Highest relevance' },
  { value: 'relevance_score.asc', label: 'Lowest relevance' },
  { value: 'created_at.desc', label: 'Recently saved' },
];

const PAGE_SIZES = [12, 24, 48, 96];

function articleDate(value) {
  if (!value) return 'Unknown date';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

export default function ArticlesPage({ event = null, eventId = null }) {
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [sentiment, setSentiment] = useState('all');
  const [category, setCategory] = useState('all');
  const [limit, setLimit] = useState(24);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState('published.desc');
  const [articles, setArticles] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingAll, setDeletingAll] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setOffset(0);
  }, [search, sentiment, category, limit, sort, eventId]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadArticles() {
      setLoading(true);
      setError('');
      try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (sentiment !== 'all') params.set('sentiment', sentiment);
        if (category !== 'all') params.set('category', category);
        if (eventId != null) params.set('event_id', String(eventId));
        params.set('limit', String(limit));
        params.set('offset', String(offset));
        params.set('sort', sort);

        const res = await fetch(`/api/articles?${params.toString()}`, { signal: controller.signal });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data?.detail || data?.error || `Failed to load articles (${res.status})`);
        }

        setArticles(Array.isArray(data?.articles) ? data.articles : []);
        setTotal(Number(data?.total) || 0);
      } catch (err) {
        if (err?.name !== 'AbortError') {
          setError(err?.message || 'Failed to load articles.');
          setArticles([]);
          setTotal(0);
        }
      } finally {
        setLoading(false);
      }
    }

    loadArticles();
    return () => controller.abort();
  }, [search, sentiment, category, limit, offset, sort, reloadToken, eventId]);

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + articles.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  const visibleRange = useMemo(() => `${start}-${end}`, [start, end]);

  const handleDeleteAll = async () => {
    if (deletingAll) return;
    const confirmed = window.confirm(
      'Delete all articles from Supabase? This will remove every row in the articles table and cannot be undone.'
    );
    if (!confirmed) return;

    setDeletingAll(true);
    setError('');
      try {
        const res = await fetch('/api/articles', { method: 'DELETE' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.error) {
          throw new Error(data?.detail || data?.error || `Failed to delete articles (${res.status})`);
        }
        setSearchInput('');
        setSearch('');
        setSentiment('all');
        setCategory('all');
        setOffset(0);
        setReloadToken((value) => value + 1);
      } catch (err) {
        setError(err?.message || 'Failed to delete articles.');
      } finally {
        setDeletingAll(false);
      }
  };

  return (
    <div style={{ minHeight: '100vh', padding: '32px 28px 40px' }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <SlidersHorizontal size={26} color="#ff6b35" />
              <h1 style={{ fontSize: '1.9rem', fontWeight: 800, margin: 0 }}>Articles</h1>
            </div>
          <p style={{ color: 'var(--text-light)', margin: 0 }}>
              Server-side search, sentiment, category, sort, and pagination powered by the API.
              {event ? ` Current event: ${event.name}.` : ' Showing all events.'}
          </p>
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              className="btn-secondary"
              onClick={handleDeleteAll}
              disabled={loading || deletingAll}
              style={{ color: '#b42318', borderColor: 'rgba(180,35,24,0.18)' }}
            >
              <Trash2 size={16} />
              {deletingAll ? 'Deleting...' : 'Delete All Articles'}
            </button>
            <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
              Back to Dashboard
            </Link>
          </div>
        </div>

        <div className="glass-card" style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 1.2fr) repeat(4, minmax(160px, 1fr))', gap: 12, alignItems: 'center', marginBottom: 18 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 12, background: 'rgba(255,255,255,0.55)' }}>
            <Search size={18} color="var(--text-light)" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search title, summary, source..."
              style={{ width: '100%', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.95rem' }}
            />
          </label>

          <select className="filter-select" value={sentiment} onChange={(e) => setSentiment(e.target.value)}>
            {SENTIMENTS.map((value) => (
              <option key={value} value={value}>
                {value === 'all' ? 'All sentiments' : value[0].toUpperCase() + value.slice(1)}
              </option>
            ))}
          </select>

          <select className="filter-select" value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {value === 'all' ? 'All categories' : value[0].toUpperCase() + value.slice(1)}
              </option>
            ))}
          </select>

          <select className="filter-select" value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <select className="filter-select" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size} per page
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
          <div style={{ color: 'var(--text-light)' }}>
            {loading ? 'Loading articles...' : `${total.toLocaleString()} articles total, showing ${visibleRange}`}
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button className="btn-secondary" onClick={() => setOffset((prev) => Math.max(0, prev - limit))} disabled={!hasPrev || loading}>
              <ChevronLeft size={16} /> Previous
            </button>
            <button className="btn-secondary" onClick={() => setOffset((prev) => prev + limit)} disabled={!hasNext || loading}>
              Next <ChevronRight size={16} />
            </button>
          </div>
        </div>

        {error ? (
          <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginBottom: 18 }}>
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="articles-grid">
            {Array.from({ length: Math.min(limit, 12) }).map((_, i) => (
              <div key={i} className="glass-card" style={{ minHeight: 240, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />
            ))}
          </div>
        ) : (
          <>
            <div className="articles-grid">
              <AnimatePresence>
                {articles.map((article, i) => (
                  <motion.div
                    key={article.url}
                    layout
                    initial={{ opacity: 0, scale: 0.96, y: 16 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ duration: 0.25, delay: Math.min((i % 12) * 0.03, 0.4) }}
                    className="glass-card article-card"
                  >
                    <div className="article-header">
                      <div className="article-meta">
                        <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`}>
                          {article.sentiment || 'Neutral'}
                        </span>
                        <span className="badge category">
                          {article.category || 'News'}
                        </span>
                        {article.relevance_score != null && (
                          <span className="badge score">Score: {Number(article.relevance_score).toFixed(1)}/10</span>
                        )}
                      </div>
                    </div>

                    <h3 className="article-title">
                      <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {article.title || 'Untitled article'} <ExternalLink size={14} style={{ opacity: 0.5 }} />
                      </a>
                    </h3>

                    <p className="article-summary">
                      {article.summary || (article.text ? `${article.text.substring(0, 160)}...` : 'No summary available.')}
                    </p>

                    {(article.brands?.length > 0 || article.car_models?.length > 0) && (
                      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 5 }}>
                        {article.brands?.slice(0, 2).map((brand) => (
                          <span key={brand} style={{ fontSize: '0.75rem', color: 'var(--secondary-color)', display: 'flex', alignItems: 'center', gap: 3 }}>
                            <Tag size={12} /> {brand}
                          </span>
                        ))}
                        {article.car_models?.slice(0, 2).map((model) => (
                          <span key={model} style={{ fontSize: '0.75rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: 3 }}>
                            <CarFront size={12} /> {model}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="article-footer">
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <Calendar size={14} /> {articleDate(article.published)}
                      </span>
                      <span>{article.source || 'Unknown source'}</span>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>

            {articles.length === 0 && (
              <div style={{ textAlign: 'center', padding: '50px', color: 'var(--text-light)' }}>
                No articles found for the current filters.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
