import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import { Activity, FileText, CheckCircle, AlertCircle } from "lucide-react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"];

export default function Home() {
  const navigate = useNavigate();
  const [data, setData] = useState([]);
  const [analytics, setAnalytics] = useState({ rejections: [], departments: [] });
  const [loading, setLoading] = useState(true);
  const [modalConfig, setModalConfig] = useState({ isOpen: false, title: "", filterType: null });

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/results`).then(r => r.json()),
      fetch(`${API_BASE}/api/analytics`).then(r => r.json())
    ])
      .then(([resultsData, analyticsData]) => {
        setData(resultsData);
        if (analyticsData && !analyticsData.status) {
          setAnalytics(analyticsData);
        }
        setLoading(false);
      })
      .catch(e => {
        console.error(e);
        setLoading(false);
      });
  }, []);

  const total = data.length;
  const passed = data.filter(t => t.value && t.value !== "N/A" && t.value !== "?").length;
  const manualReview = total - passed;

  const sourceMap = data.reduce((acc, t) => {
    const src = t.source || "Unknown";
    acc[src] = (acc[src] || 0) + 1;
    return acc;
  }, {});
  
  const pieData = Object.keys(sourceMap).map(k => ({ name: k, value: sourceMap[k] }));

  const barData = [
    { name: "Passed", count: passed },
    { name: "Manual Review", count: manualReview }
  ];

  const handleCardClick = (title, filterType) => {
    setModalConfig({ isOpen: true, title, filterType });
  };

  const getFilteredData = () => {
    if (modalConfig.filterType === 'ALL') return data;
    if (modalConfig.filterType === 'PASSED') return data.filter(t => t.value && t.value !== "N/A" && t.value !== "?");
    if (modalConfig.filterType === 'MANUAL') return data.filter(t => !(t.value && t.value !== "N/A" && t.value !== "?"));
    return [];
  };

  if (loading) {
    return <div className="loading-screen">Loading Dashboard...</div>;
  }

  return (
    <div className="home-dashboard">
      {modalConfig.isOpen && (
        <div className="modal-overlay" onClick={() => setModalConfig({ isOpen: false, title: "", filterType: null })} style={{position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{background: '#fff', padding: '2rem', borderRadius: '12px', width: '80%', maxWidth: '800px', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 10px 25px rgba(0,0,0,0.2)'}}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid #e2e8f0', paddingBottom: '1rem'}}>
              <h2 style={{margin: 0, color: '#1e293b'}}>{modalConfig.title}</h2>
              <button onClick={() => setModalConfig({ isOpen: false, title: "", filterType: null })} style={{background: 'none', border: 'none', fontSize: '1.5rem', cursor: 'pointer', color: '#64748b'}}>✕</button>
            </div>
            
            {modalConfig.filterType === 'SOURCES' ? (
              <div>
                <table style={{width: '100%', borderCollapse: 'collapse', textAlign: 'left'}}>
                  <thead>
                    <tr style={{background: '#f8fafc', borderBottom: '2px solid #e2e8f0'}}>
                      <th style={{padding: '12px', color: '#475569'}}>Source Name</th>
                      <th style={{padding: '12px', color: '#475569'}}>Tender Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(sourceMap).map(([src, count], i) => (
                      <tr key={i} style={{borderBottom: '1px solid #e2e8f0'}}>
                        <td style={{padding: '12px', fontWeight: 500}}>{src}</td>
                        <td style={{padding: '12px'}}>{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div>
                {getFilteredData().length === 0 ? (
                  <p style={{color: '#64748b', fontStyle: 'italic'}}>No tenders match this status.</p>
                ) : (
                  <table style={{width: '100%', borderCollapse: 'collapse', textAlign: 'left'}}>
                    <thead>
                      <tr style={{background: '#f8fafc', borderBottom: '2px solid #e2e8f0'}}>
                        <th style={{padding: '12px', color: '#475569'}}>ID</th>
                        <th style={{padding: '12px', color: '#475569'}}>Source</th>
                        <th style={{padding: '12px', color: '#475569'}}>Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getFilteredData().map((t, i) => (
                        <tr key={i} style={{borderBottom: '1px solid #e2e8f0'}}>
                          <td style={{padding: '12px', fontWeight: 600, color: '#3b82f6'}}>{t.id}</td>
                          <td style={{padding: '12px'}}>
                            <span style={{background: '#f1f5f9', padding: '4px 8px', borderRadius: '4px', fontSize: '0.85em'}}>{t.source || "Unknown"}</span>
                          </td>
                          <td style={{padding: '12px', fontSize: '0.9em', color: '#475569'}}>{t.summary}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="dashboard-header">
        <h1>Overview Dashboard</h1>
        <p>Live statistics of all analyzed and sourced tenders</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card" onClick={() => handleCardClick("Total Analyzed Tenders", "ALL")} style={{ cursor: "pointer" }}>
          <div className="stat-icon" style={{background: "#e0e7ff", color: "#4f46e5"}}><Activity /></div>
          <div>
            <h3>Total Analyzed</h3>
            <div className="stat-value">{total}</div>
          </div>
        </div>
        <div className="stat-card" onClick={() => handleCardClick("Passed Automatically", "PASSED")} style={{ cursor: "pointer" }}>
          <div className="stat-icon" style={{background: "#dcfce7", color: "#16a34a"}}><CheckCircle /></div>
          <div>
            <h3>Passed Automatically</h3>
            <div className="stat-value">{passed}</div>
          </div>
        </div>
        <div className="stat-card" onClick={() => handleCardClick("Needs Manual Review", "MANUAL")} style={{ cursor: "pointer" }}>
          <div className="stat-icon" style={{background: "#fef3c7", color: "#d97706"}}><AlertCircle /></div>
          <div>
            <h3>Needs Manual Review</h3>
            <div className="stat-value">{manualReview}</div>
          </div>
        </div>
        <div className="stat-card" onClick={() => handleCardClick("Sources Crawled", "SOURCES")} style={{ cursor: "pointer" }}>
          <div className="stat-icon" style={{background: "#f3e8ff", color: "#9333ea"}}><FileText /></div>
          <div>
            <h3>Sources Crawled</h3>
            <div className="stat-value">{Object.keys(sourceMap).length}</div>
          </div>
        </div>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <h3>Tenders by Source</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie 
                data={pieData} 
                cx="50%" 
                cy="50%" 
                outerRadius={100} 
                label={({ name, value }) => `${name}: ${value}`} 
                dataKey="value"
              >
                {pieData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Tender Status</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="charts-grid" style={{ marginTop: "30px" }}>
        <div className="chart-card">
          <h3>Rejection Reasons Breakdown</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie 
                data={analytics.rejections} 
                cx="50%" 
                cy="50%" 
                outerRadius={100} 
                label={({ name, value, reason }) => `${reason}: ${value}`} 
                dataKey="count"
                nameKey="reason"
              >
                {analytics.rejections.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[(index + 2) % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Tenders by Department / Zone</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={analytics.departments}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="department" tick={{fontSize: 12}} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
