import React, { useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function DocCreation() {
  const [uiStep, setUiStep] = useState(1);
  const [website, setWebsite] = useState("ireps");
  const [company, setCompany] = useState("Aquint");
  const [documentId, setDocumentId] = useState("");
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState(null);
  const [atcUpload, setAtcUpload] = useState(null);

  const [docUrl, setDocUrl] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [excelUrl, setExcelUrl] = useState("");
  const [error, setError] = useState("");

  // IREPS multi-step state
  const [analyzeResponse, setAnalyzeResponse] = useState(null);
  const [missingFieldAnswers, setMissingFieldAnswers] = useState({});
  const [mergeSelections, setMergeSelections] = useState({});
  const [gccFile, setGccFile] = useState(null);
  const [gccLoading, setGccLoading] = useState(false);
  const [gccResults, setGccResults] = useState({});

  // GeM state
  const [requirements, setRequirements] = useState([]);
  const [selectedUrls, setSelectedUrls] = useState({});
  const [customFiles, setCustomFiles] = useState({});
  const [declPrompt, setDeclPrompt] = useState("");
  const [declLoading, setDeclLoading] = useState(false);
  const [generatedDecls, setGeneratedDecls] = useState([]);
  const [annexureFile, setAnnexureFile] = useState(null);
  const [annexureLoading, setAnnexureLoading] = useState(false);
  const [extraFiles, setExtraFiles] = useState([]);
  const [orderedDocs, setOrderedDocs] = useState([]);
  const [mergeLoading, setMergeLoading] = useState(false);
  const [finalZipUrl, setFinalZipUrl] = useState("");

  const resetState = () => {
    setUiStep(1);
    setDocUrl(""); setExcelUrl(""); setError("");
    setAnalyzeResponse(null); setMissingFieldAnswers({});
    setMergeSelections({}); setGccFile(null); setGccResults({});
    setRequirements([]); setSelectedUrls({}); setCustomFiles({});
    setGeneratedDecls([]); setExtraFiles([]); setOrderedDocs([]);
    setFinalZipUrl(""); setDocumentId("");
  };

  // Step 1: Analyze (dry-run for IREPS, generate for GeM)
  const handleAnalyze = async () => {
    if (!file) return;
    setLoading(true);
    setError("");

    const formData = new FormData();
    formData.append("website", website);
      if (localPath) formData.append("local_path", localPath);
    formData.append("company", company);
    formData.append("step", "analyze");
    if (documentId) formData.append("document_id", documentId);
    formData.append("file", file);
    if (atcUpload) formData.append("atc_file", atcUpload);

    try {
      const res = await fetch(`${API_BASE}/api/docs/map`, { method: "POST", body: formData });
      const data = await res.json();

      if (data.status === "needs_info") {
        setAnalyzeResponse(data);
        const initialAnswers = {};
        if (data.missing_fields) data.missing_fields.forEach(f => initialAnswers[f] = "");
        setMissingFieldAnswers(initialAnswers);
        if (data.extracted_data && data.extracted_data.tender_no) setDocumentId(data.extracted_data.tender_no);
        const initMerges = {};
        if (data.proposed_merges) {
          data.proposed_merges.forEach(pm => {
            initMerges[pm.row_key] = pm.docs.map(d => d.id);
          });
        }
        setMergeSelections(initMerges);
        if (data.needs_gcc) setUiStep("gcc");
        else setUiStep(2);
      } else if (data.status === "success") {
        setDocUrl(data.doc_url || "");
        if (data.local_path) setLocalPath(data.local_path);
          if (data.generated_files) setGeneratedDecls(data.generated_files);
        setExcelUrl(data.excel_url || "");
        if (data.document_id) setDocumentId(data.document_id);
        if (website === "gem" && data.requirements && data.requirements.length) {
          setRequirements(data.requirements);
          const initialSelections = {};
          data.requirements.forEach(req => {
            initialSelections[req.index] = new Set(req.mapped_docs.map(d => d.url));
          });
          setSelectedUrls(initialSelections);
          setUiStep(2);
        } else {
          setUiStep("done");
        }
      } else {
        setError(data.message || "Failed to process document.");
      }
    } catch (e) {
      setError("Network error: " + e.message);
    }
    setLoading(false);
  };

  // GCC Step
  const handleProcessGcc = async () => {
    if (!gccFile) return;
    setGccLoading(true);
    setError("");
    const formData = new FormData();
    formData.append("gcc_file", gccFile);
    formData.append("needs_gcc_list", JSON.stringify(analyzeResponse && analyzeResponse.needs_gcc_list ? analyzeResponse.needs_gcc_list : []));
    try {
      const res = await fetch(`${API_BASE}/api/docs/process_gcc`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.success) { setGccResults(data.gcc_results || {}); setUiStep(2); }
      else setError(data.message || "GCC processing failed.");
    } catch (e) { setError("Network error: " + e.message); }
    setGccLoading(false);
  };

  // Step 2 -> Generate
  const handleGenerate = async () => {
    setLoading(true);
    setError("");

    const formData = new FormData();
    formData.append("website", website);
      if (localPath) formData.append("local_path", localPath);
    formData.append("company", company);
    formData.append("step", "generate");
    formData.append("document_id", (analyzeResponse && analyzeResponse.extracted_tender_no) || documentId);

    const extracted = (analyzeResponse && analyzeResponse.extracted_data) || {};
    const knownFields = [
      "tender_name","place","railway","signatory_name","signatory_designation",
      "date","days","issuing_authority","bid_security_amount",
      "execute_contract_days","commence_work_days","closing_date"
    ];
    knownFields.forEach(f => {
      const val = missingFieldAnswers[f] || extracted[f] || "";
      if (val) formData.append(f, val);
    });

    const extraObj = {};
    Object.entries(missingFieldAnswers).forEach(([k, v]) => {
      if (!knownFields.includes(k) && v) extraObj[k] = v;
    });
    if (Object.keys(extraObj).length) formData.append("extra_answers", JSON.stringify(extraObj));

    const mergesForBackend = {};
    Object.entries(mergeSelections).forEach(([k, ids]) => { mergesForBackend[k] = ids; });
    if (Object.keys(mergesForBackend).length) formData.append("merges_data", JSON.stringify(mergesForBackend));
    
    // Append custom files
    Object.entries(customFiles).forEach(([k, files]) => {
      Array.from(files).forEach(f => formData.append("req_" + k + "_custom", f));
    });

    if (Object.keys(gccResults).length) formData.append("gcc_results_data", JSON.stringify(gccResults));
    if (file) formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/docs/map`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.status === "success") {
        setDocUrl(data.doc_url || "");
        if (data.local_path) setLocalPath(data.local_path);
          if (data.generated_files) setGeneratedDecls(data.generated_files);
        setExcelUrl(data.excel_url || "");
        if (data.document_id) setDocumentId(data.document_id);
        setUiStep(3);
      } else setError(data.message || "Failed to generate documents.");
    } catch (e) { setError("Network error: " + e.message); }
    setLoading(false);
  };

  const prepareGeMOrder = () => {
    const docs = [];
    requirements.forEach(req => {
      const sel = selectedUrls[req.index] || new Set();
      Array.from(sel).forEach(url => {
        const docObj = req.mapped_docs.find(d => d.url === url);
        docs.push({ type: "url", url, name: docObj ? docObj.name : url });
      });
      const cFiles = customFiles[req.index];
      if (cFiles) Array.from(cFiles).forEach(f => docs.push({ type: "file", id: "req_" + req.index + "_custom", name: "[Custom File] " + f.name }));
    });
    generatedDecls.forEach(d => docs.push({ type: "url", url: d.url, name: "[Custom Declaration] " + d.name }));
    setOrderedDocs(docs);
  };

  const moveDoc = (index, dir) => {
    const newDocs = [...orderedDocs];
    if (dir === -1 && index > 0) [newDocs[index - 1], newDocs[index]] = [newDocs[index], newDocs[index - 1]];
    else if (dir === 1 && index < newDocs.length - 1) [newDocs[index + 1], newDocs[index]] = [newDocs[index], newDocs[index + 1]];
    setOrderedDocs(newDocs);
  };
  const removeDoc = (index) => setOrderedDocs(orderedDocs.filter((_, i) => i !== index));

  const handleToggleSelect = (reqIndex, url) => {
    setSelectedUrls(prev => {
      const newSet = new Set(prev[reqIndex] || []);
      if (newSet.has(url)) newSet.delete(url); else newSet.add(url);
      return { ...prev, [reqIndex]: newSet };
    });
  };
  const handleCustomFileChange = (reqIndex, files) => setCustomFiles(prev => ({ ...prev, [reqIndex]: files }));

  const handleCreateDecl = async () => {
    setDeclLoading(true);
    try {
      const formData = new FormData();
      formData.append("document_id", documentId);
      formData.append("company", company);
      formData.append("prompt", declPrompt);
      
      let cDate = "";
      if (analyzeResponse && analyzeResponse.extracted_data && analyzeResponse.extracted_data.closing_date) {
          cDate = analyzeResponse.extracted_data.closing_date;
      } else if (missingFieldAnswers && missingFieldAnswers["closing_date"]) {
          cDate = missingFieldAnswers["closing_date"];
      }
      formData.append("closing_date", cDate);
      
      if (localPath) formData.append("local_path", localPath);
      const res = await fetch(`${API_BASE}/api/docs/create_decl`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.status === "success") { setGeneratedDecls(prev => [...prev, data]); setDeclPrompt(""); }
      else setError(data.message || "Failed to create declaration.");
    } catch (e) { setError("Network error: " + e.message); }
    setDeclLoading(false);
  };

  const handleExtractAnnexures = async () => {
    if (!annexureFile) return;
    setAnnexureLoading(true);
    const formData = new FormData();
    formData.append("company", company);
    formData.append("document_id", documentId);
    formData.append("file", annexureFile);
    try {
      const res = await fetch(`${API_BASE}/api/docs/extract_annexures`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.status === "success") { setGeneratedDecls(prev => [...prev, data]); setAnnexureFile(null); }
      else setError(data.message || "Failed to extract annexures.");
    } catch (e) { setError("Network error: " + e.message); }
    setAnnexureLoading(false);
  };

  const handleMerge = async () => {
    if (!documentId) return;
    setMergeLoading(true);
    setError("");
    const formData = new FormData();
    formData.append("document_id", documentId);
    formData.append("website", website);
    formData.append("company", company);
    if (localPath) formData.append("local_path", localPath);
    if (website === "gem") formData.append("ordered_docs", JSON.stringify(orderedDocs));
    requirements.forEach(req => {
      const sel = selectedUrls[req.index] || new Set();
      formData.append("req_" + req.index + "_docs", JSON.stringify(Array.from(sel)));
      formData.append("req_" + req.index + "_name", req.description);
      const cFiles = customFiles[req.index];
      if (cFiles) Array.from(cFiles).forEach(f => formData.append("req_" + req.index + "_custom", f));
    });
    if (generatedDecls.length > 0) formData.append("extra_decls", JSON.stringify(generatedDecls.map(d => d.url)));
    if (extraFiles) Array.from(extraFiles).forEach(f => formData.append("global_extra", f));
    try {
      const endpoint = "/api/docs/finalize_ireps";
      const res = await fetch(`${API_BASE}${endpoint}`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.status === "success") { setFinalZipUrl(data.local_path || data.zip_url); setUiStep(5); }
      else setError(data.message || "Failed to merge documents.");
    } catch (e) { setError("Network error: " + e.message); }
    setMergeLoading(false);
  };

  return (
    <div className="phase-container">
      <div className="agent-header">
        <div className="agent-title">
          <span className="agent-icon">&#x1F4C4;</span>
          <h1>Document Processing Workflow</h1>
        </div>
      </div>
      <div className="phase-content">

        {uiStep === 1 && (
          <div className="upload-box" style={{ maxWidth: "600px", margin: "0 auto" }}>
            <h2>Step 1: Map Tender Documents</h2>
            <p>Select the website, target company, and upload the NIT doc.</p>
            <div className="option-field" style={{ textAlign: "left", marginTop: "20px" }}>
              <label>Website</label>
              <select value={website} onChange={(e) => setWebsite(e.target.value)}>
                <option value="ireps">IREPS</option>
                <option value="gem">GeM</option>
                <option value="iti">ITI</option>
                <option value="nprocure">nProcure</option>
              </select>
            </div>
            <div className="option-field" style={{ textAlign: "left", marginTop: "20px" }}>
              <label>Target Company</label>
              <select value={company} onChange={(e) => setCompany(e.target.value)}>
                <option value="Aquint">Aquint</option>
                <option value="Arkonic">Arkonic</option>
              </select>
            </div>
            <div className="option-field" style={{ textAlign: "left", marginTop: "15px" }}>
              <label>Tender ID (Optional)</label>
              <input type="text" placeholder="e.g. 12345 (Leave blank to auto-detect)"
                value={documentId} onChange={(e) => setDocumentId(e.target.value)} />
            </div>
            <div className="option-field" style={{ textAlign: "left", marginTop: "15px" }}>
              <label>Upload NIT Document (PDF)</label>
              <input type="file" accept=".pdf" className="file-input"
                onChange={(e) => setFile(e.target.files[0])} />
            </div>
            <div className="option-field" style={{ textAlign: "left", marginTop: "15px" }}>
              <label>Upload ATC / Tender Document (Optional)</label>
              <input type="file" accept=".pdf,.doc,.docx" className="file-input"
                style={{ padding: "10px", marginTop: "5px" }}
                onChange={(e) => setAtcUpload(e.target.files[0])} />
            </div>
            <button className="btn-start" onClick={handleAnalyze} disabled={!file || loading}
              style={{ background: "#10b981", marginTop: "20px", width: "100%", color: "#fff" }}>
              {loading ? "Analyzing NIT Document..." : "Generate Mapped Documents"}
            </button>
          </div>
        )}

        {error && <div className="error-msg" style={{ marginTop: "15px" }}>{error}</div>}

        {uiStep === "gcc" && (
          <div className="upload-box" style={{ maxWidth: "600px", margin: "0 auto", textAlign: "left" }}>
            <h2>&#x1F4CE; Upload GCC / Annexure Document</h2>
            <p style={{ marginBottom: "15px", color: "#555" }}>
              Some requirements reference specific form formats from the GCC or ATC document.
              Please upload it so the AI can extract and fill those forms automatically.
            </p>
            {analyzeResponse && analyzeResponse.needs_gcc_list && analyzeResponse.needs_gcc_list.length > 0 && (
              <div style={{ background: "#fef9c3", border: "1px solid #fde68a", borderRadius: "8px", padding: "12px", marginBottom: "15px" }}>
                <strong>Forms needed from GCC:</strong>
                <ul style={{ margin: "8px 0 0 0", paddingLeft: "20px" }}>
                  {analyzeResponse.needs_gcc_list.map((item, i) => (
                    <li key={i} style={{ fontSize: "13px", marginBottom: "4px" }}>{item.line}</li>
                  ))}
                </ul>
              </div>
            )}
            <input type="file" accept=".pdf,.docx,.doc" className="file-input"
              style={{ padding: "10px", marginTop: "5px", width: "100%" }}
              onChange={(e) => setGccFile(e.target.files[0])} />
            <div style={{ display: "flex", gap: "10px", marginTop: "15px" }}>
              <button onClick={() => setUiStep(2)} style={{ flex: 1, padding: "12px", background: "#6b7280", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>
                Skip GCC
              </button>
              <button onClick={handleProcessGcc} disabled={!gccFile || gccLoading}
                style={{ flex: 2, padding: "12px", background: "#8b5cf6", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>
                {gccLoading ? "Extracting Forms..." : "Extract Forms from GCC"}
              </button>
            </div>
          </div>
        )}

        {uiStep === 2 && analyzeResponse && (
          <div className="upload-box" style={{ maxWidth: "800px", margin: "0 auto", textAlign: "left" }}>
            <h2>Step 2: Confirm Details</h2>
            <p style={{ color: "#555", marginBottom: "20px" }}>
              The AI has analyzed the NIT. Please review and fill in any missing details.
            </p>
            {analyzeResponse.extracted_data && Object.values(analyzeResponse.extracted_data).some(v => v) && (
              <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "8px", padding: "12px", marginBottom: "20px" }}>
                <strong style={{ fontSize: "14px", color: "#166534" }}>Auto-Extracted Details (Editable):</strong>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginTop: "12px" }}>
                    {Object.entries(analyzeResponse.extracted_data).filter(([, v]) => v).map(([k, v]) => (
                      <div key={k} style={{ fontSize: "13px" }}>
                        <label style={{ display: "block", color: "#6b7280", textTransform: "capitalize", marginBottom: "4px" }}>{k.replace(/_/g, " ")}</label>
                        <input type="text"
                          style={{ width: "95%", padding: "6px", border: "1px solid #86efac", borderRadius: "4px", fontSize: "13px" }}
                          value={missingFieldAnswers[k] !== undefined ? missingFieldAnswers[k] : v}
                          onChange={(e) => setMissingFieldAnswers({ ...missingFieldAnswers, [k]: e.target.value })}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            {analyzeResponse.missing_fields && analyzeResponse.missing_fields.length > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <h3 style={{ fontSize: "16px", color: "#dc2626", marginBottom: "10px" }}>Missing Information Required:</h3>
                {analyzeResponse.missing_fields.map((f, i) => (
                  <div key={i} style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", textTransform: "capitalize" }}>
                      {f.replace(/_/g, " ")}
                    </label>
                    <input type="text"
                      style={{ width: "100%", padding: "10px", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "14px" }}
                      value={missingFieldAnswers[f] || ""}
                      onChange={(e) => setMissingFieldAnswers({ ...missingFieldAnswers, [f]: e.target.value })}
                      placeholder={"Enter " + f.replace(/_/g, " ") + "..."} />
                  </div>
                ))}
              </div>
            )}
            {analyzeResponse.proposed_merges && analyzeResponse.proposed_merges.length > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <h3 style={{ fontSize: "16px", color: "#2563eb", marginBottom: "10px" }}>
                  Document Mapping Review (Select/Deselect or Upload Custom):
                </h3>
                {analyzeResponse.proposed_merges.map((pm, i) => (
                  <div key={i} style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: "8px", padding: "12px", marginBottom: "10px" }}>
                    <p style={{ fontSize: "13px", fontWeight: "600", marginBottom: "8px" }}>{pm.line}</p>
                    {pm.docs.map((doc, j) => (
                      <label key={j} style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px", fontSize: "13px", cursor: "pointer" }}>
                        <input type="checkbox"
                          checked={(mergeSelections[pm.row_key] || []).includes(doc.id)}
                          onChange={(e) => {
                            const cur = mergeSelections[pm.row_key] || [];
                            if (e.target.checked) setMergeSelections(p => ({ ...p, [pm.row_key]: [...cur, doc.id] }));
                            else setMergeSelections(p => ({ ...p, [pm.row_key]: cur.filter(id => id !== doc.id) }));
                          }} />
                        {doc.name}
                      </label>
                    ))}
                    <div style={{ marginTop: "10px" }}>
                      <label style={{ fontSize: "12px", color: "#4b5563" }}>Upload Extra/Custom File (Optional):</label>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                        <input type="file" multiple
                          id={`custom_file_${pm.row_key}`}
                          style={{ fontSize: "12px" }}
                          onChange={(e) => setCustomFiles({ ...customFiles, [pm.row_key]: e.target.files })}
                        />
                        {customFiles[pm.row_key] && customFiles[pm.row_key].length > 0 && (
                          <button 
                            onClick={() => {
                              const newFiles = { ...customFiles };
                              delete newFiles[pm.row_key];
                              setCustomFiles(newFiles);
                              document.getElementById(`custom_file_${pm.row_key}`).value = "";
                            }}
                            style={{ fontSize: "11px", padding: "2px 6px", background: "#ef4444", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                          >
                            Clear
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <button className="btn-start" onClick={handleGenerate} disabled={loading}
              style={{ background: "#10b981", width: "100%", color: "#fff", padding: "14px", fontSize: "15px" }}>
              {loading ? "Generating Documents..." : "Generate Documents"}
            </button>
          </div>
        )}

        

        {uiStep === "gem_review" && (
          <div className="upload-box" style={{ maxWidth: "800px", margin: "0 auto", textAlign: "left" }}>
            <h2>Step 2.5: Mapped & Merged Documents Ready</h2>
            <p>Your documents have been successfully mapped and placed in the folder:</p>
            <div style={{ background: "#eef2ff", padding: "15px", borderRadius: "8px", border: "1px solid #c7d2fe", margin: "15px 0", color: "#1e40af", fontWeight: "bold", wordBreak: "break-all" }}>
              {localPath}
            </div>
            
            <div style={{ marginTop: "20px", padding: "15px", background: "#e8f5e9", borderRadius: "8px" }}>
              <strong>Generated Documents:</strong>
              {generatedDecls.map((d, i) => (
                <div key={i} style={{ marginTop: "5px" }}>
                  <a href={`${API_BASE}${d.url}`} target="_blank" rel="noreferrer" style={{ color: "#2563eb" }}>{d.name}</a>
                </div>
              ))}
            </div>

            <button className="btn-start" onClick={() => setUiStep(3)} style={{ marginTop: "30px", background: "#10b981", color: "#fff", width: "100%" }}>
              Next: Move to Step 3 (Create Declarations)
            </button>
          </div>
        )}

        {uiStep === 3 && (
          <div className="upload-box" style={{ maxWidth: "600px", margin: "0 auto", textAlign: "left" }}>
            <h2>Step 3: Create Custom Declarations </h2>
            
            <div style={{ background: "#f8fafc", padding: "15px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <h3 style={{ fontSize: "16px", marginBottom: "10px" }}>Write Custom Declaration</h3>
              <textarea placeholder="E.g. Create a GST Declaration stating that we are exempt from..."
                value={declPrompt} onChange={(e) => setDeclPrompt(e.target.value)}
                style={{ width: "100%", height: "100px", padding: "10px", marginTop: "10px", borderRadius: "4px", border: "1px solid #ccc" }} />
              <button onClick={handleCreateDecl} disabled={declLoading || !declPrompt}
                style={{ padding: "10px", width: "100%", marginTop: "10px", cursor: "pointer", background: "#10b981", color: "white", border: "none", borderRadius: "4px" }}>
                {declLoading ? "Generating PDF..." : "Generate Custom Declaration PDF"}
              </button>
            </div>
            {generatedDecls.length > 0 && (
              <div style={{ marginTop: "20px", padding: "15px", background: "#e8f5e9", borderRadius: "8px" }}>
                <strong>Generated Documents:</strong>
                {generatedDecls.map((d, i) => (
                  <div key={i} style={{ marginTop: "5px" }}>
                    <a href={`${API_BASE}${d.url}`} target="_blank" rel="noreferrer" style={{ color: "#2563eb" }}>{d.name}</a>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: "15px", marginTop: "30px" }}>
              <button className="btn-start" onClick={() => setUiStep(4)}
                style={{ background: "#6b7280", flex: 1, color: "#fff" }}>Skip</button>
              <button className="btn-start" onClick={() => setUiStep(4)}
                style={{ background: "#2563eb", flex: 2, color: "#fff" }}>
                Next: Edit Other Docs
              </button>
            </div>
          </div>
        )}

        {uiStep === 4 && (
          <div className="upload-box" style={{ maxWidth: "600px", margin: "0 auto", textAlign: "left" }}>
            <>
              <h2>Step 4: Add Extra Files</h2>
              <p>Upload any remaining standalone PDFs or files to include in the final package.</p>
            </>
            <input type="file" multiple className="file-input"
              style={{ padding: "10px", marginTop: "15px", width: "100%" }}
              onChange={(e) => setExtraFiles(e.target.files)} />
            <div style={{ display: "flex", gap: "15px", marginTop: "30px" }}>
              <button className="btn-start" onClick={handleMerge} disabled={mergeLoading}
                style={{ background: "#6b7280", flex: 1, color: "#fff" }}>
                {mergeLoading ? "..." : "Skip & Finish"}
              </button>
              <button className="btn-start" onClick={handleMerge} disabled={mergeLoading}
                style={{ background: "#10b981", flex: 2, color: "#fff" }}>
                {mergeLoading ? "Finalizing Package..." : "Finalize & Download Package"}
              </button>
            </div>
          </div>
        )}

        {uiStep === 5 && (website === "gem" ? localPath : finalZipUrl) && (
          <div className="summary-preview" style={{ maxWidth: "800px", margin: "20px auto" }}>
            <h3>Final Package Ready!</h3>
            <p>Your tender documents have been fully merged and saved.</p>
            <div style={{ background: "#eef2ff", padding: "15px", borderRadius: "8px", border: "1px solid #c7d2fe", margin: "15px 0", color: "#1e40af", fontWeight: "bold", wordBreak: "break-all" }}>
              Local Folder Path: {website === "gem" ? localPath : finalZipUrl}
            </div>
            <button onClick={resetState} style={{ display: "block", margin: "20px auto 0", background: "none", border: "none", color: "#2563eb", cursor: "pointer", textDecoration: "underline" }}>
              Start New Tender
            </button>
          </div>
        )}

        {uiStep === "done" && docUrl && (
          <div className="summary-preview" style={{ maxWidth: "800px", margin: "20px auto", textAlign: "center" }}>
            <div style={{ fontSize: "60px", marginBottom: "10px" }}>&#x1F389;</div>
            <h3 style={{ marginBottom: "10px" }}>Documents Generated Successfully!</h3>
            <p style={{ color: "#555", marginBottom: "20px" }}>Your IREPS tender documents have been mapped, filled and packaged.</p>
            <a href={`${API_BASE}${docUrl}`} target="_blank" rel="noreferrer"
              style={{ display: "inline-block", padding: "14px 30px", background: "#10b981", color: "white", borderRadius: "8px", textDecoration: "none", fontSize: "16px", fontWeight: "bold", marginBottom: "10px" }}>
              Download Document Package (ZIP)
            </a>
            {excelUrl && (
              <div style={{ marginTop: "10px" }}>
                <a href={`${API_BASE}${excelUrl}`} target="_blank" rel="noreferrer"
                  style={{ display: "inline-block", padding: "10px 20px", background: "#2563eb", color: "white", borderRadius: "6px", textDecoration: "none", fontSize: "14px" }}>
                  Download Requirements Excel
                </a>
              </div>
            )}
            <div style={{ marginTop: "20px" }}>
              <button onClick={resetState} style={{ background: "none", border: "none", color: "#2563eb", cursor: "pointer", textDecoration: "underline", fontSize: "14px" }}>
                Start New Tender
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
