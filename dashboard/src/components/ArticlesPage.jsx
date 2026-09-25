import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import { Calendar, Search, ChevronLeft, ChevronRight, SlidersHorizontal, Trash2, Filter, Download, Upload, AlertTriangle, LayoutGrid, List, FolderKanban, X } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import DocumentImportBanner from './articles/DocumentImportBanner.jsx';
import ImportOptionsModal from './articles/ImportOptionsModal.jsx';
import RemoveProjectArticlesDialog from './articles/RemoveProjectArticlesDialog.jsx';
import SkeletonArticleCard from './articles/SkeletonArticleCard.jsx';
import ArticleCard from './articles/ArticleCard.jsx';
import ArticleRow from './articles/ArticleRow.jsx';
import { useAuth } from '../auth/useAuth.js';
import {
  SENTIMENTS, SORT_OPTIONS, PAGE_SIZES, DOCUMENT_NAME_RE,
  FULL_IMPORT_ACCEPT, getPageNumbers,
} from '../lib/articleHelpers.jsx';
import {
  uploadDocuments,
  pollDocumentExtraction,
  pollArticleCandidates,
  listDocumentArticles,
  approveDocumentArticlesForDocuments,
  listDocuments,
} from '../api/projectDocumentsApi.js';
import {
  listArticles,
  exportArticles,
} from '../api/articlesApi.js';
import { listProjectSources } from '../api/projectsApi.js';
import { formatNumber } from '../lib/i18nFormat.js';
import '../styles/Articles.css';

const VIEW_MODES = [
  { value: 'card', labelKey: 'viewMode.cards', icon: LayoutGrid },
  { value: 'list', labelKey: 'viewMode.list', icon: List },
];

// SORT_OPTIONS' own `label` (from articleHelpers.jsx, not owned by this
// localization pass) stays the English fallback if a future sort value isn't
// in this map yet - the `value` driving the actual sort query is untouched
// either way.
const SORT_LABEL_KEYS = {
  'published.desc': 'sort.publishedDesc',
  'published.asc': 'sort.publishedAsc',
  'relevance_score.desc': 'sort.relevanceDesc',
  'relevance_score.asc': 'sort.relevanceAsc',
  'created_at.desc': 'sort.createdDesc',
};

// Bounded enum (positive/negative/neutral/mixed) - only the displayed label
// is translated, the <option value=""> stays the raw English enum code.
const SENTIMENT_LABEL_KEYS = {
  positive: 'sentiment.positive',
  negative: 'sentiment.negative',
  neutral: 'sentiment.neutral',
  mixed: 'sentiment.mixed',
};

export default function ArticlesPage({ project = null, projectId = null, projects = [] }) {
  const { t, i18n } = useTranslation(['articles', 'common']);
  const locale = i18n.language;
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
  // hashtags" card) pre-fills the filters. Later edits to these filters do
  // get mirrored back into the URL (see the sync effect below), so a round
  // trip through the article detail page can restore them on return.
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const [searchInput, setSearchInput] = useState(() => searchParams.get('search') || '');
  const [search, setSearch] = useState(() => searchParams.get('search') || '');
  const [sentiment, setSentiment] = useState(() => searchParams.get('sentiment') || 'all');
  const [projectFilter, setProjectFilter] = useState(() => (
    searchParams.get('project_id') || (normalizedProjectId != null ? String(normalizedProjectId) : 'all')
  ));
  // Lets a link from the Sources tab (SourcesPage.jsx) deep-link straight
  // into the matching document's articles, the same way `search`/`project_id`
  // above pre-fill from the URL.
  const [sourceFilter, setSourceFilter] = useState(() => searchParams.get('source') || 'all');
  // The real-source counterpart to sourceFilter above: a "real" source (an
  // article whose own url isn't the document:// scheme, grouped by hostname -
  // see list_project_sources()) instead of an uploaded document. The two are
  // mutually exclusive by construction (an article is either a document split
  // or has its own real url, never both), so picking one clears the other.
  const [sourceHostFilter, setSourceHostFilter] = useState(() => searchParams.get('source_host') || 'all');
  const [limit, setLimit] = useState(24);
  const [offset, setOffset] = useState(() => {
    const parsed = Number(searchParams.get('offset'));
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  });
  const [sort, setSort] = useState(() => searchParams.get('sort') || 'published.desc');
  const [addedFrom, setAddedFrom] = useState(() => searchParams.get('added_from') || '');
  const [addedTo, setAddedTo] = useState(() => searchParams.get('added_to') || '');
  const [articles, setArticles] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [documentImportStatus, setDocumentImportStatus] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [showRemoveModal, setShowRemoveModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [viewMode, setViewMode] = useState(() => {
    try {
      return window.localStorage.getItem('articles-view-mode') === 'list' ? 'list' : 'card';
    } catch {
      return 'card';
    }
  });
  const [expandedRows, setExpandedRows] = useState(() => new Set());
  const hasArticlesRef = useRef(false);
  const searchInputRef = useRef(null);
  const importInputRef = useRef(null);
  const importFolderInputRef = useRef(null);
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canRemoveProjectArticles = hasPermission('articles.delete');
  const canImport = hasPermission('articles.import');

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Compares the actual filter *values* against what they were last time,
  // rather than counting invocations ("have I run before?"): the latter
  // breaks under React StrictMode, which deliberately double-invokes a
  // fresh mount's effects (with identical deps both times) to surface
  // exactly this kind of bug - an invocation-count flag sees the harmless
  // second invocation as a "real" subsequent change and zeroes offset right
  // back out, undoing the restore-from-URL below on every single mount in
  // dev. Comparing values instead of counting runs means the ref only ever
  // reads as "changed" when a filter actually did.
  const filtersKeyRef = useRef(null);
  useEffect(() => {
    const key = JSON.stringify([search, sentiment, projectFilter, sourceFilter, sourceHostFilter, limit, sort, addedFrom, addedTo]);
    if (filtersKeyRef.current !== null && filtersKeyRef.current !== key) {
      setOffset(0);
    }
    filtersKeyRef.current = key;
  }, [search, sentiment, projectFilter, sourceFilter, sourceHostFilter, limit, sort, addedFrom, addedTo]);

  const activeProject = useMemo(() => {
    if (projectFilter === 'all') return null;
    return projects.find((item) => String(item.id) === String(projectFilter)) || null;
  }, [projects, projectFilter]);

  // Keeps the URL's query string mirroring the live filters/offset (a plain
  // `replace`, so it doesn't grow the back-button history) so that navigating
  // to /articles/:id and back lands on the same search, filters, and page
  // instead of resetting to the defaults - the round trip a routed detail
  // page (as opposed to the old in-place modal) makes possible.
  useEffect(() => {
    const next = new URLSearchParams();
    if (search) next.set('search', search);
    if (projectFilter !== 'all') next.set('project_id', projectFilter);
    if (sourceFilter !== 'all') next.set('source', sourceFilter);
    if (sourceHostFilter !== 'all') next.set('source_host', sourceHostFilter);
    if (sentiment !== 'all') next.set('sentiment', sentiment);
    if (addedFrom) next.set('added_from', addedFrom);
    if (addedTo) next.set('added_to', addedTo);
    if (sort !== 'published.desc') next.set('sort', sort);
    if (offset > 0) next.set('offset', String(offset));
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, projectFilter, sourceFilter, sourceHostFilter, sentiment, addedFrom, addedTo, sort, offset]);

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

  // The real (hostname-grouped) sources for the same project - see
  // list_project_sources()'s "real" groups, whose `label` is already the
  // plain hostname. A generous limit rather than real pagination: this feeds
  // a dropdown, and a project's distinct real hostnames are few compared to
  // its articles.
  const [realSources, setRealSources] = useState([]);

  useEffect(() => {
    const id = activeProject?.id;
    if (id == null) {
      setRealSources([]);
      return undefined;
    }
    let cancelled = false;
    listProjectSources(id, { limit: 500 })
      .then((data) => {
        if (cancelled) return;
        const sources = Array.isArray(data?.sources) ? data.sources : [];
        setRealSources(sources.filter((source) => source.type === 'real'));
      })
      .catch(() => { if (!cancelled) setRealSources([]); });
    return () => { cancelled = true; };
  }, [activeProject?.id]);

  const sourceHostOptions = useMemo(
    () => realSources.map((source) => ({
      value: source.label,
      label: `${source.label} (${source.article_count})`,
    })),
    [realSources],
  );

  // Skips the mount-time run so a `?source=`/`?source_host=` deep link (see
  // sourceFilter/sourceHostFilter's initializers above) survives instead of
  // being wiped by this effect firing once on the very render that set it.
  const skipNextSourceReset = useRef(true);
  useEffect(() => {
    if (skipNextSourceReset.current) {
      skipNextSourceReset.current = false;
      return;
    }
    setSourceFilter('all');
    setSourceHostFilter('all');
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
          source_host: sourceHostFilter !== 'all' ? sourceHostFilter : undefined,
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
          setError(err?.message || t('errors.loadFailed'));
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
  }, [search, sentiment, projectFilter, sourceFilter, sourceHostFilter, limit, offset, sort, addedFrom, addedTo, reloadToken, t]);

  useEffect(() => {
    hasArticlesRef.current = articles.length > 0;
  }, [articles.length]);

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

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + articles.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  const isInitialLoading = loading && articles.length === 0;
  const isRefreshing = loading && articles.length > 0;
  const scopeLabel = projectFilter === 'all' ? t('toolbar.allProjectsScope') : (activeProject?.name || t('toolbar.activeProjectScope'));

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

  // Removal is always one project's articles (never "all projects" - SM-101),
  // so the list stays on that project and only the page resets.
  const handleProjectArticlesRemoved = (result, projectName) => {
    setShowRemoveModal(false);
    setError('');
    setNotice(t('removeProject.success', {
      name: projectName,
      removed: formatNumber(Number(result?.articles_removed) || 0, locale),
    }));
    setOffset(0);
    setReloadToken((value) => value + 1);
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
        source_host: sourceHostFilter !== 'all' ? sourceHostFilter : undefined,
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
      setError(err?.message || t('errors.exportFailed'));
    } finally {
      setExporting(false);
    }
  };

  // Imports a batch of documents (PDF/DOC/XLS/CSV/image/JSON/JSONL/NDJSON) via
  // the same upload -> extract -> LLM-split pipeline the project-create
  // wizard uses, then approves only the candidates split out of *these*
  // documents (not every pending candidate in the project - see
  // approve_for_documents' docstring - a wizard mid-review elsewhere
  // shouldn't get its candidates silently approved by an Articles-page
  // import). Every resulting article gets a document_id (via its synthetic
  // source_url), so it's filterable by document the same way any other
  // uploaded document's articles are.
  const importDocumentFiles = async (files) => {
    const projectId = projectFilter;
    setDocumentImportStatus({ message: t('import.uploadingFiles', { count: files.length }) });
    const { documents } = await uploadDocuments(projectId, files);
    const documentIds = documents.map((doc) => doc.id);

    setDocumentImportStatus({ message: t('import.extractingText') });
    await pollDocumentExtraction(projectId, documentIds, () => {});

    setDocumentImportStatus({ message: t('import.splittingIntoArticles') });
    const afterSplit = await pollArticleCandidates(projectId, documentIds, () => {});
    const thisBatch = afterSplit.filter((doc) => documentIds.includes(doc.id));
    const failedIds = new Set(
      thisBatch.filter((doc) => doc.status === 'failed' || doc.articles_status === 'failed').map((doc) => doc.id)
    );
    // A document can finish 'ready' and still leave a note behind:
    // articles_error also carries a .json/.jsonl/.ndjson upload's truncation
    // report (records left behind past the per-file cap - see
    // project_documents_store.py's _process_record_document and
    // listDocuments' own doc comment). That must not be swallowed just
    // because the document itself didn't fail outright.
    const notes = thisBatch
      .filter((doc) => !failedIds.has(doc.id) && doc.articles_error)
      .map((doc) => t('import.documentNote', { name: doc.original_filename || `Document #${doc.id}`, error: doc.articles_error }));

    setDocumentImportStatus({ message: t('import.addingArticles') });
    // One request for the whole batch, scoped to just these documents (see
    // approve_for_documents' docstring), instead of one approval request per
    // candidate - process_document already auto-approves each document as it
    // finishes splitting, so this is also a safety net for whatever that
    // missed, and it's what starts (or joins) the one analysis run this
    // import needs rather than a run-start call per document/candidate.
    await approveDocumentArticlesForDocuments(projectId, documentIds);
    setReloadToken((value) => value + 1);

    const { articles: candidates } = await listDocumentArticles(projectId);
    const approved = candidates.filter(
      (candidate) => documentIds.includes(candidate.document_id) && candidate.status === 'approved'
    ).length;

    setDocumentImportStatus({
      message:
        `${t('import.addedCount', { count: approved })} ${t('import.fromFileCount', { count: documents.length })}`
        + (notes.length ? ` ${notes.join(' ')}` : ''),
      done: true,
      warning: notes.length > 0,
    });

    if (failedIds.size) {
      const names = documents.filter((doc) => failedIds.has(doc.id)).map((doc) => doc.original_filename || `Document #${doc.id}`);
      throw new Error(t('import.filesFailedToProcess', { count: failedIds.size, names: names.join(', ') }));
    }
  };

  const handleImportFile = async (event) => {
    const picked = Array.from(event.target.files || []);
    // Clear the input straight away so re-picking the same file(s)/folder still fires onChange.
    event.target.value = '';
    if (!picked.length || importing) return;

    // All supported formats (PDF/DOC/XLS/CSV/image/JSON/JSONL/NDJSON) go
    // through the project-documents pipeline, which is project-scoped - so
    // they're only accepted once a specific project is in the filter, same
    // as project-create requires one.
    const hasProject = projectFilter !== 'all';
    const documentFiles = [];
    const skipped = [];
    for (const file of picked) {
      const name = file.webkitRelativePath || file.name;
      if (DOCUMENT_NAME_RE.test(name)) {
        if (hasProject) documentFiles.push(file);
        else skipped.push(name);
      }
    }

    if (!documentFiles.length) {
      setError(
        skipped.length
          ? t('import.selectProjectToImport', { names: skipped.join(', ') })
          : t('import.noSupportedFiles')
      );
      return;
    }

    setImporting(true);
    setError('');
    setDocumentImportStatus(null);

    const failures = [];
    try {
      await importDocumentFiles(documentFiles);
    } catch (err) {
      const name = documentFiles.length > 1 ? `${documentFiles.length} document(s)` : (documentFiles[0].webkitRelativePath || documentFiles[0].name);
      failures.push({ name, error: err?.message || t('import.genericFailure') });
    }

    const messages = [];
    if (failures.length) messages.push(failures[0].error);
    if (skipped.length) {
      messages.push(t('import.selectProjectToImport', { names: skipped.join(', ') }));
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
              <span>{t('list.kicker')}</span>
            </div>
            <h1 className="admin-page-title">{t('list.title')}</h1>
            <p className="admin-page-subtitle">
              {t('list.subtitle')}
              {project ? t('list.subtitleProjectSuffix', { name: project.name }) : t('list.subtitleAllProjects')}
            </p>
          </div>

          <div className="dashboard-hero-actions">
            <div className="report-project-control">
              <label className="report-project-control-label" htmlFor="articles-project-select">
                <FolderKanban size={13} /> {t('list.projectScopeLabel')}
              </label>
              <div className="report-project-select-wrap">
                <FolderKanban size={16} aria-hidden="true" />
                <select
                  id="articles-project-select"
                  className="filter-select report-project-select"
                  value={projectFilter}
                  onChange={(e) => {
                    setProjectFilter(e.target.value);
                    // A "removed articles from X" notice belongs to the project it was about.
                    setNotice('');
                  }}
                  aria-label={t('list.projectScopeAriaLabel')}
                >
                  <option value="all">{t('list.allProjectsOption')}</option>
                  {projects.map((item) => (
                    <option key={item.id} value={item.id} dir="auto">
                      {item.name} ({item.status || t('list.draftStatus')})
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {canRemoveProjectArticles && activeProject && (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setShowRemoveModal(true)}
                disabled={loading}
              >
                <Trash2 size={16} aria-hidden="true" />
                {t('removeProject.openButton')}
              </button>
            )}
            <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
              {t('list.backToDashboard')}
            </Link>
          </div>
        </div>

        {showRemoveModal && activeProject ? (
          <RemoveProjectArticlesDialog
            key={activeProject.id}
            open
            project={activeProject}
            onClose={() => setShowRemoveModal(false)}
            onRemoved={handleProjectArticlesRemoved}
          />
        ) : null}

        <ConfirmModal
          open={showExportModal}
          title={t('list.exportModal.title')}
          message={t('list.exportModal.message', { count: total, formatted: formatNumber(total, locale) })}
          confirmLabel={exporting ? t('list.exportModal.confirmLabelBusy') : t('list.exportModal.confirmLabel')}
          cancelLabel={t('common:actions.cancel')}
          onClose={() => {
            if (!exporting) setShowExportModal(false);
          }}
          onConfirm={async () => {
            if (exporting) return;
            setShowExportModal(false);
            await handleExportJsonl();
          }}
        />

        <ImportOptionsModal
          open={showImportModal}
          hasProject={projectFilter !== 'all'}
          disabled={importing}
          onClose={() => setShowImportModal(false)}
          onChooseFiles={() => {
            setShowImportModal(false);
            importInputRef.current?.click();
          }}
          onChooseFolder={() => {
            setShowImportModal(false);
            importFolderInputRef.current?.click();
          }}
        />

        <div className="articles-filters-row">
          <div className="glass-card articles-filter-panel">
            <select
              className="filter-select"
              value={sourceFilter}
              onChange={(e) => {
                setSourceFilter(e.target.value);
                if (e.target.value !== 'all') setSourceHostFilter('all');
              }}
              disabled={!activeProject || sourceOptions.length === 0}
            >
              <option value="all">
                {activeProject ? t('filters.allDocuments') : t('filters.selectProjectForDocuments')}
              </option>
              {sourceOptions.map((option) => (
                <option key={option.value} value={option.value} dir="auto">
                  {option.label}
                </option>
              ))}
            </select>

            <select
              className="filter-select"
              value={sourceHostFilter}
              onChange={(e) => {
                setSourceHostFilter(e.target.value);
                if (e.target.value !== 'all') setSourceFilter('all');
              }}
              disabled={!activeProject || sourceHostOptions.length === 0}
            >
              <option value="all">
                {activeProject ? t('filters.allRealSources') : t('filters.selectProjectForSources')}
              </option>
              {sourceHostOptions.map((option) => (
                <option key={option.value} value={option.value} dir="ltr">
                  {option.label}
                </option>
              ))}
            </select>

            <div className="articles-date-range">
              <span className="articles-date-range-label">
                <Calendar size={14} /> {t('filters.addedBetween')}
              </span>
              <input
                type="date"
                className="filter-select"
                value={addedFrom}
                max={addedTo || undefined}
                onChange={(e) => setAddedFrom(e.target.value)}
                title={t('filters.addedFromTitle')}
                aria-label={t('filters.addedFromAriaLabel')}
              />
              <span className="articles-date-range-sep">{t('filters.dateRangeSeparator')}</span>
              <input
                type="date"
                className="filter-select"
                value={addedTo}
                min={addedFrom || undefined}
                onChange={(e) => setAddedTo(e.target.value)}
                title={t('filters.addedToTitle')}
                aria-label={t('filters.addedToAriaLabel')}
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
                placeholder={t('filters.searchPlaceholder')}
                aria-label={t('filters.searchAriaLabel')}
                dir="auto"
                style={{ width: '100%', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.95rem' }}
              />
              {searchBusy ? (
                <span className="articles-search-spinner" aria-hidden="true" />
              ) : searchInput ? (
                <button
                  type="button"
                  className="articles-search-clear"
                  onClick={clearSearch}
                  aria-label={t('filters.clearSearchAriaLabel')}
                  title={t('filters.clearSearchAriaLabel')}
                >
                  <X size={14} />
                </button>
              ) : null}
            </label>

            <select className="filter-select" value={sentiment} onChange={(e) => setSentiment(e.target.value)}>
              {SENTIMENTS.map((value) => (
                <option key={value} value={value}>
                  {value === 'all' ? t('filters.allSentiments') : t(SENTIMENT_LABEL_KEYS[value] || 'sentiment.neutral')}
                </option>
              ))}
            </select>

            <select className="filter-select" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {SORT_LABEL_KEYS[option.value] ? t(SORT_LABEL_KEYS[option.value]) : option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="admin-toolbar-row" style={{ justifyContent: 'space-between' }}>
          <div className="articles-toolbar-summary">
            <span>{loading ? t('toolbar.loading') : t('toolbar.totalShowing', { total: formatNumber(total, locale), range: visibleRange })}</span>
            <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} dir="auto">
              <Filter size={12} />
              {scopeLabel}
            </span>
            {sourceFilter !== 'all' && (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} dir="auto">
                <Filter size={12} />
                {sourceOptions.find((option) => option.value === sourceFilter)?.label || sourceFilter}
              </span>
            )}
            {sourceHostFilter !== 'all' && (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} dir="ltr">
                <Filter size={12} />
                {sourceHostOptions.find((option) => option.value === sourceHostFilter)?.label || sourceHostFilter}
              </span>
            )}
            {(addedFrom || addedTo) && (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
                <Calendar size={12} />
                {t('toolbar.addedRange', { from: addedFrom || t('toolbar.any'), to: addedTo || t('toolbar.any') })}
              </span>
            )}
          </div>
          <div className="articles-pager-actions">
            <div className="source-type-tabs" role="tablist" aria-label={t('viewMode.ariaLabel')}>
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
                    <Icon size={14} /> {t(mode.labelKey)}
                  </button>
                );
              })}
            </div>
            <select className="filter-select" value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label={t('perPage.ariaLabel')}>
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {t('perPage.option', { count: size })}
                </option>
              ))}
            </select>
            <button className="btn-secondary" onClick={() => setShowExportModal(true)} disabled={loading || exporting}>
              <Upload size={16} />
              {exporting ? t('list.exportModal.confirmLabelBusy') : t('common:actions.export')}
            </button>
            {canImport && (
              <>
                <input
                  ref={importInputRef}
                  type="file"
                  accept={FULL_IMPORT_ACCEPT}
                  multiple
                  onChange={handleImportFile}
                  style={{ display: 'none' }}
                />
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
                  onClick={() => setShowImportModal(true)}
                  disabled={loading || importing}
                >
                  <Download size={16} />
                  {importing ? t('import.importingButton') : t('common:actions.import')}
                </button>
              </>
            )}
          </div>
        </div>

        {error ? (
          <div className="glass-card articles-error-banner">
            <AlertTriangle size={18} />
            <span dir="auto">{error}</span>
          </div>
        ) : null}

        {notice ? (
          <div className="glass-card articles-notice-banner" role="status">
            <span dir="auto">{notice}</span>
            <button type="button" className="confirm-modal-close" onClick={() => setNotice('')} aria-label={t('removeProject.dismiss')}>
              <X size={16} />
            </button>
          </div>
        ) : null}

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
                  <div style={{ fontWeight: 600, marginBottom: 3 }}>{t('refreshing.title')}</div>
                  <div style={{ color: 'var(--text-light)', fontSize: '0.9rem' }}>
                    {t('refreshing.body')}
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
                      onShowDetails={() => navigate(`/articles/${article.id}`, { state: { from: `${location.pathname}${location.search}` } })}
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
                      onShowDetails={() => navigate(`/articles/${article.id}`, { state: { from: `${location.pathname}${location.search}` } })}
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
                  <strong>{t('emptyState.title')}</strong>
                  <span>{t('emptyState.body')}</span>
                </div>
              </div>
            )}
          </>
        )}

        {!isInitialLoading && articles.length > 0 && (
          <div className="articles-pagination" role="navigation" aria-label={t('pagination.ariaLabel')}>
            <button className="btn-secondary" onClick={() => setOffset((prev) => Math.max(0, prev - limit))} disabled={!hasPrev || loading}>
              <ChevronLeft size={16} className="rtl-mirror" /> {t('common:actions.previous')}
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
              {t('common:actions.next')} <ChevronRight size={16} className="rtl-mirror" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
