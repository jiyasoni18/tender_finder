import { useState, useEffect, useRef } from 'react';
import './App.css';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_BASE = API_BASE.replace('http', 'ws');

function TenderCard({ tender }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="tender-card" onClick={() => setExpanded(!expanded)}>
      <div className="tender-card-header">
        <div className="tender-id">{tender.id}</div>
        <div className="tender-badge">Passed</div>
      </div>

      {tender.summary && tender.summary !== 'No summary available.' && (
        <p className="tender-summary">{tender.summary}</p>
      )}

      {expanded && (
        <div className="tender-actions" onClick={e => e.stopPropagation()}>
          {tender.details_pdf && (
            <a
              href={`${API_BASE}${tender.details_pdf}`}
              target="_blank"
              rel="noreferrer"
              className="action-link action-ai"
            >
              ✨ AI Summary PDF
            </a>
          )}
          {tender.original_docs.filter(d => !d.endsWith('.html')).map((doc, i) => (
            <a
              key={i}
              href={`${API_BASE}${doc}`}
              target="_blank"
              rel="noreferrer"
              className="action-link action-doc"
            >
              📄 {doc.split('/').pop()}
            </a>
          ))}
        </div>
      )}

      <div className="tender-expand-hint">
        {expanded ? '▲ collapse' : '▼ view files'}
      </div>
    </div>
  );
}

function Dashboard({ refreshTrigger }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const fetchResults = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/results`, { cache: 'no-store' });
      const data = await res.json();
      setResults(data);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { fetchResults(); }, [refreshTrigger]);

  const filtered = results.filter(t =>
    t.id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h2>Results</h2>
        <span className="result-count">{results.length}</span>
      </div>

      <div className="search-box">
        <input
          type="text"
          placeholder="Search ID..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="search-input"
          onClick={e => e.stopPropagation()}
        />
      </div>

      <div className="tender-list">
        {loading && <div className="sidebar-status">Scanning...</div>}
        {!loading && filtered.length === 0 && (
          <div className="sidebar-status">No tenders found.</div>
        )}
        {filtered.map(t => <TenderCard key={t.id} tender={t} />)}
      </div>

      <div className="sidebar-footer">
        <button className="refresh-btn" onClick={fetchResults}>↻ Refresh</button>
      </div>
    </aside>
  );
}

function Agent({ onSessionComplete }) {
  const [messages, setMessages] = useState([
    { type: 'bot', text: 'Welcome to TenderFinder. Select a site below to begin a scraping session.' }
  ]);
  const [isScraping, setIsScraping] = useState(false);
  const [savePath, setSavePath] = useState('');
  const [logs, setLogs] = useState([]);
  const ws = useRef(null);
  const logEndRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    const connectWs = () => {
      ws.current = new WebSocket(`${WS_BASE}/ws/logs`);
      ws.current.onmessage = e => {
        setLogs(prev => {
          const next = [...prev, e.data];
          return next.length > 500 ? next.slice(next.length - 500) : next;
        });
      };
      ws.current.onclose = () => setTimeout(connectWs, 3000);
    };
    connectWs();
    return () => { if (ws.current) ws.current.close(); };
  }, []);

  useEffect(() => {
    if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    if (messagesEndRef.current) messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const addBot = (text) => setMessages(prev => [...prev, { type: 'bot', text }]);
  const addUser = (text) => setMessages(prev => [...prev, { type: 'user', text }]);
  const addError = (text) => setMessages(prev => [...prev, { type: 'error', text }]);

  const handleStart = async (choice) => {
    const siteName = choice === '1' ? 'IREPS' : 'Tender Detail';
    addUser(`Start ${siteName}${savePath ? ` → Save to: ${savePath}` : ''}`);
    setIsScraping(true);
    setLogs([]);

    try {
      const res = await fetch(`${API_BASE}/api/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ choice, save_path: savePath })
      });
      const data = await res.json();
      if (data.status === 'error') {
        addError(data.message);
        setIsScraping(false);
      } else {
        addBot(`Initializing ${siteName} session... monitoring live output below.`);
      }
    } catch (e) {
      addError('Could not reach the backend server.');
      setIsScraping(false);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${API_BASE}/api/stop`, { method: 'POST' });
      addBot('Stop signal sent. Gracefully shutting down...');
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/status`, { cache: 'no-store' });
        const data = await res.json();
        
        if (data.status === 'running' && !isScraping) {
          setIsScraping(true);
        } else if (data.status === 'idle' && isScraping) {
          setIsScraping(false);
          try {
            const rr = await fetch(`${API_BASE}/api/results`, { cache: 'no-store' });
            const rd = await rr.json();
            const ids = rd.slice(0, 5).map(t => t.id).join(', ');
            addBot(`Session complete. Captured: ${ids || 'none'}.`);
            addBot('Results updated in the left panel. Click a tender to download files.');
            onSessionComplete && onSessionComplete();
          } catch {
            addBot('Session complete. Refresh the Results panel to view downloads.');
          }
        }
      } catch (e) { /* ignore */ }
    };

    checkStatus(); // Initial check
    const interval = setInterval(checkStatus, 3000);
    return () => clearInterval(interval);
  }, [isScraping, onSessionComplete]);

  return (
    <main className="agent-panel">
      <div className="agent-header">
        <div className="agent-title">
          <span className="agent-icon">🔍</span>
          <h1>TenderFinder Agent</h1>
        </div>
        <div className="status-pill">
          <span className={`status-dot ${isScraping ? 'active' : 'idle'}`}></span>
          {isScraping ? 'Running' : 'Idle'}
        </div>
      </div>

      <div className="messages-area">
        {messages.map((m, i) => (
          <div key={i} className={`msg-row ${m.type}`}>
            {m.type === 'bot' && <div className="msg-avatar">🤖</div>}
            <div className="msg-bubble">{m.text}</div>
            {m.type === 'user' && <div className="msg-avatar user-av">👤</div>}
          </div>
        ))}

        {isScraping && (
          <div className="terminal-block">
            <div className="terminal-bar">
              <span className="t-dot r"></span>
              <span className="t-dot y"></span>
              <span className="t-dot g"></span>
              <span className="t-label">Live Output</span>
            </div>
            <div className="terminal-body">
              {logs.map((l, i) => <div key={i} className="t-line">{l}</div>)}
              <div ref={logEndRef} />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="agent-input-area">
        {!isScraping ? (
          <div className="controls">
            <div className="path-field">
              <label>Save Location (optional)</label>
              <input
                type="text"
                placeholder="e.g. C:\Tenders"
                value={savePath}
                onChange={e => setSavePath(e.target.value)}
                className="path-input"
              />
            </div>
            <div className="site-buttons">
              <button className="btn-start btn-ireps" onClick={() => handleStart('1')}>
                Analyze IREPS
              </button>
              <button className="btn-start btn-td" onClick={() => handleStart('2')}>
                Analyze Tender Detail
              </button>
            </div>
          </div>
        ) : (
          <div className="controls">
            <button className="btn-stop" onClick={handleStop}>
              ⏹ Stop Session
            </button>
          </div>
        )}
      </div>
    </main>
  );
}

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="app-shell">
      <Dashboard refreshTrigger={refreshKey} />
      <Agent onSessionComplete={() => setRefreshKey(k => k + 1)} />
    </div>
  );
}
