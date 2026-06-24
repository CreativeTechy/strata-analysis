import React, { useState, useRef, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Bug,
  Play,
  Square,
  Database,
  Globe2,
  FileText,
  Layers3,
  TimerReset,
  ShieldCheck,
  Zap,
  Workflow,
  AlertTriangle,
  Sparkles,
} from 'lucide-react';
import '../styles/Spider.css';

const fmt = (n) => {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
};

// Spider backend base URL. Empty in dev (Vite proxy -> localhost:8000); in
// production set VITE_SPIDER_URL to the Hugging Face Space, e.g.
// https://<user>-strata-spider.hf.space
const SPIDER_BASE = import.meta.env.VITE_SPIDER_URL || '';

const VIEW = 1000;
const CENTER = VIEW / 2;
const RING = 150;

// Soft color per depth ring.
const depthColor = (d) => ['#ff6b35', '#ffb13b', '#4aa3ff', '#9b6bff', '#2ed573'][d % 5];

const safeHost = (value) => {
  try {
    return new URL(value).host.replace(/^www\./, '');
  } catch {
    return value.replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  }
};

export default function SpiderPage() {
  const [seed, setSeed] = useState('https://www.carscoops.com/');
  const [depth, setDepth] = useState(2);
  const [pages, setPages] = useState(300);

  const [nodes, setNodes] = useState([]); // {url, depth, parent, isArticle, words}
  const [ticker, setTicker] = useState([]); // last URLs
  const [stats, setStats] = useState({ pages: 0, articles: 0, words: 0, sources: 0, depth: 0 });
  const [running, setRunning] = useState(false);
  const [engine, setEngine] = useState('');
  const [save, setSave] = useState(true);
  const [saved, setSaved] = useState(0);
  const [error, setError] = useState('');
  const [startedAt, setStartedAt] = useState(null);
  const [elapsed, setElapsed] = useState(0);

  const esRef = useRef(null);

  useEffect(() => () => esRef.current?.close(), []);

  // Tick the elapsed clock while running.
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 200);
    return () => clearInterval(t);
  }, [running, startedAt]);

  const stop = () => {
    esRef.current?.close();
    esRef.current = null;
    setRunning(false);
  };

  const launch = () => {
    esRef.current?.close();
    setNodes([]);
    setTicker([]);
    setError('');
    setSaved(0);
    setStats({ pages: 0, articles: 0, words: 0, sources: 0, depth: 0 });
    setStartedAt(Date.now());
    setElapsed(0);
    setRunning(true);

    const qs = new URLSearchParams({
      seed,
      depth: String(depth),
      pages: String(pages),
      save: save ? '1' : '0',
    });
    const es = new EventSource(`${SPIDER_BASE}/api/spider/stream?${qs}`);
    esRef.current = es;

    es.onmessage = (e) => {
      let ev;
      try {
        ev = JSON.parse(e.data);
      } catch {
        return;
      }
      if (ev.type === 'start') {
        setEngine(ev.engine || '');
      } else if (ev.type === 'saved') {
        setSaved(ev.count || 0);
      } else if (ev.type === 'node') {
        setNodes((prev) => (prev.length > 600 ? prev : [...prev, ev]));
        setTicker((prev) => [{ url: ev.url, article: ev.is_article }, ...prev].slice(0, 14));
        setStats((s) => ({
          pages: s.pages + 1,
          articles: s.articles + (ev.is_article ? 1 : 0),
          words: s.words + (ev.is_article ? ev.words : 0),
          sources: s.sources,
          depth: Math.max(s.depth, ev.depth),
        }));
      } else if (ev.type === 'done') {
        setStats((s) => ({ ...s, ...ev.stats }));
        stop();
      } else if (ev.type === 'error') {
        setError(ev.message || 'Spider error');
        stop();
      }
    };

    es.onerror = () => {
      setError(
        (prev) =>
          prev ||
          'Lost connection to the spider backend. Is the FastAPI server running (uvicorn main:app --port 8000)?'
      );
      stop();
    };
  };

  // Radial layout: position nodes on concentric depth rings.
  const positioned = useMemo(() => {
    const byDepth = {};
    nodes.forEach((n) => {
      (byDepth[n.depth] ??= []).push(n);
    });
    const pos = new Map();
    Object.entries(byDepth).forEach(([d, list]) => {
      const dd = Number(d);
      const r = dd === 0 ? 0 : RING * dd;
      list.forEach((n, i) => {
        const ang = (i / Math.max(list.length, 1)) * Math.PI * 2 - Math.PI / 2;
        pos.set(n.url, { x: CENTER + r * Math.cos(ang), y: CENTER + r * Math.sin(ang), n });
      });
    });
    return pos;
  }, [nodes]);

  const rate = elapsed > 0 ? stats.pages / elapsed : 0;
  const sourceCount = stats.sources || new Set(nodes.map((n) => n.source).filter(Boolean)).size;
  const tweetCount = stats.tweets || nodes.filter((n) => (n.source || '').startsWith('x.com')).length;
  const savedLabel = save ? 'saving enabled' : 'saving disabled';

  return (
    <div className="spider-layout">
      <div className="spider-shell">
        <motion.section
          className="spider-hero"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="spider-hero-copy">
            <div className="spider-kicker">
              <Bug size={14} />
              Spider Mode
            </div>
            <h1>Deep crawl with a live radial map.</h1>
            <p>
              Launch a focused spider run, watch the graph expand in real time, and feed the Spark pipeline with
              fresh pages, sources, and article text.
            </p>
            <div className="spider-hero-chips">
              <span className={`spider-chip ${running ? 'live' : 'idle'}`}>
                <Zap size={14} />
                {running ? 'Crawling now' : 'Ready to launch'}
              </span>
              <span className="spider-chip">
                <Workflow size={14} />
                {engine ? `engine: ${engine}` : 'engine pending'}
              </span>
              <span className="spider-chip">
                <ShieldCheck size={14} />
                {savedLabel}
              </span>
            </div>
          </div>

          <div className="spider-hero-stats">
            <div className="spider-stat-card accent">
              <span>Pages</span>
              <strong>{fmt(stats.pages)}</strong>
              <small>Crawled in this run</small>
            </div>
            <div className="spider-stat-card green">
              <span>Articles</span>
              <strong>{fmt(stats.articles)}</strong>
              <small>Article pages detected</small>
            </div>
            <div className="spider-stat-card blue">
              <span>Words</span>
              <strong>{fmt(stats.words)}</strong>
              <small>Text harvested</small>
            </div>
            <div className="spider-stat-card">
              <span>Speed</span>
              <strong>{rate.toFixed(1)}</strong>
              <small>Pages per second</small>
            </div>
          </div>
        </motion.section>

        <div className="spider-grid">
          <motion.aside
            className="spider-panel"
            initial={{ opacity: 0, x: -14 }}
            animate={{ opacity: 1, x: 0 }}
          >
            <div className="spider-panel-top">
            <div className="spider-title">
                <Bug size={18} color="#ff9b57" />
                Crawl Controls
              </div>
              <div className="spider-sub">
                Shape the crawl before launch, then monitor what gets discovered as the graph expands.
              </div>
            </div>

            <div className="spider-field">
              <label htmlFor="spider-seed">Seed URL</label>
              <input
                id="spider-seed"
                className="spider-input"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                disabled={running}
                placeholder="https://example.com"
              />
            </div>

            <div className="spider-row">
              <div className="spider-field">
                <label htmlFor="spider-depth">Max Depth</label>
                <input
                  id="spider-depth"
                  className="spider-input"
                  type="number"
                  min={1}
                  max={4}
                  value={depth}
                  onChange={(e) => setDepth(Number(e.target.value))}
                  disabled={running}
                />
              </div>
              <div className="spider-field">
                <label htmlFor="spider-pages">Max Pages</label>
                <input
                  id="spider-pages"
                  className="spider-input"
                  type="number"
                  min={10}
                  max={2000}
                  step={10}
                  value={pages}
                  onChange={(e) => setPages(Number(e.target.value))}
                  disabled={running}
                />
              </div>
            </div>

            <label className="spider-toggle">
              <input
                type="checkbox"
                checked={save}
                disabled={running}
                onChange={(e) => setSave(e.target.checked)}
              />
              <span>
                <strong>Save crawled pages</strong>
                <small>Persist results to Supabase for Spark</small>
              </span>
            </label>

            <div className="spider-actions">
              {!running ? (
                <button className="spider-launch" onClick={launch}>
                  <Play size={16} /> Launch Spider
                </button>
              ) : (
                <button className="spider-launch stop" onClick={stop}>
                  <Square size={14} /> Stop Run
                </button>
              )}
            </div>

            {error && (
              <div className="spider-error">
                <AlertTriangle size={14} />
                <span>{error}</span>
              </div>
            )}

            <div className="spider-stat-grid">
              <div className="stat-box accent">
                <div className="num">{fmt(stats.pages)}</div>
                <div className="lbl">Pages Crawled</div>
              </div>
              <div className="stat-box green">
                <div className="num">{fmt(stats.articles)}</div>
                <div className="lbl">Articles</div>
              </div>
              <div className="stat-box blue">
                <div className="num">{fmt(stats.words)}</div>
                <div className="lbl">Words Harvested</div>
              </div>
              <div className="stat-box">
                <div className="num">{rate.toFixed(1)}</div>
                <div className="lbl">Pages / sec</div>
              </div>
              <div className="stat-box">
                <div className="num">{sourceCount}</div>
                <div className="lbl">Sources</div>
              </div>
              <div className="stat-box green">
                <div className="num">{fmt(saved)}</div>
                <div className="lbl">Saved to DB</div>
              </div>
              <div className="stat-box blue">
                <div className="num">{fmt(tweetCount)}</div>
                <div className="lbl">Tweets Harvested</div>
              </div>
              <div className="stat-box accent">
                <div className="num">{stats.depth}</div>
                <div className="lbl">Deepest Level</div>
              </div>
            </div>

            {!running && stats.pages > 0 && (
              <div className="spider-summary">
                <Database size={14} />
                {save ? (
                  <>
                    {fmt(saved)} pages saved to Supabase with {fmt(stats.words)} words, ready for Spark.
                  </>
                ) : (
                  <>
                    {fmt(stats.words)} words across {fmt(stats.articles)} articles. Saving is currently off.
                  </>
                )}
              </div>
            )}
          </motion.aside>

          <motion.main
            className="spider-canvas-wrap"
            initial={{ opacity: 0, scale: 0.99 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <div className="spider-canvas-shell">
              <div className="spider-canvas-head">
                <div>
                  <div className="spider-canvas-kicker">
                    <Globe2 size={13} />
                    Live graph
                  </div>
                  <div className="spider-canvas-title">Radial crawl map</div>
                </div>
                <div className="spider-canvas-meta">
                  <span>
                    <Layers3 size={13} />
                    {nodes.length} nodes
                  </span>
                  <span>
                    <FileText size={13} />
                    {ticker.length} recent events
                  </span>
                  <span>
                    <TimerReset size={13} />
                    {elapsed.toFixed(1)}s
                  </span>
                </div>
              </div>

              <svg
                className="spider-graph-svg"
                viewBox={`0 0 ${VIEW} ${VIEW}`}
                width="100%"
                height="100%"
                preserveAspectRatio="xMidYMid meet"
              >
                {[1, 2, 3, 4].map((d) => (
                  <circle
                    key={d}
                    cx={CENTER}
                    cy={CENTER}
                    r={RING * d}
                    fill="none"
                    stroke="rgba(255,255,255,0.06)"
                    strokeDasharray="4 8"
                  />
                ))}

                {nodes.map((n) => {
                  const p = positioned.get(n.url);
                  const par = n.parent && positioned.get(n.parent);
                  const from = par || { x: CENTER, y: CENTER };
                  if (!p) return null;
                  return (
                    <line
                      key={'e' + n.url}
                      x1={from.x}
                      y1={from.y}
                      x2={p.x}
                      y2={p.y}
                      stroke={n.is_article ? 'rgba(46, 213, 115, 0.18)' : 'rgba(255,255,255,0.12)'}
                      strokeWidth="1"
                    />
                  );
                })}

                {nodes.map((n) => {
                  const p = positioned.get(n.url);
                  if (!p) return null;
                  const r = n.depth === 0 ? 9 : n.is_article ? 5.5 : 3.5;
                  const color = n.is_article ? '#2ed573' : depthColor(n.depth);
                  return (
                    <motion.circle
                      key={n.url}
                      cx={p.x}
                      cy={p.y}
                      initial={{ r: 0, opacity: 0 }}
                      animate={{ r, opacity: 1 }}
                      transition={{ type: 'spring', stiffness: 200, damping: 18 }}
                      fill={color}
                      stroke={n.depth === 0 ? '#fff' : 'rgba(0,0,0,0.3)'}
                      strokeWidth={n.depth === 0 ? 2 : 0.5}
                    />
                  );
                })}
              </svg>

              <div className="spider-legend">
                <span>
                  <span className="legend-dot seed" /> Seed
                </span>
                <span>
                  <span className="legend-dot page" /> Page
                </span>
                <span>
                  <span className="legend-dot article" /> Article
                </span>
                <span>
                  <span className="legend-line" /> Edge
                </span>
              </div>

              <div className="spider-ticker">
                {ticker.map((t, i) => (
                  <div key={`${t.url}-${i}`} className={`ticker-line ${t.article ? 'article' : ''}`}>
                    <span className={`ticker-dot ${t.article ? 'article' : 'page'}`} />
                    <span className="ticker-url">{safeHost(t.url)}</span>
                    <span className="ticker-full">{t.url}</span>
                  </div>
                ))}
                {!ticker.length && (
                  <div className="ticker-empty">
                    <Sparkles size={13} />
                    Launch a crawl to watch discovered URLs appear here.
                  </div>
                )}
              </div>
            </div>
          </motion.main>
        </div>
      </div>
    </div>
  );
}
