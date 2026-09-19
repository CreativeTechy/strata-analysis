import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, AlertTriangle, ExternalLink, FileText, Globe2, ChevronDown, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import { listProjectSources } from '../api/projectsApi.js';
import { articleDate, getPageNumbers } from '../lib/articleHelpers.jsx';
import '../styles/IntelligenceDashboard.css';
import '../styles/Articles.css';

const SOURCES_PAGE_SIZES = [10, 20, 50, 100];

// Mirrors backend list_project_sources(): a "real" source is an article's
// own url grouped by hostname (a JSONL import that carried a genuine url),
// a "document" source is everything else grouped by the uploaded document
// every LLM-split article shares (see project_document_articles._materialize()
// and CLAUDE.md's note on source/source_url always pointing at the document).
//
// A global page (sidebar nav item, like Articles/Reports) rather than
// project-scoped-only: `/api/projects/{id}/sources` still needs one project,
// so this picks a starting one from `projectId`/`?project_id=` and otherwise
// lets the dropdown below choose - there's no "all projects" source view.
export default function SourcesPage({ projectId = null, projects = [] }) {
  const [searchParams] = useSearchParams();
  const normalizedProjectId = useMemo(() => {
    if (projectId == null) return null;
    if (typeof projectId === 'object') {
      const nested = Number(projectId?.id);
      return Number.isFinite(nested) ? nested : null;
    }
    const parsed = Number(projectId);
    return Number.isFinite(parsed) ? parsed : null;
  }, [projectId]);

  const [selectedProjectId, setSelectedProjectId] = useState(() => (
    searchParams.get('project_id') || (normalizedProjectId != null ? String(normalizedProjectId) : '')
  ));

  // Falls back to the first available project once the list loads in, for
  // whoever opens this from the sidebar with nothing selected yet.
  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(String(projects[0].id));
    }
  }, [projects, selectedProjectId]);

  const project = useMemo(
    () => projects.find((item) => String(item.id) === String(selectedProjectId)) || null,
    [projects, selectedProjectId],
  );

  const [sources, setSources] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalArticles, setTotalArticles] = useState(0);
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedKey, setExpandedKey] = useState(null);

  // A new project or page size invalidates whatever page we were on.
  useEffect(() => {
    setOffset(0);
  }, [selectedProjectId, limit]);

  useEffect(() => {
    if (!selectedProjectId) {
      setSources([]);
      setTotal(0);
      setTotalArticles(0);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    listProjectSources(selectedProjectId, { limit, offset })
      .then((data) => {
        if (cancelled) return;
        setSources(Array.isArray(data?.sources) ? data.sources : []);
        setTotal(Number(data?.total) || 0);
        setTotalArticles(Number(data?.total_articles) || 0);
      })
      .catch((err) => {
        if (!cancelled) {
          setSources([]);
          setTotal(0);
          setTotalArticles(0);
          setError(err?.message || 'Failed to load sources.');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedProjectId, limit, offset]);

  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.min(totalPages, Math.floor(offset / limit) + 1);
  const pageNumbers = useMemo(() => getPageNumbers(currentPage, totalPages), [currentPage, totalPages]);
  const goToPage = (page) => setOffset((page - 1) * limit);

  return (
    <div className="admin-page-shell articles-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker"><Globe2 size={14} /> Sources</div>
          <h1 className="admin-page-title">Sources</h1>
          <p className="admin-page-subtitle">
            {project ? `${project.name} — ` : ''}where this project's articles actually came from: a real outlet when an
            article carries its own URL, the uploaded document otherwise.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} /> Back to Dashboard
          </Link>
        </div>
      </div>

      <div className="glass-card" style={{ marginBottom: 18, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <label htmlFor="sources-project-select" style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-light)' }}>
          Project
        </label>
        <select
          id="sources-project-select"
          value={selectedProjectId}
          onChange={(event) => setSelectedProjectId(event.target.value)}
          className="filter-select"
          style={{ maxWidth: 320 }}
        >
          {projects.length === 0 && <option value="">No projects yet</option>}
          {projects.map((item) => (
            <option key={item.id} value={item.id}>{item.name}</option>
          ))}
        </select>
        <select
          value={limit}
          onChange={(event) => setLimit(Number(event.target.value))}
          className="filter-select"
          aria-label="Sources per page"
          style={{ marginLeft: 'auto' }}
        >
          {SOURCES_PAGE_SIZES.map((size) => (
            <option key={size} value={size}>{size} per page</option>
          ))}
        </select>
      </div>

      {!selectedProjectId ? (
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon"><Globe2 size={18} /></div>
          <strong>Pick a project</strong>
          <span>Sources are scoped to one opinion-monitor project at a time.</span>
        </div>
      ) : loading ? (
        <div className="glass-card run-detail-fallback"><Loader2 size={14} className="spin" /> Loading sources…</div>
      ) : error ? (
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon"><AlertTriangle size={18} /></div>
          <strong>Couldn't load sources</strong>
          <span>{error}</span>
        </div>
      ) : sources.length === 0 ? (
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon"><FileText size={18} /></div>
          <strong>No sources yet</strong>
          <span>Upload a document or import articles into this project first.</span>
        </div>
      ) : (
        <>
          <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: 'var(--text-light)' }}>
            Showing {offset + 1}–{Math.min(offset + sources.length, total)} of {total.toLocaleString()} source{total === 1 ? '' : 's'}
            {' '}· {totalArticles.toLocaleString()} article{totalArticles === 1 ? '' : 's'} total
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {sources.map((source) => {
              const isExpanded = expandedKey === source.key;
              const isReal = source.type === 'real';
              return (
                <div key={source.key} className="glass-card" style={{ padding: 0, overflow: 'hidden' }}>
                  <button
                    type="button"
                    onClick={() => setExpandedKey(isExpanded ? null : source.key)}
                    aria-expanded={isExpanded}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12, width: '100%', padding: '14px 16px',
                      background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
                    }}
                  >
                    {isReal ? <Globe2 size={16} style={{ flexShrink: 0, opacity: 0.6 }} /> : <FileText size={16} style={{ flexShrink: 0, opacity: 0.6 }} />}
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <strong className="project-detail-break-text">{source.label}</strong>
                        <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
                          {isReal ? 'Real source' : 'Uploaded document'}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-light)', marginTop: 2 }}>
                        {source.article_count} article{source.article_count === 1 ? '' : 's'}
                        {source.latest_published_at ? ` · latest ${articleDate(source.latest_published_at)}` : ''}
                      </div>
                    </div>
                    {isReal && source.url ? (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(event) => event.stopPropagation()}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '0.72rem', textDecoration: 'none', flexShrink: 0 }}
                      >
                        <ExternalLink size={12} /> Visit
                      </a>
                    ) : !isReal && project ? (
                      <Link
                        to={`/articles?project_id=${project.id}&source=${encodeURIComponent(source.url || '')}`}
                        onClick={(event) => event.stopPropagation()}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '0.72rem', textDecoration: 'none', flexShrink: 0 }}
                      >
                        View articles
                      </Link>
                    ) : null}
                    <ChevronDown size={16} style={{ flexShrink: 0, transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
                  </button>

                  {isExpanded ? (
                    <div style={{ padding: '0 16px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {(source.articles || []).map((article) => (
                        <div
                          key={article.id}
                          style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
                            padding: '8px 10px', borderRadius: 8, background: 'rgba(0,0,0,0.02)', fontSize: '0.82rem',
                          }}
                        >
                          <span className="project-detail-break-text">{article.title || 'Untitled article'}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0, color: 'var(--text-light)' }}>
                            <span>{articleDate(article.published_at)}</span>
                            {article.url ? (
                              <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                Open <ExternalLink size={11} />
                              </a>
                            ) : null}
                          </span>
                        </div>
                      ))}
                      {source.article_count > (source.articles || []).length ? (
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-light)' }}>
                          Showing {(source.articles || []).length} of {source.article_count}.
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {totalPages > 1 ? (
            <div className="articles-pagination" role="navigation" aria-label="Sources pagination">
              <button className="btn-secondary" onClick={() => setOffset((prev) => Math.max(0, prev - limit))} disabled={!hasPrev || loading}>
                <ChevronLeft size={16} /> Previous
              </button>
              {pageNumbers.map((page, index) =>
                page === '...' ? (
                  <span key={`ellipsis-${index}`} className="articles-page-ellipsis">
                    &hellip;
                  </span>
                ) : (
                  <button
                    key={page}
                    type="button"
                    className={`articles-page-btn ${page === currentPage ? 'active' : ''}`}
                    onClick={() => goToPage(page)}
                    disabled={loading}
                    aria-current={page === currentPage ? 'page' : undefined}
                  >
                    {page}
                  </button>
                )
              )}
              <button className="btn-secondary" onClick={() => setOffset((prev) => prev + limit)} disabled={!hasNext || loading}>
                Next <ChevronRight size={16} />
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
