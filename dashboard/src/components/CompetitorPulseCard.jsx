/**
 * Competitor findings for the Dashboard and Reports pages, scoped to the
 * competitor study selected in the top project picker.
 *
 * Those two pages are sentiment-focused and deliberately don't render the full
 * competitor workspace (see CompetitorStudiesPage.jsx) — this card lists every
 * finding for the selected study, highest impact first, with links out to the
 * full experience for depth.
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Radar } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { IMPACT_LABELS, avatarGradient, initials, listStudyFindings, relativeTime } from '../competitorApi.js';
import '../styles/Competitors.css';

const PAGE_SIZE = 5;

export default function CompetitorPulseCard({ studyId, backTo, backLabel }) {
  const { hasPermission } = useAuth();
  const canView = hasPermission('competitors.view');
  const [page, setPage] = useState(0);
  const [findings, setFindings] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(canView);
  const [error, setError] = useState('');

  useEffect(() => {
    setPage(0);
  }, [studyId]);

  useEffect(() => {
    if (!canView || !studyId) return undefined;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const result = await listStudyFindings(studyId, { limit: PAGE_SIZE, offset: page * PAGE_SIZE });
        if (!cancelled) {
          setFindings(result.findings || []);
          setTotal(result.total || 0);
        }
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canView, studyId, page]);

  if (!canView) return null;

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <article className="glass-card cs-pulse-card">
      <div className="cs-pulse-head">
        <span className="cs-pulse-eyebrow"><Radar size={13} /> Competitor intelligence</span>
      </div>

      {loading ? (
        <div className="cs-skeleton" style={{ height: 64 }} />
      ) : error ? (
        <p className="cs-pulse-empty">Couldn&rsquo;t load competitor data: {error}</p>
      ) : findings.length === 0 ? (
        <p className="cs-pulse-empty">No findings generated yet — run analysis from this study to populate this.</p>
      ) : (
        <>
          <ul className="cs-pulse-list">
            {findings.map((finding) => (
              <li key={finding.id}>
                <Link
                  to={`/competitors/${finding.study_id}/reports/${finding.id}`}
                  state={backTo ? { from: backTo, fromLabel: backLabel } : undefined}
                  className="cs-pulse-row"
                >
                  <span className="cs-avatar" style={{ background: avatarGradient(finding.competitor_name), width: 28, height: 28, fontSize: '0.7rem' }}>
                    {initials(finding.competitor_name)}
                  </span>
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

          {totalPages > 1 ? (
            <div className="cs-pulse-pagination">
              <button
                type="button"
                className="cs-btn cs-btn-ghost cs-btn-sm"
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                disabled={page === 0}
              >
                <ChevronLeft size={14} /> Prev
              </button>
              <span className="cs-pulse-pagination-status">Page {page + 1} of {totalPages}</span>
              <button
                type="button"
                className="cs-btn cs-btn-ghost cs-btn-sm"
                onClick={() => setPage((current) => Math.min(totalPages - 1, current + 1))}
                disabled={page >= totalPages - 1}
              >
                Next <ChevronRight size={14} />
              </button>
            </div>
          ) : null}
        </>
      )}
    </article>
  );
}
