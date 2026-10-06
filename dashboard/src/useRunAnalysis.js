/**
 * "Run analysis" is the same flow (scope picker, queue, poll, log) on every
 * page that offers it - Reports and Competitors both need it as their first
 * action - so it lives here once instead of copied per page. Each page owns
 * what happens to the result via onSuccess/onError. Split out of
 * CompetitorRunAnalysis.jsx (which stays component-only) because a file
 * mixing hooks/constants with components breaks React Fast Refresh.
 *
 * Scope replaced the old period_days/pipeline_run_id date-window picker:
 * document-based evidence isn't meaningfully time-windowed (see
 * document_analysis.py's own reasoning for always passing period_days=None),
 * so which *documents* a run reads is the choice that actually matters here.
 *
 * The run-in-progress state (analyzing/logs) lives in a module-level store
 * keyed by studyId rather than component state: a study's workspace, its
 * "manage competitors" page and its documents page are separate routes a
 * user moves between like tabs, and a run that takes minutes must keep
 * showing as in-progress - button disabled, log still streaming - across
 * that navigation instead of resetting every time the page remounts.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  analyze, getAnalysisScope, listAnalysisRuns, pollAnalysisRun,
} from './api/competitorApi.js';
import { stopPipelineRun } from './api/pipelineRunsApi.js';

export const SCOPE_LABELS = {
  pending: 'Documents not yet analyzed',
  all: 'All documents',
  selected: 'Selected documents',
};

function formatAnalysisRunLabel(run) {
  const value = run?.finished_at || run?.started_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return 'Run';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export function analysisRunTitle(run) {
  return `Analysis #${run?.sequence_number ?? '?'}: ${formatAnalysisRunLabel(run)}`;
}

const ACTIVE_RUN_STATUSES = ['queued', 'running'];

// --- shared, per-study run-watch store --------------------------------------
// One in-flight poll per study, however many pages/components currently
// render it - re-entering a page that's already watching a run reattaches to
// the same state instead of starting a second poll loop or losing the log.
const watchStates = new Map(); // studyId -> { analyzing, logs, terminalRun, runId }
const watchListeners = new Map(); // studyId -> Set<listener>
// useSyncExternalStore requires getSnapshot to return a stable reference when
// nothing changed - a fresh {} literal on every call for a study with no
// entry yet would look like a change on every render and loop forever.
const IDLE_WATCH_STATE = { analyzing: false, logs: [], terminalRun: null, runId: null };

function getWatchState(studyId) {
  return watchStates.get(studyId) || IDLE_WATCH_STATE;
}

function setWatchState(studyId, patch) {
  watchStates.set(studyId, { ...getWatchState(studyId), ...patch });
  (watchListeners.get(studyId) || []).forEach((listener) => listener());
}

function subscribeWatch(studyId, listener) {
  if (!watchListeners.has(studyId)) watchListeners.set(studyId, new Set());
  watchListeners.get(studyId).add(listener);
  return () => watchListeners.get(studyId)?.delete(listener);
}

// Starts (or, if one is already running, simply returns - the existing poll
// already covers it) the background watch for one study's run. Pushed state
// is consumed by every mounted useRunAnalysis(studyId) instance; which page
// happens to be mounted when the run finishes reacts via the effect below.
function watchRun(studyId, runId) {
  if (getWatchState(studyId).analyzing) return;
  setWatchState(studyId, { analyzing: true, logs: [], terminalRun: null, runId });
  (async () => {
    try {
      const run = await pollAnalysisRun(studyId, runId, (r) => setWatchState(studyId, { logs: r.logs || [] }));
      setWatchState(studyId, { analyzing: false, terminalRun: run });
    } catch (caught) {
      setWatchState(studyId, {
        analyzing: false,
        terminalRun: { status: 'failed', error: caught.message },
      });
    }
  })();
}

export function useRunAnalysis(studyId, { onSuccess, onError } = {}) {
  const watchState = useSyncExternalStore(
    (listener) => subscribeWatch(studyId, listener),
    () => getWatchState(studyId),
  );
  const [showRunChoice, setShowRunChoice] = useState(false);
  const [scope, setScope] = useState('pending');
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [analysisRuns, setAnalysisRuns] = useState([]);
  const [stopping, setStopping] = useState(false);

  // Seeded with whatever terminal run already exists at mount time, so a run
  // that finished before this page opened (or before it was last reopened)
  // is treated as "already handled" rather than replaying its success/error
  // notice every time the page is revisited - only a run that finishes while
  // this instance is actually mounted should fire onSuccess/onError.
  const handledRunRef = useRef(watchState.terminalRun);

  // Read via refs inside the terminal-run effect below instead of listed as
  // effect dependencies - these are freshly recreated every render by
  // whichever page is currently mounted, and the effect should always call
  // whichever version is current without re-running itself on every render.
  const onSuccessRef = useRef(onSuccess);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onSuccessRef.current = onSuccess;
    onErrorRef.current = onError;
  });

  const refreshScope = useCallback(async () => {
    if (!studyId) return;
    try {
      const result = await getAnalysisScope(studyId);
      setDocuments(result.documents || []);
    } catch {
      setDocuments([]);
    }
  }, [studyId]);

  const refreshRuns = useCallback(async () => {
    if (!studyId) return;
    try {
      const result = await listAnalysisRuns(studyId);
      setAnalysisRuns(result.runs || []);
    } catch {
      setAnalysisRuns([]);
    }
  }, [studyId]);

  // A study is a project, so its documents/run-history are fetched here so
  // the dialog can offer "not yet analyzed" counts and a hand-pick checklist,
  // and the reports toolbar can filter by a specific past run.
  useEffect(() => {
    if (!studyId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const [scopeResult, runsResult] = await Promise.all([
          getAnalysisScope(studyId),
          listAnalysisRuns(studyId),
        ]);
        if (cancelled) return;
        setDocuments(scopeResult.documents || []);
        setAnalysisRuns(runsResult.runs || []);
        // A run started elsewhere (another page, another user, or this page
        // having been reloaded mid-run) is still queued/running in the
        // backend even though a freshly-mounted watch state starts out
        // idle - without this, "Run analysis" would re-enable and a second
        // click would just attach to the same run (see analyze()'s
        // active-run dedupe) while looking, misleadingly, like nothing was
        // happening.
        const active = (runsResult.runs || []).find((candidate) => ACTIVE_RUN_STATUSES.includes(candidate.status));
        if (active) watchRun(studyId, active.id);
      } catch {
        if (!cancelled) {
          setDocuments([]);
          setAnalysisRuns([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId]);

  // Reacts once per finished run, however this page came to be watching it -
  // a run it queued itself, or one it discovered already in flight above.
  useEffect(() => {
    const run = watchState.terminalRun;
    if (!run || handledRunRef.current === run) return undefined;
    handledRunRef.current = run;
    if (run.status === 'failed') {
      onErrorRef.current?.(run.error || 'Analysis failed.');
      return undefined;
    }
    let cancelled = false;
    (async () => {
      // The run just changed which documents count as "analyzed" and added
      // itself to the run history - both need to be current before the next
      // dialog open or toolbar filter reflects reality.
      await Promise.all([refreshScope(), refreshRuns()]);
      // A stopped run still changes the run history, but it is not a result to announce.
      if (!cancelled && run.status !== 'cancelled') onSuccessRef.current?.(run);
    })();
    return () => {
      cancelled = true;
    };
  }, [watchState.terminalRun, refreshScope, refreshRuns]);

  const eligibleDocuments = documents.filter((document) => document.approved_article_count > 0);
  const pendingDocuments = eligibleDocuments.filter((document) => !document.analyzed);

  const runAnalysis = async () => {
    setShowRunChoice(false);
    try {
      const queued = await analyze(studyId, {
        scope,
        document_ids: scope === 'selected' ? selectedDocumentIds : undefined,
      });
      watchRun(studyId, queued.run_id);
    } catch (caught) {
      onError?.(caught.message);
    }
  };

  // The backend ends the run at its next checkpoint (not mid LLM call), and the
  // poll then delivers the 'cancelled' terminal run, which clears `analyzing`.
  const stopAnalysis = async () => {
    if (!watchState.runId || stopping) return;
    setStopping(true);
    try {
      await stopPipelineRun(String(watchState.runId));
    } catch (caught) {
      onError?.(caught.message);
    } finally {
      setStopping(false);
    }
  };

  return {
    analyzing: watchState.analyzing, stopping, stopAnalysis, showRunChoice, setShowRunChoice,
    scope, setScope, documents, eligibleDocuments, pendingDocuments,
    selectedDocumentIds, setSelectedDocumentIds,
    analysisRuns, analysisLogs: watchState.logs, runAnalysis,
  };
}
