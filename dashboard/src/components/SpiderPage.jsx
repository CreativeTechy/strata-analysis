import React, { useState, useRef, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Bug, Play, Square, Database } from 'lucide-react';
import '../Spider.css';

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

export default function SpiderPage() {
  const [seed, setSeed] = useState('https://www.carscoops.com/');
  const [depth, setDepth] = useState(2);
  const [pages, setPages] = useState(300);

  const [nodes, setNodes] = useState([]);     // {url, depth, parent, isArticle, words}
  const [ticker, setTicker] = useState([]);   // last URLs
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

  // tick the elapsed clock while running (drives pages/sec)
  useEffect(() => {
    if (!running) return;
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
    setNodes([]); setTicker([]); setError(''); setSaved(0);
    setStats({ pages: 0, articles: 0, words: 0, sources: 0, depth: 0 });
    setStartedAt(Date.now()); setElapsed(0); setRunning(true);

    const qs = new URLSearchParams({
      seed, depth: String(depth), pages: String(pages), save: save ? '1' : '0',
    });
    const es = new EventSource(`${SPIDER_BASE}/api/spider/stream?${qs}`);
    esRef.current = es;

    es.onmessage = (e) => {
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }
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
          sources: s.sources, // finalized on done
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
      setError((prev) => prev || 'Lost connection to the spider backend. Is the FastAPI server running (uvicorn main:app --port 8000)?');
      stop();
    };
  };

  // Radial layout: position nodes on concentric depth rings.
  const positioned = useMemo(() => {
    const byDepth = {};
    nodes.forEach((n) => { (byDepth[n.depth] ??= []).push(n); });
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

  return (
    <div className="spider-layout">
      <div className="spider-grid">
        {/* CONTROLS + STATS */}
        <div className="spider-panel">
          <div className="spider-title"><Bug size={24} color="#ff6b35" /> Spider Mode</div>
          <div className="spider-sub">
            Deep-crawl a site and fan out at scale — feeding the Spark sentiment engine.
            {engine && <span style={{ marginLeft: 6, color: engine === 'crawl4ai' ? '#6fe3a0' : '#ffb13b' }}>· engine: {engine}</span>}
          </div>

          <div className="spider-field">
            <label>Seed URL</label>
            <input className="spider-input" value={seed} onChange={(e) => setSeed(e.target.value)} disabled={running} />
          </div>
          <div className="spider-row">
            <div className="spider-field" style={{ flex: 1 }}>
              <label>Max Depth</label>
              <input className="spider-input" type="number" min={1} max={4} value={depth}
                     onChange={(e) => setDepth(Number(e.target.value))} disabled={running} />
            </div>
            <div className="spider-field" style={{ flex: 1 }}>
              <label>Max Pages</label>
              <input className="spider-input" type="number" min={10} max={2000} step={10} value={pages}
                     onChange={(e) => setPages(Number(e.target.value))} disabled={running} />
            </div>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 12px', fontSize: '0.82rem', color: '#c4c9d2', cursor: running ? 'default' : 'pointer' }}>
            <input type="checkbox" checked={save} disabled={running}
                   onChange={(e) => setSave(e.target.checked)} />
            Save crawled pages to Supabase (for Spark)
          </label>

          {!running ? (
            <button className="spider-launch" onClick={launch}><Play size={18} /> Launch Spider</button>
          ) : (
            <button className="spider-launch" onClick={stop} style={{ background: 'linear-gradient(135deg,#555,#333)' }}>
              <Square size={16} /> Stop
            </button>
          )}

          {error && <div className="spider-error">{error}</div>}

          <div className="stat-row">
            <div className="stat-box accent"><div className="num">{fmt(stats.pages)}</div><div className="lbl">Pages Crawled</div></div>
            <div className="stat-box green"><div className="num">{fmt(stats.articles)}</div><div className="lbl">Articles</div></div>
            <div className="stat-box blue"><div className="num">{fmt(stats.words)}</div><div className="lbl">Words Harvested</div></div>
            <div className="stat-box"><div className="num">{rate.toFixed(1)}</div><div className="lbl">Pages / sec</div></div>
            <div className="stat-box"><div className="num">{stats.sources || new Set(nodes.map(n => n.source)).size}</div><div className="lbl">Sources</div></div>
            <div className="stat-box green"><div className="num">{fmt(saved)}</div><div className="lbl">Saved to DB</div></div>
            <div className="stat-box blue"><div className="num">{fmt(stats.tweets || nodes.filter(n => (n.source || '').startsWith('x.com')).length)}</div><div className="lbl">Tweets Harvested</div></div>
          </div>

          {!running && stats.pages > 0 && (
            <div style={{ marginTop: 16, fontSize: '0.8rem', color: '#6fe3a0', display: 'flex', gap: 8, alignItems: 'center' }}>
              <Database size={16} />
              {save
                ? <>{fmt(saved)} pages saved to Supabase ({fmt(stats.words)} words) — ready for Spark.</>
                : <>{fmt(stats.words)} words across {fmt(stats.articles)} articles (saving was off).</>}
            </div>
          )}
        </div>

        {/* LIVE GRAPH */}
        <div className="spider-canvas-wrap">
          <svg viewBox={`0 0 ${VIEW} ${VIEW}`} width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
            {/* depth rings */}
            {[1, 2, 3, 4].map((d) => (
              <circle key={d} cx={CENTER} cy={CENTER} r={RING * d} fill="none"
                      stroke="rgba(255,255,255,0.05)" strokeDasharray="4 6" />
            ))}
            {/* edges */}
            {nodes.map((n) => {
              const p = positioned.get(n.url);
              const par = n.parent && positioned.get(n.parent);
              const from = par || { x: CENTER, y: CENTER };
              if (!p) return null;
              return <line key={'e' + n.url} x1={from.x} y1={from.y} x2={p.x} y2={p.y}
                           stroke="rgba(255,255,255,0.10)" strokeWidth="1" />;
            })}
            {/* nodes */}
            {nodes.map((n) => {
              const p = positioned.get(n.url);
              if (!p) return null;
              const r = n.depth === 0 ? 9 : n.is_article ? 5.5 : 3.5;
              const color = n.is_article ? '#2ed573' : depthColor(n.depth);
              return (
                <motion.circle
                  key={n.url}
                  cx={p.x} cy={p.y}
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

          <div className="spider-ticker">
            {ticker.map((t, i) => (
              <div key={i} className={`ticker-line ${t.article ? 'article' : ''}`}>
                {t.article ? '📄 ' : '→ '}{t.url}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
