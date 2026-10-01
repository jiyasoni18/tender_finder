import React, { useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function SummaryCreation() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [summaryUrl, setSummaryUrl] = useState("");
  const [error, setError] = useState("");

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const generateSummary = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    setSummaryUrl("");
    
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/summary/generate`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.status === "success") {
        setSummaryUrl(data.summary_url);
      } else {
        setError(data.message || "Failed to generate summary.");
      }
    } catch (e) {
      setError("Network error: " + e.message);
    }
    setLoading(false);
  };

  return (
    <div className="phase-container">
      <div className="agent-header">
        <div className="agent-title">
          <span className="agent-icon">📄</span>
          <h1>Summary Creation</h1>
        </div>
      </div>
      
      <div className="phase-content">
        <div className="upload-box">
          <h2>Upload NIT Document</h2>
          <p>Select a PDF tender document to automatically extract and generate a standard formatted summary.</p>
          
          <input 
            type="file" 
            accept=".pdf" 
            onChange={handleFileChange} 
            className="file-input"
          />
          
          <button 
            className="btn-start" 
            onClick={generateSummary} 
            disabled={!file || loading}
            style={{ background: "#3b82f6", marginTop: "20px" }}
          >
            {loading ? "Generating..." : "Generate Summary"}
          </button>
        </div>

        {error && <div className="error-msg">{error}</div>}

        {summaryUrl && (
          <div className="summary-preview">
            <h3>Summary Generated Successfully!</h3>
            <p>The summary format matches the required structure (Overview, Scope, Strategy, Risks, Eligibility, Mapping).</p>
            <a href={`${API_BASE}${summaryUrl}`} target="_blank" rel="noreferrer" className="action-link action-ai">
              View Generated PDF
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
