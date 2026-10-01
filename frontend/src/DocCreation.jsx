import React, { useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function DocCreation() {
  const [company, setCompany] = useState("Arkonic");
  const [documentId, setDocumentId] = useState("");
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState(null);
  const [docUrl, setDocUrl] = useState("");
  const [error, setError] = useState("");

  const handleMapDocument = async () => {
    if (!documentId || !file) return;
    setLoading(true);
    setError("");
    setDocUrl("");

    const formData = new FormData();
    formData.append("company", company);
    formData.append("document_id", documentId);
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/docs/map`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.status === "success") {
        setDocUrl(data.doc_url);
      } else {
        setError(data.message || "Failed to map document.");
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
          <span className="agent-icon">📑</span>
          <h1>Document Mapping</h1>
        </div>
      </div>
      
      <div className="phase-content">
        <div className="upload-box" style={{ maxWidth: "500px", margin: "0 auto" }}>
          <h2>Map Tender Documents</h2>
          <p>Select the target company, enter the Tender ID, and upload the NIT doc.</p>
          
          <div className="option-field" style={{ textAlign: "left", marginTop: "20px" }}>
            <label>Target Company</label>
            <select value={company} onChange={(e) => setCompany(e.target.value)}>
              <option value="Arkonic">Arkonic</option>
              <option value="Aquint">Aquint</option>
            </select>
          </div>

          <div className="option-field" style={{ textAlign: "left", marginTop: "15px" }}>
            <label>Tender ID</label>
            <input 
              type="text" 
              placeholder="e.g. 12345" 
              value={documentId} 
              onChange={(e) => setDocumentId(e.target.value)} 
            />
          </div>

          <div className="option-field" style={{ textAlign: "left", marginTop: "15px" }}>
            <label>Upload NIT Document (PDF)</label>
            <input 
              type="file" 
              accept=".pdf"
              className="file-input"
              onChange={(e) => setFile(e.target.files[0])} 
            />
          </div>
          
          <button 
            className="btn-start" 
            onClick={handleMapDocument} 
            disabled={!documentId || !file || loading}
            style={{ background: "#10b981", marginTop: "20px", width: "100%", color: "#fff" }}
          >
            {loading ? "Mapping..." : "Generate Mapped Document"}
          </button>
        </div>

        {error && <div className="error-msg">{error}</div>}

        {docUrl && (
          <div className="summary-preview">
            <h3>Document Mapped Successfully!</h3>
            <a href={`${API_BASE}${docUrl}`} target="_blank" rel="noreferrer" className="action-link action-doc">
              Download Mapped Package
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
