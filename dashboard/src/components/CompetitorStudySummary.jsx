/**
 * Per-study competitor summary — what Dashboard/Reports render in place of the
 * sentiment view when the selected project is a competitor study (mode ===
 * 'competitor'), since sentiment charts have nothing to show for it. Still a
 * summary, not the full interactive workspace (CompetitorWorkspace.jsx) — that
 * stays one click away via "Open full workspace".
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Building2 } from 'lucide-react';
import { IMPACT_LABELS, SIZE_TIER_LABELS, getStudy, relativeTime } from '../competitorApi.js';
import '../styles/Competitors.css';

export default function CompetitorStudySummary({ studyId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (cancelled) return;
      setLoading(true);
      setError('');
      try {
        const result = await getStudy(studyId);
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
  }, [studyId]);

  if (loading) {
    return <div className="glass-card cs-study-summary"><div className="cs-skeleton" style={{ height: 180 }} /></div>;
  }

  if (error) {
    return (
      <div className="glass-card cs-study-summary">
        <div className="cs-alert cs-alert-error">Couldn&rsquo;t load this study: {error}</div>
      </div>
    );
  }

  const study = data?.study || {};
  const profile = data?.profile;
  const competitors = (data?.competitors || []).filter((c) => c.status === 'tracked');
  const findings = data?.findings || [];

  return (
    <article className="glass-card cs-study-summary">
      <div className="cs-study-summary-head">
        <div>
          <span className="cs-pulse-eyebrow"><Building2 size={13} /> Competitor study</span>
          <h3>{study.name}</h3>
          {profile?.market || profile?.industry ? (
            <p className="cs-card-domain">{[profile?.industry, profile?.market].filter(Boolean).join(' · ')}</p>
          ) : null}
        </div>
        <Link to={`/competitors/${studyId}`} className="cs-btn cs-btn-primary cs-btn-sm">
          Open full workspace <ArrowRight size={13} />
        </Link>
      </div>

      {competitors.length ? (
        <div className="cs-pills" style={{ marginTop: 14 }}>
          {competitors.map((competitor) => (
            <span key={competitor.id} className={`cs-pill cs-pill-${competitor.size_tier || 'unknown'}`}>
              {competitor.name}{competitor.size_tier ? ` · ${SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}` : ''}
            </span>
          ))}
        </div>
      ) : (
        <p className="cs-pulse-empty">No competitors tracked yet in this study.</p>
      )}

      {findings.length ? (
        <ul className="cs-pulse-list" style={{ marginTop: 16 }}>
          {findings.slice(0, 5).map((finding) => (
            <li key={finding.id}>
              <Link to={`/competitors/${studyId}/reports/${finding.id}`} className="cs-pulse-row">
                <span className="cs-pulse-row-main">
                  <span className="cs-pulse-row-headline">{finding.headline}</span>
                  <span className="cs-pulse-row-meta">{finding.competitor_name}</span>
                </span>
                <span className={`cs-pill cs-pill-${finding.impact_level}`}>{IMPACT_LABELS[finding.impact_level] || finding.impact_level}</span>
                <span className="cs-pulse-row-time">{relativeTime(finding.generated_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="cs-pulse-empty">No findings generated yet for this study.</p>
      )}
    </article>
  );
}
