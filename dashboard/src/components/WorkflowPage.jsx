import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Globe, AtSign, Share2, Link2, Type, Plus, 
  ArrowRight, DownloadCloud, Sparkles, Database, 
  CheckCircle2, RefreshCw, BarChart2 
} from 'lucide-react';
import '../Workflow.css';

const PlatformIcon = ({ platform }) => {
  if (platform === 'web') return <Globe size={18} />;
  if (platform === 'x') return <AtSign size={18} />;
  if (platform === 'facebook') return <Share2 size={18} />;
  return <Globe size={18} />;
};

const TypeIcon = ({ type }) => {
  if (type === 'link') return <Link2 size={18} />;
  if (type === 'keywords') return <Type size={18} />;
  return <Link2 size={18} />;
};

export default function WorkflowPage({ articles = [] }) {
  const [rows, setRows] = useState([
    { id: 1, platform: 'web', type: 'link', value: 'https://www.bmwblog.com/feed/' }
  ]);
  
  const [workflowState, setWorkflowState] = useState('idle'); // idle, cleaning, ready

  const addRow = () => {
    setRows([...rows, { id: Date.now(), platform: 'web', type: 'keywords', value: '' }]);
  };

  const updateRow = (id, field, value) => {
    setRows(rows.map(r => r.id === id ? { ...r, [field]: value } : r));
  };

  const triggerCleanup = () => {
    setWorkflowState('cleaning');
    setTimeout(() => {
      setWorkflowState('ready');
    }, 3000);
  };

  return (
    <div className="workflow-layout">
      <div className="bg-pattern"></div>
      
      <div className="miro-board">
        
        {/* BLOCK 1: GET */}
        <motion.div 
          className="workflow-block"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="miro-badge top-right">
            <Sparkles size={14} /> Sources
          </div>
          
          <div className="block-header">
            <div className="block-icon get">
              <DownloadCloud size={20} />
            </div>
            <div className="block-title">Get Data</div>
          </div>

          <div className="get-rows">
            <AnimatePresence>
              {rows.map(row => (
                <motion.div 
                  key={row.id}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="get-row"
                >
                  <div className="row-icon">
                    <PlatformIcon platform={row.platform} />
                  </div>
                  <select 
                    className="row-dropdown"
                    value={row.platform}
                    onChange={(e) => updateRow(row.id, 'platform', e.target.value)}
                  >
                    <option value="web">Web RSS</option>
                    <option value="x">X (Twitter)</option>
                    <option value="facebook">Facebook</option>
                  </select>

                  <div className="row-input-wrapper">
                    <input 
                      type="text" 
                      className="row-input"
                      placeholder={row.type === 'link' ? "Paste URL..." : "Enter keywords..."}
                      value={row.value}
                      onChange={(e) => updateRow(row.id, 'value', e.target.value)}
                    />
                  </div>

                  <select 
                    className="row-dropdown"
                    value={row.type}
                    onChange={(e) => updateRow(row.id, 'type', e.target.value)}
                  >
                    <option value="link">Link</option>
                    <option value="keywords">Keywords</option>
                  </select>
                  <div className="row-icon">
                    <TypeIcon type={row.type} />
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          <button className="add-row-btn" onClick={addRow}>
            <Plus size={18} /> Add Source
          </button>
          
          <button 
            className="btn-primary" 
            style={{ marginTop: '15px' }}
            onClick={triggerCleanup}
          >
            Run Extractor
          </button>
        </motion.div>

        {/* ARROW 1 */}
        <div className="workflow-arrow">
          <ArrowRight size={32} />
        </div>

        {/* BLOCK 2: CLEANUP */}
        <motion.div 
          className="workflow-block"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          style={{ opacity: workflowState === 'idle' ? 0.5 : 1 }}
        >
          <div className="miro-badge bottom-left" style={{ color: 'var(--primary-color)' }}>
            <RefreshCw size={14} /> Pipeline Active
          </div>

          <div className="block-header">
            <div className="block-icon clean">
              <Sparkles size={20} />
            </div>
            <div className="block-title">Cleanup & Enrich</div>
          </div>

          <div className="cleanup-status">
            {workflowState === 'idle' && (
              <div style={{ textAlign: 'center', color: 'var(--text-light)' }}>
                Waiting for extraction...
              </div>
            )}
            
            {(workflowState === 'cleaning' || workflowState === 'ready') && (
              <>
                <motion.div className="status-item" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}>
                  <div className="status-spinner">
                    {workflowState === 'cleaning' ? <RefreshCw size={18} className="spin" /> : <CheckCircle2 size={18} color="#2ed573" />}
                  </div>
                  <div className="status-text">Parsing Raw HTML content</div>
                </motion.div>
                
                <motion.div className="status-item" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.5 }}>
                  <div className="status-spinner">
                    {workflowState === 'cleaning' ? <RefreshCw size={18} className="spin" /> : <CheckCircle2 size={18} color="#2ed573" />}
                  </div>
                  <div className="status-text">DeepSeek AI Sentiment Analysis</div>
                </motion.div>
                
                <motion.div className="status-item" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 1 }}>
                  <div className="status-spinner">
                    {workflowState === 'cleaning' ? <RefreshCw size={18} className="spin" /> : <CheckCircle2 size={18} color="#2ed573" />}
                  </div>
                  <div className="status-text">Extracting Car Models & Brands</div>
                </motion.div>
              </>
            )}
          </div>
        </motion.div>

        {/* ARROW 2 */}
        <div className="workflow-arrow">
          <ArrowRight size={32} />
        </div>

        {/* BLOCK 3: SAVE */}
        <motion.div 
          className="workflow-block"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          style={{ opacity: workflowState !== 'ready' ? 0.5 : 1 }}
        >
          <div className="block-header">
            <div className="block-icon save">
              <Database size={20} />
            </div>
            <div className="block-title">Save & Store</div>
          </div>

          <div className="save-summary">
            {workflowState !== 'ready' ? (
              <div style={{ textAlign: 'center', color: 'var(--text-light)' }}>
                Awaiting enriched data...
              </div>
            ) : (
              <>
                <div className="summary-stat">
                  <span className="summary-label">Total Rows Processed</span>
                  <span className="summary-value">53 Rows</span>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Positive Sentiment</span>
                  <span className="summary-value" style={{ color: '#2ed573' }}>12 Articles</span>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Facebook Sources</span>
                  <span className="summary-value" style={{ color: 'var(--secondary-color)' }}>0 Found</span>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Average Relevance</span>
                  <span className="summary-value" style={{ color: 'var(--primary-color)' }}>8.4 / 10</span>
                </div>

                <button className="save-btn">
                  <Database size={18} /> Push to Supabase
                </button>
              </>
            )}
          </div>
        </motion.div>
        
      </div>
    </div>
  );
}
