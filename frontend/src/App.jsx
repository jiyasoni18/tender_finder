import { useState, useEffect, useRef } from "react";
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
  "Surat Municipal Corporation",
  "Ahmedabad Municipal Corporation",
  "Vadodara Municipal Corporation",
  "Rajkot Municipal Corporation",
  "Bhavnagar Municipal Corporation",
  "Jamnagar Municipal Corporation",
  "Junagadh Municipal Corporation",
  "Gandhinagar Municipal Corporation",
  "Gujarat Fibre Grid Network Limited"
];

function TenderCard({ tender }) {
  const [expanded, setExpanded] = useState(false);
  const isNA = !tender.value || tender.value === "N/A" || tender.value === "?";

  return (
    <div className={`tender-card${isNA ? " manual-review" : ""}`} onClick={() => setExpanded(!expanded)}>
      <div className="tender-card-header">
        <div className="tender-id">{tender.id}</div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          {isNA && <span className="na-badge">⚠️ N/A</span>}
          <div className={`tender-badge${isNA ? " badge-na" : ""}`}>{isNA ? "Manual Review" : "Passed"}</div>
        </div>
      </div>

      {tender.summary && tender.summary !== "No summary available." && (
        <p className="tender-summary">{tender.summary}</p>
      )}

      {isNA && (
        <div className="manual-review-notice">
          📋 Value could not be extracted automatically. Please review the documents below.
        </div>
      )}

      {expanded && (
        <div className="tender-actions" onClick={e => e.stopPropagation()}>
          {tender.details_pdf && (
            <a href={`${API_BASE}${tender.details_pdf}`} target="_blank" rel="noreferrer" className="action-link action-ai">
              ✨ AI Summary PDF
            </a>
          )}
          {tender.original_docs.filter(d => !d.endsWith(".html")).map((doc, i) => (
            <a key={i} href={`${API_BASE}${doc}`} target="_blank" rel="noreferrer" className="action-link action-doc">
              📄 {doc.split("/").pop()}
            </a>
          ))}
        </div>
      )}

      <div className="tender-expand-hint">{expanded ? "▲ collapse" : "▼ view files"}</div>
    </div>
  );
}

function Dashboard({ refreshTrigger }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showNAOnly, setShowNAOnly] = useState(false);

  const fetchResults = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/results`, { cache: "no-store" });
      setResults(await res.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { fetchResults(); }, [refreshTrigger]);

  const isNA = t => !t.value || t.value === "N/A" || t.value === "?";
  const naCount = results.filter(isNA).length;
  const filtered = results.filter(t =>
    t.id.toLowerCase().includes(search.toLowerCase()) && (!showNAOnly || isNA(t))
  );

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h2>Results</h2>
        <span className="result-count">{results.length}</span>
      </div>
      <div className="search-box">
        <input type="text" placeholder="Search ID..." value={search}
          onChange={e => setSearch(e.target.value)} className="search-input"
          onClick={e => e.stopPropagation()} />
      </div>
      {naCount > 0 && (
        <div className={`na-filter-banner${showNAOnly ? " active" : ""}`} onClick={() => setShowNAOnly(v => !v)}>
          ⚠️ {naCount} tender{naCount !== 1 ? "s" : ""} need manual review
          <span className="na-filter-toggle">{showNAOnly ? "✕ Show all" : "→ View"}</span>
        </div>
      )}
      <div className="tender-list">
        {loading && <div className="sidebar-status">Scanning...</div>}
        {!loading && filtered.length === 0 && <div className="sidebar-status">No tenders found.</div>}
        {filtered.map(t => <TenderCard key={t.id} tender={t} />)}
      </div>
      <div className="sidebar-footer">
        <button className="refresh-btn" onClick={fetchResults}>↻ Refresh</button>
      </div>
    </aside>
  );
}

function SearchOptions({ options, onChange, activePortal }) {
  const set = key => e => onChange({ ...options, [key]: e.target.value });
  return (
    <div className="search-options-grid">
      {activePortal === "1" && (
        <>
          <div className="option-field">
            <label>Department</label>
            <select value={options.department} onChange={set("department")}>
              {DEPARTMENTS.map(d => <option key={d} value={d === "ALL" ? "" : d}>{d}</option>)}
            </select>
          </div>
          <div className="option-field">
            <label>Railway / PU</label>
            <select value={options.railway_pu} onChange={set("railway_pu")}>
              {RAILWAYS.map(r => <option key={r} value={r === "All" ? "" : r}>{r}</option>)}
            </select>
          </div>
        </>
      )}

      {activePortal === "3" && (
        <div className="option-field">
          <label>nProcure Client</label>
          <select value={options.nprocure_client} onChange={set("nprocure_client")} style={{ width: "auto", minWidth: "250px", maxWidth: "400px" }}>
            {NPROCURE_CLIENTS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      )}

      {activePortal === "2" && (
        <div className="option-field">
          <label>Keywords</label>
          <input type="text" placeholder="e.g. CCTV, smart city" value={options.keywords || ""} onChange={set("keywords")} />
        </div>
      )}

      <div className="option-field">
        <label>Closing Date From</label>
        <input type="date" value={options.date_from} onChange={set("date_from")} />
      </div>
      <div className="option-field">
        <label>Closing Date To</label>
        <input type="date" value={options.date_to} onChange={set("date_to")} />
      </div>
      
      {activePortal !== "2" && (
        <>
          <div className="option-field">
            <label>Price Range Min (₹)</label>
            <input type="number" placeholder="e.g. 5000000" value={options.price_min || ""} onChange={set("price_min")} />
          </div>
          <div className="option-field">
            <label>Price Range Max (₹)</label>
            <input type="number" placeholder="e.g. 500000000" value={options.price_max || ""} onChange={set("price_max")} />
          </div>
        </>
      )}

      <div className="option-field">
        <label>Max Tenders to Analyze</label>
        <input type="number" min="1" max="200" placeholder="All" value={options.max_tenders} onChange={set("max_tenders")} />
      </div>
      <div className="option-field">
        <label>Save Location (optional)</label>
        <input type="text" placeholder="e.g. C:\Tenders" value={options.save_path} onChange={set("save_path")} />
      </div>
    </div>
  );
}

function Agent({ onSessionComplete }) {
  const [messages, setMessages] = useState([
    { type: "bot", text: "Welcome to TenderFinder. Select a portal above, configure your search, and click Start Analysis." }
  ]);
  const [isScraping, setIsScraping] = useState(false);
  const [isConfigMinimized, setIsConfigMinimized] = useState(false);
  const [activePortal, setActivePortal] = useState("1");
  const [searchOptions, setSearchOptions] = useState({
    department: "S AND T", railway_pu: "", date_from: "", date_to: "", max_tenders: "", save_path: "",
    price_min: "", price_max: "", nprocure_client: "Surat Municipal Corporation", keywords: ""
  });
  const [logs, setLogs] = useState([]);
  const ws = useRef(null);
  const logEndRef = useRef(null);
  const messagesEndRef = useRef(null);

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
  useEffect(() => { if (messagesEndRef.current) messagesEndRef.current.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const addBot = text => setMessages(prev => [...prev, { type: "bot", text }]);
  const addUser = text => setMessages(prev => [...prev, { type: "user", text }]);

  const handleStart = async choice => {
    const siteName = choice === "1" ? "IREPS" : choice === "2" ? "Tender Detail" : "nProcure";
    const parts = [
      choice === "1" && searchOptions.department && searchOptions.department !== "ALL" && `Dept: ${searchOptions.department}`,
      choice === "1" && searchOptions.railway_pu && `Railway: ${searchOptions.railway_pu}`,
      choice === "3" && searchOptions.nprocure_client && `Client: ${searchOptions.nprocure_client}`,
      searchOptions.date_from && `From: ${searchOptions.date_from}`,
      searchOptions.date_to && `To: ${searchOptions.date_to}`,
      searchOptions.max_tenders && `Max: ${searchOptions.max_tenders}`,
      searchOptions.price_min && `Min: ₹${searchOptions.price_min}`,
      searchOptions.price_max && `Max: ₹${searchOptions.price_max}`,
    ].filter(Boolean);
    addUser(`Analyze ${siteName}${parts.length ? ` [${parts.join(" | ")}]` : ""}`);
    
    // Automatically minimize configuration when starting a run
    setIsConfigMinimized(true);

    try {
      const res = await fetch(`${API_BASE}/api/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice, ...searchOptions })
      });
      const data = await res.json();
      if (data.status === "success") {
        addBot(`Initializing ${siteName} session... monitoring live output below.`);
        setIsScraping(true);
      } else {
        addBot(`Failed to start: ${data.message}`);
      }
    } catch (e) {
      addBot(`Error connecting to server: ${e.message}`);
    }
  };

  const handleFileUpload = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    addBot(`Uploading session file ${file.name}...`);
    try {
      const res = await fetch(`${API_BASE}/api/upload-ireps-session`, { method: "POST", body: formData });
      const data = await res.json();
      addBot(data.message);
    } catch (error) { addBot(`Upload failed: ${error.message}`); }
  };

  const handleStop = async () => {
    try {
      await fetch(`${API_BASE}/api/stop`, { method: "POST" });
      addBot("Stop signal sent. Gracefully shutting down...");
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/status`, { cache: "no-store" });
        const data = await res.json();
        if (data.status === "running" && !isScraping) setIsScraping(true);
        else if (data.status === "idle" && isScraping) {
          setIsScraping(false);
          try {
            const rr = await fetch(`${API_BASE}/api/results`, { cache: "no-store" });
            const rd = await rr.json();
            addBot(`Session complete. Captured: ${rd.slice(0, 5).map(t => t.id).join(", ") || "none"}.`);
            addBot("Results updated in the left panel. Click a tender to download files.");
            onSessionComplete && onSessionComplete();
          } catch { addBot("Session complete. Refresh the Results panel to view downloads."); }
        }
      } catch (e) { /* ignore */ }
    };
    check();
    const iv = setInterval(check, 3000);
    return () => clearInterval(iv);
  }, [isScraping, onSessionComplete]);

  return (
    <main className="agent-panel">
      <div className="agent-header">
        <div className="agent-title">
          <span className="agent-icon">🔍</span>
          <h1>TenderFinder Agent</h1>
        </div>
        <div className="status-pill">
          <span className={`status-dot ${isScraping ? "active" : "idle"}`}></span>
          {isScraping ? "Running" : "Idle"}
        </div>
      </div>

      <div className="messages-area">
        {messages.map((m, i) => (
          <div key={i} className={`msg-row ${m.type}`}>
            {m.type === "bot" && <div className="msg-avatar">🤖</div>}
            <div className="msg-bubble">{m.text}</div>
            {m.type === "user" && <div className="msg-avatar user-av">👤</div>}
          </div>
        ))}
        {(isScraping || logs.length > 0) && (
          <div className="terminal-block">
            <div className="terminal-bar">
              <span className="t-dot r"></span><span className="t-dot y"></span><span className="t-dot g"></span>
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
            <div className="portal-tabs" style={{ display: "flex", gap: "10px", marginBottom: "15px" }}>
              <button 
                className={`btn-start ${activePortal === "1" ? "btn-ireps" : ""}`} 
                style={{ flex: 1, padding: "10px", background: activePortal === "1" ? "" : "#e2e8f0", color: activePortal === "1" ? "" : "#64748b", boxShadow: activePortal === "1" ? "" : "none" }} 
                onClick={() => setActivePortal("1")}
              >IREPS</button>
              <button 
                className={`btn-start ${activePortal === "2" ? "btn-td" : ""}`} 
                style={{ flex: 1, padding: "10px", background: activePortal === "2" ? "" : "#e2e8f0", color: activePortal === "2" ? "" : "#64748b", boxShadow: activePortal === "2" ? "" : "none" }} 
                onClick={() => setActivePortal("2")}
              >Tender Detail</button>
              <button 
                className={`btn-start ${activePortal === "3" ? "btn-nprocure" : ""}`} 
                style={{ flex: 1, padding: "10px", background: activePortal === "3" ? "linear-gradient(135deg, #10b981 0%, #059669 100%)" : "#e2e8f0", color: activePortal === "3" ? "#fff" : "#64748b", boxShadow: activePortal === "3" ? "" : "none" }} 
                onClick={() => setActivePortal("3")}
              >nProcure</button>
            </div>

            <div className="search-options-panel">
              <div 
                className="options-header" 
                onClick={() => setIsConfigMinimized(!isConfigMinimized)}
                style={{ cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}
              >
                <span>⚙️ Search Configuration</span>
                <span>{isConfigMinimized ? "▼" : "▲"}</span>
              </div>
              {!isConfigMinimized && <SearchOptions activePortal={activePortal} options={searchOptions} onChange={setSearchOptions} />}
            </div>
            <div className="site-buttons" style={{ flexDirection: "column", gap: "10px" }}>
              <button className="btn-start" style={{ background: "#3b82f6", width: "100%", padding: "14px", fontSize: "16px" }} onClick={() => handleStart(activePortal)}>
                🚀 Start Analysis for {activePortal === "1" ? "IREPS" : activePortal === "2" ? "Tender Detail" : "nProcure"}
              </button>
              {activePortal === "1" && (
                <div style={{ textAlign: "center" }}>
                  <label className="upload-label" style={{ display: "inline-block" }}>
                    <input type="file" style={{ display: "none" }} accept=".json" onChange={handleFileUpload} />
                    📤 Upload Auth JSON
                  </label>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="controls">
            <button className="btn-stop" onClick={handleStop}>⏹ Stop Session</button>
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
