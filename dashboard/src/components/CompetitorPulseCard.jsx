/**
 * Cross-study competitor summary for the Dashboard and Reports pages.
 *
 * Those two pages are sentiment-focused and deliberately don't render the full
 * competitor workspace (see CompetitorStudiesPage.jsx) — this card only answers
 * "is anything happening across my competitor studies", with links out to the
 * full experience for depth.
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Radar, Sparkles } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { IMPACT_LABELS, avatarGradient, getOverview, initials, relativeTime } from '../competitorApi.js';
import '../styles/Competitors.css';

export default function CompetitorPulseCard() {
  const { hasPermission } = useAuth();
  const canView = hasPermission('competitors.view');
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(canView);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!canView) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const result = await getOverview();
        if (!cancelled) setOverview(result);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canView]);

  if (!canView) return null;

  const totals = overview?.totals || { studies: 0, tracked_competitors: 0, high_impact_findings: 0 };
  const findings = overview?.recent_findings || [];

  return (
    <article className="glass-card cs-pulse-card">
      <div className="cs-pulse-head">
        <span className="cs-pulse-eyebrow"><Radar size={13} /> Competitor intelligence</span>
        <Link to="/competitors" className="cs-pulse-viewall">View all <ArrowRight size={13} /></Link>
      </div>

      {loading ? (
        <div className="cs-skeleton" style={{ height: 64 }} />
      ) : error ? (
        <p className="cs-pulse-empty">Couldn&rsquo;t load competitor data: {error}</p>
      ) : totals.studies === 0 ? (
        <div className="cs-pulse-empty-state">
          <p>No competitor studies yet. Track what competitors are doing and what it means for you.</p>
          <Link to="/competitors/new" className="cs-btn cs-btn-primary cs-btn-sm">
            <Sparkles size={13} /> Start a study
          </Link>
        </div>
      ) : (
        <>
          <div className="cs-pulse-stats">
            <div><strong>{totals.studies}</strong><span>studies tracked</span></div>
            <div><strong>{totals.tracked_competitors}</strong><span>competitors tracked</span></div>
            <div><strong>{totals.high_impact_findings}</strong><span>high-impact findings</span></div>
          </div>

          {findings.length ? (
            <ul className="cs-pulse-list">
              {findings.slice(0, 5).map((finding) => (
                <li key={finding.id}>
                  <Link to={`/competitors/${finding.study_id}/reports/${finding.id}`} className="cs-pulse-row">
                    <span className="cs-avatar" style={{ background: avatarGradient(finding.competitor_name), width: 28, height: 28, fontSize: '0.7rem' }}>
                      {initials(finding.competitor_name)}
                    </span>
                    <span className="cs-pulse-row-main">
                      <span className="cs-pulse-row-headline">{finding.headline}</span>
                      <span className="cs-pulse-row-meta">{finding.competitor_name} · {finding.study_name}</span>
                    </span>
                    <span className={`cs-pill cs-pill-${finding.impact_level}`}>{IMPACT_LABELS[finding.impact_level] || finding.impact_level}</span>
                    <span className="cs-pulse-row-time">{relativeTime(finding.generated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="cs-pulse-empty">No findings generated yet — run analysis from a study to populate this.</p>
          )}
        </>
      )}
    </article>
  );
}
