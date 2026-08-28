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
 */

import { useEffect, useState } from 'react';
import {
  analyze, getAnalysisScope, listAnalysisRuns, pollAnalysisRun,
} from './api/competitorApi.js';

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

export function useRunAnalysis(studyId, { onSuccess, onError } = {}) {
  const [analyzing, setAnalyzing] = useState(false);
  const [showRunChoice, setShowRunChoice] = useState(false);
  const [scope, setScope] = useState('pending');
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [analysisRuns, setAnalysisRuns] = useState([]);
  const [analysisLogs, setAnalysisLogs] = useState([]);

  const refreshScope = async () => {
    if (!studyId) return;
    try {
      const result = await getAnalysisScope(studyId);
      setDocuments(result.documents || []);
    } catch {
      setDocuments([]);
    }
  };

  const refreshRuns = async () => {
    if (!studyId) return;
    try {
      const result = await listAnalysisRuns(studyId);
      setAnalysisRuns(result.runs || []);
    } catch {
      setAnalysisRuns([]);
    }
  };

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

  const eligibleDocuments = documents.filter((document) => document.approved_article_count > 0);
  const pendingDocuments = eligibleDocuments.filter((document) => !document.analyzed);

  const runAnalysis = async () => {
    setShowRunChoice(false);
    setAnalyzing(true);
    setAnalysisLogs([]);
    try {
      const queued = await analyze(studyId, {
        scope,
        document_ids: scope === 'selected' ? selectedDocumentIds : undefined,
      });
      const run = await pollAnalysisRun(studyId, queued.run_id, (r) => setAnalysisLogs(r.logs || []));
      if (run.status === 'failed') throw new Error(run.error || 'Analysis failed.');
      // The run just changed which documents count as "analyzed" and added
      // itself to the run history - both need to be current before the next
      // dialog open or toolbar filter reflects reality.
      await Promise.all([refreshScope(), refreshRuns()]);
      onSuccess?.(run);
    } catch (caught) {
      onError?.(caught.message);
    } finally {
      setAnalyzing(false);
    }
  };

  return {
    analyzing, showRunChoice, setShowRunChoice,
    scope, setScope, documents, eligibleDocuments, pendingDocuments,
    selectedDocumentIds, setSelectedDocumentIds,
    analysisRuns, analysisLogs, runAnalysis,
  };
}
