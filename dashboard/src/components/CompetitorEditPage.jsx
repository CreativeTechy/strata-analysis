/**
 * Full edit — the one page for everything about a study that isn't a
 * day-to-day action: its name/status/description, the business profile every
 * "how does this affect us" judgement is measured against, and deleting the
 * study outright. Replaces the two "Edit study"/"Edit profile" modals that
 * used to live on the workspace.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { AlertTriangle, Check, ChevronRight, Trash2 } from 'lucide-react';
import {
  deleteStudy, getStudy, saveProfile, updateStudy,
} from '../api/competitorApi.js';
import ConfirmModal from './ConfirmModal';
import { ListEditor } from './CompetitorOnboarding.jsx';
import '../styles/Competitors.css';

const STUDY_STATUS_OPTIONS = ['draft', 'active', 'archived'];

export default function CompetitorEditPage() {
  const { t } = useTranslation(['competitors', 'common']);
  const { studyId } = useParams();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [studyName, setStudyName] = useState('');
  const [studyDescription, setStudyDescription] = useState('');
  const [studyStatus, setStudyStatus] = useState('active');
  const [profileDraft, setProfileDraft] = useState({
    industry: '', market: '', positioning: '', offerings: [], audience: [],
    differentiators: [], context_summary: '',
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const detail = await getStudy(studyId);
        if (cancelled) return;
        setStudyName(detail.study?.name || '');
        setStudyDescription(detail.study?.description || '');
        setStudyStatus(detail.study?.status || 'active');
        setProfileDraft({
          industry: detail.profile?.industry || '',
          market: detail.profile?.market || '',
          positioning: detail.profile?.positioning || '',
          offerings: detail.profile?.offerings || [],
          audience: detail.profile?.audience || [],
          differentiators: detail.profile?.differentiators || [],
          context_summary: detail.profile?.context_summary || '',
        });
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId]);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError('');
    try {
      await Promise.all([
        updateStudy(studyId, { name: studyName, description: studyDescription, status: studyStatus }),
        saveProfile(studyId, profileDraft),
      ]);
      setSaved(true);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteStudy = async () => {
    setDeleting(true);
    try {
      await deleteStudy(studyId);
      navigate('/competitors');
    } catch (caught) {
      setError(caught.message);
      setDeleting(false);
      setDeleteOpen(false);
    }
  };

  if (loading) {
    return (
      <div className="cs-page">
        <div className="cs-skeleton" style={{ height: 34, width: 280, marginBottom: 12 }} />
        <div className="cs-skeleton" style={{ height: 400 }} />
      </div>
    );
  }

  return (
    <div className="cs-page">
      <div className="cs-head">
        <div>
          <Link to={`/competitors/${studyId}`} className="cs-link-back">
            <ChevronRight size={14} className="rtl-mirror" style={{ transform: 'rotate(180deg)' }} /> {t('shared.reports')}
          </Link>
          <h1 dir="auto">{t('editPage.editTitle', { name: studyName || t('editPage.competitorStudyFallbackLower') })}</h1>
          <p>{t('editPage.subtitle')}</p>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span dir="auto">{error}</span>
        </div>
      ) : null}

      <div className="cs-panel" style={{ marginBottom: 20 }}>
        <h2 className="cs-panel-title">{t('editPage.studyHeading')}</h2>
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-study-name">{t('editPage.nameLabel')}</label>
          <input id="cs-study-name" className="cs-input" value={studyName} dir="auto"
            onChange={(event) => { setStudyName(event.target.value); setSaved(false); }} />
        </div>
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-study-description">{t('editPage.descriptionLabel')}</label>
          <textarea id="cs-study-description" className="cs-textarea" style={{ minHeight: 80 }} dir="auto"
            value={studyDescription}
            onChange={(event) => { setStudyDescription(event.target.value); setSaved(false); }} />
        </div>
        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-study-status">{t('editPage.statusLabel')}</label>
          <select id="cs-study-status" className="cs-input" value={studyStatus}
            onChange={(event) => { setStudyStatus(event.target.value); setSaved(false); }}>
            {STUDY_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>{t(`editPage.statusOptions.${status}`)}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="cs-panel" style={{ marginBottom: 20 }}>
        <h2 className="cs-panel-title">{t('editPage.profileHeading')}</h2>
        <p className="cs-panel-hint">{t('editPage.profileHint')}</p>

        <div className="cs-grid-2">
          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-p-industry">{t('editPage.industryLabel')}</label>
            <input id="cs-p-industry" className="cs-input" value={profileDraft.industry} dir="auto"
              onChange={(event) => { setProfileDraft({ ...profileDraft, industry: event.target.value }); setSaved(false); }} />
          </div>
          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-p-market">{t('editPage.marketLabel')}</label>
            <input id="cs-p-market" className="cs-input" value={profileDraft.market} dir="auto"
              onChange={(event) => { setProfileDraft({ ...profileDraft, market: event.target.value }); setSaved(false); }} />
          </div>
        </div>

        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-p-positioning">{t('editPage.positioningLabel')}</label>
          <input id="cs-p-positioning" className="cs-input" value={profileDraft.positioning} dir="auto"
            onChange={(event) => { setProfileDraft({ ...profileDraft, positioning: event.target.value }); setSaved(false); }} />
        </div>

        <ListEditor label={t('editPage.offeringsLabel')} values={profileDraft.offerings}
          placeholder={t('editPage.offeringsPlaceholder')}
          onChange={(offerings) => { setProfileDraft({ ...profileDraft, offerings }); setSaved(false); }} />
        <ListEditor label={t('editPage.audienceLabel')} values={profileDraft.audience}
          placeholder={t('editPage.audiencePlaceholder')}
          onChange={(audience) => { setProfileDraft({ ...profileDraft, audience }); setSaved(false); }} />
        <ListEditor label={t('editPage.differentiatorsLabel')} hint={t('editPage.differentiatorsHint')}
          values={profileDraft.differentiators} placeholder={t('editPage.differentiatorsPlaceholder')}
          onChange={(differentiators) => { setProfileDraft({ ...profileDraft, differentiators }); setSaved(false); }} />

        <div className="cs-field">
          <label className="cs-label" htmlFor="cs-p-context">{t('editPage.contextLabel')}</label>
          <textarea id="cs-p-context" className="cs-textarea" style={{ minHeight: 110 }} dir="auto"
            value={profileDraft.context_summary}
            onChange={(event) => { setProfileDraft({ ...profileDraft, context_summary: event.target.value }); setSaved(false); }} />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
        <button type="button" className="cs-btn cs-btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? <span className="cs-spinner" /> : <Check size={15} />}
          {saving ? t('editPage.savingEllipsis') : t('editPage.saveChanges')}
        </button>
        {saved && !saving ? <span style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>{t('editPage.savedText')}</span> : null}
      </div>

      <div className="cs-panel" style={{ borderColor: 'rgba(255, 71, 87, 0.35)' }}>
        <h2 className="cs-panel-title" style={{ color: '#ff4757' }}>{t('editPage.dangerZoneHeading')}</h2>
        <p className="cs-panel-hint">{t('editPage.dangerZoneHint')}</p>
        <button type="button" className="cs-btn" onClick={() => setDeleteOpen(true)} style={{ color: '#ff4757' }}>
          <Trash2 size={15} /> {t('editPage.deleteStudyBtn')}
        </button>
      </div>

      <ConfirmModal
        open={deleteOpen}
        title={t('editPage.confirmDeleteTitle', { name: studyName })}
        message={t('editPage.confirmDeleteMessage')}
        confirmLabel={deleting ? t('editPage.deletingEllipsis') : t('editPage.deleteStudyBtn')}
        cancelLabel={t('editPage.keepStudy')}
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDeleteStudy}
      />
    </div>
  );
}
