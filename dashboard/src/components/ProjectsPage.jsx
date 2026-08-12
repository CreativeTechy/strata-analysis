import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';
import { REPEAT_UNIT_OPTIONS } from '../constants/schedule.js';
import '../styles/Projects.css';
import {
  CalendarDays,
  Eye,
  Plus,
  Check,
  X,
  Search,
  Flag,
  Clock3,
  Layers3,
  Link2,
  RefreshCw,
  Sparkles,
  Rss,
  Users,
} from 'lucide-react';

const emptyNewSourceDraft = {
  url: '',
  name: '',
  source_type: 'rss',
};

const SOURCE_TYPE_OPTIONS = [
  { value: 'rss', label: 'RSS' },
  { value: 'web', label: 'Web' },
  { value: 'social', label: 'Social' },
  { value: 'hashtag', label: 'Hashtag' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'username', label: 'X Account' },
  { value: 'reddit', label: 'Reddit' },
  { value: 'telegram', label: 'Telegram' },
];

const TERM_SOURCE_TYPES = new Set(['hashtag', 'keyword', 'username']);

const TERM_SOURCE_PLACEHOLDERS = {
  hashtag: 'Hashtag, without # (e.g. EVSummit)',
  username: 'X account, without @ (e.g. elonmusk)',
  keyword: 'Keyword or phrase (e.g. electric vehicles)',
};

function sourceTypeLabel(sourceType) {
  const match = SOURCE_TYPE_OPTIONS.find((option) => option.value === (sourceType || 'rss'));
  return match ? match.label : (sourceType || 'RSS');
}

// "keyword" sources are crawled as a bare Google News/GDELT/CSE search query
// (see backend/services/sources/sources_store.py's _derive_term_url), so a
// generic term like "coffee" alone returns industry-wide news, not news
// about this project. Prefixing the project name scopes the query to the
// project (e.g. "Starbucks coffee") instead. Hashtag/username terms already
// resolve to a specific page (an X hashtag/profile), not a search query, so
// they don't need this.
function scopeKeywordTerm(projectName, term, sourceType) {
  const trimmedTerm = (term || '').trim();
  if (sourceType !== 'keyword') return trimmedTerm;
  const trimmedName = (projectName || '').trim();
  if (!trimmedName || trimmedTerm.toLowerCase().includes(trimmedName.toLowerCase())) return trimmedTerm;
  return `${trimmedName} ${trimmedTerm}`.trim();
}

const SOURCE_ASSIGN_TABS = [{ value: 'all', label: 'All' }, ...SOURCE_TYPE_OPTIONS];

const DISCOVERY_STEPS = [
  { key: 'suggesting', label: 'Generating AI suggestions' },
  { key: 'prefilling', label: 'Prefilling sources' },
  { key: 'syncing', label: 'Syncing sources' },
  { key: 'success', label: 'Success' },
];

const DISCOVERY_PHASE_LABELS = {
  suggesting: 'Generating AI suggestions...',
  prefilling: 'Prefilling sources...',
  syncing: 'Syncing sources...',
  success: 'Sources ready',
};

function sourceMatchesQuery(source, needle) {
  if (!needle) return true;
  return [
    source.name,
    source.url,
    source.source_type,
    source.enabled ? 'enabled' : 'disabled',
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(needle));
}

const emptyDraft = {
  name: '',
  status: 'draft',
  description: '',
  location: '',
  location_type: '',
  target_audience: '',
  usernames: [],
  hashtags: [],
  keywords: [],
  start_date: '',
  end_date: '',
  source_ids: [],
  user_ids: [],
  repeat_enabled: false,
  repeat_interval_value: 30,
  repeat_interval_unit: 'minutes',
  first_run_at: '',
  repeat_weekdays: [],
};

const STATUS_OPTIONS = ['draft', 'active', 'archived'];
const LOCATION_TYPE_OPTIONS = [
  { value: 'on_site', label: 'On site' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
];
const WEEKDAY_OPTIONS = [
  { value: 'monday', label: 'Monday' },
  { value: 'tuesday', label: 'Tuesday' },
  { value: 'wednesday', label: 'Wednesday' },
  { value: 'thursday', label: 'Thursday' },
  { value: 'friday', label: 'Friday' },
  { value: 'saturday', label: 'Saturday' },
  { value: 'sunday', label: 'Sunday' },
];
const PAGE_SIZE = 10;

function formatDateTime(value) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

function repeatSummary(draft) {
  const value = Number(draft.repeat_interval_value);
  if (!draft.repeat_enabled || !Number.isFinite(value) || value <= 0) return '';
  const unitLabel = value === 1 ? draft.repeat_interval_unit.replace(/s$/, '') : draft.repeat_interval_unit;
  const weekdays = Array.isArray(draft.repeat_weekdays) ? draft.repeat_weekdays : [];
  const weekdaySuffix = weekdays.length
    ? ` on ${weekdays
        .map((day) => WEEKDAY_OPTIONS.find((option) => option.value === day)?.label || day)
        .join(', ')}`
    : '';
  return `Runs again every ${value} ${unitLabel} after completion${weekdaySuffix}`;
}

function toDateInput(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toISOString().slice(0, 10);
}

function toDateTimeLocalInput(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  const year = parsed.getFullYear();
  const month = pad(parsed.getMonth() + 1);
  const day = pad(parsed.getDate());
  const hours = pad(parsed.getHours());
  const minutes = pad(parsed.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function fromDateTimeLocalInput(value) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

function sanitizeTermArray(values) {
  return [
    ...new Set(
      (Array.isArray(values) ? values : [])
        .map((item) => String(item || '').trim())
        .filter(Boolean)
    ),
  ];
}

function normalizeTermListForCompare(values) {
  return sanitizeTermArray(values).sort();
}

function normalizeDraftForCompare(value) {
  return {
    name: String(value?.name || '').trim(),
    status: String(value?.status || 'draft').trim().toLowerCase(),
    description: String(value?.description || '').trim(),
    location: String(value?.location || '').trim(),
    location_type: String(value?.location_type || '').trim().toLowerCase(),
    target_audience: String(value?.target_audience || '').trim(),
    usernames: normalizeTermListForCompare(value?.usernames),
    hashtags: normalizeTermListForCompare(value?.hashtags),
    keywords: normalizeTermListForCompare(value?.keywords),
    start_date: String(value?.start_date || ''),
    end_date: String(value?.end_date || ''),
    source_ids: Array.isArray(value?.source_ids)
      ? [...new Set(value.source_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
    user_ids: Array.isArray(value?.user_ids)
      ? [...new Set(value.user_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
    repeat_enabled: Boolean(value?.repeat_enabled),
    repeat_interval_value: Number(value?.repeat_interval_value) || 0,
    repeat_interval_unit: String(value?.repeat_interval_unit || 'minutes').trim().toLowerCase(),
    first_run_at: String(value?.first_run_at || ''),
    repeat_weekdays: normalizeTermListForCompare(value?.repeat_weekdays),
  };
}

function TermChipsField({ label, placeholder, values, onChange, options = [], disabled, hint }) {
  const [manualValue, setManualValue] = useState('');

  const availableOptions = useMemo(
    () => options.filter((option) => !values.includes(option)),
    [options, values]
  );

  const addValue = (raw) => {
    const trimmed = String(raw || '').trim();
    if (!trimmed || values.includes(trimmed)) return;
    onChange([...values, trimmed]);
  };

  const removeValue = (value) => {
    onChange(values.filter((item) => item !== value));
  };

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <label style={{ fontSize: '0.82rem', color: 'var(--text-light)' }}>{label}</label>
      {values.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {values.map((value) => (
            <span
              key={value}
              className="panel-chip"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, maxWidth: '100%', overflowWrap: 'anywhere' }}
            >
              {value}
              <button
                type="button"
                onClick={() => removeValue(value)}
                disabled={disabled}
                aria-label={`Remove ${value}`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  cursor: disabled ? 'default' : 'pointer',
                  color: 'inherit',
                }}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          addValue(manualValue);
          setManualValue('');
        }}
        style={{ display: 'flex', gap: 6 }}
      >
        <input
          type="text"
          className="source-input"
          placeholder={placeholder}
          value={manualValue}
          onChange={(e) => setManualValue(e.target.value)}
          disabled={disabled}
          style={{ flex: 1 }}
        />
        <button
          type="submit"
          className="btn-secondary"
          disabled={disabled || !manualValue.trim()}
          style={{ padding: '8px 10px' }}
        >
          <Plus size={14} />
        </button>
      </form>
      {availableOptions.length > 0 && (
        <select
          className="filter-select"
          value=""
          onChange={(e) => {
            if (e.target.value) addValue(e.target.value);
          }}
          disabled={disabled}
        >
          <option value="">Add from existing sources...</option>
          {availableOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      )}
      {hint && (
        <span style={{ fontSize: '0.76rem', color: 'var(--text-light)', lineHeight: 1.4 }}>{hint}</span>
      )}
    </div>
  );
}

export function WeekdayPicker({ values, onChange, disabled }) {
  const toggleDay = (day) => {
    onChange(values.includes(day) ? values.filter((value) => value !== day) : [...values, day]);
  };

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>
        Repeat on these days
      </span>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {WEEKDAY_OPTIONS.map((option) => {
          const active = values.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              className={`btn-secondary ${active ? 'active' : ''}`}
              onClick={() => toggleDay(option.value)}
              disabled={disabled}
              style={{ padding: '8px 12px', fontSize: '0.8rem' }}
            >
              {option.label.slice(0, 3)}
            </button>
          );
        })}
      </div>
      <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
        {values.length ? `Restricted to ${values.length} day${values.length === 1 ? '' : 's'} per week.` : 'Runs on any day the interval lands on.'}
      </span>
    </div>
  );
}

function UserAssignField({ users, selectedIds, onToggle, query, onQueryChange, disabled }) {
  const visibleUsers = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((user) =>
      [user.username, user.email, user.role].filter(Boolean).some((value) => String(value).toLowerCase().includes(needle))
    );
  }, [users, query]);

  return (
    <div className="assign-sources-panel">
      <div className="assign-sources-header">
        <div>
          <div className="assign-sources-kicker">
            <Users size={12} style={{ verticalAlign: -1, marginRight: 4 }} /> Linked users
          </div>
          <strong className="assign-sources-title">Choose dashboard users linked to this project</strong>
        </div>
        <div className="assign-sources-summary">
          <span className="panel-chip">{selectedIds.length} selected</span>
        </div>
      </div>

      <div className="assign-sources-toolbar">
        <label className="assign-sources-search">
          <Search size={14} />
          <input
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Filter users by username, email, or role"
            disabled={disabled}
          />
        </label>
      </div>

      <div className="assign-sources-list">
        {users.length === 0 ? (
          <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
            No dashboard users yet.
          </div>
        ) : visibleUsers.length === 0 ? (
          <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
            <div className="admin-empty-state-icon" style={{ width: 36, height: 36 }}>
              <Search size={16} />
            </div>
            <strong>No matching users</strong>
            <span>Try a different search term in this assignment box.</span>
          </div>
        ) : (
          visibleUsers.map((user) => {
            const userId = Number(user.id);
            const isSelected = selectedIds.includes(userId);
            return (
              <label key={user.id} className={`assign-source-item ${isSelected ? 'selected' : ''}`}>
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggle(userId)}
                  disabled={disabled}
                />
                <div className="assign-source-copy">
                  <div className="assign-source-topline">
                    <strong className="assign-source-name project-term-name">{user.username}</strong>
                    <span className={`panel-chip role-${user.role}`}>{user.role}</span>
                  </div>
                  <div className="assign-source-url">{user.email || 'No email on file'}</div>
                </div>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

export default function ProjectsPage({
  projects = [],
  sources = [],
  users = [],
  onCreateProject,
  onUpdateProject,
  onCreateSource,
  onRefreshSources,
  isLoadingProjects,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('projects.create') || hasPermission('projects.update') || hasPermission('projects.delete');
  const canLinkUsers = hasPermission('projects.link_users');
  const STEP = useMemo(() => {
    const keys = ['basics', ...(canLinkUsers ? ['users'] : []), 'discovery', 'schedule', 'sources'];
    return Object.fromEntries(keys.map((key, index) => [key, index + 1]));
  }, [canLinkUsers]);
  const pathname = location.pathname;
  const isCreateRoute = pathname.endsWith('/new');
  const isEditRoute = pathname.endsWith('/edit');
  const isFormRoute = isCreateRoute || isEditRoute;
  const editingId = isEditRoute ? Number(params.projectId) : null;
  const currentProject = useMemo(
    () => (editingId != null ? projects.find((project) => Number(project.id) === Number(editingId)) || null : null),
    [editingId, projects]
  );

  const [draft, setDraft] = useState(emptyDraft);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [isSaving, setIsSaving] = useState(false);
  const [lastDiscovery, setLastDiscovery] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [sourceAssignQuery, setSourceAssignQuery] = useState('');
  const [activeSourceTab, setActiveSourceTab] = useState('all');
  const [userAssignQuery, setUserAssignQuery] = useState('');
  const [initialDraft, setInitialDraft] = useState(emptyDraft);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [fillMode, setFillMode] = useState('');
  const [isGeneratingMetadata, setIsGeneratingMetadata] = useState(false);
  const [discoveryPhase, setDiscoveryPhase] = useState('idle');
  const [showDiscoverySuccessModal, setShowDiscoverySuccessModal] = useState(false);
  const discoveryPhaseTimersRef = useRef([]);
  // Id of the project currently loaded into the draft - lets the reset effect
  // below tell "switched to a different project" apart from "the same
  // project's array reference changed" (e.g. syncTermSourcesToDraft's
  // onCreateSource call triggers a projects refetch mid-wizard), which would
  // otherwise wipe in-progress edits and kick the wizard back to step 1.
  const loadedProjectIdRef = useRef(null);
  const [metadataError, setMetadataError] = useState('');
  const [showNewSourceForm, setShowNewSourceForm] = useState(false);
  const [newSourceDraft, setNewSourceDraft] = useState(emptyNewSourceDraft);
  const [isCreatingSource, setIsCreatingSource] = useState(false);
  const [newSourceError, setNewSourceError] = useState('');
  const [isSyncingSources, setIsSyncingSources] = useState(false);

  const clearDiscoveryPhaseTimers = () => {
    discoveryPhaseTimersRef.current.forEach(clearTimeout);
    discoveryPhaseTimersRef.current = [];
  };

  useEffect(() => () => clearDiscoveryPhaseTimers(), []);

  const sourceProjectsById = useMemo(() => {
    const map = new Map();
    projects.forEach((project) => {
      (project.source_ids || []).forEach((sourceId) => {
        const id = Number(sourceId);
        if (!map.has(id)) map.set(id, []);
        map.get(id).push(project);
      });
    });
    return map;
  }, [projects]);

  const assignableSources = useMemo(() => {
    const selected = new Set(draft.source_ids.map((id) => Number(id)));
    return sources.filter((source) => !source.limited || selected.has(Number(source.id)));
  }, [sources, draft.source_ids]);

  const globalTermOptions = useMemo(() => {
    const nonLimitedSources = sources.filter((source) => !source.limited);
    const optionsForType = (sourceType) =>
      [
        ...new Set(
          nonLimitedSources
            .filter((source) => source.source_type === sourceType)
            .map((source) => String(source.name || '').trim())
            .filter(Boolean)
        ),
      ];
    return {
      username: optionsForType('username'),
      hashtag: optionsForType('hashtag'),
      keyword: optionsForType('keyword'),
    };
  }, [sources]);

  // Both the create wizard's Step 4 and the edit form's assign-sources block scope
  // selection/search to whichever source-type tab is active.
  const sourceTabCounts = useMemo(() => {
    const counts = { all: assignableSources.length };
    SOURCE_TYPE_OPTIONS.forEach((option) => {
      counts[option.value] = assignableSources.filter((source) => (source.source_type || 'rss') === option.value).length;
    });
    return counts;
  }, [assignableSources]);

  const sourcesForActiveTab = useMemo(() => {
    if (activeSourceTab === 'all') return assignableSources;
    return assignableSources.filter((source) => (source.source_type || 'rss') === activeSourceTab);
  }, [assignableSources, activeSourceTab]);

  const visibleSourcesForActiveTab = useMemo(() => {
    const needle = sourceAssignQuery.trim().toLowerCase();
    return sourcesForActiveTab.filter((source) => sourceMatchesQuery(source, needle));
  }, [sourcesForActiveTab, sourceAssignQuery]);

  const selectedSourceCount = draft.source_ids.length;
  const visibleSelectedCountForActiveTab = visibleSourcesForActiveTab.filter((source) => draft.source_ids.includes(Number(source.id))).length;
  const allVisibleSelectedForActiveTab = visibleSourcesForActiveTab.length > 0 && visibleSelectedCountForActiveTab === visibleSourcesForActiveTab.length;

  const stats = useMemo(() => {
    const total = projects.length;
    const active = projects.filter((project) => (project.status || '').toLowerCase() === 'active').length;
    const draftCount = projects.filter((project) => (project.status || '').toLowerCase() === 'draft').length;
    const archived = projects.filter((project) => (project.status || '').toLowerCase() === 'archived').length;
    const assignedSources = new Set(projects.flatMap((project) => (project.source_ids || []).map(Number))).size;
    return { total, active, draftCount, archived, assignedSources };
  }, [projects]);

  const visibleProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      const hashtagNames = (project.hashtags || []).map((value) => String(value).trim()).filter(Boolean);
      const keywordNames = (project.keywords || []).map((value) => String(value).trim()).filter(Boolean);
      const usernameNames = (project.usernames || []).map((value) => String(value).trim()).filter(Boolean);
      const matchesQuery =
        !needle ||
        [
          project.name,
          project.status,
          project.description,
          project.location,
          project.target_audience,
          project.start_date,
          project.end_date,
          ...hashtagNames,
          ...keywordNames,
          ...usernameNames,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle));
      const matchesStatus = statusFilter === 'all' || (project.status || 'draft').toLowerCase() === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [projects, query, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(visibleProjects.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedProjects = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleProjects.slice(start, start + PAGE_SIZE);
  }, [visibleProjects, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  useEffect(() => {
    if (!isFormRoute) {
      loadedProjectIdRef.current = null;
      setDraft(emptyDraft);
      setLastDiscovery(null);
      setInitialDraft(emptyDraft);
      setShowCancelModal(false);
      setWizardStep(1);
      setFillMode('');
      setIsGeneratingMetadata(false);
      clearDiscoveryPhaseTimers();
      setDiscoveryPhase('idle');
      setShowDiscoverySuccessModal(false);
      setMetadataError('');
      setShowNewSourceForm(false);
      setNewSourceDraft(emptyNewSourceDraft);
      setNewSourceError('');
      setActiveSourceTab('all');
      return;
    }

    if (isEditRoute) {
      if (!currentProject) {
        if (loadedProjectIdRef.current !== editingId) {
          setDraft(emptyDraft);
          setInitialDraft(emptyDraft);
        }
        return;
      }

      if (loadedProjectIdRef.current === Number(currentProject.id)) {
        // Same project already loaded - this fired only because the projects
        // array got a new reference (e.g. a source-creation refetch), not
        // because the user switched projects. Leave the in-progress draft
        // and wizard step alone.
        return;
      }
      loadedProjectIdRef.current = Number(currentProject.id);

      const draftFromProject = {
        name: currentProject.name || '',
        status: currentProject.status || 'draft',
        description: currentProject.description || '',
        location: currentProject.location || '',
        location_type: currentProject.location_type || '',
        target_audience: currentProject.target_audience || '',
        usernames: sanitizeTermArray(currentProject.usernames),
        hashtags: sanitizeTermArray(currentProject.hashtags),
        keywords: sanitizeTermArray(currentProject.keywords),
        start_date: toDateInput(currentProject.start_date),
        end_date: toDateInput(currentProject.end_date),
        source_ids: Array.isArray(currentProject.source_ids) ? currentProject.source_ids.map(Number) : [],
        user_ids: Array.isArray(currentProject.user_ids) ? currentProject.user_ids.map(Number) : [],
        repeat_enabled: Boolean(currentProject.repeat_enabled),
        repeat_interval_value: currentProject.repeat_interval_value || 30,
        repeat_interval_unit: currentProject.repeat_interval_unit || 'minutes',
        first_run_at: toDateTimeLocalInput(currentProject.first_run_at),
        repeat_weekdays: sanitizeTermArray(currentProject.repeat_weekdays),
      };
      setDraft(draftFromProject);
      setSourceAssignQuery('');
      setUserAssignQuery('');
      setActiveSourceTab('all');
      setLastDiscovery(null);
      setInitialDraft(draftFromProject);
      setWizardStep(1);
      // An existing project already has its metadata filled in manually; default to the
      // "manual" fill mode so all wizard steps unlock immediately instead of forcing the
      // user to pick a fill method before they can see their own data.
      setFillMode('manual');
      setIsGeneratingMetadata(false);
      clearDiscoveryPhaseTimers();
      setDiscoveryPhase('idle');
      setShowDiscoverySuccessModal(false);
      setMetadataError('');
      setShowNewSourceForm(false);
      setNewSourceDraft(emptyNewSourceDraft);
      setNewSourceError('');
      return;
    }

    loadedProjectIdRef.current = null;
    setDraft(emptyDraft);
    setSourceAssignQuery('');
    setUserAssignQuery('');
    setLastDiscovery(null);
    setInitialDraft(emptyDraft);
    setWizardStep(1);
    setFillMode('');
    setIsGeneratingMetadata(false);
    clearDiscoveryPhaseTimers();
    setDiscoveryPhase('idle');
    setShowDiscoverySuccessModal(false);
    setMetadataError('');
    setShowNewSourceForm(false);
    setNewSourceDraft(emptyNewSourceDraft);
    setNewSourceError('');
    setActiveSourceTab('all');
  }, [currentProject, isEditRoute, isFormRoute, editingId]);

  const discardChanges = () => {
    setShowCancelModal(false);
    setSourceAssignQuery('');
    setUserAssignQuery('');
    setActiveSourceTab('all');
    setDraft(emptyDraft);
    setLastDiscovery(null);
    navigate('/projects');
  };

  const toggleSource = (sourceId) => {
    const id = Number(sourceId);
    setDraft((prev) => ({
      ...prev,
      source_ids: prev.source_ids.includes(id)
        ? prev.source_ids.filter((value) => value !== id)
        : [...prev.source_ids, id],
    }));
  };

  const toggleUserLink = (userId) => {
    const id = Number(userId);
    setDraft((prev) => ({
      ...prev,
      user_ids: prev.user_ids.includes(id)
        ? prev.user_ids.filter((value) => value !== id)
        : [...prev.user_ids, id],
    }));
  };

  // Scoped to the sources visible in the active source-type tab.
  const selectAllSourcesForActiveTab = () => {
    setDraft((prev) => ({
      ...prev,
      source_ids: Array.from(new Set([...prev.source_ids, ...visibleSourcesForActiveTab.map((source) => Number(source.id))])),
    }));
  };

  const clearSourcesForActiveTab = () => {
    const visibleIds = new Set(visibleSourcesForActiveTab.map((source) => Number(source.id)));
    setDraft((prev) => ({
      ...prev,
      source_ids: prev.source_ids.filter((id) => !visibleIds.has(Number(id))),
    }));
  };

  const createSourceInline = async () => {
    const isTermType = TERM_SOURCE_TYPES.has(newSourceDraft.source_type);
    const payload = {
      url: isTermType ? '' : newSourceDraft.url.trim(),
      name: isTermType
        ? scopeKeywordTerm(draft.name, newSourceDraft.name, newSourceDraft.source_type)
        : newSourceDraft.name.trim(),
      source_type: newSourceDraft.source_type,
      enabled: true,
      project_ids: [],
    };

    if (isCreatingSource) return;
    if (isTermType ? !payload.name : !payload.url) return;

    setIsCreatingSource(true);
    setNewSourceError('');
    try {
      const created = await onCreateSource?.(payload);
      const createdId = Number(created?.id);
      if (Number.isFinite(createdId)) {
        setDraft((prev) => ({
          ...prev,
          source_ids: Array.from(new Set([...prev.source_ids, createdId])),
        }));
      }
      setNewSourceDraft(emptyNewSourceDraft);
      setShowNewSourceForm(false);
    } catch (error) {
      setNewSourceError(error?.message || 'Failed to create source.');
    } finally {
      setIsCreatingSource(false);
    }
  };

  // Returns the full set of term-derived source ids (existing + newly synced) so
  // callers that need them immediately (e.g. submit()) aren't stuck reading
  // draft.source_ids before the setDraft below has applied.
  const syncTermSourcesToDraft = async () => {
    const terms = [
      ...draft.usernames.map((term) => ({ term, source_type: 'username' })),
      ...draft.hashtags.map((term) => ({ term, source_type: 'hashtag' })),
      ...draft.keywords.map((term) => ({ term, source_type: 'keyword' })),
    ];
    if (!terms.length || !onCreateSource) return draft.source_ids;

    setIsSyncingSources(true);
    try {
      const created = await Promise.all(
        terms.map(({ term, source_type }) =>
          onCreateSource({
            name: scopeKeywordTerm(draft.name, term, source_type),
            source_type,
            enabled: true,
            project_ids: [],
          }).catch(() => null)
        )
      );
      const ids = created
        .filter(Boolean)
        .map((source) => Number(source.id))
        .filter((id) => Number.isFinite(id));
      const mergedIds = Array.from(new Set([...draft.source_ids, ...ids]));
      if (ids.length) {
        setDraft((prev) => ({
          ...prev,
          source_ids: Array.from(new Set([...prev.source_ids, ...ids])),
        }));
      }
      return mergedIds;
    } finally {
      setIsSyncingSources(false);
    }
  };

  const generateMetadataFromAi = async () => {
    const name = draft.name.trim();
    const description = draft.description.trim();
    if (!name || !description || isGeneratingMetadata) return;

    setIsGeneratingMetadata(true);
    setMetadataError('');
    try {
      const res = await fetch('/api/projects/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        throw new Error(data?.detail || data?.error || `Failed to generate discovery details (${res.status})`);
      }

      const suggestions = data?.suggestions || {};
      setDraft((prev) => ({
        ...prev,
        target_audience: suggestions.target_audience || prev.target_audience,
        usernames: Array.isArray(suggestions.usernames)
          ? sanitizeTermArray([...prev.usernames, ...suggestions.usernames])
          : prev.usernames,
        hashtags: Array.isArray(suggestions.hashtags)
          ? sanitizeTermArray([...prev.hashtags, ...suggestions.hashtags])
          : prev.hashtags,
        keywords: Array.isArray(suggestions.keywords)
          ? sanitizeTermArray([...prev.keywords, ...suggestions.keywords])
          : prev.keywords,
      }));
      return suggestions;
    } catch (error) {
      setMetadataError(error?.message || 'Failed to generate AI suggestions.');
      throw error;
    } finally {
      setIsGeneratingMetadata(false);
    }
  };

  const discoverSourcesFromDraft = async (nextDraft = draft) => {
    const payload = {
      name: nextDraft.name.trim(),
      description: nextDraft.description.trim(),
      location: nextDraft.location.trim(),
      target_audience: nextDraft.target_audience.trim(),
      usernames: sanitizeTermArray(nextDraft.usernames),
      hashtags: sanitizeTermArray(nextDraft.hashtags),
      keywords: sanitizeTermArray(nextDraft.keywords),
      source_ids: Array.isArray(nextDraft.source_ids) ? nextDraft.source_ids : [],
    };

    if (!payload.name) return null;

    clearDiscoveryPhaseTimers();
    setShowDiscoverySuccessModal(false);
    setDiscoveryPhase('suggesting');
    setMetadataError('');
    // The discovery endpoint runs AI suggestion + resolution + source creation as one
    // request, so there's no real progress signal from the server; step the label to
    // "prefilling" partway through so the wait doesn't look stuck on one phase.
    discoveryPhaseTimersRef.current.push(setTimeout(() => setDiscoveryPhase('prefilling'), 1800));

    try {
      const res = await fetch('/api/projects/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        throw new Error(data?.detail || data?.error || `Failed to discover sources (${res.status})`);
      }

      const discovery = data?.discovery || {};
      const discoveredSourceIds = Array.isArray(discovery.source_ids)
        ? [...new Set(discovery.source_ids.map((value) => Number(value)).filter((value) => Number.isFinite(value)))]
        : [];
      if (discoveredSourceIds.length) {
        setDraft((prev) => ({
          ...prev,
          source_ids: Array.from(new Set([...prev.source_ids, ...discoveredSourceIds])),
        }));
      }
      setLastDiscovery(discovery);

      clearDiscoveryPhaseTimers();
      setDiscoveryPhase('syncing');
      await onRefreshSources?.();

      setDiscoveryPhase('success');
      setShowDiscoverySuccessModal(true);
      return discovery;
    } catch (error) {
      clearDiscoveryPhaseTimers();
      setDiscoveryPhase('idle');
      setMetadataError(error?.message || 'Failed to prefill sources.');
      return null;
    }
  };

  const closeDiscoverySuccessModal = () => {
    setShowDiscoverySuccessModal(false);
    setDiscoveryPhase('idle');
  };

  const chooseManualFill = () => {
    setMetadataError('');
    setFillMode('manual');
    setWizardStep(STEP.discovery);
  };

  const chooseAiFill = async () => {
    setFillMode('ai');
    setWizardStep(STEP.discovery);
    try {
      const suggestions = await generateMetadataFromAi();
      if (!suggestions) return;
      const nextDraft = {
        ...draft,
        target_audience: suggestions.target_audience || draft.target_audience,
        usernames: Array.isArray(suggestions.usernames)
          ? sanitizeTermArray([...draft.usernames, ...suggestions.usernames])
          : draft.usernames,
        hashtags: Array.isArray(suggestions.hashtags)
          ? sanitizeTermArray([...draft.hashtags, ...suggestions.hashtags])
          : draft.hashtags,
        keywords: Array.isArray(suggestions.keywords)
          ? sanitizeTermArray([...draft.keywords, ...suggestions.keywords])
          : draft.keywords,
      };
      await discoverSourcesFromDraft(nextDraft);
    } catch {
      // The UI already stores the error state for the user.
    }
  };

  const submit = async () => {
    if (isSaving) return;
    if (!draft.name.trim()) return;

    setIsSaving(true);
    try {
      // Terms (keywords/hashtags/usernames) only turn into actual scraped sources
      // once synced here - relying solely on the discovery step's own "Continue"
      // click meant terms added/edited after that step, or reached by jumping
      // straight to a later step, never got a source_ids entry. Syncing again on
      // every submit (idempotent - create_source upserts on url) guarantees the
      // saved project always reflects the current keywords/hashtags/usernames.
      const syncedSourceIds = await syncTermSourcesToDraft();

      const payload = {
        name: draft.name.trim(),
        status: draft.status,
        description: draft.description.trim(),
        location: draft.location.trim(),
        location_type: draft.location_type || null,
        target_audience: draft.target_audience.trim(),
        usernames: sanitizeTermArray(draft.usernames),
        hashtags: sanitizeTermArray(draft.hashtags),
        keywords: sanitizeTermArray(draft.keywords),
        start_date: draft.start_date || null,
        end_date: draft.end_date || null,
        source_ids: Array.from(new Set([...draft.source_ids, ...(syncedSourceIds || [])])),
        ...(canLinkUsers ? { user_ids: draft.user_ids } : {}),
        repeat_enabled: Boolean(draft.repeat_enabled),
        repeat_interval_value: draft.repeat_interval_value,
        repeat_interval_unit: draft.repeat_interval_unit,
        first_run_at: fromDateTimeLocalInput(draft.first_run_at),
        repeat_weekdays: sanitizeTermArray(draft.repeat_weekdays),
      };

      if (editingId) {
        await onUpdateProject?.(editingId, payload);
      } else {
        await onCreateProject?.(payload);
        setLastDiscovery(null);
      }
      if (editingId) {
        navigate(`/projects/${editingId}`);
      } else {
        navigate('/projects');
      }
    } finally {
      setIsSaving(false);
    }
  };

  const isDirty = useMemo(() => {
    return JSON.stringify(normalizeDraftForCompare(draft)) !== JSON.stringify(normalizeDraftForCompare(initialDraft));
  }, [draft, initialDraft]);

  const handleCancel = () => {
    if (isDirty) {
      setShowCancelModal(true);
      return;
    }
    discardChanges();
  };

  if (isFormRoute) {
    const heading = isEditRoute ? 'Edit Project' : 'Create Project';
    const step1Complete = Boolean(draft.name.trim() && draft.description.trim());
    const step2Complete = fillMode === 'manual' || fillMode === 'ai';
    const canContinueFromStep2 = step2Complete && !isGeneratingMetadata;
    const step3Complete = !draft.repeat_enabled || Boolean(Number(draft.repeat_interval_value) > 0 && draft.repeat_interval_unit);
    const totalSteps = Object.keys(STEP).length;
    const discoveredSources = Array.isArray(lastDiscovery?.sources) ? lastDiscovery.sources : [];
    const discoveredResolvedUrls = Array.isArray(lastDiscovery?.resolved_urls) ? lastDiscovery.resolved_urls : [];
    const discoveryPreviewLimit = 6;
    const discoveryPreviewItems = discoveredSources.length
      ? discoveredSources.slice(0, discoveryPreviewLimit).map((source) => ({ name: source.name || source.url, url: source.url }))
      : discoveredResolvedUrls.slice(0, discoveryPreviewLimit).map((url) => ({ name: url, url }));
    const stepMeta = {
      basics: { label: 'Project basics', detail: 'Name, location, and description', complete: step1Complete },
      users: { label: 'Linked users', detail: 'Choose dashboard users to link', complete: true },
      discovery: { label: 'Discovery details', detail: 'Manual or AI fill', complete: step2Complete },
      schedule: { label: 'Schedule', detail: 'Status and automatic runs', complete: step3Complete },
      sources: { label: 'Sources', detail: isEditRoute ? 'Assign sources, data window, and save' : 'Assign sources, data window, and create', complete: true },
    };
    const stepOrder = Object.keys(STEP).sort((a, b) => STEP[a] - STEP[b]);

    return (
      <div className="admin-page-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker">
              <CalendarDays size={14} /> Opinion monitoring
            </div>
            <h1 className="admin-page-title">{heading}</h1>
            <p className="admin-page-subtitle">
              {isEditRoute
                ? `Update the project in ${totalSteps} steps. Revisit any step, then save your changes.`
                : `Build the project in ${totalSteps} steps, then create the workspace.`}
            </p>
          </div>
          <div className="admin-page-toolbar">
            <div className="admin-page-toolbar-meta">
              <span>Step</span>
              <strong>{wizardStep} of {totalSteps}</strong>
            </div>
            <div className="admin-page-toolbar-meta">
              <span>Mode</span>
              <strong>{fillMode ? fillMode.toUpperCase() : 'Choose one'}</strong>
            </div>
          </div>
        </div>

        <div className="glass-card project-wizard-shell">
          <div className="project-wizard-steps">
            {stepOrder.map((key) => {
              const item = stepMeta[key];
              const step = STEP[key];
              const active = wizardStep === step;
              const done = wizardStep > step;
              const allowed = stepOrder.filter((k) => STEP[k] < step).every((k) => stepMeta[k].complete);
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    if (allowed) {
                      setWizardStep(step);
                    }
                  }}
                  className="btn-secondary project-wizard-step-btn"
                  style={{
                    borderColor: active ? 'rgba(46, 134, 222, 0.28)' : 'rgba(0,0,0,0.08)',
                    background: active ? 'rgba(46, 134, 222, 0.08)' : 'rgba(255,255,255,0.72)',
                  }}
                >
                  <span className="panel-chip" style={{ marginRight: 10 }}>
                    {done ? 'Done' : `0${step}`}
                  </span>
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
                    <strong style={{ fontSize: '0.92rem' }}>{item.label}</strong>
                    <span style={{ fontSize: '0.74rem', color: 'var(--text-light)', textTransform: 'none', letterSpacing: 0 }}>
                      {item.detail}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          {wizardStep === STEP.basics && (
          <div className="glass-card project-wizard-panel">
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.basics}. Project basics</strong>
              <span className="panel-chip">{step1Complete ? 'Ready' : 'Required'}</span>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Project name</span>
                <input
                  type="text"
                  className="source-input"
                  placeholder="Project name"
                  value={draft.name}
                  onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                  disabled={isSaving}
                />
              </label>
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Description</span>
                <textarea
                  className="source-input"
                  placeholder="Project description"
                  rows={4}
                  value={draft.description}
                  onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
                  style={{ resize: 'vertical', minHeight: 110 }}
                  disabled={isSaving}
                />
              </label>

              <div className="form-row-location">
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Location type</span>
                  <select
                    className="filter-select"
                    value={draft.location_type}
                    onChange={(e) => setDraft((prev) => ({ ...prev, location_type: e.target.value }))}
                    disabled={isSaving}
                  >
                    <option value="">Select...</option>
                    {LOCATION_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Location</span>
                  <input
                    type="text"
                    className="source-input"
                    placeholder="Location"
                    value={draft.location}
                    onChange={(e) => setDraft((prev) => ({ ...prev, location: e.target.value }))}
                    disabled={isSaving}
                  />
                </label>
              </div>

              <div className="project-wizard-nav-row">
                <span style={{ color: 'var(--text-light)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                  Use a clear working title and a short description. We’ll use these to seed the AI suggestions and source discovery.
                </span>
                <button
                  type="button"
                  className="btn-primary wizard-btn-continue"
                  onClick={() => setWizardStep(STEP.users || STEP.discovery)}
                  disabled={!step1Complete || isSaving}
                >
                  Continue
                </button>
              </div>
            </div>
          </div>
          )}

          {canLinkUsers && wizardStep === STEP.users && (
          <div className="glass-card project-wizard-panel">
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.users}. Linked users</strong>
              <span className="panel-chip">{draft.user_ids.length} selected</span>
            </div>
            <div style={{ display: 'grid', gap: 14 }}>
              <UserAssignField
                users={users}
                selectedIds={draft.user_ids}
                onToggle={toggleUserLink}
                query={userAssignQuery}
                onQueryChange={setUserAssignQuery}
                disabled={isSaving}
              />

              <div className="project-wizard-nav-row">
                <button type="button" className="btn-secondary wizard-btn-back" onClick={() => setWizardStep(STEP.basics)} disabled={isSaving}>
                  Back
                </button>
                <button
                  type="button"
                  className="btn-primary wizard-btn-continue"
                  onClick={() => setWizardStep(STEP.discovery)}
                  disabled={isSaving}
                >
                  Continue
                </button>
              </div>
            </div>
          </div>
          )}

          {wizardStep === STEP.discovery && (
          <div
            className="glass-card project-wizard-panel"
            style={{ opacity: step1Complete ? 1 : 0.7 }}
          >
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.discovery}. Discovery details</strong>
              <span className="panel-chip">{fillMode ? fillMode.toUpperCase() : 'Choose a method'}</span>
            </div>

            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
              <button
                type="button"
                className={`btn-secondary ${fillMode === 'manual' ? 'active' : ''}`}
                onClick={chooseManualFill}
                disabled={!step1Complete || isSaving}
              >
                Fill manually
              </button>
              <button
                type="button"
                className={`btn-secondary ${fillMode === 'ai' ? 'active' : ''}`}
                onClick={chooseAiFill}
                disabled={!step1Complete || isSaving || isGeneratingMetadata || discoveryPhase !== 'idle'}
              >
                {isGeneratingMetadata
                  ? 'Generating with AI...'
                  : discoveryPhase !== 'idle'
                  ? DISCOVERY_PHASE_LABELS[discoveryPhase]
                  : 'Fill by AI'}
              </button>
            </div>

            {!step2Complete ? (
              <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                <div className="admin-empty-state-icon">
                  <Sparkles size={18} />
                </div>
                <strong>Choose a fill method</strong>
                <span>AI will draft X accounts, hashtags, keywords, and a target audience. Manual mode lets you enter them yourself.</span>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 12 }}>
                {metadataError && (
                  <div
                    style={{
                      padding: '12px 14px',
                      borderRadius: 14,
                      background: 'rgba(255, 71, 87, 0.08)',
                      border: '1px solid rgba(255, 71, 87, 0.16)',
                      color: '#b42318',
                      fontSize: '0.84rem',
                      lineHeight: 1.5,
                    }}
                  >
                    {metadataError}
                  </div>
                )}

                <div style={{ display: 'grid', gap: 8 }}>
                  <label style={{ fontSize: '0.82rem', color: 'var(--text-light)' }}>Target audience</label>
                  <input
                    type="text"
                    className="source-input"
                    placeholder="Target audience"
                    value={draft.target_audience}
                    onChange={(e) => setDraft((prev) => ({ ...prev, target_audience: e.target.value }))}
                    disabled={isSaving || isGeneratingMetadata}
                  />
                </div>

                <div className="wizard-term-fields">
                  <TermChipsField
                    label="X Accounts"
                    placeholder="Add an X account, without @"
                    values={draft.usernames}
                    onChange={(next) => setDraft((prev) => ({ ...prev, usernames: next }))}
                    options={globalTermOptions.username}
                    disabled={isSaving || isGeneratingMetadata}
                  />
                  <TermChipsField
                    label="Hashtags"
                    placeholder="Add a hashtag, without #"
                    values={draft.hashtags}
                    onChange={(next) => setDraft((prev) => ({ ...prev, hashtags: next }))}
                    options={globalTermOptions.hashtag}
                    disabled={isSaving || isGeneratingMetadata}
                  />
                  <TermChipsField
                    label="Keywords"
                    placeholder="Add a keyword or phrase"
                    values={draft.keywords}
                    onChange={(next) => setDraft((prev) => ({ ...prev, keywords: next }))}
                    options={globalTermOptions.keyword}
                    disabled={isSaving || isGeneratingMetadata}
                    hint={
                      draft.name.trim()
                        ? `Each keyword is searched together with the project name, e.g. "${scopeKeywordTerm(draft.name, draft.keywords[0] || 'coffee', 'keyword')}" - so results stay specific to this project.`
                        : 'Each keyword is searched together with the project name, so results stay specific to this project.'
                    }
                  />
                </div>

                <div className="admin-form-hint">
                  {isEditRoute
                    ? 'Selected sources stay reusable across projects. Prefilling looks at the current X accounts, hashtags, and keywords.'
                    : 'Use AI to prefill sources from the X accounts, hashtags, and keywords above, then assign or add more sources in the next steps.'}
                </div>

                {lastDiscovery && (
                  <div
                    style={{
                      padding: 14,
                      borderRadius: 16,
                      background: 'rgba(255,255,255,0.72)',
                      border: '1px solid rgba(15, 23, 42, 0.08)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 10,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                      <strong style={{ fontSize: '0.92rem', color: 'var(--text-dark)' }}>Discovery results</strong>
                      <span className="panel-chip">
                        {(lastDiscovery.resolved_urls || []).length} source{(lastDiscovery.resolved_urls || []).length === 1 ? '' : 's'}
                      </span>
                    </div>

                    {(lastDiscovery.resolved_urls || []).length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {(lastDiscovery.resolved_urls || []).map((url) => (
                          <a
                            key={url}
                            href={url}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                              fontSize: '0.84rem',
                              color: 'var(--text-dark)',
                              textDecoration: 'none',
                              padding: '10px 12px',
                              borderRadius: 12,
                              background: 'rgba(15, 23, 42, 0.04)',
                              wordBreak: 'break-word',
                            }}
                          >
                            {url}
                          </a>
                        ))}
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                        No valid URLs were resolved from the X accounts, hashtags, and keywords for this save.
                      </div>
                    )}
                  </div>
                )}

                {discoveryPhase !== 'idle' && (
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {DISCOVERY_STEPS.map((step) => {
                      const stepIndex = DISCOVERY_STEPS.findIndex((s) => s.key === step.key);
                      const currentIndex = DISCOVERY_STEPS.findIndex((s) => s.key === discoveryPhase);
                      const state = stepIndex < currentIndex ? 'done' : stepIndex === currentIndex ? 'active' : 'pending';
                      return (
                        <span
                          key={step.key}
                          className={`panel-chip ${state === 'done' ? 'success' : state === 'active' ? 'warning' : 'muted'}`}
                          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                        >
                          {state === 'active' && <RefreshCw size={12} className="spin" />}
                          {state === 'done' && <Check size={12} />}
                          {step.label}
                        </span>
                      );
                    })}
                  </div>
                )}

                <div className="project-wizard-nav-row">
                  <span style={{ color: 'var(--text-light)', fontSize: '0.85rem', lineHeight: 1.5, maxWidth: 480 }}>
                    The AI step gives you a starting point. You can still reshape handles, tags, and keywords before creating the project.
                  </span>
                  <div className="project-wizard-nav-actions">
                    <button
                      type="button"
                      className="btn-secondary wizard-btn-back"
                      onClick={() => setWizardStep(STEP.users || STEP.basics)}
                      disabled={isSaving || isGeneratingMetadata}
                    >
                      Back
                    </button>
                    <button
                      type="button"
                      className="btn-primary wizard-btn-continue"
                      onClick={async () => {
                        await syncTermSourcesToDraft();
                        setWizardStep(STEP.schedule);
                      }}
                      disabled={!canContinueFromStep2 || isSaving || isSyncingSources}
                    >
                      {isSyncingSources ? (
                        <>
                          <RefreshCw size={18} className="spin" /> Syncing sources...
                        </>
                      ) : (
                        'Continue'
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
          )}

          {wizardStep === STEP.schedule && (
          <div
            className="glass-card project-wizard-panel"
            style={{ opacity: step1Complete && step2Complete ? 1 : 0.7 }}
          >
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.schedule}. Schedule and automatic runs</strong>
              <span className={`panel-chip ${draft.repeat_enabled ? 'success' : 'muted'}`}>
                {draft.repeat_enabled ? 'Repeat on' : 'Repeat off'}
              </span>
            </div>

            <div style={{ display: 'grid', gap: 14 }}>
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Status</span>
                <select
                  className="filter-select"
                  value={draft.status}
                  onChange={(e) => setDraft((prev) => ({ ...prev, status: e.target.value }))}
                  disabled={isSaving}
                >
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {status[0].toUpperCase() + status.slice(1)}
                    </option>
                  ))}
                </select>
              </label>

              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Start first run at</span>
                <input
                  type="datetime-local"
                  className="source-input"
                  value={draft.first_run_at}
                  onChange={(e) => setDraft((prev) => ({ ...prev, first_run_at: e.target.value }))}
                  disabled={isSaving}
                />
              </label>

              <div className="admin-item-card" style={{ margin: 0 }}>
                <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                  <strong style={{ fontSize: '0.94rem' }}>Run automatically</strong>
                  <span className={`panel-chip ${draft.repeat_enabled ? 'success' : 'muted'}`}>
                    {draft.repeat_enabled ? 'Repeat on' : 'Repeat off'}
                  </span>
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: draft.repeat_enabled ? 12 : 0 }}>
                  <input
                    type="checkbox"
                    checked={draft.repeat_enabled}
                    onChange={(e) => setDraft((prev) => ({ ...prev, repeat_enabled: e.target.checked }))}
                    disabled={isSaving}
                  />
                  <span style={{ fontSize: '0.86rem' }}>Automatically rerun this project's workflow after each completion</span>
                </label>
                {draft.repeat_enabled && (
                  <>
                    <div className="form-row-even">
                      <label style={{ display: 'grid', gap: 6 }}>
                        <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Repeat every</span>
                        <input
                          type="number"
                          min="1"
                          className="source-input"
                          value={draft.repeat_interval_value}
                          onChange={(e) => setDraft((prev) => ({ ...prev, repeat_interval_value: e.target.value }))}
                          disabled={isSaving}
                        />
                      </label>
                      <label style={{ display: 'grid', gap: 6 }}>
                        <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Unit</span>
                        <select
                          className="filter-select"
                          value={draft.repeat_interval_unit}
                          onChange={(e) => setDraft((prev) => ({ ...prev, repeat_interval_unit: e.target.value }))}
                          disabled={isSaving}
                        >
                          {REPEAT_UNIT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div style={{ marginTop: 12 }}>
                      <WeekdayPicker
                        values={draft.repeat_weekdays}
                        onChange={(next) => setDraft((prev) => ({ ...prev, repeat_weekdays: next }))}
                        disabled={isSaving}
                      />
                    </div>
                    <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.84rem' }}>{repeatSummary(draft)}</div>
                  </>
                )}
              </div>

              <div className="project-wizard-nav-row">
                <button type="button" className="btn-secondary wizard-btn-back" onClick={() => setWizardStep(STEP.discovery)} disabled={isSaving}>
                  Back
                </button>
                <button
                  type="button"
                  className="btn-primary wizard-btn-continue"
                  onClick={() => setWizardStep(STEP.sources)}
                  disabled={!step3Complete || isSaving}
                >
                  Continue
                </button>
              </div>
            </div>
          </div>
          )}

          {wizardStep === STEP.sources && (
          <div
            className="glass-card project-wizard-panel"
            style={{ opacity: step1Complete && step2Complete && step3Complete ? 1 : 0.7 }}
          >
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.sources}. Assign sources and {isEditRoute ? 'save' : 'create'}</strong>
              <span className="panel-chip">{selectedSourceCount} selected sources</span>
            </div>

            <div style={{ display: 'grid', gap: 14 }}>
              <div className="admin-item-card" style={{ margin: 0 }}>
                <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                  <strong style={{ fontSize: '0.94rem' }}>Data retrieval window</strong>
                </div>
                <div className="form-row-even">
                  <label style={{ display: 'grid', gap: 6 }}>
                    <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Start date</span>
                    <input
                      type="date"
                      className="source-input"
                      value={draft.start_date}
                      onChange={(e) => setDraft((prev) => ({ ...prev, start_date: e.target.value }))}
                      disabled={isSaving}
                    />
                  </label>
                  <label style={{ display: 'grid', gap: 6 }}>
                    <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>End date</span>
                    <input
                      type="date"
                      className="source-input"
                      value={draft.end_date}
                      onChange={(e) => setDraft((prev) => ({ ...prev, end_date: e.target.value }))}
                      disabled={isSaving}
                    />
                  </label>
                </div>
                <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.84rem', lineHeight: 1.5 }}>
                  These dates scope which article publish dates get retrieved when the sources below are scraped - they don't set how long the project itself runs.
                </div>
              </div>

              <div className="assign-sources-panel">
                <div className="assign-sources-header">
                  <div>
                    <div className="assign-sources-kicker">Assign sources</div>
                    <strong className="assign-sources-title">Choose the sources that should power this project</strong>
                  </div>
                  <div className="assign-sources-summary">
                    <span className="panel-chip">{selectedSourceCount} selected</span>
                    <span className="panel-chip muted">{visibleSourcesForActiveTab.length} shown</span>
                  </div>
                </div>

                {assignableSources.length > 0 && (
                  <div className="source-type-tabs" role="tablist" aria-label="Filter sources by type">
                    {SOURCE_ASSIGN_TABS.map((tab) => {
                      const isActive = activeSourceTab === tab.value;
                      return (
                        <button
                          key={tab.value}
                          type="button"
                          role="tab"
                          aria-selected={isActive}
                          className={`source-type-tab ${isActive ? 'active' : ''}`}
                          onClick={() => setActiveSourceTab(tab.value)}
                          disabled={isSaving}
                        >
                          {tab.label}
                          <span className="source-type-tab-count">{sourceTabCounts[tab.value] || 0}</span>
                        </button>
                      );
                    })}
                  </div>
                )}

                <div className="assign-sources-toolbar">
                  <label className="assign-sources-search">
                    <Search size={14} />
                    <input
                      type="text"
                      value={sourceAssignQuery}
                      onChange={(e) => setSourceAssignQuery(e.target.value)}
                      placeholder="Filter sources by name or URL"
                      disabled={isSaving}
                    />
                  </label>

                  <div className="assign-sources-actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={selectAllSourcesForActiveTab}
                      disabled={isSaving || visibleSourcesForActiveTab.length === 0 || allVisibleSelectedForActiveTab}
                      style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                    >
                      Select visible
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={clearSourcesForActiveTab}
                      disabled={isSaving || visibleSelectedCountForActiveTab === 0}
                      style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                    >
                      Clear visible
                    </button>
                    <button
                      type="button"
                      className={`btn-secondary ${showNewSourceForm ? 'active' : ''}`}
                      onClick={() => {
                        setNewSourceError('');
                        setShowNewSourceForm((prev) => !prev);
                      }}
                      disabled={isSaving}
                      style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                    >
                      <Rss size={14} /> {showNewSourceForm ? 'Close' : 'New source'}
                    </button>
                  </div>
                </div>

                {showNewSourceForm && (
                  <div
                    style={{
                      display: 'grid',
                      gap: 10,
                      padding: 14,
                      marginBottom: 10,
                      borderRadius: 14,
                      border: '1px solid rgba(15, 23, 42, 0.08)',
                      background: 'rgba(255,255,255,0.7)',
                    }}
                  >
                    <strong style={{ fontSize: '0.86rem' }}>Create a new source</strong>
                    {!TERM_SOURCE_TYPES.has(newSourceDraft.source_type) && (
                      <input
                        type="text"
                        className="source-input"
                        placeholder="Source URL"
                        value={newSourceDraft.url}
                        onChange={(e) => setNewSourceDraft((prev) => ({ ...prev, url: e.target.value }))}
                        disabled={isCreatingSource}
                      />
                    )}
                    <input
                      type="text"
                      className="source-input"
                      placeholder={TERM_SOURCE_PLACEHOLDERS[newSourceDraft.source_type] || 'Display name'}
                      value={newSourceDraft.name}
                      onChange={(e) => setNewSourceDraft((prev) => ({ ...prev, name: e.target.value }))}
                      disabled={isCreatingSource}
                    />
                    <select
                      className="filter-select"
                      value={newSourceDraft.source_type}
                      onChange={(e) => setNewSourceDraft((prev) => ({ ...prev, source_type: e.target.value }))}
                      disabled={isCreatingSource}
                    >
                      {SOURCE_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    {newSourceError && (
                      <div
                        style={{
                          padding: '10px 12px',
                          borderRadius: 12,
                          background: 'rgba(255, 71, 87, 0.08)',
                          border: '1px solid rgba(255, 71, 87, 0.16)',
                          color: '#b42318',
                          fontSize: '0.82rem',
                          lineHeight: 1.5,
                        }}
                      >
                        {newSourceError}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={createSourceInline}
                        disabled={
                          isCreatingSource ||
                          (TERM_SOURCE_TYPES.has(newSourceDraft.source_type)
                            ? !newSourceDraft.name.trim()
                            : !newSourceDraft.url.trim())
                        }
                        style={{ minWidth: 160 }}
                      >
                        {isCreatingSource ? (
                          <>
                            <RefreshCw size={16} className="spin" /> Creating...
                          </>
                        ) : (
                          <>
                            <Plus size={16} /> Create source
                          </>
                        )}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => {
                          setShowNewSourceForm(false);
                          setNewSourceDraft(emptyNewSourceDraft);
                          setNewSourceError('');
                        }}
                        disabled={isCreatingSource}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                <div className="assign-sources-list">
                  {assignableSources.length === 0 ? (
                    <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
                      No sources yet. Add sources first, then attach them to projects.
                    </div>
                  ) : visibleSourcesForActiveTab.length === 0 ? (
                    <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                      <div className="admin-empty-state-icon" style={{ width: 36, height: 36 }}>
                        <Search size={16} />
                      </div>
                      <strong>No matching sources</strong>
                      <span>
                        {sourceAssignQuery.trim()
                          ? 'Try a different search term in this assignment box.'
                          : activeSourceTab === 'all'
                          ? 'No sources are available to assign yet.'
                          : `No ${sourceTypeLabel(activeSourceTab)} sources yet. Switch tabs or add one below.`}
                      </span>
                    </div>
                  ) : (
                    visibleSourcesForActiveTab.map((source) => {
                      const sourceId = Number(source.id);
                      const isSelected = draft.source_ids.includes(sourceId);
                      const projectCount = (sourceProjectsById.get(sourceId) || []).length;
                      return (
                        <label key={source.id} className={`assign-source-item ${isSelected ? 'selected' : ''}`}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSource(source.id)}
                            disabled={isSaving}
                          />
                          <div className="assign-source-copy">
                            <div className="assign-source-topline">
                              <strong className="assign-source-name project-term-name">{source.name || source.url}</strong>
                              <span className={`panel-chip ${source.enabled ? 'success' : 'muted'}`}>
                                {source.enabled ? 'Enabled' : 'Disabled'}
                              </span>
                            </div>
                            <div className="assign-source-url">{source.url}</div>
                            <div className="assign-source-meta">
                              <span>{sourceTypeLabel(source.source_type)}</span>
                              <span>
                                {projectCount} project{projectCount === 1 ? '' : 's'}
                              </span>
                            </div>
                          </div>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="project-wizard-final-actions">
                <button className="btn-secondary wizard-btn-fixed" type="button" onClick={() => setWizardStep(STEP.schedule)} disabled={isSaving}>
                  Back
                </button>
                <button className="btn-primary wizard-btn-grow" onClick={submit} disabled={isSaving || !step1Complete || !step3Complete}>
                  {isSaving ? (
                    <>
                      <RefreshCw size={18} className="spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Plus size={18} /> {isEditRoute ? 'Update Project' : 'Create Project'}
                    </>
                  )}
                </button>
                <button className="btn-secondary wizard-btn-fixed" type="button" onClick={handleCancel}>
                  <X size={18} /> Cancel
                </button>
              </div>
            </div>
          </div>
          )}
        </div>

        <ConfirmModal
          open={showCancelModal}
          title="Discard changes?"
          message="You have unsaved changes on this project. If you cancel now, all edits on this page will be lost."
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          onClose={() => setShowCancelModal(false)}
          onConfirm={discardChanges}
        />

        <ConfirmModal
          open={showDiscoverySuccessModal}
          title="Sources prefilled with AI"
          message="AI discovery finished successfully and the sources list has been refreshed."
          confirmLabel="Done"
          hideCancel
          onClose={closeDiscoverySuccessModal}
        >
          <div style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span className="panel-chip success">
                {discoveredSources.length} source{discoveredSources.length === 1 ? '' : 's'} collected
              </span>
              <span className="panel-chip">
                {discoveredResolvedUrls.length} URL{discoveredResolvedUrls.length === 1 ? '' : 's'} resolved
              </span>
            </div>

            {discoveryPreviewItems.length > 0 ? (
              <div style={{ display: 'grid', gap: 6, maxHeight: 220, overflowY: 'auto' }}>
                {discoveryPreviewItems.map((item) => (
                  <div
                    key={item.url}
                    style={{
                      fontSize: '0.82rem',
                      padding: '8px 10px',
                      borderRadius: 10,
                      background: 'rgba(15, 23, 42, 0.04)',
                    }}
                  >
                    <strong style={{ display: 'block' }}>{item.name}</strong>
                    {item.url && item.url !== item.name && (
                      <div style={{ color: 'var(--text-light)', wordBreak: 'break-word' }}>{item.url}</div>
                    )}
                  </div>
                ))}
                {discoveredSources.length > discoveryPreviewItems.length && (
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                    +{discoveredSources.length - discoveryPreviewItems.length} more
                  </span>
                )}
              </div>
            ) : (
              <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                No new sources were collected from the X accounts, hashtags, and keywords for this project.
              </div>
            )}
          </div>
        </ConfirmModal>
      </div>
    );
  }


  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> Opinion monitoring
          </div>
          <h1 className="admin-page-title">Opinion Monitor</h1>
          <p className="admin-page-subtitle">
            Track what people are saying about each project as its own workspace, attach shared sources, and keep every scrape tied to a named project.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Status</span>
            <strong>{projects.length ? 'Configured' : 'Empty'}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Search</span>
            <strong>{visibleProjects.length.toLocaleString()} matches</strong>
          </div>
          {canEdit && (
            <Link to="/projects/new" className="btn-primary" style={{ textDecoration: 'none' }}>
              <Plus size={16} /> Add Project
            </Link>
          )}
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon">
            <Layers3 size={18} />
          </div>
          <div>
            <span>Total projects</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}>
            <Flag size={18} />
          </div>
          <div>
            <span>Active</span>
            <strong>{stats.active.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <Clock3 size={18} />
          </div>
          <div>
            <span>Draft</span>
            <strong>{stats.draftCount.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Link2 size={18} />
          </div>
          <div>
            <span>Unique sources in use</span>
            <strong>{stats.assignedSources.toLocaleString()}</strong>
          </div>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <label className="admin-search">
          <Search size={16} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects, dates, statuses, or assigned sources"
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status[0].toUpperCase() + status.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="glass-card admin-list-panel">
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>Tracked Projects</strong>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isLoadingProjects && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
            <span className="panel-chip">{visibleProjects.length} visible</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {isLoadingProjects && projects.length === 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <RefreshCw size={18} className="spin" />
              </div>
              <strong>Loading projects...</strong>
              <span>Fetching the latest project list from the workspace.</span>
            </div>
          )}

          {projects.length === 0 && !isLoadingProjects && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <CalendarDays size={18} />
              </div>
              <strong>No projects yet</strong>
              <span>Start by creating a project, then assign sources and run the scraper against that scope.</span>
              {canEdit && (
                <Link to="/projects/new" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
                  <Plus size={16} /> Add Project
                </Link>
              )}
            </div>
          )}

          {pagedProjects.map((project, index) => {
            const assignedSourceCount = Array.isArray(project.source_ids) ? project.source_ids.length : 0;
            const isActive = (project.status || '').toLowerCase() === 'active';
            return (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="admin-item-card"
              >
                <div className="admin-item-top">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <strong className="admin-item-title project-item-title">{project.name}</strong>
                      <span className={`panel-chip ${isActive ? 'success' : project.status === 'archived' ? 'muted' : 'warning'}`}>
                        {(project.status || 'draft').toUpperCase()}
                      </span>
                      {project.repeat_enabled && (
                        <span className="panel-chip success">
                          <RefreshCw size={12} /> Every {project.repeat_interval_value} {project.repeat_interval_unit}
                        </span>
                      )}
                    </div>
                    <div className="admin-item-meta">
                      <span>{project.start_date || 'No start date'}</span>
                      <span>{project.end_date || 'No end date'}</span>
                      <span>
                        {assignedSourceCount} source{assignedSourceCount === 1 ? '' : 's'}
                      </span>
                      {project.repeat_enabled && (
                        <span>Next run: {formatDateTime(project.next_run_at) || 'Pending first run'}</span>
                      )}
                      {project.last_run_at && <span>Last run: {formatDateTime(project.last_run_at)}</span>}
                    </div>
                    <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.88rem', lineHeight: 1.5, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      {project.description || 'Open the project to see assigned sources, tags, and metadata.'}
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary"
                      to={`/projects/${project.id}`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Eye size={14} /> View
                    </Link>
                  </div>
                </div>
              </motion.div>
            );
          })}

          {!isLoadingProjects && visibleProjects.length === 0 && projects.length > 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Search size={18} />
              </div>
              <strong>No matching projects</strong>
              <span>Try another search term or switch the status filter.</span>
            </div>
          )}
        </div>

        {visibleProjects.length > 0 && (
          <div
            style={{
              marginTop: 14,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 12,
              flexWrap: 'wrap',
              paddingTop: 12,
              borderTop: '1px solid rgba(15, 23, 42, 0.08)',
            }}
          >
            <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
              Showing {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visibleProjects.length)} of {visibleProjects.length}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                className="btn-secondary"
                onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
                disabled={safePage <= 1}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                Previous
              </button>
              <span className="panel-chip">
                Page {safePage} of {totalPages}
              </span>
              <button
                className="btn-secondary"
                onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
                disabled={safePage >= totalPages}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                Next
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
