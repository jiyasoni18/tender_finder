import React, { useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function SummaryCreation() {
  const [website, setWebsite] = useState("ireps");
  const [company, setCompany] = useState("Arkonic");
  const [file, setFile] = useState(null);
  const [atcUpload, setAtcUpload] = useState(null);
  const [atcAutoFetched, setAtcAutoFetched] = useState(null);
  const [atcFetchLoading, setAtcFetchLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [summaryUrl, setSummaryUrl] = useState("");
  const [generatedMeta, setGeneratedMeta] = useState(null);
  const [error, setError] = useState("");

  const triggerAtcFetch = async (selectedFile) => {
    if (!selectedFile || website !== "gem") return;
    setAtcFetchLoading(true);
    setAtcAutoFetched(null);
    try {
      const fd = new FormData();
      fd.append("file", selectedFile);
      const res = await fetch(`${API_BASE}/api/docs/fetch_atc`, { method: "POST", body: fd });
      const data = await res.json();
      if (data.status === "success" && data.atc_found) {
        setAtcAutoFetched({ name: data.atc_filename, count: data.attachments_count });
      } else {
        setAtcAutoFetched(null);
      }
    } catch (err) {
      console.warn("Failed to auto-fetch ATC:", err);
    }
    setAtcFetchLoading(false);
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      setFile(selected);
      if (website === "gem") {
        triggerAtcFetch(selected);
      }
    }
  };

  const generateSummary = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    setSummaryUrl("");
    setGeneratedMeta(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("website", website);
    formData.append("company", company);

    if (atcUpload) {
      formData.append("atc_file", atcUpload);
    } else if (atcAutoFetched && atcAutoFetched.name) {
      formData.append("atc_file_name", atcAutoFetched.name);
    }

    try {
      const res = await fetch(`${API_BASE}/api/summary/generate`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.status === "success") {
        setSummaryUrl(data.summary_url);
        setGeneratedMeta({
          website: website.toUpperCase(),
          company: company,
          filename: file.name
        });
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
        <div className="upload-box" style={{ maxWidth: "650px", margin: "0 auto", textAlign: "left" }}>
          <h2 style={{ textAlign: "center" }}>Create Tender Summary</h2>
          <p style={{ textAlign: "center", color: "#64748b", marginBottom: "25px" }}>
            Select the bidding portal &amp; target company, then upload the NIT to generate a tailored, professional tender summary.
          </p>

          {/* Upper Side: Portal Selection */}
          <div className="option-field" style={{ marginBottom: "18px" }}>
            <label style={{ display: "block", fontWeight: "600", marginBottom: "6px", color: "#1e293b" }}>
              Website / Portal (Upper Side)
            </label>
            <select
              value={website}
              onChange={(e) => {
                const val = e.target.value;
                setWebsite(val);
                if (val === "gem" && file) triggerAtcFetch(file);
              }}
              style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "14px" }}
            >
              <option value="ireps">IREPS (Railway Tenders)</option>
              <option value="gem">GeM (Government e-Marketplace)</option>
            </select>
          </div>

          {/* Lower Side: Target Company Selection */}
          <div className="option-field" style={{ marginBottom: "18px" }}>
            <label style={{ display: "block", fontWeight: "600", marginBottom: "6px", color: "#1e293b" }}>
              Target Company (Lower Side)
            </label>
            <select
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "14px" }}
            >
              <option value="Arkonic">Arkonic (Arkonik Fibertech India Pvt. Ltd.)</option>
              <option value="Aquint">Aquint (Aquint Infratele India Pvt. Ltd.)</option>
            </select>
          </div>

          {/* Upload NIT Document */}
          <div className="option-field" style={{ marginBottom: "18px" }}>
            <label style={{ display: "block", fontWeight: "600", marginBottom: "6px", color: "#1e293b" }}>
              Upload NIT Document (PDF)
            </label>
            <input
              type="file"
              accept=".pdf"
              onChange={handleFileChange}
              className="file-input"
            />
          </div>

          {/* If GeM: ATC Document Upload / Auto-Fetch */}
          {website === "gem" && (
            <div className="option-field" style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", fontWeight: "600", marginBottom: "6px", color: "#1e293b" }}>
                Upload ATC / Tender Document (Optional)
              </label>
              <input
                type="file"
                accept=".pdf,.doc,.docx"
                className="file-input"
                style={{ padding: "10px" }}
                onChange={(e) => setAtcUpload(e.target.files[0])}
              />
              {atcFetchLoading && (
                <div style={{ fontSize: "12px", color: "#2563eb", marginTop: "6px" }}>
                  ⏳ Auto-fetching buyer ATC &amp; SOW attachments from GeM...
                </div>
              )}
              {atcAutoFetched && !atcUpload && (
                <div style={{ fontSize: "12px", color: "#16a34a", marginTop: "6px", background: "#f0fdf4", padding: "6px 10px", borderRadius: "4px", border: "1px solid #86efac" }}>
                  <strong>✅ Auto-Fetched from GeM:</strong> {atcAutoFetched.name} ({atcAutoFetched.count} attachment{atcAutoFetched.count > 1 ? "s" : ""} merged)
                </div>
              )}
            </div>
          )}

          <button
            className="btn-start"
            onClick={generateSummary}
            disabled={!file || loading}
            style={{
              background: "#2563eb",
              marginTop: "10px",
              width: "100%",
              color: "#fff",
              padding: "12px",
              fontSize: "15px",
              fontWeight: "600",
              borderRadius: "6px",
              border: "none",
              cursor: file && !loading ? "pointer" : "not-allowed"
            }}
          >
            {loading ? "Generating Professional Summary..." : `Generate Summary for ${company} (${website.toUpperCase()})`}
          </button>
        </div>

        {error && <div className="error-msg" style={{ maxWidth: "650px", margin: "15px auto" }}>{error}</div>}

        {summaryUrl && (
          <div className="summary-preview" style={{ maxWidth: "650px", margin: "25px auto", padding: "20px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", textAlign: "center" }}>
            <h3 style={{ color: "#166534", marginBottom: "8px" }}>✅ Summary Generated Successfully!</h3>
            {generatedMeta && (
              <div style={{ display: "flex", justifyContent: "center", gap: "10px", marginBottom: "12px" }}>
                <span style={{ background: "#e0f2fe", color: "#0369a1", padding: "3px 10px", borderRadius: "12px", fontSize: "12px", fontWeight: "600" }}>
                  Portal: {generatedMeta.website}
                </span>
                <span style={{ background: "#fef3c7", color: "#b45309", padding: "3px 10px", borderRadius: "12px", fontSize: "12px", fontWeight: "600" }}>
                  Company: {generatedMeta.company}
                </span>
              </div>
            )}
            <p style={{ color: "#64748b", fontSize: "14px", marginBottom: "16px" }}>
              The comprehensive tender summary has been generated with all 6 sections (Overview, Scope, Strategy, Risks, Eligibility, Mandatory Submission Checklist &amp; Document Mapping).
            </p>
            <div style={{ display: "flex", gap: "12px", justifyContent: "center" }}>
              <a
                href={`${API_BASE}${summaryUrl}`}
                target="_blank"
                rel="noreferrer"
                className="action-link action-ai"
                style={{ padding: "10px 20px", textDecoration: "none", background: "#10b981", color: "#fff", borderRadius: "6px", fontWeight: "600" }}
              >
                📄 View Generated PDF
              </a>
              <a
                href={`${API_BASE}${summaryUrl}`}
                download
                className="action-link"
                style={{ padding: "10px 20px", textDecoration: "none", background: "#64748b", color: "#fff", borderRadius: "6px", fontWeight: "600" }}
              >
                ⬇️ Download PDF
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
