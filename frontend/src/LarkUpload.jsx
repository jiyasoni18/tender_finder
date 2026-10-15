import React, { useState } from "react";
import { UploadCloud, FileSpreadsheet, CheckCircle, AlertCircle, Loader } from "lucide-react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function LarkUpload() {
  const [file, setFile] = useState(null);
  const [uploadMode, setUploadMode] = useState("whole"); // "whole" or "custom"
  const [customRows, setCustomRows] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [result, setResult] = useState(null);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
      setResult(null);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      alert("Please select an Excel file first.");
      return;
    }

    setIsUploading(true);
    setResult(null);

    const formData = new FormData();
    formData.append("file", file);
    if (uploadMode === "custom") {
      formData.append("custom_rows", customRows);
    } else {
      formData.append("custom_rows", "");
    }

    try {
      const response = await fetch(`${API_BASE}/api/upload-lark`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      setResult(data);
    } catch (error) {
      setResult({ status: "error", message: error.message });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="home-dashboard" style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div className="dashboard-header">
        <h1>Tender Advertising Upload</h1>
        <p>Upload Excel files to sync tender records with Lark Base</p>
      </div>

      <div style={{ background: '#fff', padding: '2rem', borderRadius: '12px', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)', marginTop: '2rem' }}>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {/* File Selection */}
          <div>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.5rem', color: '#1e293b' }}>
              1. Select Excel File
            </label>
            <div style={{
              border: '2px dashed #cbd5e1', 
              borderRadius: '8px', 
              padding: '2rem',
              textAlign: 'center',
              backgroundColor: '#f8fafc',
              cursor: 'pointer'
            }}>
              <input 
                type="file" 
                accept=".xlsx, .xls, .csv" 
                onChange={handleFileChange}
                style={{ display: 'none' }}
                id="file-upload"
              />
              <label htmlFor="file-upload" style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
                <FileSpreadsheet size={48} color="#3b82f6" />
                <span style={{ fontSize: '1.1rem', fontWeight: 500, color: '#475569' }}>
                  {file ? file.name : "Click to browse or drag and drop"}
                </span>
                {!file && <span style={{ fontSize: '0.9rem', color: '#94a3b8' }}>Supports .xlsx, .xls</span>}
              </label>
            </div>
          </div>

          {/* Upload Mode Selection */}
          <div>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.5rem', color: '#1e293b' }}>
              2. Select Upload Mode
            </label>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <label style={{ 
                flex: 1, 
                border: `2px solid ${uploadMode === 'whole' ? '#3b82f6' : '#e2e8f0'}`,
                borderRadius: '8px',
                padding: '1rem',
                cursor: 'pointer',
                backgroundColor: uploadMode === 'whole' ? '#eff6ff' : '#fff',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}>
                <input 
                  type="radio" 
                  name="uploadMode" 
                  value="whole" 
                  checked={uploadMode === 'whole'}
                  onChange={() => setUploadMode('whole')}
                  style={{ accentColor: '#3b82f6' }}
                />
                <span style={{ fontWeight: 500 }}>Upload Whole File</span>
              </label>

              <label style={{ 
                flex: 1, 
                border: `2px solid ${uploadMode === 'custom' ? '#3b82f6' : '#e2e8f0'}`,
                borderRadius: '8px',
                padding: '1rem',
                cursor: 'pointer',
                backgroundColor: uploadMode === 'custom' ? '#eff6ff' : '#fff',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}>
                <input 
                  type="radio" 
                  name="uploadMode" 
                  value="custom" 
                  checked={uploadMode === 'custom'}
                  onChange={() => setUploadMode('custom')}
                  style={{ accentColor: '#3b82f6' }}
                />
                <span style={{ fontWeight: 500 }}>Upload Custom Rows</span>
              </label>
            </div>
          </div>

          {/* Custom Rows Input */}
          {uploadMode === 'custom' && (
            <div style={{ animation: 'fadeIn 0.3s ease' }}>
              <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.5rem', color: '#1e293b' }}>
                Specify Rows (e.g. 1, 2, 5-10)
              </label>
              <input 
                type="text" 
                value={customRows}
                onChange={(e) => setCustomRows(e.target.value)}
                placeholder="Enter row numbers (1-indexed based on Excel)"
                style={{ 
                  width: '100%', 
                  padding: '0.75rem', 
                  borderRadius: '6px', 
                  border: '1px solid #cbd5e1',
                  fontSize: '1rem'
                }}
              />
              <p style={{ fontSize: '0.85rem', color: '#64748b', marginTop: '0.5rem' }}>
                Enter the exact row numbers as they appear in Excel (e.g. 2 for the first data row if row 1 is header, or if you want the 1st row of data, type 1 depending on your file structure. Script maps this directly.)
              </p>
            </div>
          )}

          {/* Action Button */}
          <button 
            onClick={handleUpload}
            disabled={!file || isUploading || (uploadMode === 'custom' && !customRows.trim())}
            style={{
              backgroundColor: (!file || isUploading || (uploadMode === 'custom' && !customRows.trim())) ? '#94a3b8' : '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '1rem',
              fontSize: '1.1rem',
              fontWeight: 600,
              cursor: (!file || isUploading || (uploadMode === 'custom' && !customRows.trim())) ? 'not-allowed' : 'pointer',
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              gap: '0.5rem',
              transition: 'background-color 0.2s',
              marginTop: '1rem'
            }}
          >
            {isUploading ? <Loader className="animate-spin" /> : <UploadCloud />}
            {isUploading ? "Uploading to Lark..." : "Start Upload"}
          </button>

          {/* Results Area */}
          {result && (
            <div style={{ 
              marginTop: '1rem', 
              padding: '1.5rem', 
              borderRadius: '8px', 
              backgroundColor: result.status === 'success' ? '#dcfce7' : '#fee2e2',
              border: `1px solid ${result.status === 'success' ? '#bbf7d0' : '#fecaca'}`,
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: result.status === 'success' ? '#166534' : '#991b1b', fontWeight: 600, fontSize: '1.1rem' }}>
                {result.status === 'success' ? <CheckCircle /> : <AlertCircle />}
                {result.status === 'success' ? "Upload Complete" : "Upload Failed"}
              </div>
              <p style={{ margin: 0, color: result.status === 'success' ? '#15803d' : '#b91c1c' }}>
                {result.message}
              </p>
              {result.failed_rows && result.failed_rows.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <span style={{ fontWeight: 600, color: '#991b1b' }}>Failed Rows: </span>
                  <span style={{ color: '#b91c1c' }}>{result.failed_rows.join(", ")}</span>
                </div>
              )}
            </div>
          )}

        </div>
      </div>
      <style>{`
        .animate-spin {
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-10px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
