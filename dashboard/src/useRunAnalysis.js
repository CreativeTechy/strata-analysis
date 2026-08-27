/**
 * "Run analysis" is the same flow (period/run picker, queue, poll, log) on
 * every page that offers it - Reports and Competitors both need it as their
 * first action - so it lives here once instead of copied per page. Each page
 * owns what happens to the result via onSuccess/onError. Split out of
 * CompetitorRunAnalysis.jsx (which stays component-only) because a file
 * mixing hooks/constants with components breaks React Fast Refresh.
 */

import { useEffect, useRef, useState } from 'react';
import { analyze, pollAnalysisRun } from './competitorApi.js';

// How far back analysis looks for evidence. The backend accepts 1-365 and
// stamps the chosen window on every card as period_start/period_end.
export const ANALYSIS_PERIODS = [
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 180, label: 'Last 6 months' },
  { days: 365, label: 'Last 12 months' },
];

// Same run-labeling convention as Dashboard/Reports - "Analysis #N: <date>" -
// so a run means the same thing wherever it's picked from.
function formatPipelineRunLabel(run) {
  const value = run?.finished_at || run?.created_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return 'Run';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export function pipelineRunTitle(run, index) {
  const number = run?.sequence_number ?? (index + 1);
  return `Analysis #${number}: ${formatPipelineRunLabel(run)}`;
}

export function useRunAnalysis(studyId, { onSuccess, onError } = {}) {
  const [analyzing, setAnalyzing] = useState(false);
  const [showRunChoice, setShowRunChoice] = useState(false);
  const [periodDays, setPeriodDays] = useState(ANALYSIS_PERIODS[0].days);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [pipelineRunId, setPipelineRunId] = useState(null);
  const pipelineRunDefaultedRef = useRef(new Set());
  const [analysisLogs, setAnalysisLogs] = useState([]);

  // A study is a project, so it has the same pipeline_runs rows any project's
  // analysis runs write - fetched here so "Run analysis" can offer analyzing
  // one specific past run instead of only a date window. Defaults to the
  // latest completed run the first time this study is opened (tracked per
  // study id so it doesn't fight a choice the user already made).
  useEffect(() => {
    if (!studyId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/pipeline-runs?project_id=${studyId}&limit=500`);
        if (!res.ok) return;
        const data = await res.json().catch(() => ({}));
        const runs = Array.isArray(data?.runs) ? data.runs : [];
        const completed = runs
          .filter((run) => run?.finished_at)
          .sort((a, b) => new Date(b.finished_at).getTime() - new Date(a.finished_at).getTime());
        if (cancelled) return;
        setPipelineRuns(completed);
        if (!pipelineRunDefaultedRef.current.has(studyId)) {
          pipelineRunDefaultedRef.current.add(studyId);
          if (completed.length > 0) setPipelineRunId(completed[0].id);
        }
      } catch {
        if (!cancelled) setPipelineRuns([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studyId]);

  const runAnalysis = async () => {
    const runFilter = pipelineRunId;
    setShowRunChoice(false);
    setAnalyzing(true);
    setAnalysisLogs([]);
    try {
      // Queued, not awaited: one LLM call per competitor runs for minutes
      // against a local model. Poll for progress so the log renders live.
      const queued = await analyze(studyId, {
        period_days: periodDays,
        pipeline_run_id: runFilter || undefined,
      });
      const run = await pollAnalysisRun(studyId, queued.run_id, (r) => setAnalysisLogs(r.logs || []));
      if (run.status === 'failed') throw new Error(run.error || 'Analysis failed.');
      onSuccess?.(run);
    } catch (caught) {
      onError?.(caught.message);
    } finally {
      setAnalyzing(false);
    }
  };

  return {
    analyzing, showRunChoice, setShowRunChoice, periodDays, setPeriodDays,
    pipelineRuns, pipelineRunId, setPipelineRunId, analysisLogs, runAnalysis,
  };
}
