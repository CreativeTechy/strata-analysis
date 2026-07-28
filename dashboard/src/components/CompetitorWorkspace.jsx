/**
 * Competitor workspace — the card grid.
 *
 * Each card answers the same three questions in the same order, so the eye learns
 * the shape once: what they're up to, how it affects us, what to do. Cards are
 * ordered by impact then competitor size, because the point of the screen is to
 * put the thing worth acting on first rather than the most recent thing.
 *
 * Clicking a card opens the full report. The card is a genuine <button> so it is
 * keyboard-reachable, since the whole surface is the click target.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, BarChart3, CalendarClock, Check, ChevronRight, Filter,
  Layers, Lightbulb, Radar, ShieldCheck, Sparkles, Target, TrendingUp,
} from 'lucide-react';
import {
  IMPACT_LABELS, SIZE_TIER_LABELS, analyze, avatarGradient, getStudy, initials,
  listCompetitors, listFindings, relativeTime, setCompetitorStatus, syncSources,
} from '../competitorApi.js';
import '../styles/Competitors.css';

const IMPACT_FILTERS = [
  { key: '', label: 'All impact' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
];

function FindingCard({ finding, onOpen }) {
  const actions = Array.isArray(finding.actions) ? finding.actions : [];
  const signals = Array.isArray(finding.signals) ? finding.signals : [];
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];

  return (
    <button type="button" className="cs-card" onClick={() => onOpen(finding.id)}>
      <span className={`cs-card-spine cs-card-spine-${finding.impact_level}`} aria-hidden="true" />
      <div className="cs-card-body">
        <div className="cs-card-top">
          <div className="cs-card-competitor">
            <span className="cs-avatar" style={{ background: avatarGradient(finding.competitor_name) }} aria-hidden="true">
              {initials(finding.competitor_name)}
            </span>
            <div style={{ minWidth: 0 }}>
              <p className="cs-card-name">{finding.competitor_name}</p>
              <p className="cs-card-domain">
                {finding.competitor_domain || '-'}
                {finding.size_tier ? ` · ${SIZE_TIER_LABELS[finding.size_tier] || finding.size_tier}` : ''}
              </p>
            </div>
          </div>
          <span className={`cs-pill cs-pill-${finding.impact_level}`}>
            {IMPACT_LABELS[finding.impact_level] || finding.impact_level}
          </span>
        </div>

        <h3 className="cs-card-headline">{finding.headline}</h3>

        <div className="cs-answer">
          <span className="cs-answer-label"><Activity size={11} /> What they&rsquo;re up to</span>
          <p className="cs-answer-text cs-answer-clamp">{finding.whats_up}</p>
        </div>

        <div className="cs-answer">
          <span className="cs-answer-label"><Target size={11} /> How it affects us</span>
          <p className="cs-answer-text cs-answer-clamp">{finding.impact}</p>
        </div>

        {actions.length ? (
          <div className="cs-answer">
            <span className="cs-answer-label"><Lightbulb size={11} /> Suggested actions</span>
            <ul className="cs-actions-preview">
              {actions.slice(0, 2).map((item, index) => (
                <li key={index}>{item.action}</li>
              ))}
            </ul>
            {actions.length > 2 ? (
              <span style={{ fontSize: '0.79rem', color: 'var(--text-light)', paddingLeft: 17 }}>
                +{actions.length - 2} more
              </span>
            ) : null}
          </div>
        ) : null}

        {signals.length ? (
          <div className="cs-pills">
            {signals.slice(0, 4).map((signal) => (
              <span key={signal} className="cs-pill cs-pill-signal">{signal}</span>
            ))}
          </div>
        ) : null}

        <div className="cs-card-foot">
          <span>
            {finding.story_count} source{finding.story_count === 1 ? '' : 's'}
            {evidence.length ? ` · ${evidence.length} cited` : ''}
            {finding.generated_at ? ` · ${relativeTime(finding.generated_at)}` : ''}
          </span>
          <span className="cs-card-foot-open">Full report <ChevronRight size={13} /></span>
        </div>
      </div>
    </button>
  );
}

function StatTile({ icon: Icon, label, value, tone }) {
  return (
    <div className="cs-panel" style={{ padding: '15px 17px', flex: '1 1 150px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--text-light)', fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        <Icon size={13} /> {label}
      </div>
      <div style={{ fontSize: '1.5rem', fontWeight: 680, marginTop: 6, color: tone || 'var(--text-dark)', letterSpacing: '-0.02em' }}>
        {value}
      </div>
    </div>
  );
}

export default function CompetitorWorkspace() {
  const { studyId } = useParams();
  const navigate = useNavigate();

  const [study, setStudy] = useState(null);
  const [profile, setProfile] = useState(null);
  const [competitors, setCompetitors] = useState([]);
  const [findings, setFindings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [notice, setNotice] = useState(null);
  const [impact, setImpact] = useState('');
  const [showCompetitors, setShowCompetitors] = useState(false);

  // Fetch inside the effect with a cancel guard, so switching studies mid-request
  // cannot resolve into the newly-selected study's state.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [detail, competitorList] = await Promise.all([
          getStudy(studyId),
          listCompetitors(studyId),
        ]);
        if (cancelled) return;
        setStudy(detail.study);
        setProfile(detail.profile);
        setFindings(detail.findings || []);
        setCompetitors(competitorList.competitors || []);
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

  const applyFilter = async (next) => {
    setImpact(next);
    try {
      const result = await listFindings(studyId, { impact: next || undefined });
      setFindings(result.findings || []);
    } catch (caught) {
      setError(caught.message);
    }
  };

  const runAnalysis = async () => {
    setAnalyzing(true);
    setError('');
    setNotice(null);
    try {
      await syncSources(studyId);
      const result = await analyze(studyId, { period_days: 30 });
      setFindings(result.findings || []);
      const validation = result.validation || {};
      const reasons = validation.rejection_reasons || {};
      setNotice({
        generated: result.generated,
        scanned: validation.scanned || 0,
        skipped: result.skipped || [],
        reasons,
      });
      setImpact('');
    } catch (caught) {
      setError(caught.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const toggleTracking = async (competitor) => {
    try {
      await setCompetitorStatus(competitor.id, competitor.status === 'tracked' ? 'ignored' : 'tracked');
      const result = await listCompetitors(studyId);
      setCompetitors(result.competitors || []);
    } catch (caught) {
      setError(caught.message);
    }
  };

  const stats = useMemo(() => {
    const tracked = competitors.filter((item) => item.status === 'tracked');
    const pendingChannels = competitors.reduce((sum, item) => sum + (item.pending_account_count || 0), 0);
    const highImpact = findings.filter((item) => item.impact_level === 'high').length;
    return { tracked: tracked.length, pendingChannels, highImpact };
  }, [competitors, findings]);

  if (loading) {
    return (
      <div className="cs-page">
        <div className="cs-skeleton" style={{ height: 34, width: 280, marginBottom: 12 }} />
        <div className="cs-skeleton" style={{ height: 18, width: 460, marginBottom: 28 }} />
        <div className="cs-card-grid">
          {[0, 1, 2].map((key) => (
            <div key={key} className="cs-skeleton" style={{ height: 300 }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="cs-page">
      <div className="cs-head">
        <div>
          <Link to="/competitors" className="cs-link-back">
            <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> All studies
          </Link>
          <h1>{study?.name || 'Competitor study'}</h1>
          <p>
            {profile?.name ? (
              <>
                Measured against <strong>{profile.name}</strong>
                {profile.market ? ` in ${profile.market}` : ''}. Each card is one competitor: what
                they are doing, what it means for you, and what to do about it.
              </>
            ) : (
              'Add your business profile so competitor activity can be judged against it.'
            )}
          </p>
        </div>
        <div className="cs-head-actions">
          <button type="button" className="cs-btn" onClick={() => setShowCompetitors((value) => !value)}>
            <Layers size={15} /> {competitors.length} competitor{competitors.length === 1 ? '' : 's'}
          </button>
          <button type="button" className="cs-btn cs-btn-primary" onClick={runAnalysis} disabled={analyzing}>
            {analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />}
            {analyzing ? 'Analysing...' : 'Run analysis'}
          </button>
        </div>
      </div>

      {error ? (
        <div className="cs-alert cs-alert-error">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{error}</span>
        </div>
      ) : null}

      {stats.pendingChannels > 0 ? (
        <div className="cs-alert cs-alert-warn">
          <ShieldCheck size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            {stats.pendingChannels} channel{stats.pendingChannels === 1 ? '' : 's'} still awaiting
            confirmation. Unconfirmed channels are not scraped, so their activity is missing from
            these reports.{' '}
            <button type="button" onClick={() => setShowCompetitors(true)}
              style={{ background: 'none', border: 'none', padding: 0, color: 'inherit', fontWeight: 700, textDecoration: 'underline', cursor: 'pointer' }}>
              Review them
            </button>
          </span>
        </div>
      ) : null}

      {notice ? (
        <div className="cs-alert cs-alert-info">
          <Check size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            Generated {notice.generated} report{notice.generated === 1 ? '' : 's'} from{' '}
            {notice.scanned} scanned article{notice.scanned === 1 ? '' : 's'}.
            {Object.keys(notice.reasons).length ? (
              <>
                {' '}Filtered out:{' '}
                {Object.entries(notice.reasons)
                  .map(([reason, count]) => `${count} ${reason.replace(/_/g, ' ')}`)
                  .join(', ')}
                .
              </>
            ) : null}
            {notice.skipped.length ? (
              <> {notice.skipped.length} competitor{notice.skipped.length === 1 ? '' : 's'} had no
                usable evidence this period.</>
            ) : null}
          </span>
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 20 }}>
        <StatTile icon={Radar} label="Tracked" value={stats.tracked} />
        <StatTile icon={BarChart3} label="Reports" value={findings.length} />
        <StatTile icon={TrendingUp} label="High impact" value={stats.highImpact}
          tone={stats.highImpact ? '#b91c1c' : undefined} />
        <StatTile icon={CalendarClock} label="Last run"
          value={study?.last_run_at ? relativeTime(study.last_run_at) : 'Never'} />
      </div>

      {showCompetitors ? (
        <div className="cs-panel" style={{ marginBottom: 20 }}>
          <h2 className="cs-panel-title"><Layers size={16} /> Competitors</h2>
          <p className="cs-panel-hint">
            Only tracked competitors are scraped and analysed. Ranked by size.
          </p>
          <div className="cs-rows">
            {competitors.map((competitor) => (
              <div key={competitor.id} className="cs-row">
                <span className="cs-row-rank">{competitor.size_rank ?? '-'}</span>
                <div className="cs-avatar" style={{ background: avatarGradient(competitor.name), width: 30, height: 30, fontSize: '0.72rem' }} aria-hidden="true">
                  {initials(competitor.name)}
                </div>
                <div className="cs-row-main">
                  <div className="cs-row-name">{competitor.name}</div>
                  <div className="cs-row-desc">
                    {competitor.valid_account_count}/{competitor.account_count} channels confirmed
                    {competitor.pending_account_count ? ` · ${competitor.pending_account_count} pending` : ''}
                    {competitor.finding_count ? ` · ${competitor.finding_count} report(s)` : ''}
                  </div>
                </div>
                <div className="cs-row-side">
                  <span className={`cs-pill cs-pill-${competitor.size_tier}`}>
                    {SIZE_TIER_LABELS[competitor.size_tier] || competitor.size_tier}
                  </span>
                  <button type="button" className={`cs-btn cs-btn-sm${competitor.status === 'tracked' ? ' cs-btn-primary' : ''}`}
                    onClick={() => toggleTracking(competitor)}>
                    {competitor.status === 'tracked' ? <><Check size={13} /> Tracking</> : 'Track'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {findings.length ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 15, flexWrap: 'wrap' }}>
            <Filter size={14} style={{ color: 'var(--text-light)' }} />
            {IMPACT_FILTERS.map((option) => (
              <button key={option.key} type="button"
                className={`cs-btn cs-btn-sm${impact === option.key ? ' cs-btn-primary' : ''}`}
                onClick={() => applyFilter(option.key)} aria-pressed={impact === option.key}>
                {option.label}
              </button>
            ))}
          </div>

          <div className="cs-card-grid">
            {findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding}
                onOpen={(id) => navigate(`/competitors/${studyId}/reports/${id}`)} />
            ))}
          </div>
        </>
      ) : (
        <div className="cs-empty">
          <div className="cs-empty-icon"><Sparkles size={20} /></div>
          <h3>No reports yet</h3>
          <p>
            {stats.tracked
              ? 'Competitors are tracked but nothing has been analysed. Run the analysis once their channels have been scraped.'
              : 'Track at least one competitor, confirm their channels, then run the analysis.'}
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            {stats.tracked ? (
              <button type="button" className="cs-btn cs-btn-primary" onClick={runAnalysis} disabled={analyzing}>
                {analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />} Run analysis
              </button>
            ) : (
              <button type="button" className="cs-btn cs-btn-primary" onClick={() => setShowCompetitors(true)}>
                <Layers size={15} /> Choose competitors
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
