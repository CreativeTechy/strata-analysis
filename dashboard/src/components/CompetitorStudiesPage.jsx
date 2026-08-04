/**
 * Competitor studies index — the entry point for the competitor experience.
 *
 * Separate from the sentiment/opinion screens on purpose: the two answer different
 * questions and mixing them was what made the old single dashboard hard to read.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle, Building2, CalendarClock, ChevronRight, LayoutGrid, List, Plus, Radar, Search,
  Sparkles, X,
} from 'lucide-react';
import { avatarGradient, initials, listStudies, relativeTime } from '../competitorApi.js';
import '../styles/Competitors.css';

const STATUS_FILTERS = [
  { key: 'all', label: 'All statuses' },
  { key: 'active', label: 'Active' },
  { key: 'draft', label: 'Draft' },
  { key: 'archived', label: 'Archived' },
];

const VIEW_MODES = [
  { value: 'card', label: 'Cards', icon: LayoutGrid },
  { value: 'list', label: 'List', icon: List },
];

function StudyRow({ study }) {
  return (
    <Link to={`/competitors/${study.id}`} className="cs-finding-row" style={{ textDecoration: 'none' }}>
      <span className="cs-avatar cs-finding-row-avatar" style={{ background: avatarGradient(study.name) }} aria-hidden="true">
        {initials(study.name)}
      </span>
      <span className="cs-finding-row-main">
        <span className="cs-finding-row-name">
          {study.business_name || 'Business profile not set up yet'}
          {study.market ? ` · ${study.market}` : ''}
        </span>
        <span className="cs-finding-row-headline">{study.name}</span>
      </span>
      <span className="cs-finding-row-meta">
        {study.tracked_competitors} tracked · {study.finding_count} report{study.finding_count === 1 ? '' : 's'}
        {study.latest_generated_at ? ` · ${relativeTime(study.latest_generated_at)}` : ' · Not analysed yet'}
      </span>
      {study.high_impact_count ? <span className="cs-pill cs-pill-high">{study.high_impact_count} high</span> : null}
      <ChevronRight size={15} className="cs-finding-row-chevron" />
    </Link>
  );
}

export default function CompetitorStudiesPage() {
  const navigate = useNavigate();
  const [studies, setStudies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [viewMode, setViewMode] = useState(() => {
    try {
      return window.localStorage.getItem('competitor-studies-view-mode') === 'list' ? 'list' : 'card';
    } catch {
      return 'card';
    }
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await listStudies();
        if (!cancelled) setStudies(result.studies || []);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounce the free-text search the same way ArticlesPage does, so every
  // keystroke doesn't re-filter the list.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const hasFilters = Boolean(search || statusFilter !== 'all' || dateFrom || dateTo);

  const clearFilters = () => {
    setSearchInput('');
    setSearch('');
    setStatusFilter('all');
    setDateFrom('');
    setDateTo('');
  };

  const changeViewMode = (mode) => {
    setViewMode(mode);
    try {
      window.localStorage.setItem('competitor-studies-view-mode', mode);
    } catch {
      // ignore - persistence is a nicety, not a requirement
    }
  };

  // Studies are a small, fully-loaded list (unlike articles), so filtering
  // client-side avoids adding query params to an endpoint built for a
  // one-shot summary read.
  const filteredStudies = useMemo(() => {
    const fromTime = dateFrom ? new Date(dateFrom).getTime() : null;
    const toTime = dateTo ? new Date(`${dateTo}T23:59:59.999`).getTime() : null;
    return studies.filter((study) => {
      if (statusFilter !== 'all' && (study.status || 'active') !== statusFilter) return false;
      if (search) {
        const haystack = [study.name, study.business_name, study.market, study.industry]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      if (fromTime != null || toTime != null) {
        const generated = study.latest_generated_at ? new Date(study.latest_generated_at).getTime() : null;
        if (generated == null) return false;
        if (fromTime != null && generated < fromTime) return false;
        if (toTime != null && generated > toTime) return false;
      }
      return true;
    });
  }, [studies, search, statusFilter, dateFrom, dateTo]);

  return (
    <div className="cs-page">
      <div className="cs-head">
        <div>
          <h1>Competitor Analysis</h1>
          <p>
            Track what your competitors are doing, what it means for your business, and what to do
            about it. Separate from sentiment and opinion tracking, which answers what people are
            saying.
          </p>
        </div>
        <div className="cs-head-actions">
          <button type="button" className="cs-btn cs-btn-primary" onClick={() => navigate('/competitors/new')}>
            <Plus size={15} /> New study
          </button>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{error}</span>
        </div>
      ) : null}

      {loading ? (
        <div className="cs-card-grid">
          {[0, 1].map((key) => <div key={key} className="cs-skeleton" style={{ height: 170 }} />)}
        </div>
      ) : studies.length ? (
        <>
          <div className="cs-panel cs-findings-toolbar">
            <label className="cs-search-field">
              <Search size={16} />
              <input
                type="text"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search study, business, market..."
              />
            </label>

            <select className="cs-select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}
              aria-label="Filter by status">
              {STATUS_FILTERS.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
            </select>

            <div className="cs-date-range">
              <input type="date" className="cs-input" value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)} aria-label="Last analysed from" />
              <span>to</span>
              <input type="date" className="cs-input" value={dateTo}
                onChange={(event) => setDateTo(event.target.value)} aria-label="Last analysed to" />
            </div>

            {hasFilters ? (
              <button type="button" className="cs-btn cs-btn-sm" onClick={clearFilters}>
                <X size={13} /> Clear filters
              </button>
            ) : null}

            <div className="cs-view-tabs" role="tablist" aria-label="Switch study view">
              {VIEW_MODES.map((mode) => {
                const Icon = mode.icon;
                const isActive = viewMode === mode.value;
                return (
                  <button key={mode.value} type="button" role="tab" aria-selected={isActive}
                    className={`cs-view-tab${isActive ? ' active' : ''}`} onClick={() => changeViewMode(mode.value)}>
                    <Icon size={14} /> {mode.label}
                  </button>
                );
              })}
            </div>
          </div>

          {filteredStudies.length ? (
            viewMode === 'list' ? (
              <div className="cs-finding-list">
                {filteredStudies.map((study) => <StudyRow key={study.id} study={study} />)}
              </div>
            ) : (
              <div className="cs-card-grid">
                {filteredStudies.map((study) => (
                  <Link key={study.id} to={`/competitors/${study.id}`} className="cs-card" style={{ textDecoration: 'none' }}>
                    <span className={`cs-card-spine ${study.high_impact_count ? 'cs-card-spine-high' : 'cs-card-spine-low'}`} aria-hidden="true" />
                    <div className="cs-card-body">
                      <div className="cs-card-top">
                        <div style={{ minWidth: 0 }}>
                          <h3 className="cs-card-headline" style={{ fontSize: '1.05rem' }}>{study.name}</h3>
                          {study.business_name ? (
                            <p className="cs-card-domain" style={{ marginTop: 5 }}>
                              <Building2 size={11} style={{ display: 'inline', verticalAlign: -1, marginRight: 4 }} />
                              {study.business_name}
                              {study.market ? ` · ${study.market}` : ''}
                            </p>
                          ) : (
                            <p className="cs-card-domain" style={{ marginTop: 5, color: '#a16207' }}>
                              Business profile not set up yet
                            </p>
                          )}
                        </div>
                        {study.high_impact_count ? (
                          <span className="cs-pill cs-pill-high">{study.high_impact_count} high impact</span>
                        ) : null}
                      </div>

                      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: '0.83rem', color: 'var(--text-light)' }}>
                        <span><strong style={{ color: 'var(--text-dark)' }}>{study.tracked_competitors}</strong> tracked</span>
                        <span><strong style={{ color: 'var(--text-dark)' }}>{study.finding_count}</strong> report{study.finding_count === 1 ? '' : 's'}</span>
                        {study.repeat_enabled ? (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            <CalendarClock size={12} /> scheduled
                          </span>
                        ) : null}
                      </div>

                      <div className="cs-card-foot">
                        <span>
                          {study.latest_generated_at
                            ? `Last analysed ${relativeTime(study.latest_generated_at)}`
                            : 'Not analysed yet'}
                        </span>
                        <span className="cs-card-foot-open">Open <ChevronRight size={13} /></span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )
          ) : (
            <div className="cs-empty">
              <div className="cs-empty-icon"><Search size={20} /></div>
              <h3>No matching studies</h3>
              <p>Try adjusting your search, status, or date filters.</p>
              <button type="button" className="cs-btn" onClick={clearFilters}>
                <X size={15} /> Clear filters
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="cs-empty">
          <div className="cs-empty-icon"><Radar size={20} /></div>
          <h3>No competitor studies yet</h3>
          <p>
            Start one and Strata will read your website to work out your market, find who you
            compete with, and report what they are doing about it.
          </p>
          <button type="button" className="cs-btn cs-btn-primary" onClick={() => navigate('/competitors/new')}>
            <Sparkles size={15} /> Create your first study
          </button>
        </div>
      )}
    </div>
  );
}
