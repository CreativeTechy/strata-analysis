import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ExternalLink, Calendar, CarFront, Tag, Search, ChevronLeft, ChevronRight, SlidersHorizontal, Trash2, Filter, Download } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';

const SENTIMENTS = ['all', 'positive', 'negative', 'neutral'];
const CATEGORIES = ['all', 'review', 'comparison', 'complaint', 'news', 'ownership_experience', 'buying_guide', 'general_article'];
const SORT_OPTIONS = [
  { value: 'published.desc', label: 'Newest first' },
  { value: 'published.asc', label: 'Oldest first' },
  { value: 'relevance_score.desc', label: 'Highest relevance' },
  { value: 'relevance_score.asc', label: 'Lowest relevance' },
  { value: 'created_at.desc', label: 'Recently saved' },
];

const PAGE_SIZES = [12, 24, 48, 96];

function prettyLabel(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function articleDate(value) {
  if (!value) return 'Unknown date';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

function formatMatchScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return '';
  return score.toFixed(2);
}

function SkeletonArticleCard() {
  return (
    <div className="glass-card article-card article-skeleton" aria-hidden="true">
      <div className="skeleton-row">
        <div className="skeleton-pill skeleton-shimmer" />
        <div className="skeleton-pill skeleton-shimmer" style={{ width: '62%' }} />
      </div>
      <div className="skeleton-title skeleton-shimmer" />
      <div className="skeleton-line skeleton-shimmer" />
      <div className="skeleton-line skeleton-shimmer" style={{ width: '88%' }} />
      <div className="skeleton-tags">
        <div className="skeleton-chip skeleton-shimmer" />
        <div className="skeleton-chip skeleton-shimmer" style={{ width: 92 }} />
      </div>
      <div className="skeleton-footer">
        <div className="skeleton-line skeleton-shimmer" style={{ width: '38%' }} />
        <div className="skeleton-line skeleton-shimmer" style={{ width: '28%' }} />
      </div>
    </div>
  );
}

export default function ArticlesPage({ project = null, projectId = null, projects = [] }) {
  const normalizedProjectId = useMemo(() => {
    if (projectId == null) return null;
    if (typeof projectId === 'object') {
      const nestedId = Number(projectId?.id);
      return Number.isFinite(nestedId) ? nestedId : null;
    }
    const parsed = Number(projectId);
    return Number.isFinite(parsed) ? parsed : null;
  }, [projectId]);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [sentiment, setSentiment] = useState('all');
  const [category, setCategory] = useState('all');
  const [projectFilter, setProjectFilter] = useState(() => (normalizedProjectId != null ? String(normalizedProjectId) : 'all'));
  const [limit, setLimit] = useState(24);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState('published.desc');
  const [articles, setArticles] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingAll, setDeletingAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);
  const hasArticlesRef = useRef(false);
  const { hasRole } = useAuth();
  const canDeleteAll = hasRole('operator');

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setOffset(0);
  }, [search, sentiment, category, projectFilter, limit, sort]);

  const activeProject = useMemo(() => {
    if (projectFilter === 'all') return null;
    return projects.find((item) => String(item.id) === String(projectFilter)) || null;
  }, [projects, projectFilter]);

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
        if (projectFilter !== 'all') params.set('project_id', String(projectFilter));
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
          if (!hasArticlesRef.current) {
            setArticles([]);
            setTotal(0);
          }
        }
      } finally {
        setLoading(false);
      }
    }

    loadArticles();
    return () => controller.abort();
  }, [search, sentiment, category, projectFilter, limit, offset, sort, reloadToken]);

  useEffect(() => {
    hasArticlesRef.current = articles.length > 0;
  }, [articles.length]);

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + articles.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  const isInitialLoading = loading && articles.length === 0;
  const isRefreshing = loading && articles.length > 0;
  const scopeLabel = projectFilter === 'all' ? 'All projects' : (activeProject?.name || 'Selected project');

  const visibleRange = useMemo(() => `${start}-${end}`, [start, end]);

  const handleDeleteAll = async () => {
    if (deletingAll) return;
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
      setProjectFilter(normalizedProjectId != null ? String(normalizedProjectId) : 'all');
      setOffset(0);
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(err?.message || 'Failed to delete articles.');
    } finally {
      setDeletingAll(false);
    }
  };

  const handleExportJsonl = async () => {
    if (exporting) return;
    setExporting(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (sentiment !== 'all') params.set('sentiment', sentiment);
      if (category !== 'all') params.set('category', category);
      if (projectFilter !== 'all') params.set('project_id', String(projectFilter));
      params.set('sort', sort);

      const res = await fetch(`/api/articles/export?${params.toString()}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.error || `Failed to export articles (${res.status})`);
      }

      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      anchor.href = objectUrl;
      anchor.download = `articles-${timestamp}.jsonl`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      setError(err?.message || 'Failed to export articles.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <div className="content-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker" style={{ marginBottom: 10 }}>
              <SlidersHorizontal size={26} color="#ff6b35" />
              <span>Article Library</span>
            </div>
            <h1 className="admin-page-title">Articles</h1>
            <p className="admin-page-subtitle">
              Server-side search, sentiment, category, project, sort, and pagination powered by the API.
              {project ? ` Dashboard project: ${project.name}.` : ' Showing all projects.'}
            </p>
          </div>

          <div className="dashboard-hero-actions">
            {canDeleteAll && (
              <button
                className="btn-secondary"
                onClick={() => setShowDeleteAllModal(true)}
                disabled={loading || deletingAll}
                style={{ color: '#b42318', borderColor: 'rgba(180,35,24,0.18)' }}
              >
                <Trash2 size={16} />
                {deletingAll ? 'Deleting...' : 'Delete All Articles'}
              </button>
            )}
            <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
              Back to Dashboard
            </Link>
          </div>
        </div>

        <ConfirmModal
          open={showDeleteAllModal}
          title="Delete all articles?"
          message="This will remove every row in the articles table and cannot be undone."
          confirmLabel={deletingAll ? 'Deleting...' : 'Delete all articles'}
          cancelLabel="Keep articles"
          confirmButtonStyle={{
            background: 'linear-gradient(135deg, #ff4757, #e03131)',
            boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
          }}
          onClose={() => {
            if (!deletingAll) setShowDeleteAllModal(false);
          }}
          onConfirm={async () => {
            if (deletingAll) return;
            setShowDeleteAllModal(false);
            await handleDeleteAll();
          }}
        />

        <div className="glass-card articles-toolbar">
          <label className="articles-search">
            <Search size={18} color="var(--text-light)" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search title, summary, source..."
              style={{ width: '100%', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.95rem' }}
            />
          </label>

          <select className="filter-select" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="all">All projects</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.status || 'draft'})
              </option>
            ))}
          </select>

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
                {value === 'all' ? 'All categories' : prettyLabel(value)}
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

        <div className="admin-toolbar-row" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)', flexWrap: 'wrap' }}>
            <span>{loading ? 'Loading articles...' : `${total.toLocaleString()} articles total, showing ${visibleRange}`}</span>
            <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
              <Filter size={12} />
              {scopeLabel}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button className="btn-secondary" onClick={handleExportJsonl} disabled={loading || exporting || deletingAll}>
              <Download size={16} />
              {exporting ? 'Exporting...' : 'Export JSONL'}
            </button>
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

        {isInitialLoading ? (
          <div className="articles-grid">
            {Array.from({ length: Math.min(limit, 12) }).map((_, i) => (
              <SkeletonArticleCard key={i} />
            ))}
          </div>
        ) : (
          <>
            {isRefreshing && (
              <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, padding: '14px 18px' }}>
                <div className="loading-spinner" />
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 3 }}>Refreshing results</div>
                  <div style={{ color: 'var(--text-light)', fontSize: '0.9rem' }}>
                    Keeping the current list visible while the new filter set loads.
                  </div>
                </div>
              </div>
            )}

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
                    style={isRefreshing ? { opacity: 0.72, pointerEvents: 'none' } : undefined}
                  >
                    <div className="article-header">
                      <div className="article-meta">
                        <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`}>
                          {article.sentiment || 'Neutral'}
                        </span>
                        <span className="badge category">
                          {prettyLabel(article.article_category || article.category || 'general_article')}
                        </span>
                        {article.relevance_score != null && (
                          <span className="badge score">Score: {Number(article.relevance_score).toFixed(1)}/10</span>
                        )}
                        {article.project_similarity_score != null && (
                          <span className="badge score">Project match: {formatMatchScore(article.project_similarity_score)}</span>
                        )}
                      </div>
                    </div>

                    <h3 className="article-title">
                      <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {article.title || 'Untitled article'} <ExternalLink size={14} style={{ opacity: 0.5 }} />
                      </a>
                    </h3>

                    <p className="article-summary">
                      {article.summary || article.insight_json?.summary || (article.text ? `${article.text.substring(0, 160)}...` : 'No summary available.')}
                    </p>

                    {article.insight_json?.frequent_ideas?.length ? (
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                        {article.insight_json.frequent_ideas.slice(0, 3).map((item) => (
                          <span key={item.idea} className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
                            {item.idea}
                          </span>
                        ))}
                      </div>
                    ) : null}

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
