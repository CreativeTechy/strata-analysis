import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import ConfirmModal from './ConfirmModal';
import ErrorBanner from './project-wizard/ErrorBanner.jsx';
import TermChipsField from './project-wizard/TermChipsField.jsx';
import UserAssignField from './project-wizard/UserAssignField.jsx';
import { useAuth } from '../auth/useAuth.js';
import { emptyDraft, LOCATION_TYPE_OPTIONS, sanitizeTermArray, normalizeDraftForCompare, toDateInput } from '../lib/projectHelpers.js';
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
} from 'lucide-react';

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
              JSON/JSONL exports are read as articles directly — one record per article, no splitting.
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
                      {/* Only a records file sets this on a *successful* read —
                          it is how a cut-off import ("first 500 of 40,000")
                          says so, which would otherwise look complete. */}
                      {document.articles_error && (
                        <span className="proj-row-desc" style={{ color: '#b54708', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <AlertTriangle size={12} /> {document.articles_error}
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
            Strata read your documents into individual articles. Approve the ones worth
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
