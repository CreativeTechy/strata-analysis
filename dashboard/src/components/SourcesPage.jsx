import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft, AlertTriangle, ExternalLink, FileText, Globe2, ChevronDown, ChevronLeft, ChevronRight, Loader2,
  ShieldAlert, ShieldCheck, ShieldQuestionMark, ShieldX,
} from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { listProjectSources, setSourceTrust } from '../api/projectsApi.js';
import { articleDate, getPageNumbers } from '../lib/articleHelpers.jsx';
import { formatNumber } from '../lib/i18nFormat.js';
import '../styles/IntelligenceDashboard.css';
import '../styles/Articles.css';

const SOURCES_PAGE_SIZES = [10, 20, 50, 100];

// Offline, operator-set trust tier for a source group - see backend's
// services/articles/source_trust.py. 'unknown' (not yet assessed) is kept
// visually distinct from 'untrusted' (assessed and rejected) throughout -
// collapsing the two is exactly what made the older boolean
// `articles.verified` column useless as a trust signal. Built from `t` (not a
// module-level constant) so the labels re-render in the active locale.
function buildTrustTierMeta(t) {
  return {
    trusted: { label: t('sources:trustTier.trusted'), chipClass: 'success', icon: ShieldCheck },
    mixed: { label: t('sources:trustTier.mixed'), chipClass: 'warning', icon: ShieldAlert },
    untrusted: { label: t('sources:trustTier.untrusted'), chipClass: 'danger', icon: ShieldX },
    unknown: { label: t('sources:trustTier.unknown'), chipClass: 'muted', icon: ShieldQuestionMark },
  };
}
const TRUST_TIER_OPTIONS = ['trusted', 'mixed', 'untrusted', 'unknown'];

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
  const { t, i18n } = useTranslation(['sources', 'common']);
  const TRUST_TIER_META = buildTrustTierMeta(t);
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

  const { hasPermission } = useAuth();
  const canEditTrust = hasPermission('projects.update');
  const [trustEditKey, setTrustEditKey] = useState(null);
  const [trustTierDraft, setTrustTierDraft] = useState('unknown');
  const [trustReasonDraft, setTrustReasonDraft] = useState('');
  const [savingTrust, setSavingTrust] = useState(false);
  const [trustError, setTrustError] = useState('');

  const startEditingTrust = (source) => {
    setTrustEditKey(source.key);
    setTrustTierDraft(source.trust?.tier || 'unknown');
    setTrustReasonDraft('');
    setTrustError('');
  };

  const saveTrust = async (source) => {
    if (!selectedProjectId || !trustReasonDraft.trim()) return;
    setSavingTrust(true);
    setTrustError('');
    try {
      const trust = await setSourceTrust(selectedProjectId, {
        key: source.key, type: source.type, tier: trustTierDraft, reason: trustReasonDraft.trim(),
      });
      setSources((prev) => prev.map((item) => (item.key === source.key ? { ...item, trust } : item)));
      setTrustEditKey(null);
    } catch (err) {
      setTrustError(err?.message || t('sources:trustEditor.genericError'));
    } finally {
      setSavingTrust(false);
    }
  };

  // A new project or page size invalidates whatever page we were on. Reset
  // and fetch live in the same effect so a project/limit change never fires
  // a request with the offset left over from the previous project/page
  // size - it resets first (skipping the fetch this render) and fetches
  // exactly once, on the next render, at the corrected offset.
  const prevPageKeyRef = useRef(`${selectedProjectId}|${limit}`);
  useEffect(() => {
    const pageKey = `${selectedProjectId}|${limit}`;
    const pageKeyChanged = prevPageKeyRef.current !== pageKey;
    prevPageKeyRef.current = pageKey;

    if (pageKeyChanged && offset !== 0) {
      setOffset(0);
      return undefined;
    }

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
          setError(err?.message || t('sources:emptyState.loadErrorFallback'));
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedProjectId, limit, offset]); // eslint-disable-line react-hooks/exhaustive-deps

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
          <div className="admin-page-kicker"><Globe2 size={14} /> {t('sources:page.kicker')}</div>
          <h1 className="admin-page-title">{t('sources:page.title')}</h1>
          <p className="admin-page-subtitle">
            {project ? <span dir="auto">{project.name}</span> : null}
            {project ? ' — ' : ''}
            {t('sources:page.subtitle')}
          </p>
        </div>
        <div className="admin-page-toolbar">
          <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} className="rtl-mirror" /> {t('sources:page.backToDashboard')}
          </Link>
        </div>
      </div>

      <div className="glass-card" style={{ marginBottom: 18, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <label htmlFor="sources-project-select" style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-light)' }}>
          {t('sources:toolbar.projectLabel')}
        </label>
        <select
          id="sources-project-select"
          value={selectedProjectId}
          onChange={(event) => setSelectedProjectId(event.target.value)}
          className="filter-select"
          style={{ maxWidth: 320 }}
        >
          {projects.length === 0 && <option value="">{t('sources:toolbar.noProjectsYet')}</option>}
          {projects.map((item) => (
            <option key={item.id} value={item.id} dir="auto">{item.name}</option>
          ))}
        </select>
        <select
          value={limit}
          onChange={(event) => setLimit(Number(event.target.value))}
          className="filter-select"
          aria-label={t('sources:toolbar.perPageAriaLabel')}
          style={{ marginLeft: 'auto' }}
        >
          {SOURCES_PAGE_SIZES.map((size) => (
            <option key={size} value={size}>{t('sources:perPageOption', { count: size })}</option>
          ))}
        </select>
      </div>

      {!selectedProjectId ? (
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon"><Globe2 size={18} /></div>
          <strong>{t('sources:emptyState.pickProjectTitle')}</strong>
          <span>{t('sources:emptyState.pickProjectBody')}</span>
        </div>
      ) : loading ? (
        <div className="glass-card run-detail-fallback"><Loader2 size={14} className="spin" /> {t('sources:emptyState.loading')}</div>
      ) : error ? (
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon"><AlertTriangle size={18} /></div>
          <strong>{t('sources:emptyState.loadErrorTitle')}</strong>
          <span dir="auto">{error}</span>
        </div>
      ) : sources.length === 0 ? (
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon"><FileText size={18} /></div>
          <strong>{t('sources:emptyState.noSourcesTitle')}</strong>
          <span>{t('sources:emptyState.noSourcesBody')}</span>
        </div>
      ) : (
        <>
          <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: 'var(--text-light)' }}>
            {t('sources:summary.sourcesRange', {
              count: total,
              from: formatNumber(offset + 1, i18n.language),
              to: formatNumber(Math.min(offset + sources.length, total), i18n.language),
              total: formatNumber(total, i18n.language),
            })}
            {' · '}
            {t('sources:summary.articlesTotal', { count: totalArticles, formatted: formatNumber(totalArticles, i18n.language) })}
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
                        <strong className="project-detail-break-text" dir="auto">{source.label}</strong>
                        <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
                          {isReal ? t('sources:sourceRow.realSource') : t('sources:sourceRow.uploadedDocument')}
                        </span>
                        {(() => {
                          const tierMeta = TRUST_TIER_META[source.trust?.tier] || TRUST_TIER_META.unknown;
                          const TierIcon = tierMeta.icon;
                          const trust = source.trust || {};
                          // A default can still carry a real reason - e.g. a
                          // hit in the locally imported Iffy.news dataset -
                          // not just the hand-curated allowlist's plain
                          // "no override yet" case, so this prefers whatever
                          // reason is actually there before falling back.
                          let tooltip;
                          if (trust.is_default === false) {
                            tooltip = t('sources:trustTooltip.setBy', {
                              setBy: trust.set_by || t('sources:trustTooltip.setByFallback'),
                              reason: trust.reason || '',
                            });
                          } else if (trust.reason) {
                            tooltip = t('sources:trustTooltip.defaultWithReason', {
                              reason: trust.reason,
                              setBySuffix: trust.set_by
                                ? t('sources:trustTooltip.defaultSetBySuffix', { setBy: trust.set_by })
                                : '',
                            });
                          } else {
                            tooltip = t('sources:trustTooltip.defaultNoReason');
                          }
                          return (
                            <span
                              className={`panel-chip ${tierMeta.chipClass}`}
                              style={{ textTransform: 'none', letterSpacing: 0 }}
                              title={tooltip}
                            >
                              <TierIcon size={12} /> {tierMeta.label}
                            </span>
                          );
                        })()}
                      </div>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-light)', marginTop: 2 }}>
                        {t('sources:sourceRow.articleCount', { count: source.article_count })}
                        {source.latest_published_at
                          ? t('sources:sourceRow.latestPublished', { date: articleDate(source.latest_published_at) })
                          : ''}
                      </div>
                    </div>
                    {isReal && project ? (
                      <Link
                        to={`/articles?project_id=${project.id}&source_host=${encodeURIComponent(source.label || '')}`}
                        onClick={(event) => event.stopPropagation()}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '0.72rem', textDecoration: 'none', flexShrink: 0 }}
                      >
                        {t('sources:sourceRow.viewArticles')}
                      </Link>
                    ) : null}
                    {isReal && source.url ? (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(event) => event.stopPropagation()}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '0.72rem', textDecoration: 'none', flexShrink: 0 }}
                      >
                        <ExternalLink size={12} /> {t('sources:sourceRow.visit')}
                      </a>
                    ) : !isReal && project ? (
                      <Link
                        to={`/articles?project_id=${project.id}&source=${encodeURIComponent(source.url || '')}`}
                        onClick={(event) => event.stopPropagation()}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '0.72rem', textDecoration: 'none', flexShrink: 0 }}
                      >
                        {t('sources:sourceRow.viewArticles')}
                      </Link>
                    ) : null}
                    {canEditTrust ? (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          trustEditKey === source.key ? setTrustEditKey(null) : startEditingTrust(source);
                        }}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '0.72rem', flexShrink: 0 }}
                      >
                        {t('sources:trustEditor.setTrust')}
                      </button>
                    ) : null}
                    <ChevronDown size={16} style={{ flexShrink: 0, transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
                  </button>

                  {trustEditKey === source.key ? (
                    <div style={{ padding: '0 16px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-light)' }}>
                        {t('sources:trustEditor.trustTierLabel')}
                        <select
                          value={trustTierDraft}
                          onChange={(event) => setTrustTierDraft(event.target.value)}
                          className="filter-select"
                        >
                          {TRUST_TIER_OPTIONS.map((tier) => (
                            <option key={tier} value={tier}>{TRUST_TIER_META[tier].label}</option>
                          ))}
                        </select>
                      </label>
                      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-light)' }}>
                        {t('sources:reasonLabel')}
                        <textarea
                          rows={2}
                          value={trustReasonDraft}
                          onChange={(event) => setTrustReasonDraft(event.target.value)}
                          placeholder={t('sources:trustEditor.reasonPlaceholder')}
                        />
                      </label>
                      {trustError ? <span style={{ fontSize: '0.78rem', color: '#ff4757' }} dir="auto">{trustError}</span> : null}
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          type="button"
                          className="btn-primary"
                          disabled={savingTrust || !trustReasonDraft.trim()}
                          onClick={() => saveTrust(source)}
                        >
                          {savingTrust ? t('common:status.saving') : t('sources:trustEditor.save')}
                        </button>
                        <button type="button" className="btn-secondary" onClick={() => setTrustEditKey(null)} disabled={savingTrust}>
                          {t('common:actions.cancel')}
                        </button>
                      </div>
                    </div>
                  ) : null}

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
                          <span className="project-detail-break-text" dir="auto">{article.title || t('sources:sourceRow.untitledArticle')}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0, color: 'var(--text-light)' }}>
                            <span>{articleDate(article.published_at)}</span>
                            {article.url ? (
                              <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                {t('sources:sourceRow.open')} <ExternalLink size={11} />
                              </a>
                            ) : null}
                          </span>
                        </div>
                      ))}
                      {source.article_count > (source.articles || []).length ? (
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-light)' }}>
                          {t('sources:sourceRow.showingOfCount', { shown: (source.articles || []).length, total: source.article_count })}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {totalPages > 1 ? (
            <div className="articles-pagination" role="navigation" aria-label={t('sources:pagination.ariaLabel')}>
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
                    {formatNumber(page, i18n.language)}
                  </button>
                )
              )}
              <button className="btn-secondary" onClick={() => setOffset((prev) => prev + limit)} disabled={!hasNext || loading}>
                {t('common:actions.next')} <ChevronRight size={16} className="rtl-mirror" />
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
