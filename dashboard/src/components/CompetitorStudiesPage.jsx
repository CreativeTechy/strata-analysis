/**
 * Competitor studies index — the entry point for the competitor experience.
 *
 * Separate from the sentiment/opinion screens on purpose: the two answer different
 * questions and mixing them was what made the old single dashboard hard to read.
 */

import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle, Building2, CalendarClock, ChevronRight, Plus, Radar, Sparkles,
} from 'lucide-react';
import { listStudies, relativeTime } from '../competitorApi.js';
import '../styles/Competitors.css';

export default function CompetitorStudiesPage() {
  const navigate = useNavigate();
  const [studies, setStudies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await listStudies();
        if (!cancelled) setStudies(result.studies || []);
      } catch (caught) {
        if (!cancelled) setError(caught.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="cs-page">
      <div className="cs-head">
        <div>
          <h1>Competitor studies</h1>
          <p>
            Track what your competitors are doing, what it means for your business, and what to do
            about it. Separate from sentiment and opinion tracking, which answers what people are
            saying.
          </p>
        </div>
        <div className="cs-head-actions">
          <button type="button" className="cs-btn cs-btn-primary" onClick={() => navigate('/competitors/new')}>
            <Plus size={15} /> New study
          </button>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{error}</span>
        </div>
      ) : null}

      {loading ? (
        <div className="cs-card-grid">
          {[0, 1].map((key) => <div key={key} className="cs-skeleton" style={{ height: 170 }} />)}
        </div>
      ) : studies.length ? (
        <div className="cs-card-grid">
          {studies.map((study) => (
            <Link key={study.id} to={`/competitors/${study.id}`} className="cs-card" style={{ textDecoration: 'none' }}>
              <span className={`cs-card-spine ${study.high_impact_count ? 'cs-card-spine-high' : 'cs-card-spine-low'}`} aria-hidden="true" />
              <div className="cs-card-body">
                <div className="cs-card-top">
                  <div style={{ minWidth: 0 }}>
                    <h3 className="cs-card-headline" style={{ fontSize: '1.05rem' }}>{study.name}</h3>
                    {study.business_name ? (
                      <p className="cs-card-domain" style={{ marginTop: 5 }}>
                        <Building2 size={11} style={{ display: 'inline', verticalAlign: -1, marginRight: 4 }} />
                        {study.business_name}
                        {study.market ? ` · ${study.market}` : ''}
                      </p>
                    ) : (
                      <p className="cs-card-domain" style={{ marginTop: 5, color: '#a16207' }}>
                        Business profile not set up yet
                      </p>
                    )}
                  </div>
                  {study.high_impact_count ? (
                    <span className="cs-pill cs-pill-high">{study.high_impact_count} high impact</span>
                  ) : null}
                </div>

                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: '0.83rem', color: 'var(--text-light)' }}>
                  <span><strong style={{ color: 'var(--text-dark)' }}>{study.tracked_competitors}</strong> tracked</span>
                  <span><strong style={{ color: 'var(--text-dark)' }}>{study.finding_count}</strong> report{study.finding_count === 1 ? '' : 's'}</span>
                  {study.repeat_enabled ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <CalendarClock size={12} /> scheduled
                    </span>
                  ) : null}
                </div>

                <div className="cs-card-foot">
                  <span>
                    {study.latest_generated_at
                      ? `Last analysed ${relativeTime(study.latest_generated_at)}`
                      : 'Not analysed yet'}
                  </span>
                  <span className="cs-card-foot-open">Open <ChevronRight size={13} /></span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="cs-empty">
          <div className="cs-empty-icon"><Radar size={20} /></div>
          <h3>No competitor studies yet</h3>
          <p>
            Start one and Strata will read your website to work out your market, find who you
            compete with, and report what they are doing about it.
          </p>
          <button type="button" className="cs-btn cs-btn-primary" onClick={() => navigate('/competitors/new')}>
            <Sparkles size={15} /> Create your first study
          </button>
        </div>
      )}
    </div>
  );
}
