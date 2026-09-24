/**
 * Competitors — the tracked-competitor roster for one study, split out of the
 * reports workspace so managing who's tracked isn't buried behind a toggle on
 * the findings screen. Actions here: run analysis (first, since it's the
 * thing you came here to eventually do), then re-read documents (the way this
 * roster grows in the first place), then per-competitor track/alias controls.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle, Check, ChevronRight, FileText, Layers, Pencil, Tags, Upload,
} from 'lucide-react';
import {
  SIZE_TIER_LABELS, avatarGradient, getStudy, importCompetitors, initials,
  listCompetitors, setCompetitorStatus, updateCompetitor,
} from '../api/competitorApi.js';
import { countryLabel } from '../constants/countries.js';
import { useAuth } from '../auth/useAuth.js';
import {
  RunAnalysisButton, RunAnalysisChoiceModal, RunAnalysisLog,
} from './CompetitorRunAnalysis.jsx';
import { useRunAnalysis } from '../useRunAnalysis.js';
import '../styles/Competitors.css';

function sizeTierLabel(t, tier) {
  return t(`labels.sizeTier.${tier}`, { defaultValue: SIZE_TIER_LABELS[tier] || tier });
}

/** Alternate names a competitor is published under, edited as a
 *  comma-separated list. See CompetitorWorkspace for the full rationale. */
function AliasEditor({ competitor, onSave }) {
  const { t } = useTranslation('competitors');
  const stored = Array.isArray(competitor.aliases) ? competitor.aliases : [];
  const [value, setValue] = useState(stored.join(', '));
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = value !== stored.join(', ');

  const save = async () => {
    setBusy(true);
    try {
      await onSave(value.split(',').map((item) => item.trim()).filter(Boolean));
      setSaved(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cs-alias-editor">
      <label className="cs-label" htmlFor={`cs-aliases-${competitor.id}`}>{t('competitorsPage.aliasEditor.label')}</label>
      <div className="cs-alias-editor-row">
        <input
          id={`cs-aliases-${competitor.id}`}
          className="cs-input"
          value={value}
          placeholder={t('competitorsPage.aliasEditor.placeholder')}
          onChange={(event) => { setValue(event.target.value); setSaved(false); }}
          dir="auto"
        />
        <button type="button" className="cs-btn cs-btn-sm" onClick={save} disabled={busy || !dirty}>
          {busy ? <span className="cs-spinner" /> : null} {saved && !dirty ? t('competitorsPage.aliasEditor.saved') : t('common:actions.save')}
        </button>
      </div>
      <small className="cs-row-desc">
        {t('competitorsPage.aliasEditor.hint')}
      </small>
    </div>
  );
}

export default function CompetitorsPage() {
  const { t } = useTranslation(['competitors', 'common']);
  const { studyId } = useParams();
  const { hasPermission } = useAuth();
  const canManage = hasPermission('competitors.manage');

  const [study, setStudy] = useState(null);
  const [competitors, setCompetitors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(null);
  const [trackingBusy, setTrackingBusy] = useState({});
  const [expandedAliases, setExpandedAliases] = useState(() => new Set());
  const [importingCompetitors, setImportingCompetitors] = useState(false);
  const importInputRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [detail, competitorList] = await Promise.all([
          getStudy(studyId),
          listCompetitors(studyId),
        ]);
        if (cancelled) return;
        setStudy(detail.study);
        setCompetitors(competitorList.competitors || []);
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

  const refreshCompetitors = async () => {
    try {
      const result = await listCompetitors(studyId);
      setCompetitors(result.competitors || []);
    } catch (caught) {
      setError(caught.message);
    }
  };

  const run = useRunAnalysis(studyId, {
    onSuccess: (result) => {
      setNotice({
        generated: result.generated,
        scanned: result.validation?.scanned || 0,
      });
    },
    onError: (message) => setError(message),
  });

  const saveAliases = async (competitorId, aliases) => {
    try {
      await updateCompetitor(competitorId, { aliases });
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    }
  };

  const toggleAliases = (competitorId) => {
    setExpandedAliases((current) => {
      const next = new Set(current);
      if (next.has(competitorId)) next.delete(competitorId);
      else next.add(competitorId);
      return next;
    });
  };

  // A study built by scraping (rather than uploaded documents) hands its
  // tracked-competitor list over as JSONL via the scraper app's
  // `GET /api/competitors/export` - importing it here saves re-guessing that
  // same list with an LLM pass over documents, or re-typing it by hand.
  const handleImportFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || importingCompetitors) return;

    setImportingCompetitors(true);
    setError('');
    try {
      const result = await importCompetitors(studyId, file);
      await refreshCompetitors();
      setNotice({ generated: 0, scanned: 0, imported: result.saved || 0, skipped: result.skipped || 0 });
    } catch (caught) {
      setError(caught.message);
    } finally {
      setImportingCompetitors(false);
    }
  };

  const toggleTracking = async (competitor) => {
    const nextStatus = competitor.status === 'tracked' ? 'ignored' : 'tracked';
    setTrackingBusy((current) => ({ ...current, [competitor.id]: true }));
    try {
      await setCompetitorStatus(competitor.id, nextStatus);
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setTrackingBusy((current) => ({ ...current, [competitor.id]: false }));
    }
  };

  if (loading) {
    return (
      <div className="cs-page">
        <div className="cs-skeleton" style={{ height: 34, width: 280, marginBottom: 12 }} />
        <div className="cs-skeleton" style={{ height: 200 }} />
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
          <h1 dir="auto">{study?.name || t('shared.competitorStudyFallback')} — {t('competitorsPage.titleSuffix')}</h1>
          <p>{t('competitorsPage.subtitle')}</p>
        </div>
        <div className="cs-head-actions">
          <RunAnalysisButton run={run} label={t('runAnalysis.runAnalysisLabel')} />
          {canManage ? (
            <>
              <input
                ref={importInputRef}
                type="file"
                accept=".jsonl,.ndjson,application/x-ndjson"
                onChange={handleImportFile}
                style={{ display: 'none' }}
              />
              <button
                type="button"
                className="cs-btn"
                onClick={() => importInputRef.current?.click()}
                disabled={importingCompetitors}
                title={t('shared.importJsonlTitle')}
              >
                {importingCompetitors ? <span className="cs-spinner" /> : <Upload size={15} />}
                {importingCompetitors ? t('shared.importingEllipsis') : t('competitorsPage.importCompetitorsBtn')}
              </button>
            </>
          ) : null}
          {canManage ? (
            <Link to={`/competitors/${studyId}/edit`} className="cs-btn">
              <Pencil size={15} /> {t('shared.fullEdit')}
            </Link>
          ) : null}
        </div>
      </div>

      <RunAnalysisLog run={run} />

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span dir="auto">{error}</span>
        </div>
      ) : null}

      {notice ? (
        <div className="cs-alert cs-alert-info">
          <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            {notice.imported != null ? (
              <>
                {t('competitorsPage.notice.imported', { count: notice.imported })}
                {notice.skipped ? ` ${t('competitorsPage.notice.rowsSkipped', { count: notice.skipped })}` : ''}
              </>
            ) : (
              <>
                {t('competitorsPage.notice.reportsGenerated', { count: notice.generated })}{' '}
                {t('competitorsPage.notice.fromArticles', { count: notice.scanned })}
              </>
            )}
          </span>
        </div>
      ) : null}

      <div className="cs-panel">
        <h2 className="cs-panel-title"><Layers size={16} /> {t('competitorsPage.competitorCount', { count: competitors.length })}</h2>

        {competitors.length === 0 ? (
          <div className="cs-empty">
            <div className="cs-empty-icon"><FileText size={20} /></div>
            <h3>{t('competitorsPage.emptyTitle')}</h3>
            <p>{t('competitorsPage.emptyBody')}</p>
          </div>
        ) : (
          <div className="cs-rows">
            {competitors.map((competitor) => {
              const aliasesOpen = expandedAliases.has(competitor.id);
              return (
                <div key={competitor.id}>
                  <div className="cs-row">
                    <span className="cs-row-rank">{competitor.size_rank ?? '-'}</span>
                    <div className="cs-avatar" style={{ background: avatarGradient(competitor.name), width: 30, height: 30, fontSize: '0.72rem' }} aria-hidden="true">
                      {initials(competitor.name)}
                    </div>
                    <div className="cs-row-main">
                      <div className="cs-row-name" dir="auto">{competitor.name}</div>
                      <div className="cs-row-desc">
                        {competitor.finding_count
                          ? t('competitorsPage.reportCount', { count: competitor.finding_count })
                          : t('competitorsPage.noReportYet')}
                        {competitor.aliases?.length ? (
                          <span dir="auto"> · {t('competitorsPage.alsoKnownAs', { aliases: competitor.aliases.join(', ') })}</span>
                        ) : ''}
                      </div>
                    </div>
                    <div className="cs-row-side">
                      {competitor.country ? (
                        <span className="cs-pill cs-pill-signal" title={t('competitorsPage.basedInTitle')}>
                          {t('competitorsPage.basedIn', { country: countryLabel(competitor.country) })}
                        </span>
                      ) : null}
                      {Array.isArray(competitor.operates_in_countries) && competitor.operates_in_countries.length ? (
                        <span
                          className="cs-pill cs-pill-signal"
                          title={t('competitorsPage.competesInTitle')}
                        >
                          {t('competitorsPage.competesIn', { countries: competitor.operates_in_countries.map(countryLabel).join(', ') })}
                        </span>
                      ) : null}
                      <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                        {sizeTierLabel(t, competitor.size_tier)}
                      </span>
                      <button type="button" className="cs-btn cs-btn-sm" onClick={() => toggleAliases(competitor.id)}>
                        <Tags size={13} /> {aliasesOpen ? t('competitorsPage.hideNames') : t('competitorsPage.otherNames')}
                      </button>
                      <button
                        type="button"
                        className={`cs-btn cs-btn-sm${competitor.status === 'tracked' ? ' cs-btn-primary' : ''}`}
                        onClick={() => toggleTracking(competitor)}
                        disabled={Boolean(trackingBusy[competitor.id])}
                      >
                        {trackingBusy[competitor.id] ? (
                          <span className="cs-spinner" />
                        ) : competitor.status === 'tracked' ? (
                          <><Check size={13} /> {t('shared.trackingLabel')}</>
                        ) : (
                          t('shared.trackLabel')
                        )}
                      </button>
                    </div>
                  </div>

                  {aliasesOpen ? (
                    <div className="cs-rows" style={{ marginLeft: 30, marginBottom: 14 }}>
                      <AliasEditor
                        key={(competitor.aliases || []).join('|')}
                        competitor={competitor}
                        onSave={(aliases) => saveAliases(competitor.id, aliases)}
                      />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <RunAnalysisChoiceModal run={run} lastRunAt={study?.last_run_at} />
    </div>
  );
}
