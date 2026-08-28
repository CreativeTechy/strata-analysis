import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import { Calendar, Search, ChevronLeft, ChevronRight, SlidersHorizontal, Trash2, Filter, Download, Upload, AlertTriangle, LayoutGrid, List, FolderKanban, FolderInput, X } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import ImportProgressBanner from './articles/ImportProgressBanner.jsx';
import DocumentImportBanner from './articles/DocumentImportBanner.jsx';
import SkeletonArticleCard from './articles/SkeletonArticleCard.jsx';
import ArticleDetailModal from './articles/ArticleDetailModal.jsx';
import ArticleCard from './articles/ArticleCard.jsx';
import ArticleRow from './articles/ArticleRow.jsx';
import { useAuth } from '../auth/useAuth.js';
import {
  SENTIMENTS, SORT_OPTIONS, PAGE_SIZES, IMPORT_POLL_MS, JSONL_NAME_RE, DOCUMENT_NAME_RE,
  FULL_IMPORT_ACCEPT, JSONL_ONLY_ACCEPT, getPageNumbers,
} from '../lib/articleHelpers.jsx';
import {
  uploadDocuments,
  pollDocumentExtraction,
  pollArticleCandidates,
  listDocumentArticles,
  setDocumentArticleStatus,
  listDocuments,
} from '../api/projectDocumentsApi.js';
import {
  listArticles, getArticleAnalysis, reprocessArticle, deleteAllArticles,
  exportArticles, importArticles, getImportStatus,
} from '../api/articlesApi.js';
import '../styles/Articles.css';

const VIEW_MODES = [
  { value: 'card', label: 'Cards', icon: LayoutGrid },
  { value: 'list', label: 'List', icon: List },
];

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
  // Read once on mount (lazy initializers only run on the first render) so a link
  // like /articles?search=EV&project_id=3 (e.g. from the "Trending keywords &
  // hashtags" card) pre-fills the filters; later edits to these filters
  // intentionally don't rewrite the URL.
  const [searchParams] = useSearchParams();
  const [searchInput, setSearchInput] = useState(() => searchParams.get('search') || '');
  const [search, setSearch] = useState(() => searchParams.get('search') || '');
  const [sentiment, setSentiment] = useState('all');
  const [projectFilter, setProjectFilter] = useState(() => (
    searchParams.get('project_id') || (normalizedProjectId != null ? String(normalizedProjectId) : 'all')
  ));
  const [sourceFilter, setSourceFilter] = useState('all');
  const [limit, setLimit] = useState(24);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState('published.desc');
  const [addedFrom, setAddedFrom] = useState('');
  const [addedTo, setAddedTo] = useState('');
  const [articles, setArticles] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingAll, setDeletingAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importRun, setImportRun] = useState(null);
  const [documentImportStatus, setDocumentImportStatus] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);
  const [viewMode, setViewMode] = useState(() => {
    try {
      return window.localStorage.getItem('articles-view-mode') === 'list' ? 'list' : 'card';
    } catch {
      return 'card';
    }
  });
  const [expandedRows, setExpandedRows] = useState(() => new Set());
  const [detailArticleId, setDetailArticleId] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailReprocessing, setDetailReprocessing] = useState(false);
  const [detailActionMessage, setDetailActionMessage] = useState('');
  const hasArticlesRef = useRef(false);
  const searchInputRef = useRef(null);
  const importInputRef = useRef(null);
  const importFolderInputRef = useRef(null);
  const { hasPermission } = useAuth();
  const canDeleteAll = hasPermission('articles.delete');
  const canImport = hasPermission('articles.import');
  const canReprocess = hasPermission('pipeline.run');

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setOffset(0);
  }, [search, sentiment, projectFilter, sourceFilter, limit, sort, addedFrom, addedTo]);

  const activeProject = useMemo(() => {
    if (projectFilter === 'all') return null;
    return projects.find((item) => String(item.id) === String(projectFilter)) || null;
  }, [projects, projectFilter]);

  // Every article split out of a document shares that document's synthetic
  // source_url, so filtering by source_url is filtering by document.
  const [documents, setDocuments] = useState([]);

  useEffect(() => {
    const id = activeProject?.id;
    if (id == null) {
      setDocuments([]);
      return undefined;
    }
    let cancelled = false;
    listDocuments(id)
      .then((data) => { if (!cancelled) setDocuments(Array.isArray(data?.documents) ? data.documents : []); })
      .catch(() => { if (!cancelled) setDocuments([]); });
    return () => { cancelled = true; };
  }, [activeProject?.id]);

  const sourceOptions = useMemo(
    () => documents.map((document) => ({
      value: `document://project-document/${document.id}`,
      label: document.original_filename || `Document #${document.id}`,
    })),
    [documents],
  );

  useEffect(() => {
    setSourceFilter('all');
  }, [projectFilter]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadArticles() {
      setLoading(true);
      setError('');
      try {
        const data = await listArticles({
          search: search || undefined,
          sentiment: sentiment !== 'all' ? sentiment : undefined,
          project_id: projectFilter !== 'all' ? projectFilter : undefined,
          source_url: sourceFilter !== 'all' ? sourceFilter : undefined,
          added_from: addedFrom || undefined,
          added_to: addedTo || undefined,
          limit,
          offset,
          sort,
        }, controller.signal);

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
  }, [search, sentiment, projectFilter, sourceFilter, limit, offset, sort, addedFrom, addedTo, reloadToken]);

  useEffect(() => {
    hasArticlesRef.current = articles.length > 0;
  }, [articles.length]);

  useEffect(() => {
    if (detailArticleId == null) return undefined;
    const controller = new AbortController();
    async function loadDetail() {
      setDetailLoading(true);
      setDetailError('');
      setDetailActionMessage('');
      try {
        const data = await getArticleAnalysis(detailArticleId, controller.signal);
        setDetailData(data?.analysis || null);
      } catch (err) {
        if (err?.name !== 'AbortError') {
          setDetailData(null);
          setDetailError(err?.message || 'Failed to load analysis details.');
        }
      } finally {
        setDetailLoading(false);
      }
    }
    loadDetail();
    return () => controller.abort();
  }, [detailArticleId]);

  const changeViewMode = (mode) => {
    setViewMode(mode);
    try {
      window.localStorage.setItem('articles-view-mode', mode);
    } catch {
      // ignore - persistence is a nicety, not a requirement
    }
  };

  const toggleRowExpanded = (id) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const closeDetailModal = () => {
    setDetailArticleId(null);
    setDetailData(null);
    setDetailError('');
    setDetailActionMessage('');
  };

  const handleReprocess = async () => {
    if (detailArticleId == null || detailReprocessing) return;
    setDetailReprocessing(true);
    setDetailActionMessage('');
    try {
      await reprocessArticle(detailArticleId);
      setDetailActionMessage('Reprocessing started - reopen this panel in a moment to see the updated result.');
    } catch (err) {
      setDetailActionMessage(err?.message || 'Failed to reprocess article.');
    } finally {
      setDetailReprocessing(false);
    }
  };

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + articles.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  const isInitialLoading = loading && articles.length === 0;
  const isRefreshing = loading && articles.length > 0;
  const scopeLabel = projectFilter === 'all' ? 'All projects' : (activeProject?.name || 'Selected project');

  const visibleRange = useMemo(() => `${start}-${end}`, [start, end]);
  const searchBusy = Boolean(searchInput) && (searchInput.trim() !== search || loading);

  const clearSearch = () => {
    setSearchInput('');
    setSearch('');
    searchInputRef.current?.focus();
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.min(totalPages, Math.floor(offset / limit) + 1);
  const pageNumbers = useMemo(() => getPageNumbers(currentPage, totalPages), [currentPage, totalPages]);
  const goToPage = (page) => setOffset((page - 1) * limit);

  const handleDeleteAll = async () => {
    if (deletingAll) return;
    setDeletingAll(true);
    setError('');
    try {
      await deleteAllArticles();
      setSearchInput('');
      setSearch('');
      setSentiment('all');
      setProjectFilter(normalizedProjectId != null ? String(normalizedProjectId) : 'all');
      setSourceFilter('all');
      setAddedFrom('');
      setAddedTo('');
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
      const blob = await exportArticles({
        search: search || undefined,
        sentiment: sentiment !== 'all' ? sentiment : undefined,
        project_id: projectFilter !== 'all' ? projectFilter : undefined,
        source_url: sourceFilter !== 'all' ? sourceFilter : undefined,
        added_from: addedFrom || undefined,
        added_to: addedTo || undefined,
        sort,
      });
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

  // Imports one file end to end: queues the backend job, then polls it to
  // completion, rendering its counters and throughput as they arrive.
  // `batchLabel` (e.g. "File 2 of 3: foo.jsonl") is stamped onto each polled
  // run so the banner can show which file of a multi-file selection is active.
  const importSingleFile = async (file, batchLabel) => {
    const body = new FormData();
    body.append('file', file);
    // Imported rows land in the project currently in scope, mirroring what a
    // scrape for that project would have produced. 'all' imports unlinked.
    if (projectFilter !== 'all') body.append('project_id', String(projectFilter));

    const queued = await importArticles(body);

    let lastSaved = 0;
    for (;;) {
      const payload = await getImportStatus(queued.run_id);
      const run = payload.run || {};
      setImportRun(batchLabel ? { ...run, _batchLabel: batchLabel } : run);
      // Refresh the list as rows land, not only at the end, so a long import
      // visibly fills the page instead of sitting empty until it finishes.
      if ((run.saved || 0) > lastSaved) {
        lastSaved = run.saved || 0;
        setReloadToken((value) => value + 1);
      }
      if (run.status === 'success' || run.status === 'failed') {
        if (run.status === 'failed') throw new Error(run.error || run.message || 'Import failed.');
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, IMPORT_POLL_MS));
    }
  };

  // Imports a batch of non-JSONL documents (PDF/DOC/XLS/CSV/image/JSON) via
  // the same upload -> extract -> LLM-split pipeline the project-create
  // wizard uses, then auto-approves only the candidates split out of *these*
  // documents (not every pending candidate in the project - see approve_all's
  // docstring - a wizard mid-review elsewhere shouldn't get its candidates
  // silently approved by an Articles-page import).
  const importDocumentFiles = async (files) => {
    const projectId = projectFilter;
    setDocumentImportStatus({ message: `Uploading ${files.length} file${files.length === 1 ? '' : 's'}...` });
    const { documents } = await uploadDocuments(projectId, files);
    const documentIds = documents.map((doc) => doc.id);

    setDocumentImportStatus({ message: 'Extracting text...' });
    await pollDocumentExtraction(projectId, documentIds, () => {});

    setDocumentImportStatus({ message: 'Splitting into articles...' });
    const afterSplit = await pollArticleCandidates(projectId, documentIds, () => {});
    const failedIds = new Set(
      afterSplit
        .filter((doc) => documentIds.includes(doc.id) && (doc.status === 'failed' || doc.articles_status === 'failed'))
        .map((doc) => doc.id)
    );

    const { articles: candidates } = await listDocumentArticles(projectId);
    const toApprove = candidates.filter((candidate) => documentIds.includes(candidate.document_id) && candidate.status === 'pending');

    setDocumentImportStatus({ message: `Adding ${toApprove.length} article${toApprove.length === 1 ? '' : 's'}...` });
    let approved = 0;
    for (const candidate of toApprove) {
      try {
        await setDocumentArticleStatus(candidate.id, 'approved');
        approved += 1;
        setReloadToken((value) => value + 1);
      } catch {
        // Left pending - reviewable from the project's document-review view.
      }
    }

    setDocumentImportStatus({
      message: `Added ${approved} article${approved === 1 ? '' : 's'} from ${documents.length} file${documents.length === 1 ? '' : 's'}.`,
      done: true,
    });

    if (failedIds.size) {
      const names = documents.filter((doc) => failedIds.has(doc.id)).map((doc) => doc.original_filename || `Document #${doc.id}`);
      throw new Error(`${failedIds.size} file(s) failed to process: ${names.join(', ')}`);
    }
  };

  const handleImportFile = async (event) => {
    const picked = Array.from(event.target.files || []);
    // Clear the input straight away so re-picking the same file(s)/folder still fires onChange.
    event.target.value = '';
    if (!picked.length || importing) return;

    // Document formats (PDF/DOC/XLS/CSV/image/JSON) need the project-documents
    // pipeline, which is project-scoped - so they're only accepted once a
    // specific project is in the filter, same as project-create requires one.
    const hasProject = projectFilter !== 'all';
    const jsonlFiles = [];
    const documentFiles = [];
    const skipped = [];
    for (const file of picked) {
      const name = file.webkitRelativePath || file.name;
      if (JSONL_NAME_RE.test(name)) {
        jsonlFiles.push(file);
      } else if (DOCUMENT_NAME_RE.test(name)) {
        if (hasProject) documentFiles.push(file);
        else skipped.push(name);
      }
    }

    if (!jsonlFiles.length && !documentFiles.length) {
      setError(
        skipped.length
          ? `Select a project to import documents (PDF, Word, Excel, CSV, images, JSON). Skipped: ${skipped.join(', ')}`
          : 'No supported files found in the selection.'
      );
      return;
    }

    setImporting(true);
    setError('');
    setImportRun(null);
    setDocumentImportStatus(null);

    // Files are imported one at a time (the backend runs one job per upload)
    // so failures on one file don't abort the rest of the batch.
    const failures = [];
    for (let i = 0; i < jsonlFiles.length; i += 1) {
      const file = jsonlFiles[i];
      const displayName = file.webkitRelativePath || file.name;
      const batchLabel = jsonlFiles.length > 1 ? `File ${i + 1} of ${jsonlFiles.length}: ${displayName}` : null;
      try {
        await importSingleFile(file, batchLabel);
      } catch (err) {
        failures.push({ name: displayName, error: err?.message || 'Failed to import.' });
      }
    }

    if (documentFiles.length) {
      try {
        await importDocumentFiles(documentFiles);
      } catch (err) {
        const name = documentFiles.length > 1 ? `${documentFiles.length} document(s)` : (documentFiles[0].webkitRelativePath || documentFiles[0].name);
        failures.push({ name, error: err?.message || 'Failed to import.' });
      }
    }

    const messages = [];
    if (failures.length) {
      const totalFiles = jsonlFiles.length + documentFiles.length;
      messages.push(
        totalFiles > 1
          ? `${failures.length} of ${totalFiles} file(s) failed to import: ${failures
              .map((f) => `${f.name} (${f.error})`)
              .join('; ')}`
          : failures[0].error
      );
    }
    if (skipped.length) {
      messages.push(`Select a project to import documents (PDF, Word, Excel, CSV, images, JSON). Skipped: ${skipped.join(', ')}`);
    }
    if (messages.length) setError(messages.join(' '));

    setOffset(0);
    setReloadToken((value) => value + 1);
    setImporting(false);
  };

  return (
    <div className="admin-page-shell articles-page-shell">
      <div className="content-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker" style={{ marginBottom: 10 }}>
              <SlidersHorizontal size={26} color="#ff6b35" />
              <span>Article Library</span>
            </div>
            <h1 className="admin-page-title">Articles</h1>
            <p className="admin-page-subtitle">
              Server-side search, sentiment, project, sort, and pagination powered by the API.
              {project ? ` Dashboard project: ${project.name}.` : ' Showing all projects.'}
            </p>
          </div>

          <div className="dashboard-hero-actions">
            <div className="report-project-control">
              <label className="report-project-control-label" htmlFor="articles-project-select">
                <FolderKanban size={13} /> Project scope
              </label>
              <div className="report-project-select-wrap">
                <FolderKanban size={16} aria-hidden="true" />
                <select
                  id="articles-project-select"
                  className="filter-select report-project-select"
                  value={projectFilter}
                  onChange={(e) => setProjectFilter(e.target.value)}
                  aria-label="Project scope for articles"
                >
                  <option value="all">All projects</option>
                  {projects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} ({item.status || 'draft'})
                    </option>
                  ))}
                </select>
              </div>
            </div>
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

        <ArticleDetailModal
          open={detailArticleId != null}
          canReprocess={canReprocess}
          loading={detailLoading}
          error={detailError}
          data={detailData}
          actionMessage={detailActionMessage}
          reprocessing={detailReprocessing}
          onClose={closeDetailModal}
          onReprocess={handleReprocess}
        />

        <div className="articles-filters-row">
          <div className="glass-card articles-filter-panel">
            <select
              className="filter-select"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              disabled={!activeProject || sourceOptions.length === 0}
            >
              <option value="all">
                {activeProject ? 'All documents' : 'Select a project for documents'}
              </option>
              {sourceOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>

            <div className="articles-date-range">
              <span className="articles-date-range-label">
                <Calendar size={14} /> Added between
              </span>
              <input
                type="date"
                className="filter-select"
                value={addedFrom}
                max={addedTo || undefined}
                onChange={(e) => setAddedFrom(e.target.value)}
                title="Only show articles added on or after this date"
                aria-label="Added from date"
              />
              <span className="articles-date-range-sep">to</span>
              <input
                type="date"
                className="filter-select"
                value={addedTo}
                min={addedFrom || undefined}
                onChange={(e) => setAddedTo(e.target.value)}
                title="Only show articles added on or before this date"
                aria-label="Added to date"
              />
            </div>
          </div>

          <div className="glass-card articles-filter-panel">
            <label className="articles-search">
              <Search size={18} color="var(--text-light)" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape' && searchInput) {
                    e.stopPropagation();
                    clearSearch();
                  }
                }}
                placeholder="Search title, summary, source..."
                aria-label="Search articles"
                style={{ width: '100%', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.95rem' }}
              />
              {searchBusy ? (
                <span className="articles-search-spinner" aria-hidden="true" />
              ) : searchInput ? (
                <button
                  type="button"
                  className="articles-search-clear"
                  onClick={clearSearch}
                  aria-label="Clear search"
                  title="Clear search"
                >
                  <X size={14} />
                </button>
              ) : null}
            </label>

            <select className="filter-select" value={sentiment} onChange={(e) => setSentiment(e.target.value)}>
              {SENTIMENTS.map((value) => (
                <option key={value} value={value}>
                  {value === 'all' ? 'All sentiments' : value[0].toUpperCase() + value.slice(1)}
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
          </div>
        </div>

        <div className="admin-toolbar-row" style={{ justifyContent: 'space-between' }}>
          <div className="articles-toolbar-summary">
            <span>{loading ? 'Loading articles...' : `${total.toLocaleString()} articles total, showing ${visibleRange}`}</span>
            <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
              <Filter size={12} />
              {scopeLabel}
            </span>
            {sourceFilter !== 'all' && (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
                <Filter size={12} />
                {sourceOptions.find((option) => option.value === sourceFilter)?.label || sourceFilter}
              </span>
            )}
            {(addedFrom || addedTo) && (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
                <Calendar size={12} />
                Added {addedFrom || 'any'} to {addedTo || 'any'}
              </span>
            )}
          </div>
          <div className="articles-pager-actions">
            <div className="source-type-tabs" role="tablist" aria-label="Switch article view">
              {VIEW_MODES.map((mode) => {
                const Icon = mode.icon;
                const isActive = viewMode === mode.value;
                return (
                  <button
                    key={mode.value}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    className={`source-type-tab ${isActive ? 'active' : ''}`}
                    onClick={() => changeViewMode(mode.value)}
                  >
                    <Icon size={14} /> {mode.label}
                  </button>
                );
              })}
            </div>
            <select className="filter-select" value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label="Articles per page">
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size} per page
                </option>
              ))}
            </select>
            <button className="btn-secondary" onClick={handleExportJsonl} disabled={loading || exporting || deletingAll}>
              <Download size={16} />
              {exporting ? 'Exporting...' : 'Export JSONL'}
            </button>
            {canImport && (
              <>
                <input
                  ref={importInputRef}
                  type="file"
                  accept={projectFilter === 'all' ? JSONL_ONLY_ACCEPT : FULL_IMPORT_ACCEPT}
                  multiple
                  onChange={handleImportFile}
                  style={{ display: 'none' }}
                />
                <button
                  className="btn-secondary"
                  onClick={() => importInputRef.current?.click()}
                  disabled={loading || importing || deletingAll}
                  title={
                    projectFilter === 'all'
                      ? 'Import one or more JSONL exports. Articles are not linked to a project. Select a project to also import PDF, Word, Excel, CSV, image, or JSON documents.'
                      : 'Import JSONL exports, or PDF/Word/Excel/CSV/image/JSON documents, into the project currently in scope.'
                  }
                >
                  <Upload size={16} />
                  {importing ? 'Importing...' : 'Import Files'}
                </button>
                <input
                  ref={importFolderInputRef}
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  onChange={handleImportFile}
                  style={{ display: 'none' }}
                />
                <button
                  className="btn-secondary"
                  onClick={() => importFolderInputRef.current?.click()}
                  disabled={loading || importing || deletingAll}
                  title={
                    projectFilter === 'all'
                      ? 'Import every JSONL export in a folder. Articles are not linked to a project. Select a project to also import PDF, Word, Excel, CSV, image, or JSON documents.'
                      : 'Import every JSONL export, or PDF/Word/Excel/CSV/image/JSON document, in a folder into the project currently in scope.'
                  }
                >
                  <FolderInput size={16} />
                  {importing ? 'Importing...' : 'Import Folder'}
                </button>
              </>
            )}
            <div className="articles-pagination" role="navigation" aria-label="Articles pagination">
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
          </div>
        </div>

        {error ? (
          <div className="glass-card articles-error-banner">
            <AlertTriangle size={18} />
            <span>{error}</span>
          </div>
        ) : null}

        {importRun ? <ImportProgressBanner run={importRun} onDismiss={() => setImportRun(null)} /> : null}
        {documentImportStatus ? (
          <DocumentImportBanner status={documentImportStatus} onDismiss={() => setDocumentImportStatus(null)} />
        ) : null}

        {isInitialLoading ? (
          viewMode === 'list' ? (
            <div className="articles-list">
              {Array.from({ length: Math.min(limit, 12) }).map((_, i) => (
                <div key={i} className="glass-card article-row article-skeleton" aria-hidden="true">
                  <div className="skeleton-row">
                    <div className="skeleton-pill skeleton-shimmer" style={{ width: '46%' }} />
                    <div className="skeleton-pill skeleton-shimmer" style={{ width: '18%' }} />
                    <div className="skeleton-pill skeleton-shimmer" style={{ width: '14%' }} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="articles-grid">
              {Array.from({ length: Math.min(limit, 12) }).map((_, i) => (
                <SkeletonArticleCard key={i} />
              ))}
            </div>
          )
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

            {viewMode === 'list' ? (
              <div className="articles-list">
                <AnimatePresence>
                  {articles.map((article, i) => (
                    <ArticleRow
                      key={article.url}
                      article={article}
                      search={search}
                      index={i}
                      isExpanded={expandedRows.has(article.id)}
                      isRefreshing={isRefreshing}
                      onToggleExpanded={() => toggleRowExpanded(article.id)}
                      onShowDetails={() => setDetailArticleId(article.id)}
                    />
                  ))}
                </AnimatePresence>
              </div>
            ) : (
              <div className="articles-grid">
                <AnimatePresence>
                  {articles.map((article, i) => (
                    <ArticleCard
                      key={article.url}
                      article={article}
                      search={search}
                      index={i}
                      isRefreshing={isRefreshing}
                      onShowDetails={() => setDetailArticleId(article.id)}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}

            {articles.length === 0 && (
              <div className="glass-card">
                <div className="admin-empty-state">
                  <div className="admin-empty-state-icon">
                    <Search size={18} />
                  </div>
                  <strong>No articles found</strong>
                  <span>Try adjusting your search, sentiment, source, date range, or project filters.</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
