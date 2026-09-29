import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Settings, RotateCcw, Languages, Brain, Radar, Smile, Tags, Cpu, Timer, Check,
  Users, Box, HardDrive, Gauge, Building2, Filter, CheckCircle2, XCircle, Link, ChevronDown,
} from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { listRuntimeSettings, updateRuntimeSetting, resetRuntimeSetting } from '../api/adminApi.js';
import LanguageSwitcher from './LanguageSwitcher.jsx';
import '../styles/AdminUsers.css';
import '../styles/Settings.css';

// A small, hand-picked allowlist over backend/services/settings/
// runtime_settings.py's SETTINGS_SCHEMA - not every backend/.env var, just
// the knobs that are safe to change without a restart. Order/icon/grouping
// here is presentation only; the backend is the source of truth for which
// keys exist, their type/choices/description, and validation.
const GROUPS = [
  {
    key: 'ai',
    keys: [
      'LLM_PROVIDER', 'COMPETITOR_ANALYSIS_LLM_PROVIDER',
      'SENTIMENT_CLASSIFIER_PROVIDER', 'SENTIMENT_CLASSIFIER_MODEL', 'SENTIMENT_CLASSIFIER_DEVICE',
      'SENTIMENT_CONFIDENCE_THRESHOLD', 'CLASSIFICATION_PROVIDER',
    ],
  },
  {
    key: 'performance',
    keys: [
      'ANALYSIS_CONCURRENCY', 'COMPETITOR_ANALYSIS_CONCURRENCY', 'LLM_REQUEST_TIMEOUT_SECONDS',
      'BUSINESS_PROFILE_LLM_TIMEOUT_SECONDS', 'COMPETITOR_FINDING_TIMEOUT_SECONDS',
    ],
  },
  {
    key: 'relevanceScreening',
    keys: [
      'ARTICLE_RELEVANCE_SCREENING_MODE', 'ARTICLE_RELEVANCE_ACCEPT_THRESHOLD', 'ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD',
      'EVIDENCE_CLAIM_SIMILARITY_THRESHOLD',
    ],
  },
];

const ICONS = {
  LLM_PROVIDER: Brain,
  COMPETITOR_ANALYSIS_LLM_PROVIDER: Radar,
  SENTIMENT_CLASSIFIER_PROVIDER: Smile,
  SENTIMENT_CLASSIFIER_MODEL: Box,
  SENTIMENT_CLASSIFIER_DEVICE: HardDrive,
  SENTIMENT_CONFIDENCE_THRESHOLD: Gauge,
  CLASSIFICATION_PROVIDER: Tags,
  ANALYSIS_CONCURRENCY: Cpu,
  COMPETITOR_ANALYSIS_CONCURRENCY: Users,
  LLM_REQUEST_TIMEOUT_SECONDS: Timer,
  BUSINESS_PROFILE_LLM_TIMEOUT_SECONDS: Building2,
  COMPETITOR_FINDING_TIMEOUT_SECONDS: Timer,
  ARTICLE_RELEVANCE_SCREENING_MODE: Filter,
  ARTICLE_RELEVANCE_ACCEPT_THRESHOLD: CheckCircle2,
  ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD: XCircle,
  EVIDENCE_CLAIM_SIMILARITY_THRESHOLD: Link,
};

// Persisted the same way Sidebar.jsx remembers its own nav sections - open by
// default, collapsed only once the operator has explicitly closed a section.
const SECTION_STATE_KEY = 'strata.settingsSections';

function loadSectionState() {
  if (typeof window === 'undefined') return {};
  try {
    return JSON.parse(window.localStorage.getItem(SECTION_STATE_KEY)) || {};
  } catch {
    return {};
  }
}

export default function SettingsPage() {
  const { t } = useTranslation(['admin', 'common']);
  const { hasPermission } = useAuth();
  const canUpdate = hasPermission('settings.update');

  const [settings, setSettings] = useState({});
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingKey, setSavingKey] = useState(null);
  const [savedKey, setSavedKey] = useState(null);
  const [openSections, setOpenSections] = useState(loadSectionState);

  const isSectionOpen = (id) => openSections[id] !== false;

  const toggleSection = (id) => {
    setOpenSections((prev) => {
      const next = { ...prev, [id]: !(prev[id] !== false) };
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(SECTION_STATE_KEY, JSON.stringify(next));
      }
      return next;
    });
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await listRuntimeSettings();
      const loaded = data?.settings || {};
      setSettings(loaded);
      setDrafts(Object.fromEntries(Object.entries(loaded).map(([key, s]) => [key, s.value])));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const flashSaved = (key) => {
    setSavedKey(key);
    setTimeout(() => setSavedKey((prev) => (prev === key ? null : prev)), 1800);
  };

  const save = async (key) => {
    setError('');
    setSavingKey(key);
    try {
      const { setting } = await updateRuntimeSetting(key, drafts[key]);
      setSettings((prev) => ({ ...prev, [key]: setting }));
      setDrafts((prev) => ({ ...prev, [key]: setting.value }));
      flashSaved(key);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingKey(null);
    }
  };

  const reset = async (key) => {
    setError('');
    setSavingKey(key);
    try {
      const { setting } = await resetRuntimeSetting(key);
      setSettings((prev) => ({ ...prev, [key]: setting }));
      setDrafts((prev) => ({ ...prev, [key]: setting.value }));
      flashSaved(key);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Settings size={14} /> {t('kickers.settings')}
          </div>
          <h1 className="admin-page-title">{t('settings.title')}</h1>
          <p className="admin-page-subtitle">{t('settings.subtitle')}</p>
        </div>
      </div>

      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }} dir="auto">
          {error}
        </div>
      )}

      <div className="settings-section">
        <button
          type="button"
          className="settings-section-toggle"
          onClick={() => toggleSection('preferences')}
          aria-expanded={isSectionOpen('preferences')}
        >
          <h2 className="settings-section-title">{t('settings.groups.preferences')}</h2>
          <ChevronDown
            size={16}
            className={`settings-section-chevron${isSectionOpen('preferences') ? '' : ' settings-section-chevron-closed'}`}
          />
        </button>
        {isSectionOpen('preferences') && (
          <div className="glass-card settings-card">
            <div className="settings-row">
              <div className="settings-row-icon">
                <Languages size={18} />
              </div>
              <div className="settings-row-body">
                <div className="settings-row-title">{t('settings.language.label')}</div>
                <p className="settings-row-description">{t('settings.language.description')}</p>
              </div>
              <div className="settings-row-control">
                <LanguageSwitcher />
              </div>
            </div>
          </div>
        )}
      </div>

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)' }}>
          <div className="loading-spinner" /> {t('settings.loading')}
        </div>
      )}

      {!loading && GROUPS.map((group) => {
        const rows = group.keys.filter((key) => settings[key]);
        if (rows.length === 0) return null;
        const open = isSectionOpen(group.key);
        return (
          <div className="settings-section" key={group.key}>
            <button
              type="button"
              className="settings-section-toggle"
              onClick={() => toggleSection(group.key)}
              aria-expanded={open}
            >
              <h2 className="settings-section-title">{t(`settings.groups.${group.key}`)}</h2>
              <ChevronDown size={16} className={`settings-section-chevron${open ? '' : ' settings-section-chevron-closed'}`} />
            </button>
            {open && (
            <div className="glass-card settings-card">
              {rows.map((key) => {
                const setting = settings[key];
                const Icon = ICONS[key] || Settings;
                const dirty = drafts[key] !== setting.value;
                const isSaving = savingKey === key;
                const justSaved = savedKey === key;
                return (
                  <div className="settings-row" key={key}>
                    <div className="settings-row-icon">
                      <Icon size={18} />
                    </div>
                    <div className="settings-row-body">
                      <div className="settings-row-title">
                        {t(`settings.keys.${key}`, { defaultValue: key })}
                        {setting.is_default ? (
                          <span className="panel-chip muted">{t('settings.status.default')}</span>
                        ) : (
                          <span
                            className="panel-chip success"
                            title={setting.set_by ? t('settings.status.overriddenByTitle', { name: setting.set_by }) : undefined}
                          >
                            {t('settings.status.overridden')}
                          </span>
                        )}
                      </div>
                      <p className="settings-row-description" dir="auto">
                        {t(`settings.descriptions.${key}`, { defaultValue: setting.description })}
                      </p>
                    </div>
                    <div className="settings-row-control">
                      {setting.type === 'enum' ? (
                        <div className="settings-segmented" role="group">
                          {setting.choices.map((choice) => (
                            <button
                              key={choice}
                              type="button"
                              className={`settings-segmented-option${drafts[key] === choice ? ' is-active' : ''}`}
                              aria-pressed={drafts[key] === choice}
                              disabled={!canUpdate || isSaving}
                              onClick={() => setDrafts((prev) => ({ ...prev, [key]: choice }))}
                            >
                              {choice}
                            </button>
                          ))}
                        </div>
                      ) : setting.type === 'string' ? (
                        <input
                          type="text"
                          className="settings-text-input"
                          value={drafts[key] ?? ''}
                          disabled={!canUpdate || isSaving}
                          onChange={(e) => setDrafts((prev) => ({ ...prev, [key]: e.target.value }))}
                        />
                      ) : (
                        <input
                          type="number"
                          className="settings-number-input"
                          step={setting.type === 'float' ? '0.01' : '1'}
                          min={setting.min}
                          max={setting.max}
                          value={drafts[key] ?? ''}
                          disabled={!canUpdate || isSaving}
                          onChange={(e) => setDrafts((prev) => ({ ...prev, [key]: e.target.value }))}
                        />
                      )}
                    </div>
                    <div className="settings-row-actions">
                      {canUpdate ? (
                        <>
                          {justSaved && !dirty ? (
                            <span className="settings-saved-badge">
                              <Check size={14} /> {t('common:actions.saved')}
                            </span>
                          ) : (
                            <button
                              className="btn-primary"
                              disabled={!dirty || isSaving}
                              onClick={() => save(key)}
                            >
                              {isSaving ? t('common:actions.saving') : t('common:actions.save')}
                            </button>
                          )}
                          {!setting.is_default && (
                            <button
                              className="btn-secondary"
                              disabled={isSaving}
                              onClick={() => reset(key)}
                              title={t('settings.resetToDefault')}
                            >
                              <RotateCcw size={14} />
                            </button>
                          )}
                        </>
                      ) : (
                        <span className="subtitle">{t('roles.table.viewOnly')}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
