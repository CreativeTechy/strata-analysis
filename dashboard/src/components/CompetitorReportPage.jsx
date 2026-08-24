/**
 * Full competitor report — what a card expands into.
 *
 * Same three answers as the card, unclamped, plus the things a card has no room
 * for: every action with its rationale, the evidence each claim came from, and the
 * articles that were *filtered out* with the reason.
 *
 * That last part is deliberate. These reports are read as input to real decisions,
 * so the population behind the numbers has to be inspectable — a silently dropped
 * article and a silently included irrelevant one are both ways a report misleads.
 */

import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, Calendar, Check, ChevronRight, ExternalLink, FileText,
  Filter, Info, Lightbulb, ShieldCheck, Sparkles, Target, ThumbsDown,
} from 'lucide-react';
import {
  EFFORT_LABELS, IMPACT_LABELS, SIZE_TIER_LABELS, URGENCY_LABELS, avatarGradient,
  formatDate, getFinding, initials, relativeTime, validateFinding,
} from '../competitorApi.js';
import '../styles/Competitors.css';

export default function CompetitorReportPage() {
  const { studyId, findingId } = useParams();
  const location = useLocation();
  const backTo = location.state?.from || `/competitors/${studyId}`;
  const backLabel = location.state?.fromLabel || 'Back to workspace';
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Fetch inside the effect with a cancel guard, so navigating away mid-request
  // does not resolve into state for a report that is no longer on screen.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const result = await getFinding(findingId);
        if (!cancelled) setData(result);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [findingId]);

  const decide = async (status) => {
    setSaving(true);
    try {
      const result = await validateFinding(findingId, status);
      setData((current) => ({ ...current, finding: { ...current.finding, ...result.finding } }));
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="cs-page cs-report">
        <div className="cs-skeleton" style={{ height: 150, marginBottom: 18 }} />
        <div className="cs-skeleton" style={{ height: 200, marginBottom: 16 }} />
        <div className="cs-skeleton" style={{ height: 240 }} />
      </div>
    );
  }

  if (error || !data?.finding) {
    return (
      <div className="cs-page cs-report">
        <Link to={backTo} className="cs-link-back">
          <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> {backLabel}
        </Link>
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error || 'This report could not be found.'}</span>
        </div>
      </div>
    );
  }

  const { finding, rejected_evidence: rejectedEvidence = [], history = [] } = data;
  const actions = Array.isArray(finding.actions) ? finding.actions : [];
  const signals = Array.isArray(finding.signals) ? finding.signals : [];
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];

  return (
    <div className="cs-page cs-report">
      <Link to={backTo} className="cs-link-back">
        <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> {backLabel}
      </Link>

      <div className="cs-report-hero">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="cs-avatar" style={{ background: avatarGradient(finding.competitor_name), width: 42, height: 42, fontSize: '0.95rem' }} aria-hidden="true">
              {initials(finding.competitor_name)}
            </span>
            <div>
              <div style={{ fontSize: '1.02rem', fontWeight: 640, color: 'var(--text-dark)' }}>
                {finding.competitor_name}
              </div>
              {finding.competitor_website ? (
                <a href={finding.competitor_website} target="_blank" rel="noreferrer"
                  style={{ fontSize: '0.8rem', color: 'var(--text-light)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {finding.competitor_domain || finding.competitor_website} <ExternalLink size={11} />
                </a>
              ) : null}
            </div>
          </div>
          <div className="cs-pills">
            <span className={`cs-pill cs-pill-${finding.impact_level}`}>
              {IMPACT_LABELS[finding.impact_level] || finding.impact_level}
            </span>
            {finding.size_tier ? (
              <span className={`cs-pill cs-pill-${finding.size_tier}`}>
                {SIZE_TIER_LABELS[finding.size_tier] || finding.size_tier}
              </span>
            ) : null}
            {finding.size_rank ? <span className="cs-pill cs-pill-signal">#{finding.size_rank} by size</span> : null}
            <span className={`cs-pill cs-pill-${finding.validation_status === 'validated' ? 'valid' : finding.validation_status}`}>
              {finding.validation_status}
            </span>
          </div>
        </div>

        <h1>{finding.headline}</h1>

        {signals.length ? (
          <div className="cs-pills">
            {signals.map((signal) => (
              <span key={signal} className="cs-pill cs-pill-signal">{signal}</span>
            ))}
          </div>
        ) : null}

        <div className="cs-report-meta">
          <span><strong>{finding.story_count}</strong> independent source{finding.story_count === 1 ? '' : 's'}</span>
          <span><strong>{finding.article_count}</strong> article{finding.article_count === 1 ? '' : 's'} used</span>
          {finding.period_start ? (
            <span>Period <strong>{formatDate(finding.period_start)}</strong> to <strong>{formatDate(finding.period_end)}</strong></span>
          ) : null}
          <span>Generated <strong>{relativeTime(finding.generated_at)}</strong></span>
          {finding.confidence != null ? (
            <span>Confidence <strong>{Math.round(Number(finding.confidence) * 100)}%</strong></span>
          ) : null}
        </div>

        {/* A bare percentage doesn't tell you whether to act on it. "Low
            because every source is the competitor's own press release" and
            "low because there are only two mentions" call for different
            responses. Absent on findings generated before the model was
            asked for it. */}
        {finding.confidence_reason ? (
          <p className="cs-report-confidence-reason">
            <Info size={13} /> {finding.confidence_reason}
          </p>
        ) : null}
      </div>

      <div className="cs-report-cols">
        <div>
          <div className="cs-answer-block">
            <h2><Activity size={13} /> What they&rsquo;re up to</h2>
            <p>{finding.whats_up}</p>
          </div>

          <div className="cs-answer-block">
            <h2><Target size={13} /> How it affects us</h2>
            <p>{finding.impact}</p>
          </div>

          <div className="cs-answer-block">
            <h2><Lightbulb size={13} /> Suggested actions</h2>
            {actions.length ? (
              <div className="cs-action-list">
                {actions.map((item, index) => (
                  <div key={index} className="cs-action">
                    <span className="cs-action-num">{index + 1}</span>
                    <div className="cs-action-body">
                      <p className="cs-action-text">{item.action}</p>
                      {item.rationale ? <p className="cs-action-why">{item.rationale}</p> : null}
                      <div className="cs-pills">
                        {item.urgency ? (
                          <span className={`cs-pill ${item.urgency === 'now' ? 'cs-pill-high' : 'cs-pill-signal'}`}>
                            {URGENCY_LABELS[item.urgency] || item.urgency}
                          </span>
                        ) : null}
                        {item.effort ? (
                          <span className="cs-pill cs-pill-signal">{EFFORT_LABELS[item.effort] || item.effort}</span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ color: 'var(--text-light)', fontSize: '0.88rem' }}>
                No actions proposed — the evidence did not support a specific recommendation.
              </p>
            )}
          </div>

          <div className="cs-answer-block">
            <h2><FileText size={13} /> Evidence behind this report</h2>
            {evidence.length ? (
              <div className="cs-evidence">
                {evidence.map((item, index) => (
                  <a key={index} className="cs-evidence-item" href={item.url} target="_blank" rel="noreferrer">
                    <p className="cs-evidence-title">{item.title || item.url}</p>
                    <div className="cs-evidence-meta">
                      <span>{item.source || 'unknown source'}</span>
                      {item.published_at ? <span>{formatDate(item.published_at)}</span> : null}
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        Open <ExternalLink size={10} />
                      </span>
                    </div>
                    {item.excerpt ? <p className="cs-evidence-excerpt">{item.excerpt}</p> : null}
                  </a>
                ))}
              </div>
            ) : (
              <p style={{ color: 'var(--text-light)', fontSize: '0.88rem' }}>No evidence attached.</p>
            )}
          </div>

          {rejectedEvidence.length ? (
            <div className="cs-answer-block">
              <h2><Filter size={13} /> Filtered out ({rejectedEvidence.length})</h2>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-light)', marginBottom: 13, lineHeight: 1.6 }}>
                These mentioned {finding.competitor_name} but were excluded, so you can see exactly
                what the numbers above are and are not based on.
              </p>
              <div className="cs-evidence">
                {rejectedEvidence.map((item) => (
                  <a key={item.id} className="cs-evidence-item" href={item.url} target="_blank" rel="noreferrer">
                    <p className="cs-evidence-title" style={{ color: 'var(--text-light)' }}>
                      {item.title || item.url}
                    </p>
                    <div className="cs-evidence-meta">
                      <span className="cs-pill cs-pill-rejected">
                        {String(item.rejected_reason || 'excluded').replace(/_/g, ' ')}
                      </span>
                      <span>{item.source || 'unknown source'}</span>
                      {item.dated ? <span>{formatDate(item.dated)}</span> : null}
                    </div>
                  </a>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <aside>
          <div className="cs-side-panel">
            <h3><ShieldCheck size={12} /> Review this report</h3>
            <p style={{ fontSize: '0.83rem', color: 'var(--text-light)', lineHeight: 1.6, margin: '0 0 13px' }}>
              Mark it once you have checked the evidence holds up.
            </p>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className={`cs-btn cs-btn-sm${finding.validation_status === 'validated' ? ' cs-btn-primary' : ''}`}
                onClick={() => decide('validated')} disabled={saving}>
                <Check size={13} /> Validated
              </button>
              <button type="button" className="cs-btn cs-btn-sm cs-btn-danger"
                onClick={() => decide('rejected')} disabled={saving}>
                <ThumbsDown size={13} /> Reject
              </button>
            </div>
          </div>

          <div className="cs-side-panel">
            <h3><Sparkles size={12} /> How this was built</h3>
            <div className="cs-stat-row">
              <span>Independent stories</span><span className="cs-stat-value">{finding.story_count}</span>
            </div>
            <div className="cs-stat-row">
              <span>Articles used</span><span className="cs-stat-value">{finding.article_count}</span>
            </div>
            <div className="cs-stat-row">
              <span>Filtered out</span><span className="cs-stat-value">{rejectedEvidence.length}</span>
            </div>
            {finding.analysis_model ? (
              <div className="cs-stat-row">
                <span>Model</span>
                <span className="cs-stat-value" style={{ fontSize: '0.8rem' }}>{finding.analysis_model}</span>
              </div>
            ) : null}
          </div>


          {history.length > 1 ? (
            <div className="cs-side-panel">
              <h3><Calendar size={12} /> Earlier reports</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                {history
                  .filter((item) => item.id !== finding.id)
                  .slice(0, 6)
                  .map((item) => (
                    <Link key={item.id} to={`/competitors/${studyId}/reports/${item.id}`} state={location.state}
                      style={{ fontSize: '0.83rem', textDecoration: 'none', color: 'var(--text-light)' }}>
                      <span style={{ display: 'block', color: 'var(--text-dark)', fontWeight: 550, lineHeight: 1.4 }}>
                        {item.headline}
                      </span>
                      {relativeTime(item.generated_at)}
                    </Link>
                  ))}
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
