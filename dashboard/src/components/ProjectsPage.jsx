import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';
import '../styles/Projects.css';
import {
  uploadDocuments as uploadProjectDocuments,
  deleteDocument as deleteProjectDocument,
  listDocumentArticles as listProjectDocumentArticles,
  setDocumentArticleStatus as setProjectDocumentArticleStatus,
  approveAllDocumentArticles as approveAllProjectDocumentArticles,
  reanalyzeDocumentArticles as reanalyzeProjectDocumentArticles,
  pollDocumentExtraction as pollProjectDocumentExtraction,
  pollArticleCandidates as pollProjectArticleCandidates,
  pollArticleAnalysis as pollProjectArticleAnalysis,
} from '../projectDocumentsApi.js';
import {
  CalendarDays,
  Eye,
  Plus,
  Check,
  X,
  Search,
  Flag,
  Layers3,
  RefreshCw,
  Sparkles,
  Users,
  FileText,
  Upload,
  FileCheck,
  ListChecks,
  ScanText,
  AlertTriangle,
} from 'lucide-react';

const emptyDraft = {
  name: '',
  status: 'draft',
  description: '',
  location: '',
  location_type: '',
  target_audience: '',
  keywords: [],
  start_date: '',
  end_date: '',
  user_ids: [],
};

const STATUS_OPTIONS = ['draft', 'active', 'archived'];
const LOCATION_TYPE_OPTIONS = [
  { value: 'on_site', label: 'On site' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
];
const PAGE_SIZE = 10;

function formatDateTime(value) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

function toDateInput(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toISOString().slice(0, 10);
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

function ErrorBanner({ message }) {
  if (!message) return null;
  return (
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
      {message}
    </div>
  );
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
  users = [],
  onCreateProject,
  onUpdateProject,
  isLoadingProjects,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('projects.create') || hasPermission('projects.update') || hasPermission('projects.delete');
  const canLinkUsers = hasPermission('projects.link_users');
  // A project is built from uploaded documents, so there is one flow: describe
  // it, choose who can see it, upload the files, review what the model split
  // out of them, finish. The project row itself is created as soon as basics
  // are done (see ensureProject) because documents need a project_id to attach
  // to well before the wizard ends.
  const STEP = useMemo(() => {
    const keys = ['basics', ...(canLinkUsers ? ['users'] : []), 'upload', 'review', 'finish'];
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
  const [currentPage, setCurrentPage] = useState(1);
  const [userAssignQuery, setUserAssignQuery] = useState('');
  const [initialDraft, setInitialDraft] = useState(emptyDraft);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [isGeneratingMetadata, setIsGeneratingMetadata] = useState(false);
  // Id of the project currently loaded into the draft - lets the reset effect
  // below tell "switched to a different project" apart from "the same
  // project's array reference changed" (a projects refetch mid-wizard), which
  // would otherwise wipe in-progress edits and kick the wizard back to step 1.
  const loadedProjectIdRef = useRef(null);
  const [metadataError, setMetadataError] = useState('');

  // --- Document pipeline state ---------------------------------------------
  const [offlineProjectId, setOfflineProjectId] = useState(null);
  const [isCreatingOfflineProject, setIsCreatingOfflineProject] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [uploadingDocs, setUploadingDocs] = useState(false);
  const [extractingDocs, setExtractingDocs] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const fileInputRef = useRef(null);
  const documentsRef = useRef(documents);
  useEffect(() => {
    documentsRef.current = documents;
  }, [documents]);
  const [articleCandidates, setArticleCandidates] = useState([]);
  const [reviewingArticles, setReviewingArticles] = useState(false);
  const [decidingCandidate, setDecidingCandidate] = useState({});
  const [approvingAll, setApprovingAll] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);

  const resetOfflinePipelineState = () => {
    setOfflineProjectId(null);
    setIsCreatingOfflineProject(false);
    setDocuments([]);
    setPendingFiles([]);
    setUploadingDocs(false);
    setExtractingDocs(false);
    setDropActive(false);
    setArticleCandidates([]);
    setReviewingArticles(false);
    setDecidingCandidate({});
    setApprovingAll(false);
    setReanalyzing(false);
  };

  const documentById = useMemo(() => new Map(documents.map((document) => [document.id, document])), [documents]);
  const candidatesByDocument = useMemo(() => {
    const map = new Map();
    articleCandidates.forEach((candidate) => {
      if (!map.has(candidate.document_id)) map.set(candidate.document_id, []);
      map.get(candidate.document_id).push(candidate);
    });
    return Array.from(map.entries());
  }, [articleCandidates]);
  const pendingCandidateCount = useMemo(
    () => articleCandidates.filter((candidate) => candidate.status === 'pending').length,
    [articleCandidates]
  );
  const approvedCandidateCount = useMemo(
    () => articleCandidates.filter((candidate) => candidate.status === 'approved').length,
    [articleCandidates]
  );
  const analyzedCandidateCount = useMemo(
    () =>
      articleCandidates.filter((candidate) => candidate.status === 'approved' && candidate.article_analysis_status === 'success')
        .length,
    [articleCandidates]
  );
  const failedAnalysisCandidateCount = useMemo(
    () =>
      articleCandidates.filter((candidate) => candidate.status === 'approved' && candidate.article_analysis_status === 'failed')
        .length,
    [articleCandidates]
  );

  const stats = useMemo(() => {
    const total = projects.length;
    const active = projects.filter((project) => (project.status || '').toLowerCase() === 'active').length;
    const draftCount = projects.filter((project) => (project.status || '').toLowerCase() === 'draft').length;
    const archived = projects.filter((project) => (project.status || '').toLowerCase() === 'archived').length;
    return { total, active, draftCount, archived };
  }, [projects]);

  const visibleProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      const keywordNames = (project.keywords || []).map((value) => String(value).trim()).filter(Boolean);
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
          ...keywordNames,
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
      setInitialDraft(emptyDraft);
      setShowCancelModal(false);
      setWizardStep(1);
      setIsGeneratingMetadata(false);
      setMetadataError('');
      resetOfflinePipelineState();
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
        keywords: sanitizeTermArray(currentProject.keywords),
        start_date: toDateInput(currentProject.start_date),
        end_date: toDateInput(currentProject.end_date),
        user_ids: Array.isArray(currentProject.user_ids) ? currentProject.user_ids.map(Number) : [],
      };
      setDraft(draftFromProject);
      setUserAssignQuery('');
      setInitialDraft(draftFromProject);
      resetOfflinePipelineState();
      // The project already exists, so the document steps act on it directly
      // instead of waiting for ensureProject() to create one.
      setOfflineProjectId(Number(currentProject.id));
      setWizardStep(STEP.basics);
      setIsGeneratingMetadata(false);
      setMetadataError('');
      return;
    }

    loadedProjectIdRef.current = null;
    setDraft(emptyDraft);
    setUserAssignQuery('');
    setInitialDraft(emptyDraft);
    setWizardStep(1);
    setIsGeneratingMetadata(false);
    setMetadataError('');
    resetOfflinePipelineState();
  }, [currentProject, isEditRoute, isFormRoute, editingId, STEP.basics]);

  const discardChanges = () => {
    setShowCancelModal(false);
    setUserAssignQuery('');
    setDraft(emptyDraft);
    navigate('/projects');
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

  // --- Document pipeline handlers -------------------------------------------

  // Creates the project as soon as the user leaves the basics step - documents
  // need a real project_id to attach to before the wizard reaches its final
  // step (mirrors CompetitorOnboarding's ensureStudy()). Idempotent: once
  // offlineProjectId is set - including when editing an existing project -
  // later calls just return it.
  const ensureOfflineProject = async () => {
    if (offlineProjectId) return offlineProjectId;
    if (isCreatingOfflineProject) return null;
    if (!draft.name.trim()) return null;

    setIsCreatingOfflineProject(true);
    setMetadataError('');
    try {
      const payload = {
        name: draft.name.trim(),
        status: draft.status,
        description: draft.description.trim(),
        location: draft.location.trim(),
        location_type: draft.location_type || null,
        target_audience: draft.target_audience.trim(),
        keywords: sanitizeTermArray(draft.keywords),
        start_date: draft.start_date || null,
        end_date: draft.end_date || null,
        ...(canLinkUsers ? { user_ids: draft.user_ids } : {}),
      };
      const created = await onCreateProject?.(payload);
      const createdId = Number(created?.project?.id);
      if (!Number.isFinite(createdId)) {
        throw new Error('Could not create the project.');
      }
      setOfflineProjectId(createdId);
      return createdId;
    } catch (error) {
      setMetadataError(error?.message || 'Failed to create the project.');
      return null;
    } finally {
      setIsCreatingOfflineProject(false);
    }
  };

  const addPendingFiles = (fileList) => {
    const incoming = Array.from(fileList || []);
    if (incoming.length) setPendingFiles((prev) => [...prev, ...incoming]);
  };

  const removePendingFile = (index) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const removeDocument = async (documentId) => {
    try {
      await deleteProjectDocument(documentId);
      setDocuments((prev) => prev.filter((document) => document.id !== documentId));
    } catch (error) {
      setMetadataError(error?.message || 'Failed to remove the document.');
    }
  };

  const refreshArticleCandidates = async (projectId) => {
    const result = await listProjectDocumentArticles(projectId);
    setArticleCandidates(result.articles || []);
  };

  // Watches approved-but-not-yet-analyzed candidates until sentiment analysis
  // finishes for all of them - fire-and-forget, since neither review nor
  // finish gates on analysis completing (matches CompetitorOnboarding's
  // "Open workspace" being clickable regardless of analysis state).
  const watchArticleAnalysis = (projectId) => {
    pollProjectArticleAnalysis(projectId, setArticleCandidates).catch(() => {});
  };

  const uploadPendingDocuments = async () => {
    if (!pendingFiles.length) return;
    setMetadataError('');
    setUploadingDocs(true);
    let id;
    let uploadedIds;
    try {
      id = await ensureOfflineProject();
      if (!id) throw new Error('Could not create the project.');
      const result = await uploadProjectDocuments(id, pendingFiles);
      uploadedIds = (result.documents || []).map((document) => document.id);
      setPendingFiles([]);
    } catch (error) {
      setMetadataError(error?.message || 'Failed to upload documents.');
      setUploadingDocs(false);
      return;
    }
    setUploadingDocs(false);
    if (!uploadedIds.length) return;

    setExtractingDocs(true);
    try {
      await pollProjectDocumentExtraction(id, uploadedIds, setDocuments);
      await pollProjectArticleCandidates(id, uploadedIds, setDocuments);
      await refreshArticleCandidates(id);
    } catch (error) {
      setMetadataError(error?.message || 'Failed to process the uploaded documents.');
    } finally {
      setExtractingDocs(false);
    }
  };

  const decideCandidate = async (candidateId, status) => {
    setDecidingCandidate((prev) => ({ ...prev, [candidateId]: true }));
    try {
      const result = await setProjectDocumentArticleStatus(candidateId, status);
      setArticleCandidates((prev) => prev.map((candidate) => (candidate.id === candidateId ? result.article : candidate)));
      if (status === 'approved' && offlineProjectId) watchArticleAnalysis(offlineProjectId);
    } catch (error) {
      setMetadataError(error?.message || 'Failed to update the article.');
    } finally {
      setDecidingCandidate((prev) => ({ ...prev, [candidateId]: false }));
    }
  };

  const approveAllPending = async () => {
    if (!offlineProjectId) return;
    setMetadataError('');
    setApprovingAll(true);
    try {
      await approveAllProjectDocumentArticles(offlineProjectId);
      await refreshArticleCandidates(offlineProjectId);
      watchArticleAnalysis(offlineProjectId);
    } catch (error) {
      setMetadataError(error?.message || 'Failed to approve the articles.');
    } finally {
      setApprovingAll(false);
    }
  };

  // Starts a tracked analysis run, then keeps polling the candidates so the
  // per-article status on this step updates as the run works through them -
  // the run itself is watchable in full on the Analysis Runs page.
  const rerunFailedAnalysis = async () => {
    if (!offlineProjectId) return;
    setMetadataError('');
    setReanalyzing(true);
    try {
      await reanalyzeProjectDocumentArticles(offlineProjectId);
      await pollProjectArticleAnalysis(offlineProjectId, setArticleCandidates);
    } catch (error) {
      setMetadataError(error?.message || 'Failed to re-run analysis.');
    } finally {
      setReanalyzing(false);
    }
  };

  // Resumes extraction/splitting polling when the review step is (re)entered
  // (e.g. the user navigated away mid-poll) and always refreshes the
  // candidate list once. Reads documentsRef rather than documents so this
  // only depends on step/mode/project - not on every document-list update,
  // which would otherwise restart the poll loop repeatedly.
  useEffect(() => {
    if (wizardStep !== STEP.review || !offlineProjectId) return;
    let cancelled = false;
    const stillPendingIds = (documentsRef.current || [])
      .filter((document) => document.articles_status === 'pending' || document.articles_status === 'generating')
      .map((document) => document.id);

    (async () => {
      if (stillPendingIds.length) {
        setReviewingArticles(true);
        try {
          await pollProjectArticleCandidates(offlineProjectId, stillPendingIds, (docs) => {
            if (!cancelled) setDocuments(docs);
          });
        } finally {
          if (!cancelled) setReviewingArticles(false);
        }
      }
      if (!cancelled) await refreshArticleCandidates(offlineProjectId);
    })();

    return () => {
      cancelled = true;
    };
  }, [wizardStep, offlineProjectId, STEP.review]);

  // Refreshes analysis status (and resumes watching it) whenever the review
  // or finish step is entered - cheap even when nothing is active, since
  // pollProjectArticleAnalysis returns after a single list call in that case.
  useEffect(() => {
    if (!offlineProjectId) return;
    if (wizardStep !== STEP.review && wizardStep !== STEP.finish) return;
    let cancelled = false;
    pollProjectArticleAnalysis(offlineProjectId, (list) => {
      if (!cancelled) setArticleCandidates(list);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [wizardStep, offlineProjectId, STEP.review, STEP.finish]);

  const finishOffline = async () => {
    if (isSaving || !offlineProjectId) return;
    setIsSaving(true);
    setMetadataError('');
    try {
      const payload = {
        name: draft.name.trim(),
        status: draft.status,
        description: draft.description.trim(),
        location: draft.location.trim(),
        location_type: draft.location_type || null,
        target_audience: draft.target_audience.trim(),
        keywords: sanitizeTermArray(draft.keywords),
        start_date: draft.start_date || null,
        end_date: draft.end_date || null,
        ...(canLinkUsers ? { user_ids: draft.user_ids } : {}),
      };
      await onUpdateProject?.(offlineProjectId, payload);
      navigate(`/projects/${offlineProjectId}`);
    } catch (error) {
      setMetadataError(error?.message || 'Failed to finish the project.');
    } finally {
      setIsSaving(false);
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
        throw new Error(data?.detail || data?.error || `Failed to generate suggestions (${res.status})`);
      }

      const suggestions = data?.suggestions || {};
      setDraft((prev) => ({
        ...prev,
        target_audience: suggestions.target_audience || prev.target_audience,
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
    const totalSteps = Object.keys(STEP).length;
    const stepMeta = {
      basics: { label: 'Project basics', detail: 'Name, description, and topics', complete: step1Complete },
      users: { label: 'Linked users', detail: 'Choose dashboard users to link', complete: true },
      upload: { label: 'Upload documents', detail: 'Add the files to analyze', complete: documents.length > 0 },
      review: { label: 'Review articles', detail: 'Approve what should be analyzed', complete: true },
      finish: { label: 'Finish', detail: 'Review analysis and open workspace', complete: true },
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
              <span>Documents</span>
              <strong>{documents.length}</strong>
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

              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Target audience</span>
                <input
                  type="text"
                  className="source-input"
                  placeholder="Who this project is about"
                  value={draft.target_audience}
                  onChange={(e) => setDraft((prev) => ({ ...prev, target_audience: e.target.value }))}
                  disabled={isSaving}
                />
              </label>

              <TermChipsField
                label="Topics of interest"
                placeholder="Keyword or phrase (e.g. delivery times)"
                values={draft.keywords}
                onChange={(values) => setDraft((prev) => ({ ...prev, keywords: values }))}
                disabled={isSaving}
                hint="Reports charts how often each of these shows up across this project's analyzed articles."
              />

              <div>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => { generateMetadataFromAi().catch(() => {}); }}
                  disabled={!step1Complete || isSaving || isGeneratingMetadata}
                  style={{ padding: '8px 12px', fontSize: '0.82rem' }}
                >
                  {isGeneratingMetadata ? (
                    <>
                      <RefreshCw size={15} className="spin" /> Suggesting...
                    </>
                  ) : (
                    <>
                      <Sparkles size={15} /> Suggest audience and topics
                    </>
                  )}
                </button>
              </div>

              <ErrorBanner message={metadataError} />

              <div className="project-wizard-nav-row">
                <span style={{ color: 'var(--text-light)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                  Use a clear working title and a short description. They tell the model what this project is about when it
                  analyzes the documents you upload next.
                </span>
                <div className="project-wizard-nav-actions">
                  <button
                    type="button"
                    className="btn-primary wizard-btn-continue"
                    onClick={async () => {
                      if (STEP.users) {
                        setWizardStep(STEP.users);
                        return;
                      }
                      const id = await ensureOfflineProject();
                      if (id) setWizardStep(STEP.upload);
                    }}
                    disabled={!step1Complete || isSaving || isCreatingOfflineProject}
                  >
                    {isCreatingOfflineProject ? (
                      <>
                        <RefreshCw size={16} className="spin" /> Creating project...
                      </>
                    ) : (
                      'Continue'
                    )}
                  </button>
                </div>
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
                  onClick={async () => {
                    const id = await ensureOfflineProject();
                    if (id) setWizardStep(STEP.upload);
                  }}
                  disabled={isSaving || isCreatingOfflineProject}
                >
                  {isCreatingOfflineProject ? (
                    <>
                      <RefreshCw size={16} className="spin" /> Creating project...
                    </>
                  ) : (
                    'Continue'
                  )}
                </button>
              </div>
            </div>
          </div>
          )}

          {wizardStep === STEP.upload && (
          <div className="glass-card project-wizard-panel">
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.upload}. Upload documents</strong>
              <span className="panel-chip">{documents.length} uploaded</span>
            </div>

            <ErrorBanner message={metadataError} />

            <div
              className={`proj-dropzone${dropActive ? ' proj-dropzone-active' : ''}`}
              style={{ marginTop: 12 }}
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                setDropActive(true);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDropActive(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                setDropActive(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setDropActive(false);
                addPendingFiles(e.dataTransfer.files);
              }}
            >
              <div className="proj-dropzone-icon">
                <Upload size={20} />
              </div>
              <div className="proj-dropzone-title">Drag files here, or click to browse</div>
              <div className="proj-dropzone-hint">Multiple files at once are fine</div>
              <div className="proj-dropzone-types">
                {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG'].map((ext) => (
                  <span key={ext} className="panel-chip muted">
                    {ext}
                  </span>
                ))}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg"
                className="proj-sr-only"
                onChange={(e) => {
                  addPendingFiles(e.target.files);
                  e.target.value = '';
                }}
              />
            </div>

            {pendingFiles.length > 0 && (
              <div className="proj-rows" style={{ marginTop: 14 }}>
                {pendingFiles.map((file, index) => (
                  <div key={`${file.name}-${index}`} className="proj-row">
                    <div className="proj-row-main">
                      <span className="proj-row-name">{file.name}</span>
                      <span className="proj-row-desc">{(file.size / 1024).toFixed(0)} KB</span>
                    </div>
                    <div className="proj-row-side">
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                        onClick={() => removePendingFile(index)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-primary"
                  onClick={uploadPendingDocuments}
                  disabled={uploadingDocs || !draft.name.trim()}
                  style={{ alignSelf: 'flex-start' }}
                >
                  {uploadingDocs ? (
                    <>
                      <RefreshCw size={16} className="spin" /> Uploading...
                    </>
                  ) : (
                    `Upload ${pendingFiles.length} file${pendingFiles.length === 1 ? '' : 's'}`
                  )}
                </button>
              </div>
            )}

            {documents.length > 0 ? (
              <div className="proj-rows" style={{ marginTop: 14 }}>
                {documents.map((document) => {
                  const active = document.status === 'uploaded' || document.status === 'processing';
                  return (
                    <div key={document.id} className="proj-row">
                      <div className="proj-row-main">
                        <span className="proj-row-name">{document.original_filename}</span>
                        {document.extraction_error && (
                          <span className="proj-row-desc" style={{ color: '#b42318', display: 'flex', alignItems: 'center', gap: 4 }}>
                            <AlertTriangle size={12} /> {document.extraction_error}
                          </span>
                        )}
                      </div>
                      <div className="proj-row-side">
                        {active ? (
                          <span className="panel-chip warning" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                            <RefreshCw size={12} className="spin" />
                            Reading
                            {document.total_chunks ? ` (${document.processed_chunks || 0}/${document.total_chunks})` : ''}
                            {extractingDocs ? ' — reading contents...' : ''}
                          </span>
                        ) : document.status === 'failed' ? (
                          <span className="panel-chip">Not extracted</span>
                        ) : (
                          <span className="panel-chip success">
                            {document.extraction_method === 'ocr'
                              ? 'Extracted (OCR)'
                              : document.extraction_method === 'mixed'
                              ? 'Extracted (mixed)'
                              : 'Extracted'}
                          </span>
                        )}
                        <button
                          type="button"
                          className="btn-secondary"
                          style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                          onClick={() => removeDocument(document.id)}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : pendingFiles.length === 0 ? (
              <div className="admin-empty-state" style={{ padding: '16px 10px', marginTop: 14 }}>
                <div className="admin-empty-state-icon">
                  <Upload size={18} />
                </div>
                <strong>No documents yet</strong>
                <span>Drop files above or click to browse.</span>
              </div>
            ) : null}

            <div className="project-wizard-nav-row" style={{ marginTop: 16 }}>
              <button type="button" className="btn-secondary wizard-btn-back" onClick={() => setWizardStep(STEP.users || STEP.basics)} disabled={uploadingDocs}>
                Back
              </button>
              <button
                type="button"
                className="btn-primary wizard-btn-continue"
                onClick={() => setWizardStep(STEP.review)}
                disabled={!documents.length || uploadingDocs}
              >
                Continue to review articles
              </button>
            </div>
          </div>
          )}

          {wizardStep === STEP.review && (
          <div className="glass-card project-wizard-panel">
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.review}. Review articles</strong>
              <span className="panel-chip">
                {approvedCandidateCount} approved, {pendingCandidateCount} pending
              </span>
            </div>
            <p style={{ color: 'var(--text-light)', fontSize: '0.85rem', marginTop: 0, marginBottom: 14, lineHeight: 1.5 }}>
              Strata split your documents into individual articles. Approve the ones worth
              analyzing — approving queues sentiment analysis for it.
            </p>

            <ErrorBanner message={metadataError} />

            {reviewingArticles ? (
              <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                <div className="admin-empty-state-icon">
                  <RefreshCw size={18} className="spin" />
                </div>
                <strong>Reading your documents into articles...</strong>
              </div>
            ) : articleCandidates.length === 0 ? (
              <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                <div className="admin-empty-state-icon">
                  <FileCheck size={18} />
                </div>
                <strong>No articles yet</strong>
                <span>
                  {documents.some((document) => document.articles_status === 'failed')
                    ? 'Splitting failed for at least one document — try re-uploading it.'
                    : 'Go back and upload a document to get started.'}
                </span>
              </div>
            ) : (
              <>
                <div className="project-wizard-nav-row" style={{ marginBottom: 12 }}>
                  <span style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
                    {approvedCandidateCount} approved, {pendingCandidateCount} pending review
                  </span>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={approveAllPending}
                    disabled={approvingAll || !pendingCandidateCount}
                  >
                    {approvingAll ? (
                      <>
                        <RefreshCw size={16} className="spin" /> Approving...
                      </>
                    ) : (
                      <>
                        <ListChecks size={16} /> Approve all{pendingCandidateCount ? ` (${pendingCandidateCount})` : ''}
                      </>
                    )}
                  </button>
                </div>

                {candidatesByDocument.map(([documentId, candidates]) => (
                  <div key={documentId} style={{ marginBottom: 14 }}>
                    <div
                      style={{
                        fontSize: '0.74rem',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        color: 'var(--text-light)',
                        marginBottom: 8,
                      }}
                    >
                      {documentById.get(documentId)?.original_filename || 'Document'}
                    </div>
                    <div className="proj-rows">
                      {candidates.map((candidate) => (
                        <div key={candidate.id} className="proj-row" style={{ alignItems: 'flex-start' }}>
                          <div className="proj-row-main">
                            <span className="proj-row-name">{candidate.title}</span>
                            {candidate.summary && <span className="proj-row-desc">{candidate.summary}</span>}
                            {candidate.status === 'approved' && (
                              <span style={{ marginTop: 2 }}>
                                {candidate.article_analysis_status === 'success' ? (
                                  <span className="panel-chip success">Analyzed</span>
                                ) : candidate.article_analysis_status === 'failed' ? (
                                  <span className="panel-chip">Analysis failed</span>
                                ) : (
                                  <span className="panel-chip warning" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                                    <RefreshCw size={11} className="spin" /> Analyzing...
                                  </span>
                                )}
                              </span>
                            )}
                          </div>
                          <div className="proj-row-side">
                            {candidate.status === 'approved' ? (
                              <span className="panel-chip success">Approved</span>
                            ) : candidate.status === 'rejected' ? (
                              <span className="panel-chip">Rejected</span>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  className="btn-secondary"
                                  style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                                  onClick={() => decideCandidate(candidate.id, 'rejected')}
                                  disabled={Boolean(decidingCandidate[candidate.id])}
                                >
                                  Reject
                                </button>
                                <button
                                  type="button"
                                  className="btn-primary"
                                  style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                                  onClick={() => decideCandidate(candidate.id, 'approved')}
                                  disabled={Boolean(decidingCandidate[candidate.id])}
                                >
                                  {decidingCandidate[candidate.id] ? <RefreshCw size={13} className="spin" /> : 'Approve'}
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </>
            )}

            <div className="project-wizard-nav-row" style={{ marginTop: 16 }}>
              <button
                type="button"
                className="btn-secondary wizard-btn-back"
                onClick={() => setWizardStep(STEP.upload)}
                disabled={reviewingArticles}
              >
                Back
              </button>
              <button
                type="button"
                className="btn-primary wizard-btn-continue"
                onClick={() => setWizardStep(STEP.finish)}
                disabled={reviewingArticles}
              >
                Continue to finish
              </button>
            </div>
          </div>
          )}

          {wizardStep === STEP.finish && (
          <div className="glass-card project-wizard-panel">
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step {STEP.finish}. Finish</strong>
            </div>
            <p style={{ color: 'var(--text-light)', fontSize: '0.85rem', marginTop: 0, marginBottom: 14, lineHeight: 1.5 }}>
              {documents.length} document{documents.length === 1 ? '' : 's'} uploaded,{' '}
              {approvedCandidateCount} article{approvedCandidateCount === 1 ? '' : 's'} approved.
              {analyzedCandidateCount > 0 ? ` ${analyzedCandidateCount} analyzed.` : ''}
              {failedAnalysisCandidateCount > 0 ? ` ${failedAnalysisCandidateCount} failed to analyze.` : ''}
            </p>

            <ErrorBanner message={metadataError} />

            {failedAnalysisCandidateCount > 0 && (
              <button
                type="button"
                className="btn-secondary"
                onClick={rerunFailedAnalysis}
                disabled={reanalyzing}
                style={{ marginBottom: 14 }}
              >
                {reanalyzing ? (
                  <>
                    <RefreshCw size={16} className="spin" /> Re-running...
                  </>
                ) : (
                  <>
                    <ScanText size={16} /> Re-run analysis
                  </>
                )}
              </button>
            )}

            <div className="project-wizard-final-actions">
              <button
                className="btn-secondary wizard-btn-fixed"
                type="button"
                onClick={() => setWizardStep(STEP.review)}
                disabled={isSaving}
              >
                Back
              </button>
              <button className="btn-primary wizard-btn-grow" onClick={finishOffline} disabled={isSaving}>
                {isSaving ? (
                  <>
                    <RefreshCw size={18} className="spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Check size={18} /> Open workspace
                  </>
                )}
              </button>
              <button className="btn-secondary wizard-btn-fixed" type="button" onClick={handleCancel}>
                <X size={18} /> Cancel
              </button>
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
            Track what people are saying about each project as its own workspace: upload the documents it covers, approve the articles they hold, and keep every analysis tied to a named project.
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
            <FileText size={18} />
          </div>
          <div>
            <span>Draft</span>
            <strong>{stats.draftCount.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Layers3 size={18} />
          </div>
          <div>
            <span>Archived</span>
            <strong>{stats.archived.toLocaleString()}</strong>
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
            placeholder="Search projects, dates, statuses, or keywords"
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
              <span>Start by creating a project, then upload the documents it should analyze.</span>
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
