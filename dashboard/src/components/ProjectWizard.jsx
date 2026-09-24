import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ConfirmModal from './ConfirmModal';
import ErrorBanner from './project-wizard/ErrorBanner.jsx';
import TermChipsField from './project-wizard/TermChipsField.jsx';
import UserAssignField from './project-wizard/UserAssignField.jsx';
import { useAuth } from '../auth/useAuth.js';
import { translateApiError } from '../lib/apiError.js';
import { formatNumber } from '../lib/i18nFormat.js';
import { emptyDraft, LOCATION_TYPE_OPTIONS, sanitizeTermArray, normalizeDraftForCompare, toDateInput } from '../lib/projectHelpers.js';
import { getPageNumbers } from '../lib/articleHelpers.jsx';
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
} from '../api/projectDocumentsApi.js';
import { suggestProjectMetadata } from '../api/projectsApi.js';
import {
  CalendarDays,
  Check,
  X,
  RefreshCw,
  Sparkles,
  Upload,
  FileCheck,
  ListChecks,
  ScanText,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

// Article candidates are already fetched in full for the project, so review-step
// pagination just slices the in-memory list - no extra API calls needed.
const CANDIDATES_PAGE_SIZE = 10;

// The project create/edit flow, extracted out of ProjectsPage.jsx: a project
// is built from uploaded documents, so there is one wizard - describe it,
// choose who can see it, upload the files, review what the model split out
// of them, finish. Mounted only on /projects/new and /projects/:id/edit, so
// (unlike when this lived inside ProjectsPage) it owns its own routing hooks
// and can assume every render is a wizard render - no isFormRoute branch.
export default function ProjectWizard({ projects = [], users = [], onCreateProject, onUpdateProject }) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const { t, i18n } = useTranslation(['projects', 'documents']);
  const { t: tErrors } = useTranslation('errors');
  const locale = i18n.language;
  const locationTypeLabels = {
    on_site: t('shared.locationTypeLabels.on_site'),
    remote: t('shared.locationTypeLabels.remote'),
    hybrid: t('shared.locationTypeLabels.hybrid'),
  };
  const { hasPermission } = useAuth();
  const canLinkUsers = hasPermission('projects.link_users');
  const STEP = useMemo(() => {
    const keys = ['basics', ...(canLinkUsers ? ['users'] : []), 'upload', 'review', 'finish'];
    return Object.fromEntries(keys.map((key, index) => [key, index + 1]));
  }, [canLinkUsers]);
  const isEditRoute = location.pathname.endsWith('/edit');
  const editingId = isEditRoute ? Number(params.projectId) : null;
  const currentProject = useMemo(
    () => (editingId != null ? projects.find((project) => Number(project.id) === Number(editingId)) || null : null),
    [editingId, projects]
  );

  const [draft, setDraft] = useState(emptyDraft);
  const [isSaving, setIsSaving] = useState(false);
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
  const [publisherUrl, setPublisherUrl] = useState('');
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
    setPublisherUrl('');
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
  // Grouped-by-document order (not raw articleCandidates order) so a page's
  // slice never interleaves two documents' rows.
  const orderedCandidates = useMemo(
    () => candidatesByDocument.flatMap(([, candidates]) => candidates),
    [candidatesByDocument]
  );
  const [candidatesPage, setCandidatesPage] = useState(1);
  const totalCandidatePages = Math.max(1, Math.ceil(orderedCandidates.length / CANDIDATES_PAGE_SIZE));
  useEffect(() => {
    setCandidatesPage((prev) => Math.min(prev, totalCandidatePages));
  }, [totalCandidatePages]);
  const candidatePageNumbers = useMemo(
    () => getPageNumbers(candidatesPage, totalCandidatePages),
    [candidatesPage, totalCandidatePages]
  );
  const pagedCandidatesByDocument = useMemo(() => {
    const start = (candidatesPage - 1) * CANDIDATES_PAGE_SIZE;
    const pageCandidates = orderedCandidates.slice(start, start + CANDIDATES_PAGE_SIZE);
    const map = new Map();
    pageCandidates.forEach((candidate) => {
      if (!map.has(candidate.document_id)) map.set(candidate.document_id, []);
      map.get(candidate.document_id).push(candidate);
    });
    return Array.from(map.entries());
  }, [orderedCandidates, candidatesPage]);
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

  useEffect(() => {
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
  }, [currentProject, isEditRoute, editingId, STEP.basics]);

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
        throw new Error(t('wizard.errors.createProjectFailed'));
      }
      setOfflineProjectId(createdId);
      return createdId;
    } catch (error) {
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('wizard.errors.createProjectFailed')));
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('documents:wizard.errors.removeDocumentFailed')));
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
      if (!id) throw new Error(t('wizard.errors.createProjectFailed'));
      const result = await uploadProjectDocuments(id, pendingFiles, publisherUrl);
      uploadedIds = (result.documents || []).map((document) => document.id);
      setPendingFiles([]);
      setPublisherUrl('');
    } catch (error) {
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('documents:wizard.errors.uploadFailed')));
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('documents:wizard.errors.processFailed')));
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('documents:wizard.errors.updateArticleFailed')));
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('documents:wizard.errors.approveAllFailed')));
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('documents:wizard.errors.reanalyzeFailed')));
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('wizard.errors.finishProjectFailed')));
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
      const data = await suggestProjectMetadata({ name, description });
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
      setMetadataError(error?.code ? translateApiError(tErrors, error) : (error?.message || t('wizard.errors.suggestFailed')));
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

  const heading = isEditRoute ? t('wizard.heading.edit') : t('wizard.heading.create');
  const step1Complete = Boolean(draft.name.trim() && draft.description.trim());
  const totalSteps = Object.keys(STEP).length;
  const stepMeta = {
    basics: { label: t('wizard.stepNav.basics.label'), detail: t('wizard.stepNav.basics.detail'), complete: step1Complete },
    users: { label: t('wizard.stepNav.users.label'), detail: t('wizard.stepNav.users.detail'), complete: true },
    upload: { label: t('documents:wizard.stepNav.upload.label'), detail: t('documents:wizard.stepNav.upload.detail'), complete: true },
    review: { label: t('documents:wizard.stepNav.review.label'), detail: t('documents:wizard.stepNav.review.detail'), complete: true },
    finish: { label: t('wizard.stepNav.finish.label'), detail: t('wizard.stepNav.finish.detail'), complete: true },
  };
  const stepOrder = Object.keys(STEP).sort((a, b) => STEP[a] - STEP[b]);

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> {t('shared.opinionMonitoringKicker')}
          </div>
          <h1 className="admin-page-title">{heading}</h1>
          <p className="admin-page-subtitle">
            {isEditRoute
              ? t('wizard.subheading.edit', { steps: totalSteps })
              : t('wizard.subheading.create', { steps: totalSteps })}
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('wizard.toolbar.stepLabel')}</span>
            <strong>{t('wizard.toolbar.stepOfTotal', { step: wizardStep, total: totalSteps })}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>{t('wizard.toolbar.documentsLabel')}</span>
            <strong>{formatNumber(documents.length, locale)}</strong>
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
                  {done ? t('wizard.stepNav.done') : `0${step}`}
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
            <strong style={{ fontSize: '1rem' }}>{t('wizard.basics.stepHeading', { step: STEP.basics })}</strong>
            <span className="panel-chip">{step1Complete ? t('wizard.basics.readyChip') : t('wizard.basics.requiredChip')}</span>
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>{t('wizard.basics.nameLabel')}</span>
              <input
                type="text"
                className="source-input"
                placeholder={t('wizard.basics.nameLabel')}
                value={draft.name}
                onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                disabled={isSaving}
                dir="auto"
              />
            </label>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>{t('wizard.basics.descriptionLabel')}</span>
              <textarea
                className="source-input"
                placeholder={t('wizard.basics.descriptionPlaceholder')}
                rows={4}
                value={draft.description}
                onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
                style={{ resize: 'vertical', minHeight: 110 }}
                disabled={isSaving}
                dir="auto"
              />
            </label>

            <div className="form-row-location">
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>{t('wizard.basics.locationTypeLabel')}</span>
                <select
                  className="filter-select"
                  value={draft.location_type}
                  onChange={(e) => setDraft((prev) => ({ ...prev, location_type: e.target.value }))}
                  disabled={isSaving}
                >
                  <option value="">{t('wizard.basics.selectPlaceholder')}</option>
                  {LOCATION_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {locationTypeLabels[option.value] || option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>{t('wizard.basics.locationLabel')}</span>
                <input
                  type="text"
                  className="source-input"
                  placeholder={t('wizard.basics.locationPlaceholder')}
                  value={draft.location}
                  onChange={(e) => setDraft((prev) => ({ ...prev, location: e.target.value }))}
                  disabled={isSaving}
                  dir="auto"
                />
              </label>
            </div>

            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>{t('wizard.basics.audienceLabel')}</span>
              <input
                type="text"
                className="source-input"
                placeholder={t('wizard.basics.audiencePlaceholder')}
                value={draft.target_audience}
                onChange={(e) => setDraft((prev) => ({ ...prev, target_audience: e.target.value }))}
                disabled={isSaving}
                dir="auto"
              />
            </label>

            <TermChipsField
              label={t('wizard.basics.keywordsLabel')}
              placeholder={t('wizard.basics.keywordsPlaceholder')}
              values={draft.keywords}
              onChange={(values) => setDraft((prev) => ({ ...prev, keywords: values }))}
              disabled={isSaving}
              hint={t('wizard.basics.keywordsHint')}
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
                    <RefreshCw size={15} className="spin" /> {t('wizard.basics.suggesting')}
                  </>
                ) : (
                  <>
                    <Sparkles size={15} /> {t('wizard.basics.suggestButton')}
                  </>
                )}
              </button>
            </div>

            <ErrorBanner message={metadataError} />

            <div className="project-wizard-nav-row">
              <span style={{ color: 'var(--text-light)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                {t('wizard.basics.footnote')}
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
                      <RefreshCw size={16} className="spin" /> {t('wizard.actions.creatingProject')}
                    </>
                  ) : (
                    t('wizard.actions.continue')
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
            <strong style={{ fontSize: '1rem' }}>{t('wizard.users.stepHeading', { step: STEP.users })}</strong>
            <span className="panel-chip">{t('wizard.users.selectedCount', { count: draft.user_ids.length, formattedCount: formatNumber(draft.user_ids.length, locale) })}</span>
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
                {t('common:actions.back')}
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
                    <RefreshCw size={16} className="spin" /> {t('wizard.actions.creatingProject')}
                  </>
                ) : (
                  t('wizard.actions.continue')
                )}
              </button>
            </div>
          </div>
        </div>
        )}

        {wizardStep === STEP.upload && (
        <div className="glass-card project-wizard-panel">
          <div className="panel-header-tight" style={{ marginBottom: 12 }}>
            <strong style={{ fontSize: '1rem' }}>{t('documents:wizard.upload.stepHeading', { step: STEP.upload })}</strong>
            <span className="panel-chip">{t('documents:wizard.upload.uploadedCount', { count: documents.length, formattedCount: formatNumber(documents.length, locale) })}</span>
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
            <div className="proj-dropzone-title">{t('documents:wizard.upload.dropzone.title')}</div>
            <div className="proj-dropzone-hint">{t('documents:wizard.upload.dropzone.hint')}</div>
            <div className="proj-dropzone-types">
              {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG', 'JSON', 'JSONL'].map((ext) => (
                <span key={ext} className="panel-chip muted">
                  {ext}
                </span>
              ))}
            </div>
            {/* A JSON/JSONL upload is already a list of articles, so it skips
                the LLM split entirely — worth saying, since it also means
                those files keep each record's own link and date. */}
            <div className="proj-dropzone-hint" style={{ marginTop: 6 }}>
              {t('documents:wizard.upload.dropzone.recordsHint')}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.json,.jsonl,.ndjson"
              className="proj-sr-only"
              onChange={(e) => {
                addPendingFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </div>

          <label style={{ display: 'grid', gap: 6, marginTop: 14 }}>
            <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>
              {t('documents:wizard.upload.publisherUrl.label')}
            </span>
            <input
              type="url"
              className="source-input"
              placeholder="https://publisher.example"
              value={publisherUrl}
              onChange={(event) => setPublisherUrl(event.target.value)}
              disabled={uploadingDocs || extractingDocs}
            />
            <span className="proj-row-desc">
              {t('documents:wizard.upload.publisherUrl.hint')}
            </span>
          </label>

          {pendingFiles.length > 0 && (
            <div className="proj-rows" style={{ marginTop: 14 }}>
              {pendingFiles.map((file, index) => (
                <div key={`${file.name}-${index}`} className="proj-row">
                  <div className="proj-row-main">
                    <span className="proj-row-name" dir="auto">{file.name}</span>
                    <span className="proj-row-desc">{t('documents:wizard.upload.pendingFile.sizeKb', { size: formatNumber((file.size / 1024).toFixed(0), locale) })}</span>
                  </div>
                  <div className="proj-row-side">
                    <button
                      type="button"
                      className="btn-secondary"
                      style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                      onClick={() => removePendingFile(index)}
                    >
                      {t('common:actions.remove')}
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
                    <RefreshCw size={16} className="spin" /> {t('documents:wizard.upload.uploadButton.uploading')}
                  </>
                ) : (
                  t('documents:wizard.upload.uploadButton.upload', { count: pendingFiles.length, formattedCount: formatNumber(pendingFiles.length, locale) })
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
                      <span className="proj-row-name" dir="auto">{document.original_filename}</span>
                      {document.publisher_url && (
                        <span className="proj-row-desc" dir="auto">{t('documents:wizard.upload.document.publisher', { url: document.publisher_url })}</span>
                      )}
                      {document.extraction_error && (
                        <span className="proj-row-desc" dir="auto" style={{ color: '#b42318', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <AlertTriangle size={12} /> {document.extraction_error}
                        </span>
                      )}
                      {/* Only a records file sets this on a *successful* read —
                          it is how a cut-off import ("first 500 of 40,000")
                          says so, which would otherwise look complete. */}
                      {document.articles_error && (
                        <span className="proj-row-desc" dir="auto" style={{ color: '#b54708', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <AlertTriangle size={12} /> {document.articles_error}
                        </span>
                      )}
                    </div>
                    <div className="proj-row-side">
                      {active ? (
                        <span className="panel-chip warning" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <RefreshCw size={12} className="spin" />
                          {t('documents:wizard.upload.document.status.reading')}
                          {document.total_chunks ? t('documents:wizard.upload.document.status.readingProgress', { processed: formatNumber(document.processed_chunks || 0, locale), total: formatNumber(document.total_chunks, locale) }) : ''}
                          {extractingDocs ? t('documents:wizard.upload.document.status.readingContentsSuffix') : ''}
                        </span>
                      ) : document.status === 'failed' ? (
                        <span className="panel-chip">{t('documents:wizard.upload.document.status.notExtracted')}</span>
                      ) : (
                        <span className="panel-chip success">
                          {document.extraction_method === 'ocr'
                            ? t('documents:wizard.upload.document.status.extractedOcr')
                            : document.extraction_method === 'mixed'
                            ? t('documents:wizard.upload.document.status.extractedMixed')
                            : t('documents:wizard.upload.document.status.extracted')}
                        </span>
                      )}
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                        onClick={() => removeDocument(document.id)}
                      >
                        {t('common:actions.remove')}
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
              <strong>{t('documents:wizard.upload.emptyTitle')}</strong>
              <span>{t('documents:wizard.upload.emptyBody')}</span>
            </div>
          ) : null}

          <div className="project-wizard-nav-row" style={{ marginTop: 16 }}>
            <button type="button" className="btn-secondary wizard-btn-back" onClick={() => setWizardStep(STEP.users || STEP.basics)} disabled={uploadingDocs}>
              {t('common:actions.back')}
            </button>
            <button
              type="button"
              className="btn-primary wizard-btn-continue"
              onClick={() => setWizardStep(STEP.review)}
              disabled={uploadingDocs}
            >
              {documents.length ? t('documents:wizard.upload.continueButton') : t('documents:wizard.upload.skipButton')}
            </button>
          </div>
        </div>
        )}

        {wizardStep === STEP.review && (
        <div className="glass-card project-wizard-panel">
          <div className="panel-header-tight" style={{ marginBottom: 12 }}>
            <strong style={{ fontSize: '1rem' }}>{t('documents:wizard.review.stepHeading', { step: STEP.review })}</strong>
            <span className="panel-chip">
              {t('documents:wizard.review.summaryChip', { approved: approvedCandidateCount, pending: pendingCandidateCount })}
            </span>
          </div>
          <p style={{ color: 'var(--text-light)', fontSize: '0.85rem', marginTop: 0, marginBottom: 14, lineHeight: 1.5 }}>
            {t('documents:wizard.review.description')}
          </p>

          <ErrorBanner message={metadataError} />

          {reviewingArticles ? (
            <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
              <div className="admin-empty-state-icon">
                <RefreshCw size={18} className="spin" />
              </div>
              <strong>{t('documents:wizard.review.loadingTitle')}</strong>
            </div>
          ) : articleCandidates.length === 0 ? (
            <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
              <div className="admin-empty-state-icon">
                <FileCheck size={18} />
              </div>
              <strong>{t('documents:wizard.review.emptyTitle')}</strong>
              <span>
                {documents.some((document) => document.articles_status === 'failed')
                  ? t('documents:wizard.review.emptySplittingFailed')
                  : documents.length
                  ? t('documents:wizard.review.emptyGoBack')
                  : t('documents:wizard.review.emptyNoDocuments')}
              </span>
            </div>
          ) : (
            <>
              <div className="project-wizard-nav-row" style={{ marginBottom: 12 }}>
                <span style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
                  {t('documents:wizard.review.summaryChip', { approved: approvedCandidateCount, pending: pendingCandidateCount })}
                </span>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={approveAllPending}
                  disabled={approvingAll || !pendingCandidateCount}
                >
                  {approvingAll ? (
                    <>
                      <RefreshCw size={16} className="spin" /> {t('documents:wizard.review.approving')}
                    </>
                  ) : (
                    <>
                      <ListChecks size={16} /> {t('documents:wizard.review.approveAllButton')}{pendingCandidateCount ? t('documents:wizard.review.approveAllCount', { count: pendingCandidateCount }) : ''}
                    </>
                  )}
                </button>
              </div>

              {pagedCandidatesByDocument.map(([documentId, candidates]) => (
                <div key={documentId} style={{ marginBottom: 14 }}>
                  <div
                    dir="auto"
                    style={{
                      fontSize: '0.74rem',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      color: 'var(--text-light)',
                      marginBottom: 8,
                    }}
                  >
                    {documentById.get(documentId)?.original_filename || t('documents:wizard.review.documentFallback')}
                  </div>
                  <div className="proj-rows">
                    {candidates.map((candidate) => (
                      <div key={candidate.id} className="proj-row" style={{ alignItems: 'flex-start' }}>
                        <div className="proj-row-main">
                          <span className="proj-row-name" dir="auto">{candidate.title}</span>
                          {candidate.summary && <span className="proj-row-desc" dir="auto">{candidate.summary}</span>}
                          {candidate.status === 'approved' && (
                            <span style={{ marginTop: 2 }}>
                              {candidate.article_analysis_status === 'success' ? (
                                <span className="panel-chip success">{t('documents:wizard.review.status.analyzed')}</span>
                              ) : candidate.article_analysis_status === 'failed' ? (
                                <span className="panel-chip">{t('documents:wizard.review.status.analysisFailed')}</span>
                              ) : (
                                <span className="panel-chip warning" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                                  <RefreshCw size={11} className="spin" /> {t('documents:wizard.review.status.analyzing')}
                                </span>
                              )}
                            </span>
                          )}
                        </div>
                        <div className="proj-row-side">
                          {candidate.status === 'approved' ? (
                            <span className="panel-chip success">{t('documents:wizard.review.status.approved')}</span>
                          ) : candidate.status === 'rejected' ? (
                            <span className="panel-chip">{t('documents:wizard.review.status.rejected')}</span>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="btn-secondary"
                                style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                                onClick={() => decideCandidate(candidate.id, 'rejected')}
                                disabled={Boolean(decidingCandidate[candidate.id])}
                              >
                                {t('documents:wizard.review.rejectButton')}
                              </button>
                              <button
                                type="button"
                                className="btn-primary"
                                style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                                onClick={() => decideCandidate(candidate.id, 'approved')}
                                disabled={Boolean(decidingCandidate[candidate.id])}
                              >
                                {decidingCandidate[candidate.id] ? <RefreshCw size={13} className="spin" /> : t('documents:wizard.review.approveButton')}
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              {totalCandidatePages > 1 && (
                <div className="proj-pagination" role="navigation" aria-label={t('documents:wizard.review.paginationLabel')}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setCandidatesPage((prev) => Math.max(1, prev - 1))}
                    disabled={candidatesPage <= 1}
                  >
                    <ChevronLeft size={16} className="rtl-mirror" /> {t('common:actions.previous')}
                  </button>
                  {candidatePageNumbers.map((page, index) =>
                    page === '...' ? (
                      <span key={`ellipsis-${index}`} className="proj-page-ellipsis">
                        &hellip;
                      </span>
                    ) : (
                      <button
                        key={page}
                        type="button"
                        className={`proj-page-btn ${page === candidatesPage ? 'active' : ''}`}
                        onClick={() => setCandidatesPage(page)}
                        aria-current={page === candidatesPage ? 'page' : undefined}
                      >
                        {formatNumber(page, locale)}
                      </button>
                    )
                  )}
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setCandidatesPage((prev) => Math.min(totalCandidatePages, prev + 1))}
                    disabled={candidatesPage >= totalCandidatePages}
                  >
                    {t('common:actions.next')} <ChevronRight size={16} className="rtl-mirror" />
                  </button>
                </div>
              )}
            </>
          )}

          <div className="project-wizard-nav-row" style={{ marginTop: 16 }}>
            <button
              type="button"
              className="btn-secondary wizard-btn-back"
              onClick={() => setWizardStep(STEP.upload)}
              disabled={reviewingArticles}
            >
              {t('common:actions.back')}
            </button>
            <button
              type="button"
              className="btn-primary wizard-btn-continue"
              onClick={() => setWizardStep(STEP.finish)}
              disabled={reviewingArticles}
            >
              {t('documents:wizard.review.continueButton')}
            </button>
          </div>
        </div>
        )}

        {wizardStep === STEP.finish && (
        <div className="glass-card project-wizard-panel">
          <div className="panel-header-tight" style={{ marginBottom: 12 }}>
            <strong style={{ fontSize: '1rem' }}>{t('wizard.finish.stepHeading', { step: STEP.finish })}</strong>
          </div>
          <p style={{ color: 'var(--text-light)', fontSize: '0.85rem', marginTop: 0, marginBottom: 14, lineHeight: 1.5 }}>
            {t('documents:wizard.finish.summary.documentsUploaded', { count: documents.length, formattedCount: formatNumber(documents.length, locale) })}
            {', '}
            {t('documents:wizard.finish.summary.articlesApproved', { count: approvedCandidateCount, formattedCount: formatNumber(approvedCandidateCount, locale) })}
            {'.'}
            {analyzedCandidateCount > 0 ? t('documents:wizard.finish.summary.analyzedSuffix', { count: analyzedCandidateCount, formattedCount: formatNumber(analyzedCandidateCount, locale) }) : ''}
            {failedAnalysisCandidateCount > 0 ? t('documents:wizard.finish.summary.failedSuffix', { count: failedAnalysisCandidateCount, formattedCount: formatNumber(failedAnalysisCandidateCount, locale) }) : ''}
          </p>

          <ErrorBanner message={metadataError} />

          {!isEditRoute && (
            <div className="project-status-choice">
              <label className="project-status-choice-label" htmlFor="project-status-choice-select">{t('wizard.finish.statusChoice.label')}</label>
              <select
                id="project-status-choice-select"
                className="filter-select project-status-choice-select"
                value={draft.status}
                onChange={(event) => setDraft((prev) => ({ ...prev, status: event.target.value }))}
                disabled={isSaving}
                aria-describedby="project-status-choice-help"
              >
                <option value="draft">{t('wizard.finish.statusChoice.draftOption')}</option>
                <option value="active">{t('wizard.finish.statusChoice.activeOption')}</option>
              </select>
              <span id="project-status-choice-help" className="project-status-choice-help">
                {draft.status === 'active'
                  ? t('wizard.finish.statusChoice.activeHelp')
                  : t('wizard.finish.statusChoice.draftHelp')}
              </span>
            </div>
          )}

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
                  <RefreshCw size={16} className="spin" /> {t('documents:wizard.finish.rerunning')}
                </>
              ) : (
                <>
                  <ScanText size={16} /> {t('documents:wizard.finish.rerunButton')}
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
              {t('common:actions.back')}
            </button>
            <button className="btn-primary wizard-btn-grow" onClick={finishOffline} disabled={isSaving}>
              {isSaving ? (
                <>
                  <RefreshCw size={18} className="spin" />
                  {t('wizard.finish.saving')}
                </>
                ) : (
                  <>
                    <Check size={18} />
                    {isEditRoute
                      ? t('wizard.finish.openWorkspace')
                      : draft.status === 'active'
                        ? t('wizard.finish.activateAndOpen')
                        : t('wizard.finish.saveDraftAndOpen')}
                  </>
                )}
            </button>
            <button className="btn-secondary wizard-btn-fixed" type="button" onClick={handleCancel}>
              <X size={18} /> {t('common:actions.cancel')}
            </button>
          </div>
        </div>
        )}
      </div>

      <ConfirmModal
        open={showCancelModal}
        title={t('wizard.cancelModal.title')}
        message={t('wizard.cancelModal.body')}
        confirmLabel={t('wizard.cancelModal.confirmLabel')}
        cancelLabel={t('wizard.cancelModal.cancelLabel')}
        onClose={() => setShowCancelModal(false)}
        onConfirm={discardChanges}
      />
    </div>
  );
}
