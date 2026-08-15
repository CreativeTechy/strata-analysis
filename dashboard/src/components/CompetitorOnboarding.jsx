/**
 * Competitor study onboarding.
 *
 * Step 1 (data source) branches the rest of the wizard in two:
 *
 *   Online (AI discovery):
 *   1. Data source
 *   2. Your business  — name + website. The website is what makes the rest work,
 *                       so it is asked for first and its scrape is shown honestly.
 *   3. Market context — the AI's reading of the site, editable. Shown rather than
 *                       hidden because everything downstream is judged against it.
 *   4. Competitors    — manual-first: add competitors and their sources directly,
 *                       and they are valid and scrape-ready immediately, no
 *                       confirmation step needed. "Suggest with AI" is an optional
 *                       action on the same screen; AI-suggested competitors and
 *                       their channels still need a quick review before they're
 *                       trusted the same way a manual entry already is.
 *   5. Channels       — every channel found for a tracked competitor, manual or
 *                       AI-discovered, is listed here already included (channels
 *                       are trusted by default, same as a manually-entered
 *                       competitor). Discard any that aren't actually theirs, or
 *                       add one yourself if something's missing, before moving on.
 *   6. Schedule       — how often confirmed sources get re-scraped, then finish.
 *
 *   Offline (uploaded documents):
 *   1. Data source
 *   2. Upload documents — a study name plus the files themselves. Each upload
 *                         is saved immediately, then extracted (text library or
 *                         OCR, decided server-side) in the background; this step
 *                         polls and shows each file's status as it resolves.
 *                         Extraction success also kicks off splitting the text
 *                         into candidate articles, reviewed next.
 *   3. Review articles   — each document's extracted text is split into
 *                         candidate articles by the LLM; approving one turns it
 *                         into a real article the existing analysis pipeline can
 *                         read later (same table scraped articles use), exactly
 *                         like AI-suggested competitors need a look before
 *                         they're trusted. "Approve all" is the fast path.
 *   5. Schedule          — re-scraping doesn't apply with nothing to scrape, and
 *                         there are no competitor channels to review either, so
 *                         this reuses the same step id only for a consistent
 *                         finish, then opens the workspace with approved articles
 *                         ready.
 *
 * Long steps (scrape, discovery) run tens of seconds, so each shows staged
 * progress instead of an indeterminate spinner.
 */

import { useMemo, useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Building2, CalendarClock, Check, CheckCircle2, ChevronRight,
  Database, FileCheck, FileText, Globe, Link2, ListChecks, Loader2, Plus, Radar, ScanText, Search, Sparkles,
  Trash2, Upload, X,
} from 'lucide-react';
import {
  PLATFORM_LABELS, SIZE_TIER_LABELS, addAccount, addCompetitorManual, analyzeDocuments, approveAllDocumentArticles,
  avatarGradient, buildProfile, createStudy, deleteDocument, discoverCompetitors, discoverTrackedAccounts,
  getProfile, initials, listAccounts, listCompetitors, listDocumentArticles, listStudies, pollArticleCandidates,
  pollDiscoveryRun, pollDocumentExtraction, saveProfile, setCompetitorStatus, setDocumentArticleStatus, setSchedule,
  uploadDocuments, validateAccount,
} from '../competitorApi.js';
import { COUNTRIES, countryLabel } from '../constants/countries.js';
import { REPEAT_UNIT_OPTIONS } from '../constants/schedule.js';
import { AddCompetitorForm, AddSourceRow } from './CompetitorSourceEditor.jsx';
import { WeekdayPicker } from './ProjectsPage.jsx';
import '../styles/Competitors.css';

/** Offline swaps step 3 for its own "Review articles" and skips step 4
 *  (Competitors) and step 5 (Channels) entirely — there's nothing to track or
 *  find channels for yet, so they're left out of the chip row rather than
 *  shown as passed-through. Step 5 (Channels)/6 (Schedule) also collapse into
 *  a single id 5: there's nothing to re-scrape or review, so instead it runs
 *  analysis straight off the approved articles and shows the resulting report. */
function getSteps(dataMode) {
  const steps = [
    { id: 1, label: 'Data source', icon: Database },
    dataMode === 'offline'
      ? { id: 2, label: 'Upload documents', icon: Upload }
      : { id: 2, label: 'Your business', icon: Building2 },
    dataMode === 'offline'
      ? { id: 3, label: 'Review articles', icon: FileCheck }
      : { id: 3, label: 'Market context', icon: Sparkles },
    { id: 4, label: 'Competitors', icon: Radar },
    dataMode === 'offline'
      ? { id: 5, label: 'Analyze & report', icon: ScanText }
      : { id: 5, label: 'Channels', icon: Link2 },
    ...(dataMode === 'offline' ? [] : [{ id: 6, label: 'Schedule', icon: CalendarClock }]),
  ];
  return dataMode === 'offline' ? steps.filter((s) => s.id !== 4) : steps;
}

// Mirrors document_analysis.py's two-stage shape: name the companies the
// documents are actually about, then run the same evidence-validation +
// finding-generation an online study uses.
const DOCUMENT_ANALYSIS_STAGES = [
  'Reading approved articles for company names',
  'Matching evidence to each company',
  'Writing findings',
];

const SCRAPE_STAGES = [
  'Fetching your website',
  'Extracting page text',
  'Reading how you position yourself',
  'Writing your market context',
];

// Phase 1 only asks the model for names and ranks them - no web verification
// yet (that happens per competitor when it's tracked) and channels are a
// separate step (CHANNEL_STAGES below), so this list must not claim either.
const DISCOVERY_STAGES = [
  'Comparing your profile against the market',
  'Naming candidate competitors',
  'Filtering out duplicates and unlikely matches',
  'Ranking them by size',
];

// Phase 3: finding channels for whichever competitors got tracked.
const CHANNEL_STAGES = [
  'Checking each competitor’s site for a feed',
  'Searching the web for their real accounts and hashtags',
  'Asking the model for X accounts, hashtags, and keywords to monitor',
  'Searching for review and discussion pages',
  'Linking valid channels as sources',
];

/** Real-time progress lines from a discovery run's `logs` (see
 *  competitorApi.js's pollDiscoveryRun `onUpdate`) — each poll can add more, so
 *  this auto-scrolls to keep the latest line in view. Styled like StageList
 *  (same row/icon language: a checkmark per finished line, a spinner on the
 *  most recent one while the run is still active) so the real detail trail
 *  reads as a continuation of that same progress UI rather than a separate
 *  terminal-style log. Renders nothing until there's at least one line, and
 *  stays visible after the run finishes so the trail can still be reviewed.
 *  Exported so CompetitorWorkspace.jsx can reuse it, the same way it already
 *  reuses ListEditor from this file. */
export function DiscoveryLog({ logs, active }) {
  const boxRef = useRef(null);
  const [now, setNow] = useState(null);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [logs?.length]);

  // The backend can go quiet for a while on a single slow step (an LLM call
  // has no sub-progress to report) - without this, the last line just sits
  // there and reads as stuck. Ticking a counter next to it at least shows
  // time is passing, not that the run died. `Date.now()` only ever runs here,
  // inside an effect, never during render.
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, logs?.length]);

  if (!logs?.length) return null;

  const lastTs = new Date(logs[logs.length - 1].ts).getTime();
  const elapsed = now ? Math.max(0, Math.round((now - lastTs) / 1000)) : 0;

  return (
    <div className="cs-panel cs-discovery-log" style={{ marginTop: 14, background: '#fcfdff' }}>
      <div className="cs-progress" ref={boxRef}>
        {logs.map((entry, index) => {
          const isCurrent = active && index === logs.length - 1;
          return (
            <div
              key={index}
              className={`cs-progress-row${isCurrent ? ' cs-progress-row-active' : ' cs-progress-row-done'}`}
            >
              {isCurrent ? <span className="cs-spinner" /> : <CheckCircle2 size={15} />}
              <span>
                {entry.message}
                {isCurrent && elapsed >= 4 ? ` (still working, ${elapsed}s)` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Staged feedback for a slow request. Advances on a timer purely so the wait
 *  reads as progress; it never claims the work finished — that is driven by the
 *  response, which replaces this component entirely. Rendered only while a
 *  request is in flight, so each run mounts it fresh at stage zero. */
function StageList({ stages }) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveIndex((current) => Math.min(current + 1, stages.length - 1));
    }, 2600);
    return () => clearInterval(timer);
  }, [stages.length]);

  return (
    <div className="cs-progress">
      {stages.map((stage, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        return (
          <div
            key={stage}
            className={`cs-progress-row${active ? ' cs-progress-row-active' : ''}${done ? ' cs-progress-row-done' : ''}`}
          >
            {done ? <CheckCircle2 size={15} /> : active ? <span className="cs-spinner" /> : <span style={{ width: 15 }} />}
            <span>{stage}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ListEditor({ label, hint, values, onChange, placeholder }) {
  const [draft, setDraft] = useState('');
  const items = Array.isArray(values) ? values : [];

  const add = () => {
    const value = draft.trim();
    if (!value || items.includes(value)) {
      setDraft('');
      return;
    }
    onChange([...items, value]);
    setDraft('');
  };

  return (
    <div className="cs-field">
      <label className="cs-label">
        {label}
        {hint ? <span className="cs-label-hint">{hint}</span> : null}
      </label>
      <div className="cs-pills" style={{ marginBottom: items.length ? 9 : 0 }}>
        {items.map((item) => (
          <span key={item} className="cs-pill">
            {item}
            <button
              type="button"
              onClick={() => onChange(items.filter((value) => value !== item))}
              aria-label={`Remove ${item}`}
              style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'flex', color: 'inherit' }}
            >
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          className="cs-input"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="cs-btn" onClick={add} disabled={!draft.trim()}>
          <Plus size={14} /> Add
        </button>
      </div>
    </div>
  );
}

/** Fixed-list country multi-select: type to filter, click a match to add,
 *  selected countries render as removable pills. Modeled on ListEditor above,
 *  since free text would let "USA" and "United States" reach the discovery
 *  prompt as different values. */
function CountryPicker({ label, hint, values, onChange }) {
  const [query, setQuery] = useState('');
  const selected = Array.isArray(values) ? values : [];
  const matches = query.trim()
    ? COUNTRIES.filter(
        (c) =>
          !selected.includes(c.code) &&
          (c.name.toLowerCase().includes(query.trim().toLowerCase()) ||
            c.code.toLowerCase() === query.trim().toLowerCase()),
      ).slice(0, 8)
    : [];

  const add = (code) => {
    if (!selected.includes(code)) onChange([...selected, code]);
    setQuery('');
  };

  return (
    <div className="cs-field">
      <label className="cs-label">
        {label}
        {hint ? <span className="cs-label-hint">{hint}</span> : null}
      </label>
      <div className="cs-pills" style={{ marginBottom: selected.length ? 9 : 0 }}>
        {selected.map((code) => (
          <span key={code} className="cs-pill">
            {countryLabel(code)}
            <button
              type="button"
              onClick={() => onChange(selected.filter((value) => value !== code))}
              aria-label={`Remove ${countryLabel(code)}`}
              style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'flex', color: 'inherit' }}
            >
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <div style={{ position: 'relative' }}>
        <input
          className="cs-input"
          value={query}
          placeholder="Search countries..."
          onChange={(event) => setQuery(event.target.value)}
        />
        {matches.length ? (
          <div className="cs-dropdown">
            {matches.map((c) => (
              <button key={c.code} type="button" className="cs-dropdown-item" onClick={() => add(c.code)}>
                {c.name}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function addDaysIso(dateIso, days) {
  if (!dateIso) return '';
  const parsed = new Date(`${dateIso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return '';
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

// The retrieval window is date-granular, so a minutes/hours interval still
// needs to resolve to at least a 1-day-wide window rather than 0.
function intervalToDays(value, unit) {
  const amount = Math.max(1, Number(value) || 1);
  if (unit === 'minutes') return Math.max(1, Math.ceil(amount / 1440));
  if (unit === 'hours') return Math.max(1, Math.ceil(amount / 24));
  return amount;
}

export default function CompetitorOnboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [step1Mode, setStep1Mode] = useState(null); // 'ai' | 'manual' while the business step is busy
  const [dataMode, setDataMode] = useState(null); // 'online' | 'offline'

  const [studyName, setStudyName] = useState('');
  const [studyId, setStudyId] = useState(null);

  const [business, setBusiness] = useState({ name: '', website: '', description: '' });
  const [targetCountries, setTargetCountries] = useState([]);
  const [profile, setProfile] = useState(null);
  const [scrape, setScrape] = useState(null);

  // 'new' builds a fresh business profile (scrape+AI, or manual); 'existing'
  // reuses one already derived for a past study, skipping both.
  const [businessMode, setBusinessMode] = useState('new');
  const [existingBusinesses, setExistingBusinesses] = useState([]);
  const [loadingBusinesses, setLoadingBusinesses] = useState(false);
  const [businessSearch, setBusinessSearch] = useState('');
  const [selectedBusinessId, setSelectedBusinessId] = useState(null);
  const [selectedBusinessProfile, setSelectedBusinessProfile] = useState(null);

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

  const [analyzingDocuments, setAnalyzingDocuments] = useState(false);
  const [documentAnalysis, setDocumentAnalysis] = useState(null);

  const [competitors, setCompetitors] = useState([]);
  const [rejected, setRejected] = useState([]);
  const [addingManual, setAddingManual] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [findingChannels, setFindingChannels] = useState(false);
  const [discoveryLogs, setDiscoveryLogs] = useState([]);

  const [expandedChannels, setExpandedChannels] = useState(() => new Set());
  const [accountsByCompetitor, setAccountsByCompetitor] = useState({});
  const [sourceBusy, setSourceBusy] = useState({});
  const [trackingBusy, setTrackingBusy] = useState({});
  const [trackingAllBusy, setTrackingAllBusy] = useState(false);
  const [unverified, setUnverified] = useState({});

  const [scheduleIntervalValue, setScheduleIntervalValue] = useState(1);
  const [scheduleIntervalUnit, setScheduleIntervalUnit] = useState('days');
  const [scheduleWeekdays, setScheduleWeekdays] = useState([]);
  const [scheduleOn, setScheduleOn] = useState(true);
  // Defaults to today rather than blank, since the window is required before
  // finishing — no effect needed, this only ever needs to run once.
  const [retrievalStart, setRetrievalStart] = useState(() => todayIso());
  // Only holds a real value while the schedule toggle is off (manual entry);
  // while it's on, the window's end is derived fresh each render below so
  // changing the repeat interval resizes it without a setState-in-effect.
  const [retrievalEnd, setRetrievalEnd] = useState('');

  const canLeaveStep1 = business.name.trim().length > 0;
  const trackedCompetitors = useMemo(
    () => competitors.filter((competitor) => competitor.status === 'tracked'),
    [competitors],
  );
  const untrackedCompetitors = useMemo(
    () => competitors.filter((competitor) => competitor.status !== 'tracked'),
    [competitors],
  );
  // Only counts competitors whose accounts have already loaded (undefined
  // means "not fetched yet", not "found nothing") - avoids a misleading 0
  // flashing before step 5's own effect has loaded them.
  const channellessTracked = useMemo(
    () => trackedCompetitors.filter((competitor) => accountsByCompetitor[competitor.id]?.length === 0).length,
    [trackedCompetitors, accountsByCompetitor],
  );
  const visibleSteps = useMemo(() => getSteps(dataMode), [dataMode]);
  const filteredExistingBusinesses = useMemo(() => {
    const query = businessSearch.trim().toLowerCase();
    if (!query) return existingBusinesses;
    return existingBusinesses.filter(
      (b) => (b.business_name || '').toLowerCase().includes(query)
        || (b.business_website || '').toLowerCase().includes(query),
    );
  }, [existingBusinesses, businessSearch]);

  const documentById = useMemo(
    () => Object.fromEntries(documents.map((document) => [document.id, document])),
    [documents],
  );
  const candidatesByDocument = useMemo(() => {
    const groups = new Map();
    for (const candidate of articleCandidates) {
      if (!groups.has(candidate.document_id)) groups.set(candidate.document_id, []);
      groups.get(candidate.document_id).push(candidate);
    }
    return groups;
  }, [articleCandidates]);
  const pendingCandidateCount = useMemo(
    () => articleCandidates.filter((candidate) => candidate.status === 'pending').length,
    [articleCandidates],
  );
  const approvedCandidateCount = useMemo(
    () => articleCandidates.filter((candidate) => candidate.status === 'approved').length,
    [articleCandidates],
  );

  const refreshCompetitors = async () => {
    const result = await listCompetitors(studyId);
    setCompetitors(result.competitors || []);
  };

  const ensureStudy = async () => {
    if (studyId) return studyId;
    const fallbackName = business.name.trim() ? `${business.name.trim()} - competitor study` : 'Untitled competitor study';
    const created = await createStudy({ name: studyName.trim() || fallbackName });
    setStudyId(created.study.id);
    return created.study.id;
  };

  // Step 2 -> 3: create the study, scrape the site, derive the market context.
  const submitBusiness = async () => {
    setError('');
    setBusy(true);
    setStep1Mode('ai');
    try {
      const id = await ensureStudy();
      const result = await buildProfile(id, { ...business, target_countries: targetCountries });
      setProfile(result.profile);
      setScrape(result.scrape);
      if (!result.ai_derived) {
        setError(
          'The site was read but the market context could not be generated. Fill it in below and continue.',
        );
      }
      setStep(3);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
      setStep1Mode(null);
    }
  };

  // Businesses that already have a derived profile from a past study, deduped
  // by website (falling back to name) so the same company scraped twice
  // doesn't show up as two picks.
  const loadExistingBusinesses = async () => {
    setLoadingBusinesses(true);
    try {
      const { studies } = await listStudies();
      const seen = new Set();
      const businesses = [];
      for (const study of studies || []) {
        if (!study.business_name) continue;
        const key = (study.business_website || study.business_name).trim().toLowerCase();
        if (!key || seen.has(key)) continue;
        seen.add(key);
        businesses.push(study);
      }
      setExistingBusinesses(businesses);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoadingBusinesses(false);
    }
  };

  // Lazy-load once the user actually asks to reuse a business, not on every
  // visit to step 2 — most studies create a new business and never need it.
  useEffect(() => {
    if (step !== 2 || dataMode === 'offline' || businessMode !== 'existing') return;
    if (existingBusinesses.length || loadingBusinesses) return;
    let cancelled = false;
    (async () => {
      if (cancelled) return;
      await loadExistingBusinesses();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, dataMode, businessMode]);

  const switchBusinessMode = (mode) => {
    if (mode === businessMode) return;
    setError('');
    setBusinessMode(mode);
    setSelectedBusinessId(null);
    setSelectedBusinessProfile(null);
    setBusiness({ name: '', website: '', description: '' });
    setTargetCountries([]);
  };

  const chooseExistingBusiness = async (study) => {
    setError('');
    setSelectedBusinessId(study.id);
    setSelectedBusinessProfile(null);
    try {
      const { profile: sourceProfile } = await getProfile(study.id);
      if (!sourceProfile) {
        setError('Could not load that business profile.');
        return;
      }
      setBusiness({
        name: sourceProfile.name || '',
        website: sourceProfile.website || '',
        description: sourceProfile.description || '',
      });
      setTargetCountries(sourceProfile.target_countries || []);
      setSelectedBusinessProfile(sourceProfile);
    } catch (caught) {
      setError(caught.message);
    }
  };

  // Step 2 -> 3, reusing a business: no scrape, no LLM call — just copy the
  // already-derived profile onto this study, still editable on the next step.
  const continueWithExistingBusiness = async () => {
    if (!selectedBusinessProfile) return;
    setError('');
    setBusy(true);
    setStep1Mode('existing');
    try {
      const id = await ensureStudy();
      const saved = await saveProfile(id, { ...selectedBusinessProfile, target_countries: targetCountries });
      setProfile(saved.profile);
      setScrape(null);
      setStep(3);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
      setStep1Mode(null);
    }
  };

  // Step 2 -> 3, no AI: skip the scrape/derive call entirely and persist
  // exactly what was typed in, so Step 2 opens blank and ready to fill in by hand.
  const submitBusinessManually = async () => {
    setError('');
    setBusy(true);
    setStep1Mode('manual');
    try {
      const id = await ensureStudy();
      const saved = await saveProfile(id, {
        name: business.name.trim(),
        website: business.website.trim(),
        description: business.description.trim(),
        target_countries: targetCountries,
      });
      setProfile(saved.profile);
      setScrape(null);
      setStep(3);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
      setStep1Mode(null);
    }
  };

  const addPendingFiles = (fileList) => {
    setPendingFiles((current) => [...current, ...Array.from(fileList || [])]);
  };

  const removePendingFile = (index) => {
    setPendingFiles((current) => current.filter((_, i) => i !== index));
  };

  const refreshArticleCandidates = async (id) => {
    const result = await listDocumentArticles(id);
    setArticleCandidates(result.articles || []);
  };

  // Offline step 2: create the study (if needed), upload whatever files are
  // staged, then poll until each one's background extraction (text library or
  // OCR, decided server-side) settles, then poll again until the candidate
  // articles split out of that text are ready too — the upload button
  // re-enables as soon as the files are saved, so a second batch can go up
  // while the first is still extracting; both polls just re-list from the
  // server, so overlapping calls converge on the same truth rather than
  // conflicting.
  const uploadPendingDocuments = async () => {
    if (!pendingFiles.length) return;
    setError('');
    setUploadingDocs(true);
    let id;
    let uploadedIds;
    try {
      id = await ensureStudy();
      const result = await uploadDocuments(id, pendingFiles);
      uploadedIds = (result.documents || []).map((document) => document.id);
      setPendingFiles([]);
    } catch (caught) {
      setError(caught.message);
      setUploadingDocs(false);
      return;
    }
    setUploadingDocs(false);
    if (!uploadedIds.length) return;
    setExtractingDocs(true);
    try {
      await pollDocumentExtraction(id, uploadedIds, setDocuments);
      await pollArticleCandidates(id, uploadedIds, setDocuments);
      await refreshArticleCandidates(id);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setExtractingDocs(false);
    }
  };

  const removeDocument = async (documentId) => {
    try {
      await deleteDocument(documentId);
      setDocuments((current) => current.filter((document) => document.id !== documentId));
    } catch (caught) {
      setError(caught.message);
    }
  };

  // Offline step 3: resume watching for any document still generating
  // candidates when this step is (re)entered — Continue on step 2 isn't
  // gated on generation finishing, so it can still be running here. Reads
  // documentsRef instead of depending on `documents` directly so this only
  // re-runs on an actual step change, not on every document-list update the
  // poll itself causes.
  useEffect(() => {
    if (step !== 3 || dataMode !== 'offline' || !studyId) return;
    let cancelled = false;
    (async () => {
      const activeIds = documentsRef.current
        .filter((document) => document.articles_status === 'pending' || document.articles_status === 'generating')
        .map((document) => document.id);
      if (activeIds.length) {
        setReviewingArticles(true);
        try {
          await pollArticleCandidates(studyId, activeIds, (updated) => {
            if (!cancelled) setDocuments(updated);
          });
        } catch (caught) {
          if (!cancelled) setError(caught.message);
        } finally {
          if (!cancelled) setReviewingArticles(false);
        }
      }
      if (!cancelled) {
        try {
          await refreshArticleCandidates(studyId);
        } catch (caught) {
          if (!cancelled) setError(caught.message);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, dataMode, studyId]);

  const decideCandidate = async (candidateId, status) => {
    setDecidingCandidate((current) => ({ ...current, [candidateId]: true }));
    try {
      const result = await setDocumentArticleStatus(candidateId, status);
      setArticleCandidates((current) =>
        current.map((candidate) => (candidate.id === candidateId ? result.article : candidate)),
      );
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDecidingCandidate((current) => ({ ...current, [candidateId]: false }));
    }
  };

  const approveAllPending = async () => {
    setError('');
    setApprovingAll(true);
    try {
      await approveAllDocumentArticles(studyId);
      await refreshArticleCandidates(studyId);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setApprovingAll(false);
    }
  };

  // Step 5 (offline): names the competitors the approved articles are
  // actually about, tracks them, then generates one finding card per company
  // — the same report an online study ends up with, just derived from
  // documents instead of a live scrape.
  const runDocumentAnalysis = async () => {
    setError('');
    setAnalyzingDocuments(true);
    try {
      const result = await analyzeDocuments(studyId);
      setDocumentAnalysis(result);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAnalyzingDocuments(false);
    }
  };

  // Step 2 -> 3: save any edits and move on. Competitors are added manually
  // from here; AI suggestion is an optional action on that screen, not a step.
  const submitContext = async () => {
    setError('');
    setBusy(true);
    try {
      const saved = await saveProfile(studyId, profile);
      setProfile(saved.profile);
      await refreshCompetitors();
      setStep(4);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  const handleAddManualCompetitor = async (payload) => {
    setError('');
    setAddingManual(true);
    try {
      const result = await addCompetitorManual(studyId, payload);
      await refreshCompetitors();
      // Only pre-seed the cache when there's something to show immediately -
      // an empty array here would look identical to "already fetched, found
      // nothing" to every reader of this cache (step 4's drawer, step 5's
      // auto-load), permanently hiding channels that automatic discovery
      // finds for this competitor later since nothing would think to re-fetch.
      if (result.accounts?.length) {
        setAccountsByCompetitor((current) => ({ ...current, [result.competitor.id]: result.accounts }));
      }
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAddingManual(false);
    }
  };

  const runAiSuggest = async () => {
    setError('');
    setDiscovering(true);
    setDiscoveryLogs([]);
    try {
      const queued = await discoverCompetitors(studyId, { limit: 12, with_accounts: false });
      const run = await pollDiscoveryRun(studyId, queued.run_id, (r) => setDiscoveryLogs(r.logs || []));
      if (run.status === 'failed') {
        throw new Error(run.error || run.message || 'Competitor discovery failed.');
      }
      await refreshCompetitors();
      setRejected(run.rejected || []);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDiscovering(false);
    }
  };

  // Step 4 -> 5: before showing the channels review step, find channels for
  // whichever competitors the user chose to track — best-effort, since a
  // failure here shouldn't block moving on (channels can still be found later
  // from the workspace, and the review step below shows whatever came back).
  const continueToChannels = async () => {
    setFindingChannels(true);
    setDiscoveryLogs([]);
    try {
      const queued = await discoverTrackedAccounts(studyId);
      if (queued.run_id) {
        await pollDiscoveryRun(studyId, queued.run_id, (r) => setDiscoveryLogs(r.logs || []));
        await refreshCompetitors();
      }
    } catch {
      // best-effort — see comment above.
    } finally {
      setFindingChannels(false);
      setStep(5);
    }
  };

  // Step 5's own "Find more channels" button — reruns the same bulk job as
  // above for any tracked competitor still without one (more may have been
  // tracked since, or the first pass came back empty), but stays on this step
  // and, unlike the automatic pass above, surfaces a failure instead of
  // swallowing it, since this is an explicit user action rather than a
  // best-effort step transition. Also re-fetches each competitor's account
  // list afterwards, since accounts are only lazy-loaded once per competitor.
  const findMoreChannels = async () => {
    setError('');
    setFindingChannels(true);
    setDiscoveryLogs([]);
    try {
      const queued = await discoverTrackedAccounts(studyId);
      if (queued.run_id) {
        await pollDiscoveryRun(studyId, queued.run_id, (r) => setDiscoveryLogs(r.logs || []));
      }
      await refreshCompetitors();
      const results = await Promise.allSettled(
        trackedCompetitors.map((competitor) => listAccounts(competitor.id)),
      );
      setAccountsByCompetitor((current) => {
        const next = { ...current };
        results.forEach((result, index) => {
          if (result.status === 'fulfilled') next[trackedCompetitors[index].id] = result.value.accounts || [];
        });
        return next;
      });
    } catch (caught) {
      setError(caught.message);
    } finally {
      setFindingChannels(false);
    }
  };

  const toggleTracking = async (competitor) => {
    const nextStatus = competitor.status === 'tracked' ? 'ignored' : 'tracked';
    setTrackingBusy((current) => ({ ...current, [competitor.id]: true }));
    try {
      // Phase 2: tracking an AI-suggested competitor for the first time
      // triggers a live web check server-side, so this call can take a beat
      // longer than a plain status flip — the button shows a spinner for it.
      const result = await setCompetitorStatus(competitor.id, nextStatus);
      if (result.verification) {
        setUnverified((current) => ({ ...current, [competitor.id]: !result.verification.verified }));
      }
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setTrackingBusy((current) => ({ ...current, [competitor.id]: false }));
    }
  };

  // Tracks every not-yet-tracked competitor in one go, so a user with a long
  // AI-suggested list doesn't have to click "Track" once per row. Runs the
  // per-competitor status calls (each one a live web check the first time an
  // AI suggestion is tracked, see toggleTracking above) in parallel rather
  // than one after another, and keeps going even if one of them fails.
  const trackAllCompetitors = async () => {
    const targets = untrackedCompetitors;
    if (!targets.length) return;
    setTrackingAllBusy(true);
    setTrackingBusy((current) => ({
      ...current,
      ...Object.fromEntries(targets.map((competitor) => [competitor.id, true])),
    }));
    try {
      const results = await Promise.allSettled(
        targets.map((competitor) => setCompetitorStatus(competitor.id, 'tracked')),
      );
      setUnverified((current) => {
        const next = { ...current };
        results.forEach((result, index) => {
          if (result.status === 'fulfilled' && result.value.verification) {
            next[targets[index].id] = !result.value.verification.verified;
          }
        });
        return next;
      });
      const failed = results.filter((result) => result.status === 'rejected').length;
      if (failed) {
        setError(`Tracked ${targets.length - failed} of ${targets.length} competitors — ${failed} failed.`);
      }
      await refreshCompetitors();
    } finally {
      setTrackingBusy((current) => ({
        ...current,
        ...Object.fromEntries(targets.map((competitor) => [competitor.id, false])),
      }));
      setTrackingAllBusy(false);
    }
  };

  const toggleChannels = async (competitorId) => {
    setExpandedChannels((current) => {
      const next = new Set(current);
      if (next.has(competitorId)) next.delete(competitorId);
      else next.add(competitorId);
      return next;
    });
    if (accountsByCompetitor[competitorId]) return;
    try {
      const result = await listAccounts(competitorId);
      setAccountsByCompetitor((current) => ({ ...current, [competitorId]: result.accounts || [] }));
    } catch (caught) {
      setError(caught.message);
    }
  };

  const decideAccount = async (competitorId, accountId, status) => {
    try {
      const result = await validateAccount(accountId, status);
      setAccountsByCompetitor((current) => ({
        ...current,
        [competitorId]: (current[competitorId] || []).map((account) =>
          account.id === accountId ? result.account : account,
        ),
      }));
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    }
  };

  const addSourceToCompetitor = async (competitorId, source) => {
    setSourceBusy((current) => ({ ...current, [competitorId]: true }));
    try {
      const result = await addAccount(competitorId, { ...source, validation_status: 'valid', confidence: 1 });
      setAccountsByCompetitor((current) => ({
        ...current,
        [competitorId]: [...(current[competitorId] || []), result.account],
      }));
      await refreshCompetitors();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSourceBusy((current) => ({ ...current, [competitorId]: false }));
    }
  };

  // Step 5 shows every tracked competitor's channels at once instead of the
  // per-competitor drawer step 4 uses, so make sure they're all loaded the
  // moment this step is reached rather than waiting for a click.
  useEffect(() => {
    if (step !== 5 || dataMode !== 'online') return;
    trackedCompetitors
      .filter((competitor) => !accountsByCompetitor[competitor.id])
      .forEach((competitor) => {
        listAccounts(competitor.id)
          .then((result) => {
            setAccountsByCompetitor((current) => ({ ...current, [competitor.id]: result.accounts || [] }));
          })
          .catch(() => {});
      });
  }, [step, dataMode, trackedCompetitors, accountsByCompetitor]);

  // While the repeat schedule is on, the window's end is derived fresh from
  // the interval on every render - the same start_date/end_date columns
  // Opinion Monitor projects use to scope which article publish dates get
  // pulled in - so "every 7 days" always means a 7-day window with no stale
  // state to keep in sync. Turning the schedule off freezes it at whatever it
  // last resolved to, then hands editing over to the retrievalEnd state.
  const scheduleWindowDays = intervalToDays(scheduleIntervalValue, scheduleIntervalUnit);
  const effectiveRetrievalEnd = scheduleOn ? addDaysIso(retrievalStart, scheduleWindowDays) : retrievalEnd;

  const finish = async () => {
    setError('');
    setBusy(true);
    try {
      // Offline studies have nothing to scrape yet, so scheduling never applies
      // regardless of what the (hidden, for offline) toggle happens to hold.
      await setSchedule(studyId, {
        repeat_enabled: dataMode === 'offline' ? false : scheduleOn,
        repeat_interval_value: Math.max(1, Number(scheduleIntervalValue) || 1),
        repeat_interval_unit: scheduleIntervalUnit,
        repeat_weekdays: scheduleWeekdays,
        start_date: dataMode === 'offline' ? null : retrievalStart || null,
        end_date: dataMode === 'offline' ? null : effectiveRetrievalEnd || null,
      });
      navigate(`/competitors/${studyId}`);
    } catch (caught) {
      setError(caught.message);
      setBusy(false);
    }
  };

  return (
    <div className="cs-page cs-wizard">
      <div className="cs-head">
        <div>
          <h1>New competitor study</h1>
          <p>
            Strata reads your website to understand your market, then lets you add competitors
            yourself — sources you enter are trusted right away. AI suggestions are available if you
            want a head start, but nothing about tracking a competitor requires them.
          </p>
        </div>
      </div>

      <div className="cs-steps" role="list">
        {visibleSteps.map((item, index) => {
          const state = step === item.id ? ' cs-step-active' : step > item.id ? ' cs-step-done' : '';
          const Icon = item.icon;
          // Only steps already completed can be jumped back to — their data is
          // already loaded. A step not yet reached has nothing to show yet, so
          // it stays inert rather than opening a blank/broken panel.
          const clickable = step > item.id;
          return (
            <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button
                type="button"
                className={`cs-step${state}${clickable ? ' cs-step-clickable' : ''}`}
                role="listitem"
                aria-current={step === item.id}
                onClick={clickable ? () => setStep(item.id) : undefined}
                disabled={!clickable}
                title={clickable ? `Back to ${item.label}` : undefined}
              >
                <span className="cs-step-num">
                  {step > item.id ? <Check size={12} /> : index + 1}
                </span>
                <Icon size={14} />
                <span>{item.label}</span>
              </button>
              {index < visibleSteps.length - 1 ? <ChevronRight size={14} className="cs-step-sep" /> : null}
            </div>
          );
        })}
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      ) : null}

      {/* ---------------- Step 1: data source ---------------- */}
      {step === 1 ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Database size={16} /> How should we build this study?</h2>
          <p className="cs-panel-hint">
            Choose where the data comes from. You can start a new study either way.
          </p>

          <div className="cs-mode-grid">
            <button
              type="button"
              className={`cs-mode-card${dataMode === 'online' ? ' cs-mode-card-selected' : ''}`}
              onClick={() => setDataMode('online')}
            >
              <div className="cs-mode-card-icon"><Globe size={20} /></div>
              <div className="cs-mode-card-title">Online — AI discovery</div>
              <p className="cs-mode-card-desc">
                Strata reads your website and the open web to find competitors and their public
                channels automatically, then keeps scraping them on a schedule.
              </p>
            </button>

            <button
              type="button"
              className={`cs-mode-card${dataMode === 'offline' ? ' cs-mode-card-selected' : ''}`}
              onClick={() => setDataMode('offline')}
            >
              <div className="cs-mode-card-icon"><FileText size={20} /></div>
              <div className="cs-mode-card-title">Offline — Upload documents</div>
              <p className="cs-mode-card-desc">
                Upload PDFs, images, Word, Excel or CSV files you already have. Strata reads them into
                articles you review and approve, names the competitors they're about, and runs the
                same analysis an online study would.
              </p>
            </button>
          </div>

          <div className="cs-wizard-foot">
            <span style={{ fontSize: '0.8rem', color: 'var(--text-light)' }}>
              You can add competitors manually later regardless of which you pick.
            </span>
            <button
              type="button"
              className="cs-btn cs-btn-primary"
              onClick={() => setStep(2)}
              disabled={!dataMode}
            >
              <ArrowRight size={15} /> Continue
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 2 (offline): upload documents ---------------- */}
      {step === 2 && dataMode === 'offline' ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Upload size={16} /> Upload your documents</h2>
          <p className="cs-panel-hint">
            Add every file you want this study built from. You can add more later from the workspace
            too — extraction just isn&rsquo;t built yet, so for now these are only saved.
          </p>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-offline-study-name">Study name</label>
            <input
              id="cs-offline-study-name"
              className="cs-input"
              value={studyName}
              placeholder="Q3 competitor study"
              onChange={(event) => setStudyName(event.target.value)}
            />
          </div>

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-offline-files">Files</label>
            <div
              className={`cs-dropzone${dropActive ? ' cs-dropzone-active' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              onDragEnter={(event) => { event.preventDefault(); setDropActive(true); }}
              onDragOver={(event) => { event.preventDefault(); setDropActive(true); }}
              onDragLeave={(event) => { event.preventDefault(); setDropActive(false); }}
              onDrop={(event) => {
                event.preventDefault();
                setDropActive(false);
                addPendingFiles(event.dataTransfer.files);
              }}
            >
              <div className="cs-dropzone-icon"><Upload size={20} /></div>
              <div className="cs-dropzone-title">Drag files here, or click to browse</div>
              <div className="cs-dropzone-hint">Multiple files at once are fine</div>
              <div className="cs-dropzone-types">
                {['PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG'].map((ext) => (
                  <span key={ext} className="cs-pill cs-pill-signal">{ext}</span>
                ))}
              </div>
              <input
                id="cs-offline-files"
                ref={fileInputRef}
                className="cs-sr-only"
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg"
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => {
                  addPendingFiles(event.target.files);
                  event.target.value = '';
                }}
              />
            </div>
          </div>

          {pendingFiles.length ? (
            <div className="cs-rows" style={{ marginBottom: 14 }}>
              {pendingFiles.map((file, index) => (
                <div key={`${file.name}-${index}`} className="cs-row">
                  <div className="cs-row-main">
                    <div className="cs-row-name">{file.name}</div>
                    <div className="cs-row-desc">{(file.size / 1024).toFixed(0)} KB — not uploaded yet</div>
                  </div>
                  <div className="cs-row-side">
                    <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removePendingFile(index)}>
                      <Trash2 size={13} /> Remove
                    </button>
                  </div>
                </div>
              ))}
              <button
                type="button"
                className="cs-btn cs-btn-primary"
                onClick={uploadPendingDocuments}
                disabled={uploadingDocs || !studyName.trim()}
              >
                {uploadingDocs ? <Loader2 size={15} className="cs-spin" /> : <Upload size={15} />}
                {uploadingDocs ? 'Uploading...' : `Upload ${pendingFiles.length} file${pendingFiles.length === 1 ? '' : 's'}`}
              </button>
            </div>
          ) : null}

          {documents.length ? (
            <div className="cs-field">
              <label className="cs-label">
                Uploaded
                <span className="cs-label-hint">
                  {documents.length} file{documents.length === 1 ? '' : 's'}
                  {extractingDocs ? ' — reading contents...' : ''}
                </span>
              </label>
              <div className="cs-rows">
                {documents.map((document) => {
                  const active = document.status === 'uploaded' || document.status === 'processing';
                  const progress = active && document.total_chunks ? ` (${document.processed_chunks || 0}/${document.total_chunks})` : '';
                  const methodLabel = document.extraction_method === 'ocr'
                    ? 'Extracted (OCR)'
                    : document.extraction_method === 'mixed'
                      ? 'Extracted (mixed)'
                      : 'Extracted';
                  return (
                    <div key={document.id} className="cs-row" style={{ alignItems: 'flex-start' }}>
                      <div className="cs-row-main">
                        <div className="cs-row-name">{document.original_filename}</div>
                        <div className="cs-row-desc">{(document.size_bytes / 1024).toFixed(0)} KB</div>
                        {/* Always shown when present — a partial extraction failure
                            (some pages/sheets ok, others not) must not hide behind a
                            plain "Extracted" pill just because status ended up ok. */}
                        {document.extraction_error ? (
                          <div
                            style={{
                              display: 'flex', gap: 6, alignItems: 'flex-start', marginTop: 5,
                              fontSize: '0.79rem', color: '#b91c1c', whiteSpace: 'normal', lineHeight: 1.5,
                            }}
                          >
                            <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 2 }} />
                            <span>{document.extraction_error}</span>
                          </div>
                        ) : null}
                      </div>
                      <div className="cs-row-side">
                        {active ? (
                          <span className="cs-pill cs-pill-pending">
                            <span className="cs-spinner" style={{ width: 11, height: 11 }} /> Reading{progress}...
                          </span>
                        ) : document.status === 'failed' ? (
                          <span className="cs-pill cs-pill-rejected"><AlertTriangle size={11} /> Not extracted</span>
                        ) : (
                          <span className="cs-pill cs-pill-valid"><ScanText size={11} /> {methodLabel}</span>
                        )}
                        <button type="button" className="cs-btn cs-btn-sm cs-btn-danger" onClick={() => removeDocument(document.id)}>
                          <Trash2 size={13} /> Remove
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="cs-empty">
              <div className="cs-empty-icon"><Upload size={20} /></div>
              <h3>No documents yet</h3>
              <p>Choose files above, then upload them to attach them to this study.</p>
            </div>
          )}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(1)} disabled={uploadingDocs}>
              <ArrowLeft size={15} /> Back
            </button>
            <button
              type="button"
              className="cs-btn cs-btn-primary"
              onClick={() => setStep(3)}
              disabled={!documents.length || uploadingDocs}
            >
              <ArrowRight size={15} /> Continue to review articles
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 3 (offline): review extracted articles ---------------- */}
      {step === 3 && dataMode === 'offline' ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><FileCheck size={16} /> Review extracted articles</h2>
          <p className="cs-panel-hint">
            Each item below was split out of one of your documents. Approving one turns it into an
            article your study can run analysis on later, the same way a scraped article would;
            rejecting leaves it out. Nothing here is final — you can leave items pending and decide later.
          </p>

          {reviewingArticles ? (
            <div className="cs-panel" style={{ marginBottom: 16, background: '#fcfdff' }}>
              <div className="cs-progress-row cs-progress-row-active">
                <span className="cs-spinner" />
                <span>Reading your documents into articles...</span>
              </div>
            </div>
          ) : null}

          {!reviewingArticles && !articleCandidates.length ? (
            <div className="cs-empty">
              <div className="cs-empty-icon"><FileCheck size={20} /></div>
              <h3>No articles yet</h3>
              <p>
                {documents.some((document) => document.articles_status === 'failed')
                  ? 'Splitting a document into articles failed — check its error on the upload step.'
                  : 'Nothing usable was found in your documents.'}
              </p>
            </div>
          ) : null}

          {articleCandidates.length ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
                <span style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                  <strong style={{ color: 'var(--text-dark)' }}>{approvedCandidateCount}</strong> approved,{' '}
                  <strong style={{ color: 'var(--text-dark)' }}>{pendingCandidateCount}</strong> pending review
                </span>
                <button
                  type="button"
                  className="cs-btn cs-btn-primary"
                  onClick={approveAllPending}
                  disabled={approvingAll || !pendingCandidateCount}
                >
                  {approvingAll ? <Loader2 size={15} className="cs-spin" /> : <ListChecks size={15} />}
                  {approvingAll ? 'Approving...' : `Approve all${pendingCandidateCount ? ` (${pendingCandidateCount})` : ''}`}
                </button>
              </div>

              {[...candidatesByDocument.entries()].map(([documentId, candidates]) => (
                <div key={documentId} style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: '0.76rem', fontWeight: 650, color: 'var(--text-light)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    {documentById[documentId]?.original_filename || 'Document'}
                  </div>
                  <div className="cs-rows">
                    {candidates.map((candidate) => (
                      <div key={candidate.id} className="cs-row" style={{ alignItems: 'flex-start' }}>
                        <div className="cs-row-main">
                          <div className="cs-row-name">{candidate.title}</div>
                          <div className="cs-row-desc" style={{ whiteSpace: 'normal', maxWidth: 'none' }}>
                            {candidate.summary}
                          </div>
                        </div>
                        <div className="cs-row-side">
                          {candidate.status === 'approved' ? (
                            <span className="cs-pill cs-pill-valid"><Check size={11} /> Approved</span>
                          ) : candidate.status === 'rejected' ? (
                            <span className="cs-pill cs-pill-rejected"><X size={11} /> Rejected</span>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="cs-btn cs-btn-sm cs-btn-danger"
                                disabled={decidingCandidate[candidate.id]}
                                onClick={() => decideCandidate(candidate.id, 'rejected')}
                              >
                                <X size={13} /> Reject
                              </button>
                              <button
                                type="button"
                                className="cs-btn cs-btn-sm cs-btn-primary"
                                disabled={decidingCandidate[candidate.id]}
                                onClick={() => decideCandidate(candidate.id, 'approved')}
                              >
                                {decidingCandidate[candidate.id] ? <Loader2 size={13} className="cs-spin" /> : <Check size={13} />} Approve
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
          ) : null}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(2)}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={() => setStep(5)} disabled={reviewingArticles}>
              <ArrowRight size={15} /> Continue to analysis
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 2 (online): business ---------------- */}
      {step === 2 && dataMode !== 'offline' ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Building2 size={16} /> Tell us about your business</h2>
          <p className="cs-panel-hint">
            The website matters most — we read it to work out which market you are in and how you
            position yourself. Everything after this is judged against that, so a real site gives
            much better competitors than a description alone.
          </p>

          <div className="cs-field">
            <label className="cs-label">Business</label>
            <div className="cs-view-tabs" style={{ marginLeft: 0, marginBottom: 4 }}>
              <button
                type="button"
                className={`cs-view-tab${businessMode === 'new' ? ' active' : ''}`}
                onClick={() => switchBusinessMode('new')}
              >
                <Plus size={13} /> Create new
              </button>
              <button
                type="button"
                className={`cs-view-tab${businessMode === 'existing' ? ' active' : ''}`}
                onClick={() => switchBusinessMode('existing')}
              >
                <Search size={13} /> Choose existing
              </button>
            </div>
          </div>

          {businessMode === 'existing' ? (
            <div className="cs-field">
              <div style={{ position: 'relative' }}>
                <div className="cs-search-field">
                  <Search size={14} />
                  <input
                    value={businessSearch}
                    placeholder="Search a business you've studied before..."
                    onChange={(event) => setBusinessSearch(event.target.value)}
                  />
                </div>
                {filteredExistingBusinesses.length ? (
                  <div className="cs-dropdown" style={{ position: 'static', marginTop: 8 }}>
                    {filteredExistingBusinesses.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className="cs-dropdown-item"
                        style={selectedBusinessId === item.id
                          ? { background: '#f1f5f9', fontWeight: 600 } : undefined}
                        onClick={() => chooseExistingBusiness(item)}
                      >
                        {item.business_name}
                        {item.business_website ? (
                          <span style={{ marginLeft: 8, fontWeight: 400, color: 'var(--text-light)' }}>
                            {item.business_website}
                          </span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              {loadingBusinesses ? (
                <p className="cs-panel-hint"><Loader2 size={13} className="cs-spin" /> Loading past businesses...</p>
              ) : null}
              {!loadingBusinesses && !existingBusinesses.length ? (
                <p className="cs-panel-hint">No previous business profiles yet — switch to "Create new" above.</p>
              ) : null}
              {selectedBusinessProfile ? (
                <>
                  <div className="cs-alert cs-alert-info" style={{ marginTop: 10 }}>
                    <CheckCircle2 size={16} style={{ flexShrink: 0 }} />
                    <span>
                      Reusing <strong>{selectedBusinessProfile.name}</strong>&rsquo;s market context — no
                      re-scraping or AI wait needed. You can still edit it on the next step.
                    </span>
                  </div>
                  <CountryPicker
                    label="Target countries"
                    hint="carried over from that business — edit for this study"
                    values={targetCountries}
                    onChange={setTargetCountries}
                  />
                </>
              ) : null}
            </div>
          ) : null}

          {businessMode === 'new' ? (
            <>
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-biz-name">Business name</label>
                <input
                  id="cs-biz-name"
                  className="cs-input"
                  value={business.name}
                  placeholder="Northwind Analytics"
                  onChange={(event) => setBusiness({ ...business, name: event.target.value })}
                />
              </div>

              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-biz-site">
                  Website<span className="cs-label-hint">strongly recommended</span>
                </label>
                <input
                  id="cs-biz-site"
                  className="cs-input"
                  value={business.website}
                  placeholder="northwind.com"
                  onChange={(event) => setBusiness({ ...business, website: event.target.value })}
                />
              </div>

              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-biz-desc">
                  Anything else<span className="cs-label-hint">optional</span>
                </label>
                <textarea
                  id="cs-biz-desc"
                  className="cs-textarea"
                  value={business.description}
                  placeholder="What you sell, who buys it, which markets you care about."
                  onChange={(event) => setBusiness({ ...business, description: event.target.value })}
                />
              </div>

              <CountryPicker
                label="Target countries"
                hint="optional — leave blank to search globally"
                values={targetCountries}
                onChange={setTargetCountries}
              />
            </>
          ) : null}

          <div className="cs-field">
            <label className="cs-label" htmlFor="cs-study-name">
              Study name<span className="cs-label-hint">defaults to your business name</span>
            </label>
            <input
              id="cs-study-name"
              className="cs-input"
              value={studyName}
              placeholder={business.name ? `${business.name} - competitor study` : 'Q3 competitor study'}
              onChange={(event) => setStudyName(event.target.value)}
            />
          </div>

          {busy && businessMode === 'new' ? (
            <div className="cs-panel" style={{ marginTop: 18, background: '#fcfdff' }}>
              <StageList stages={SCRAPE_STAGES} />
            </div>
          ) : null}

          <div className="cs-wizard-foot">
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(1)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-light)' }}>
                {businessMode === 'existing'
                  ? 'Reusing a saved profile skips the website read entirely.'
                  : 'Reading your site takes about 20-40 seconds — or skip that and write the context yourself.'}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {businessMode === 'existing' ? (
                <button
                  type="button"
                  className="cs-btn cs-btn-primary"
                  onClick={continueWithExistingBusiness}
                  disabled={!selectedBusinessProfile || busy}
                >
                  {busy ? <Loader2 size={15} className="cs-spin" /> : <ArrowRight size={15} />}
                  {busy ? 'Saving...' : 'Continue with this business'}
                </button>
              ) : (
                <>
                  <button type="button" className="cs-btn" onClick={submitBusinessManually} disabled={!canLeaveStep1 || busy}>
                    {busy && step1Mode === 'manual' ? <Loader2 size={15} className="cs-spin" /> : <Building2 size={15} />}
                    Write manually
                  </button>
                  <button type="button" className="cs-btn cs-btn-primary" onClick={submitBusiness} disabled={!canLeaveStep1 || busy}>
                    {busy && step1Mode === 'ai' ? <Loader2 size={15} className="cs-spin" /> : <ArrowRight size={15} />}
                    {busy && step1Mode === 'ai' ? 'Reading your site...' : 'Read my site with AI'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 3: market context ---------------- */}
      {step === 3 && profile ? (
        <>
          {scrape ? (
            <div className={`cs-alert ${scrape.status === 'success' ? 'cs-alert-info' : 'cs-alert-warn'}`}>
              {scrape.status === 'success' ? <Globe size={16} style={{ flexShrink: 0 }} /> : <AlertTriangle size={16} style={{ flexShrink: 0 }} />}
              <span>
                {scrape.status === 'success'
                  ? `Read ${scrape.pages.length} page${scrape.pages.length === 1 ? '' : 's'} from your site (${scrape.chars.toLocaleString()} characters). Check the context below — competitors are found from it.`
                  : `Could not read your website${scrape.error ? `: ${scrape.error}` : '.'} Fill the fields in below so discovery still has something to work from.`}
              </span>
            </div>
          ) : null}

          <div className="cs-panel">
            <h2 className="cs-panel-title"><Sparkles size={16} /> What we understood</h2>
            <p className="cs-panel-hint">
              Edit anything that is off. This is the description competitors get matched against and
              that every &ldquo;how does this affect us&rdquo; judgement is measured by.
            </p>

            <div className="cs-grid-2">
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-industry">Industry</label>
                <input id="cs-industry" className="cs-input" value={profile.industry || ''}
                  onChange={(event) => setProfile({ ...profile, industry: event.target.value })} />
              </div>
              <div className="cs-field">
                <label className="cs-label" htmlFor="cs-market">Market you compete in</label>
                <input id="cs-market" className="cs-input" value={profile.market || ''}
                  onChange={(event) => setProfile({ ...profile, market: event.target.value })} />
              </div>
            </div>

            <div className="cs-field">
              <label className="cs-label" htmlFor="cs-positioning">Positioning</label>
              <input id="cs-positioning" className="cs-input" value={profile.positioning || ''}
                onChange={(event) => setProfile({ ...profile, positioning: event.target.value })} />
            </div>

            <ListEditor label="What you offer" values={profile.offerings}
              placeholder="demand forecasting"
              onChange={(offerings) => setProfile({ ...profile, offerings })} />
            <ListEditor label="Who buys it" values={profile.audience}
              placeholder="operations directors"
              onChange={(audience) => setProfile({ ...profile, audience })} />
            <ListEditor label="What sets you apart" hint="used to judge competitor moves"
              values={profile.differentiators} placeholder="implementation in under 30 days"
              onChange={(differentiators) => setProfile({ ...profile, differentiators })} />

            <div className="cs-field">
              <label className="cs-label" htmlFor="cs-context">Market context</label>
              <textarea id="cs-context" className="cs-textarea" style={{ minHeight: 110 }}
                value={profile.context_summary || ''}
                onChange={(event) => setProfile({ ...profile, context_summary: event.target.value })} />
            </div>

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(2)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <button type="button" className="cs-btn cs-btn-primary" onClick={submitContext} disabled={busy}>
                {busy ? <span className="cs-spinner" /> : <ArrowRight size={15} />}
                {busy ? 'Saving...' : 'Continue to competitors'}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {/* ---------------- Step 4: competitors ---------------- */}
      {step === 4 ? (
        <>
          <div className="cs-panel">
            <h2 className="cs-panel-title"><Building2 size={16} /> Add your competitors</h2>
            <p className="cs-panel-hint">
              Add the companies you compete with directly. Sources you enter here are trusted
              immediately and start scraping right away.
            </p>
            <AddCompetitorForm onSubmit={handleAddManualCompetitor} busy={addingManual} />
          </div>

          <div className="cs-panel">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <h2 className="cs-panel-title" style={{ marginBottom: 4 }}>
                  <Sparkles size={16} /> Not sure who else to add?
                </h2>
                <p className="cs-panel-hint" style={{ marginBottom: 0 }}>
                  Optional — AI compares your profile against the market and suggests competitors to
                  review. Track the ones you want, and their channels are found automatically.
                </p>
              </div>
              <button type="button" className="cs-btn" onClick={runAiSuggest} disabled={discovering}>
                {discovering ? <span className="cs-spinner" /> : <Sparkles size={15} />}
                {discovering ? 'Suggesting...' : 'Suggest competitors with AI'}
              </button>
            </div>

            {discovering ? (
              <div className="cs-panel" style={{ marginTop: 14, background: '#fcfdff' }}>
                <StageList stages={DISCOVERY_STAGES} />
              </div>
            ) : null}
            {discovering ? <DiscoveryLog logs={discoveryLogs} active={discovering} /> : null}

            {rejected.length ? (
              <details style={{ marginTop: 16 }}>
                <summary style={{ cursor: 'pointer', fontSize: '0.82rem', color: 'var(--text-light)' }}>
                  {rejected.length} suggestion{rejected.length === 1 ? '' : 's'} dropped during checking
                </summary>
                <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {rejected.map((item) => (
                    <div key={item.name} style={{ fontSize: '0.81rem', color: 'var(--text-light)' }}>
                      <strong style={{ color: 'var(--text-dark)' }}>{item.name}</strong> — {item.reason}
                    </div>
                  ))}
                </div>
              </details>
            ) : null}
          </div>

          <div className="cs-panel">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <h2 className="cs-panel-title" style={{ marginBottom: 4 }}><Radar size={16} /> Your competitors</h2>
                <p className="cs-panel-hint" style={{ marginBottom: 0 }}>
                  <strong>{trackedCompetitors.length}</strong> tracked. Channels are found and used
                  immediately once a competitor is tracked, manual or AI-suggested.
                </p>
              </div>
              {untrackedCompetitors.length ? (
                <button type="button" className="cs-btn cs-btn-sm" onClick={trackAllCompetitors} disabled={trackingAllBusy}>
                  {trackingAllBusy ? <span className="cs-spinner" /> : <Check size={13} />}
                  {trackingAllBusy ? 'Tracking all...' : `Track all (${untrackedCompetitors.length})`}
                </button>
              ) : null}
            </div>

            {!competitors.length ? (
              <div className="cs-empty">
                <div className="cs-empty-icon"><Search size={20} /></div>
                <h3>No competitors yet</h3>
                <p>Add one above, or suggest some with AI.</p>
              </div>
            ) : (
              <div className="cs-rows">
                {competitors.map((competitor) => {
                  const channelsOpen = expandedChannels.has(competitor.id);
                  const accounts = accountsByCompetitor[competitor.id];
                  const isManual = competitor.discovery_source === 'manual';
                  const tracked = competitor.status === 'tracked';
                  return (
                    <div key={competitor.id}>
                      <div className={`cs-row${tracked ? ' cs-row-selected' : ''}`}>
                        <span className="cs-row-rank">{competitor.size_rank ?? '-'}</span>
                        <div
                          className="cs-avatar"
                          style={{ background: avatarGradient(competitor.name), width: 30, height: 30, fontSize: '0.72rem' }}
                          aria-hidden="true"
                        >
                          {initials(competitor.name)}
                        </div>
                        <div className="cs-row-main">
                          <div className="cs-row-name">{competitor.name}</div>
                          <div className="cs-row-desc">
                            {competitor.description || competitor.size_signals?.why_competitor || competitor.domain || '—'}
                          </div>
                        </div>
                        <div className="cs-row-side">
                          <span className={`cs-pill ${isManual ? 'cs-pill-manual' : 'cs-pill-ai'}`}>
                            {isManual ? 'Manual' : 'AI suggested'}
                          </span>
                          {competitor.country ? (
                            <span className="cs-pill cs-pill-signal" title="Where this company is headquartered">
                              Based in {countryLabel(competitor.country)}
                            </span>
                          ) : null}
                          {Array.isArray(competitor.operates_in_countries) && competitor.operates_in_countries.length ? (
                            <span
                              className="cs-pill cs-pill-signal"
                              title="Where this competitor actually competes with your business"
                            >
                              Competes in {competitor.operates_in_countries.map(countryLabel).join(', ')}
                            </span>
                          ) : null}
                          <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                            {SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}
                          </span>
                          {tracked && unverified[competitor.id] ? (
                            <span
                              className="cs-pill cs-pill-signal"
                              title="Tracked, but a live web check couldn't confirm this company exists — worth a manual look."
                            >
                              Couldn’t verify
                            </span>
                          ) : null}
                          <button type="button" className="cs-btn cs-btn-sm" onClick={() => toggleChannels(competitor.id)}>
                            <Link2 size={13} /> {channelsOpen ? 'Hide sources' : 'Sources'}
                          </button>
                          <button
                            type="button"
                            className={`cs-btn cs-btn-sm${tracked ? ' cs-btn-primary' : ''}`}
                            onClick={() => toggleTracking(competitor)}
                            disabled={Boolean(trackingBusy[competitor.id])}
                          >
                            {trackingBusy[competitor.id] ? (
                              <span className="cs-spinner" />
                            ) : tracked ? (
                              <><Check size={13} /> Tracking</>
                            ) : (
                              'Track'
                            )}
                          </button>
                        </div>
                      </div>

                      {channelsOpen ? (
                        <div className="cs-rows" style={{ marginLeft: 30, marginBottom: 14 }}>
                          {!accounts ? (
                            <div className="cs-row-desc" style={{ padding: '8px 0' }}>Loading sources...</div>
                          ) : (
                            accounts.map((account) => (
                              <div key={account.id} className="cs-row">
                                <div className="cs-row-main">
                                  <div className="cs-row-name">
                                    {PLATFORM_LABELS[account.platform] || account.platform}
                                    {account.handle ? <span style={{ fontWeight: 400, color: 'var(--text-light)' }}> @{account.handle}</span> : null}
                                  </div>
                                  <div className="cs-row-desc">{account.url}</div>
                                </div>
                                <div className="cs-row-side">
                                  <span className={`cs-pill cs-pill-${account.validation_status}`}>
                                    {account.validation_status}
                                  </span>
                                  {account.validation_status !== 'rejected' ? (
                                    <button type="button" className="cs-btn cs-btn-sm cs-btn-danger"
                                      onClick={() => decideAccount(competitor.id, account.id, 'rejected')}>
                                      <Trash2 size={13} /> Not theirs
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                            ))
                          )}
                          <AddSourceRow
                            busy={Boolean(sourceBusy[competitor.id])}
                            onSubmit={(source) => addSourceToCompetitor(competitor.id, source)}
                          />
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}

            {findingChannels ? (
              <div className="cs-panel" style={{ marginTop: 14, background: '#fcfdff' }}>
                <StageList stages={CHANNEL_STAGES} />
              </div>
            ) : null}
            {findingChannels ? <DiscoveryLog logs={discoveryLogs} active={findingChannels} /> : null}

            <div className="cs-wizard-foot">
              <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(3)} disabled={busy}>
                <ArrowLeft size={15} /> Back
              </button>
              <button
                type="button"
                className="cs-btn cs-btn-primary"
                onClick={continueToChannels}
                disabled={busy || findingChannels || !trackedCompetitors.length}
              >
                {findingChannels ? <Loader2 size={15} className="cs-spin" /> : <ArrowRight size={15} />}
                {findingChannels
                  ? 'Finding channels...'
                  : `Continue with ${trackedCompetitors.length} competitor${trackedCompetitors.length === 1 ? '' : 's'}`}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {/* ---------------- Step 5 (online): review channels ---------------- */}
      {step === 5 && dataMode !== 'offline' ? (
        <div className="cs-panel">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <h2 className="cs-panel-title" style={{ marginBottom: 4 }}><Link2 size={16} /> Review channels</h2>
              <p className="cs-panel-hint" style={{ marginBottom: 0 }}>
                Every channel found for your tracked competitors is listed below and already included —
                discard any that aren&rsquo;t actually theirs, or add one yourself if something&rsquo;s missing.
              </p>
            </div>
            {channellessTracked > 0 ? (
              <button type="button" className="cs-btn cs-btn-sm" onClick={findMoreChannels} disabled={findingChannels}>
                {findingChannels ? <span className="cs-spinner" /> : <Search size={13} />}
                {findingChannels ? 'Finding...' : `Find more channels (${channellessTracked})`}
              </button>
            ) : null}
          </div>

          {findingChannels ? (
            <div className="cs-panel" style={{ marginTop: 14, background: '#fcfdff' }}>
              <StageList stages={CHANNEL_STAGES} />
            </div>
          ) : null}
          {findingChannels ? <DiscoveryLog logs={discoveryLogs} active={findingChannels} /> : null}

          {!findingChannels && !trackedCompetitors.length ? (
            <div className="cs-empty">
              <div className="cs-empty-icon"><Link2 size={20} /></div>
              <h3>No tracked competitors</h3>
              <p>Go back and track at least one competitor first.</p>
            </div>
          ) : null}

          {!findingChannels ? trackedCompetitors.map((competitor) => {
            const accounts = accountsByCompetitor[competitor.id];
            return (
              <div key={competitor.id} style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div
                    className="cs-avatar"
                    style={{ background: avatarGradient(competitor.name), width: 26, height: 26, fontSize: '0.68rem' }}
                    aria-hidden="true"
                  >
                    {initials(competitor.name)}
                  </div>
                  <strong style={{ fontSize: '0.88rem' }}>{competitor.name}</strong>
                </div>
                <div className="cs-rows" style={{ marginLeft: 30 }}>
                  {!accounts ? (
                    <div className="cs-row-desc" style={{ padding: '8px 0' }}>Loading channels...</div>
                  ) : !accounts.length ? (
                    <div className="cs-row-desc" style={{ padding: '8px 0' }}>No channels found yet.</div>
                  ) : (
                    accounts.map((account) => (
                      <div key={account.id} className="cs-row">
                        <div className="cs-row-main">
                          <div className="cs-row-name">
                            {PLATFORM_LABELS[account.platform] || account.platform}
                            {account.handle ? <span style={{ fontWeight: 400, color: 'var(--text-light)' }}> @{account.handle}</span> : null}
                          </div>
                          <div className="cs-row-desc">{account.url}</div>
                        </div>
                        <div className="cs-row-side">
                          <span className={`cs-pill cs-pill-${account.validation_status}`}>
                            {account.validation_status}
                          </span>
                          {account.validation_status !== 'rejected' ? (
                            <button type="button" className="cs-btn cs-btn-sm cs-btn-danger"
                              onClick={() => decideAccount(competitor.id, account.id, 'rejected')}>
                              <Trash2 size={13} /> Not theirs
                            </button>
                          ) : null}
                        </div>
                      </div>
                    ))
                  )}
                  <AddSourceRow
                    busy={Boolean(sourceBusy[competitor.id])}
                    onSubmit={(source) => addSourceToCompetitor(competitor.id, source)}
                  />
                </div>
              </div>
            );
          }) : null}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(4)} disabled={busy}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={() => setStep(6)} disabled={busy}>
              <ArrowRight size={15} /> Continue
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 5 (offline): analyze + report ---------------- */}
      {step === 5 && dataMode === 'offline' ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><ScanText size={16} /> Analyze & report</h2>
          <p className="cs-panel-hint">
            {documents.length} document{documents.length === 1 ? '' : 's'} uploaded,{' '}
            {approvedCandidateCount} article{approvedCandidateCount === 1 ? '' : 's'} approved.
            We&rsquo;ll read those articles for the companies they&rsquo;re actually about, track each
            one, then generate a report card per company — the same report an AI-discovered study gets,
            just built from what you uploaded instead of a live scrape. You can re-run this later from
            the workspace once you approve more documents.
          </p>

          {analyzingDocuments ? <StageList stages={DOCUMENT_ANALYSIS_STAGES} /> : null}

          {!analyzingDocuments && documentAnalysis ? (
            <div className="cs-alert cs-alert-info" style={{ marginBottom: 16 }}>
              <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                Generated {documentAnalysis.generated} report{documentAnalysis.generated === 1 ? '' : 's'} from{' '}
                {documentAnalysis.articles_considered} approved article{documentAnalysis.articles_considered === 1 ? '' : 's'}
                {documentAnalysis.derived_competitors?.length
                  ? `, covering ${documentAnalysis.derived_competitors.map((c) => c.name).join(', ')}`
                  : ''}.
                {documentAnalysis.skipped?.length ? (
                  <> {documentAnalysis.skipped.length} competitor{documentAnalysis.skipped.length === 1 ? '' : 's'} had no
                    usable evidence.</>
                ) : null}
                {documentAnalysis.derivation_error ? <> {documentAnalysis.derivation_error}</> : null}
              </span>
            </div>
          ) : null}

          {!analyzingDocuments ? (
            <button type="button" className="cs-btn cs-btn-primary" onClick={runDocumentAnalysis} style={{ marginBottom: 16 }}>
              <Sparkles size={15} /> {documentAnalysis ? 'Re-run analysis' : 'Run analysis'}
            </button>
          ) : null}

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(3)} disabled={busy}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={finish} disabled={busy}>
              {busy ? <span className="cs-spinner" /> : <CheckCircle2 size={15} />} Open workspace
            </button>
          </div>
        </div>
      ) : null}

      {/* ---------------- Step 6 (online): schedule + finish ---------------- */}
      {step === 6 && dataMode !== 'offline' ? (
        <div className="cs-panel">
          <h2 className="cs-panel-title"><Globe size={16} /> Keep it current</h2>
          <p className="cs-panel-hint">
            {trackedCompetitors.length} competitor{trackedCompetitors.length === 1 ? '' : 's'} ready to
            track. Re-scrape their sources on a schedule, using the same pipeline scheduler as the
            rest of Strata.
          </p>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.88rem', marginBottom: 14 }}>
            <input
              type="checkbox"
              checked={scheduleOn}
              onChange={(event) => {
                const checked = event.target.checked;
                // Freeze the derived end date into editable state right as the
                // toggle turns off, so the field doesn't go blank.
                if (!checked) setRetrievalEnd(effectiveRetrievalEnd);
                setScheduleOn(checked);
              }}
            />
            Scrape competitors automatically
          </label>
          {scheduleOn ? (
            <div className="cs-panel" style={{ margin: '0 0 4px', background: '#fcfdff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: '0.88rem', flexWrap: 'wrap' }}>
                <span>Every</span>
                <input className="cs-input" type="number" min="1" style={{ width: 78 }}
                  value={scheduleIntervalValue} onChange={(event) => setScheduleIntervalValue(event.target.value)} />
                <select
                  className="cs-input"
                  style={{ width: 130 }}
                  value={scheduleIntervalUnit}
                  onChange={(event) => setScheduleIntervalUnit(event.target.value)}
                >
                  {REPEAT_UNIT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div style={{ marginTop: 14 }}>
                <WeekdayPicker values={scheduleWeekdays} onChange={setScheduleWeekdays} />
              </div>
            </div>
          ) : null}

          <div className="cs-field" style={{ marginTop: 18 }}>
            <label className="cs-label">
              Data retrieval window
              <span className="cs-label-hint">
                {scheduleOn ? 'optional — end date follows your repeat schedule when start is set' : 'optional'}
              </span>
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
              <input
                className="cs-input"
                type="date"
                style={{ width: 160 }}
                value={retrievalStart}
                onChange={(event) => setRetrievalStart(event.target.value)}
              />
              <span style={{ color: 'var(--text-light)' }}>to</span>
              <input
                className="cs-input"
                type="date"
                style={{ width: 160 }}
                value={effectiveRetrievalEnd}
                min={retrievalStart || undefined}
                disabled={scheduleOn}
                onChange={(event) => setRetrievalEnd(event.target.value)}
              />
            </div>
            <p className="cs-panel-hint" style={{ marginTop: 8, marginBottom: 0 }}>
              {scheduleOn
                ? `Optional — scopes which article publish dates get pulled in, kept at ${scheduleWindowDays} day(s) wide to match "every ${Math.max(1, Number(scheduleIntervalValue) || 1)} ${scheduleIntervalUnit}" above when a start date is set. Leave the start date blank to pull in articles from any date instead.`
                : 'Optional — scopes which article publish dates get pulled in. Leave blank to pull in articles from any date.'}
            </p>
          </div>

          <div className="cs-wizard-foot">
            <button type="button" className="cs-btn cs-btn-ghost" onClick={() => setStep(5)} disabled={busy}>
              <ArrowLeft size={15} /> Back
            </button>
            <button type="button" className="cs-btn cs-btn-primary" onClick={finish} disabled={busy}>
              {busy ? <span className="cs-spinner" /> : <CheckCircle2 size={15} />} Open workspace
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
