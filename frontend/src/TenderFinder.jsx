import React, { useState, useEffect, useRef } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace("http", "ws");

const DEPARTMENTS = ["S AND T", "CIVIL", "ELECTRICAL", "MECHANICAL", "STORES", "ALL"];
const RAILWAYS = [
  "All", "Northern Railway", "Southern Railway", "Eastern Railway", "Western Railway",
  "Central Railway", "North Eastern Railway", "Northeast Frontier Railway",
  "South Eastern Railway", "South Central Railway", "East Central Railway",
  "East Coast Railway", "West Central Railway", "North Central Railway",
  "North Western Railway", "South Western Railway", "Metro Railway Kolkata"
];
const NPROCURE_CLIENTS = [
  "Surat Municipal Corporation", "Ahmedabad Municipal Corporation", "Vadodara Municipal Corporation",
  "Rajkot Municipal Corporation", "Bhavnagar Municipal Corporation", "Jamnagar Municipal Corporation",
  "Junagadh Municipal Corporation", "Gandhinagar Municipal Corporation", "Gujarat Fibre Grid Network Limited"
];

function TenderTable({ results, activePortal }) {
  const [expanded, setExpanded] = useState({});
  const toggle = id => setExpanded(prev => ({...prev, [id]: !prev[id]}));
  
  return (
    <div className="tender-table-container">
      <table className="tender-table">
        <thead>
          <tr>
            <th>Tender ID</th>
            <th>Value</th>
            <th>Closing Date</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {results.map(t => (
            <React.Fragment key={t.id}>
            <tr>
              <td className="font-mono">{t.id}</td>
              <td>{t.value || "N/A"}</td>
              <td>{t.closing_date || "N/A"}</td>
              <td>
                <span className="badge badge-success">
                  In Range
                </span>
              </td>
              <td>
                <button onClick={() => toggle(t.id)} className="action-link-sm" style={{background: 'var(--primary)', color: 'white'}}>
                  {expanded[t.id] ? 'Hide Docs ▲' : 'View Docs ▼'}
                </button>
              </td>
            </tr>
            {expanded[t.id] && (
              <tr>
                <td colSpan="5" style={{background: 'var(--bg)', padding: '1rem'}}>
                  <div style={{display: 'flex', gap: '0.5rem', flexWrap: 'wrap'}}>
                    {t.details_pdf && (
                       <a href={`${API_BASE}${t.details_pdf}`} target="_blank" rel="noreferrer" className="action-link-sm" style={{borderColor: 'var(--success)', color: 'var(--success)'}}>✨ AI Summary</a>
                    )}
                    {(t.original_docs || []).filter(d => !d.endsWith(".html")).map((doc, i) => (
                      <a key={i} href={`${API_BASE}${doc}`} target="_blank" rel="noreferrer" className="action-link-sm">
                        📄 Document {i+1}
                      </a>
                    ))}
                    {(!t.original_docs || t.original_docs.length === 0) && !t.details_pdf && (
                      <span style={{color: 'var(--muted)', fontSize: '0.85rem'}}>No documents downloaded.</span>
                    )}
                  </div>
                </td>
              </tr>
            )}
            </React.Fragment>
          ))}
          {results.length === 0 && (
            <tr><td colSpan="5" style={{ textAlign: 'center', padding: '2rem', color: 'var(--muted)' }}>No tenders analyzed yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function TenderFinder() {
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const [activePortal, setActivePortal] = useState("1");
  const [searchOptions, setSearchOptions] = useState({
    department: "S AND T", railway_pu: "", date_from: "", date_to: "", max_tenders: "", save_path: "",
    price_min: "", price_max: "", nprocure_client: "Surat Municipal Corporation", keywords: ""
  });
  
  const [isScraping, setIsScraping] = useState(false);
  const [logs, setLogs] = useState([]);
  const [results, setResults] = useState([]);
  const ws = useRef(null);
  const logEndRef = useRef(null);
  
  const setOpt = key => e => setSearchOptions({ ...searchOptions, [key]: e.target.value });

  // WebSocket for Live Terminal
  useEffect(() => {
    const connect = () => {
      ws.current = new WebSocket(`${WS_BASE}/ws/logs`);
      ws.current.onmessage = e => setLogs(prev => { const n = [...prev, e.data]; return n.length > 500 ? n.slice(-500) : n; });
      ws.current.onclose = () => setTimeout(connect, 3000);
    };
    connect();
    return () => { if (ws.current) ws.current.close(); };
  }, []);

  useEffect(() => { if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  // Fetch Results
  const fetchResults = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/results`, { cache: "no-store" });
      const data = await res.json();
      setResults(data);
      return data;
    } catch (e) { console.error(e); return []; }
  };
  
  useEffect(() => { fetchResults(); }, []);

  // Polling for Status & auto-fetching results when done
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/status`, { cache: "no-store" });
        const data = await res.json();
        if (data.status === "running" && !isScraping) setIsScraping(true);
        else if (data.status === "idle" && isScraping) {
          setIsScraping(false);
          fetchResults().then(resData => {
            if (resData && resData.length > 0) {
              const confirmSummary = window.confirm(`Can I create a summary for the in-range ${resData.length} document(s) now?`);
              if (confirmSummary) {
                fetch(`${API_BASE}/api/summary/batch`, { method: "POST" })
                  .then(() => alert("Batch summary generation started in the background! Summaries will appear when you refresh."))
                  .catch(err => console.error("Batch summary failed:", err));
              }
            }
          });
        }
      } catch (e) { /* ignore */ }
    };
    check();
    const iv = setInterval(check, 3000);
    return () => clearInterval(iv);
  }, [isScraping]);

  const handleStart = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice: activePortal, ...searchOptions })
      });
      const data = await res.json();
      if (data.status === "success") {
        setIsScraping(true);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${API_BASE}/api/stop`, { method: "POST" });
    } catch (e) { console.error(e); }
  };

  return (
    <div className="two-col-layout">
      {/* LEFT SIDEBAR: PORTAL CONFIG */}
      <aside className={`config-sidebar ${!isSidebarOpen ? "closed" : ""}`}>
        <div className="sidebar-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>Portal Configuration</h2>
          <button onClick={() => setSidebarOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2rem', color: 'var(--muted)' }}>✕</button>
        </div>
        
        <div className="config-body">
          <div className="portal-tabs">
            <button className={`portal-tab ${activePortal === "1" ? "active" : ""}`} onClick={() => setActivePortal("1")}>IREPS</button>
            <button className={`portal-tab ${activePortal === "2" ? "active" : ""}`} onClick={() => setActivePortal("2")}>Tender Detail</button>
            <button className={`portal-tab ${activePortal === "3" ? "active" : ""}`} onClick={() => setActivePortal("3")}>nProcure</button>
            <button className={`portal-tab ${activePortal === "4" ? "active" : ""}`} onClick={() => setActivePortal("4")}>GEM</button>
          </div>

          <div className="search-options-form">
            {activePortal === "1" && (
              <>
                <div className="option-field">
                  <label>Department</label>
                  <select value={searchOptions.department} onChange={setOpt("department")}>
                    {DEPARTMENTS.map(d => <option key={d} value={d === "ALL" ? "" : d}>{d}</option>)}
                  </select>
                </div>
                <div className="option-field">
                  <label>Railway / PU</label>
                  <select value={searchOptions.railway_pu} onChange={setOpt("railway_pu")}>
                    {RAILWAYS.map(r => <option key={r} value={r === "All" ? "" : r}>{r}</option>)}
                  </select>
                </div>
              </>
            )}

            {activePortal === "3" && (
              <div className="option-field">
                <label>nProcure Client</label>
                <select value={searchOptions.nprocure_client} onChange={setOpt("nprocure_client")}>
                  {NPROCURE_CLIENTS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            )}

            {(activePortal === "1" || activePortal === "2" || activePortal === "4") && (
              <div className="option-field">
                <label>Keywords</label>
                <input type="text" placeholder="e.g. CCTV, smart city" value={searchOptions.keywords} onChange={setOpt("keywords")} />
              </div>
            )}

            <div className="option-row">
              <div className="option-field">
                <label>Date From</label>
                <input type="date" value={searchOptions.date_from} onChange={setOpt("date_from")} />
              </div>
              <div className="option-field">
                <label>Date To</label>
                <input type="date" value={searchOptions.date_to} onChange={setOpt("date_to")} />
              </div>
            </div>
            
            {activePortal !== "2" && (
              <div className="option-row">
                <div className="option-field">
                  <label>Min Price (₹)</label>
                  <input type="number" placeholder="5000000" value={searchOptions.price_min} onChange={setOpt("price_min")} />
                </div>
                <div className="option-field">
                  <label>Max Price (₹)</label>
                  <input type="number" placeholder="50000000" value={searchOptions.price_max} onChange={setOpt("price_max")} />
                </div>
              </div>
            )}

            <div className="option-field">
              <label>Max Tenders</label>
              <input type="number" placeholder="All" value={searchOptions.max_tenders} onChange={setOpt("max_tenders")} />
            </div>
          </div>
        </div>

        <div className="config-footer">
          {!isScraping ? (
            <button className="btn-start-large" onClick={handleStart}>🚀 Start Agent</button>
          ) : (
            <button className="btn-stop-large" onClick={handleStop}>🛑 Stop Agent</button>
          )}
        </div>
      </aside>

      {/* RIGHT MAIN CONTENT */}
      <main className="main-content">
        <div className="content-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            {!isSidebarOpen && (
              <button onClick={() => setSidebarOpen(true)} style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: 'var(--radius)', padding: '0.5rem 1rem', cursor: 'pointer', fontWeight: 600 }}>
                ☰ Config
              </button>
            )}
            <h1>Dashboard & Live Terminal</h1>
          </div>
          <div className="status-pill">
            <span className={`status-dot ${isScraping ? "active" : "idle"}`}></span>
            {isScraping ? "Agent Running" : "System Idle"}
          </div>
        </div>

        <div className="terminal-pane">
          <div className="terminal-bar">
            <span className="t-dot r"></span><span className="t-dot y"></span><span className="t-dot g"></span>
            <span className="t-label">Live Output</span>
          </div>
          <div className="terminal-body font-mono">
            {logs.length === 0 && <span style={{color: '#64748b'}}>Waiting for agent to start...</span>}
            {logs.map((l, i) => <div key={i} className="t-line">{l}</div>)}
            <div ref={logEndRef} />
          </div>
        </div>

        <div className="table-pane">
          <div className="table-header">
            <h2>{activePortal === "1" ? "IREPS" : activePortal === "2" ? "Tender Detail" : activePortal === "3" ? "nProcure" : "GEM"} Tenders</h2>
            <button className="refresh-btn" onClick={fetchResults}>↻ Refresh</button>
          </div>
          <TenderTable results={results} activePortal={activePortal} />
        </div>
      </main>
    </div>
  );
}
