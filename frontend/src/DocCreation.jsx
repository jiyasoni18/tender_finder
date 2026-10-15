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
  const [atcAutoFetched, setAtcAutoFetched] = useState(null);
  const [atcFetchLoading, setAtcFetchLoading] = useState(false);

  const [docUrl, setDocUrl] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [excelUrl, setExcelUrl] = useState("");
  const [error, setError] = useState("");

  // IREPS multi-step state
  const [analyzeResponse, setAnalyzeResponse] = useState(null);
  const [missingFieldAnswers, setMissingFieldAnswers] = useState({});
  const [tenderDetails, setTenderDetails] = useState({});
  const [missingDocQuestions, setMissingDocQuestions] = useState([]);
  const [pendingDocName, setPendingDocName] = useState("");
  const [extraDocAnswers, setExtraDocAnswers] = useState({});
  const [mergeSelections, setMergeSelections] = useState({});
  const [docSelections, setDocSelections] = useState({});
  const [declarationSelections, setDeclarationSelections] = useState({});
  const [declarationTexts, setDeclarationTexts] = useState({});
  const [createdDeclarations, setCreatedDeclarations] = useState({});
  const [singleDeclLoading, setSingleDeclLoading] = useState({});
  const [singleDeclError, setSingleDeclError] = useState({});
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
    setTenderDetails({}); setMissingDocQuestions([]);
    setPendingDocName(""); setExtraDocAnswers({});
    setMergeSelections({}); setDocSelections({});
    setDeclarationSelections({}); setDeclarationTexts({});
    setCreatedDeclarations({}); setSingleDeclLoading({}); setSingleDeclError({});
    setGccFile(null); setGccResults({});
    setRequirements([]); setSelectedUrls({}); setCustomFiles({});
    setGeneratedDecls([]); setExtraFiles([]); setOrderedDocs([]);
    setFinalZipUrl(""); setDocumentId("");
    setAtcAutoFetched(null); setAtcFetchLoading(false);
  };

  const triggerAtcFetch = async (selectedFile) => {
    if (!selectedFile || website !== "gem") return;
    setAtcFetchLoading(true);
    setAtcAutoFetched(null);
    try {
      const fd = new FormData();
      fd.append("file", selectedFile);
      if (documentId) fd.append("document_id", documentId);
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
    if (atcUpload) {
      formData.append("atc_file", atcUpload);
    } else if (atcAutoFetched && atcAutoFetched.name) {
      formData.append("atc_file_name", atcAutoFetched.name);
    }

    try {
      const res = await fetch(`${API_BASE}/api/docs/map`, { method: "POST", body: formData });
      const data = await res.json();

      if (data.status === "needs_info") {
        setAnalyzeResponse(data);
        const initialAnswers = {};
        if (data.extracted_data) {
          setTenderDetails(data.extracted_data);
          Object.entries(data.extracted_data).forEach(([k, v]) => {
            if (v) initialAnswers[k] = v;
          });
        }
        if (data.missing_fields) {
          data.missing_fields.forEach(f => {
            if (!initialAnswers[f]) initialAnswers[f] = "";
          });
        }
        setMissingFieldAnswers(initialAnswers);
        if (data.extracted_data && data.extracted_data.tender_no) setDocumentId(data.extracted_data.tender_no);
        const initMerges = {};
        const initDocSel = {};
        const initDeclSel = {};
        const initDeclTexts = {};
        if (data.proposed_merges) {
          data.proposed_merges.forEach(pm => {
            initMerges[pm.row_key] = pm.docs ? pm.docs.map(d => d.id) : [];
            const hasDocs = pm.docs && pm.docs.length > 0;
            initDocSel[pm.row_key] = hasDocs;
            initDeclSel[pm.row_key] = !hasDocs;
            initDeclTexts[pm.row_key] = "";
          });
        }
        setMergeSelections(initMerges);
        setDocSelections(initDocSel);
        setDeclarationSelections(initDeclSel);
        setDeclarationTexts(initDeclTexts);
        if (data.needs_gcc) setUiStep("gcc");
        else setUiStep(2);
      } else if (data.status === "success") {
        setDocUrl(data.doc_url || "");
        if (data.local_path) setLocalPath(data.local_path);
        if (data.generated_files) setGeneratedDecls(data.generated_files);
        setExcelUrl(data.excel_url || "");
        if (data.document_id) setDocumentId(data.document_id);
        if (data.extracted_data) setTenderDetails(data.extracted_data);
        setUiStep(3);
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
    setGccLoading(true);
    setError("");
    const formData = new FormData();
    if (gccFile) {
      formData.append("gcc_file", gccFile);
    } else if (atcUpload) {
      formData.append("gcc_file", atcUpload);
    } else if (atcAutoFetched && atcAutoFetched.name) {
      formData.append("gcc_file_name", atcAutoFetched.name);
    } else {
      setError("Please select a GCC/ATC document or use auto-fetched ATC.");
      setGccLoading(false);
      return;
    }
    formData.append("needs_gcc_list", JSON.stringify(analyzeResponse && analyzeResponse.needs_gcc_list ? analyzeResponse.needs_gcc_list : []));
    try {
      const res = await fetch(`${API_BASE}/api/docs/process_gcc`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.success) { setGccResults(data.gcc_results || {}); setUiStep(2); }
      else setError(data.message || "GCC processing failed.");
    } catch (e) { setError("Network error: " + e.message); }
    setGccLoading(false);
  };

  // Step 2 -> Create Declaration for specific requirement right on the spot
  const handleCreateRequirementDeclaration = async (rowKey, line, description) => {
    setSingleDeclLoading(prev => ({ ...prev, [rowKey]: true }));
    setSingleDeclError(prev => ({ ...prev, [rowKey]: "" }));

    const formData = new FormData();
    formData.append("row_key", rowKey);
    formData.append("description", line || description || "");
    formData.append("user_text", declarationTexts[rowKey] || "");
    formData.append("company", company);
    formData.append("document_id", (analyzeResponse && analyzeResponse.extracted_tender_no) || documentId || "");
    if (localPath) formData.append("local_path", localPath);

    const extracted = (analyzeResponse && analyzeResponse.extracted_data) || tenderDetails || {};
    const knownFields = [
      "tender_name", "place", "railway", "signatory_name", "signatory_designation",
      "date", "days", "issuing_authority", "bid_security_amount",
      "execute_contract_days", "commence_work_days", "closing_date"
    ];
    knownFields.forEach(f => {
      const val = missingFieldAnswers[f] !== undefined ? missingFieldAnswers[f] : (extracted[f] || "");
      if (val) formData.append(f, val);
    });

    try {
      const res = await fetch(`${API_BASE}/api/docs/create_requirement_declaration`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (data.status === "success") {
        setCreatedDeclarations(prev => ({
          ...prev,
          [rowKey]: {
            name: data.name,
            url: data.url,
            pdf_path: data.pdf_path
          }
        }));
      } else {
        setSingleDeclError(prev => ({
          ...prev,
          [rowKey]: data.message || "Failed to create declaration."
        }));
      }
    } catch (err) {
      setSingleDeclError(prev => ({
        ...prev,
        [rowKey]: "Network error: " + err.message
      }));
    } finally {
      setSingleDeclLoading(prev => ({ ...prev, [rowKey]: false }));
    }
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

    const extracted = (analyzeResponse && analyzeResponse.extracted_data) || tenderDetails || {};
    const knownFields = [
      "tender_name", "place", "railway", "signatory_name", "signatory_designation",
      "date", "days", "issuing_authority", "bid_security_amount",
      "execute_contract_days", "commence_work_days", "closing_date"
    ];
    knownFields.forEach(f => {
      const val = missingFieldAnswers[f] !== undefined ? missingFieldAnswers[f] : (extracted[f] || "");
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

    // Package declarations and doc selections for all websites (IREPS, GeM, nProcure)
    const declsForBackend = {};
    Object.entries(declarationSelections).forEach(([k, enabled]) => {
      if (enabled) {
        declsForBackend[k] = {
          enabled: true,
          text: declarationTexts[k] || "",
          pdf_path: (createdDeclarations[k] && createdDeclarations[k].pdf_path) || ""
        };
      }
    });
    formData.append("declarations_data", JSON.stringify(declsForBackend));

    const docSelForBackend = {};
    Object.entries(docSelections).forEach(([k, val]) => {
      docSelForBackend[k] = !!val;
    });
    formData.append("doc_selections_data", JSON.stringify(docSelForBackend));

    if (file) formData.append("file", file);
    if (atcUpload) {
      formData.append("atc_file", atcUpload);
    } else if (atcAutoFetched && atcAutoFetched.name) {
      formData.append("atc_file_name", atcAutoFetched.name);
    }

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
      const docIdToUse = (analyzeResponse && analyzeResponse.extracted_tender_no) || documentId || "";
      formData.append("document_id", docIdToUse);
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

  const handleMerge = async (isSkip = false) => {
    const docIdToUse = (analyzeResponse && analyzeResponse.extracted_tender_no) || documentId || "";
    if (!docIdToUse) {
      setError("Document/Tender ID is missing.");
      return;
    }
    setMergeLoading(true);
    setError("");
    const formData = new FormData();
    formData.append("document_id", docIdToUse);
    formData.append("website", website);
    formData.append("company", company);
    if (localPath) formData.append("local_path", localPath);
    if (isSkip) formData.append("force_finalize", "true");

    // Pass tender metadata fields so smart_fill_docx and finalize_ireps have full NIT details
    const extracted = (analyzeResponse && analyzeResponse.extracted_data) || tenderDetails || {};
    const knownFields = [
      "tender_name", "place", "railway", "signatory_name", "signatory_designation",
      "date", "days", "issuing_authority", "bid_security_amount",
      "execute_contract_days", "commence_work_days", "closing_date", "company_name"
    ];
    knownFields.forEach(f => {
      const val = missingFieldAnswers[f] !== undefined ? missingFieldAnswers[f] : (extracted[f] || "");
      if (val) formData.append(f, val);
    });

    if (extraDocAnswers && Object.keys(extraDocAnswers).length > 0) {
      formData.append("extra_answers", JSON.stringify(extraDocAnswers));
    }

    if (website === "gem") formData.append("ordered_docs", JSON.stringify(orderedDocs));
    requirements.forEach(req => {
      const sel = selectedUrls[req.index] || new Set();
      formData.append("req_" + req.index + "_docs", JSON.stringify(Array.from(sel)));
      formData.append("req_" + req.index + "_name", req.description);
      const cFiles = customFiles[req.index];
      if (cFiles) Array.from(cFiles).forEach(f => formData.append("req_" + req.index + "_custom", f));
    });
    if (generatedDecls.length > 0) formData.append("extra_decls", JSON.stringify(generatedDecls.filter(d => d && d.url).map(d => d.url)));
    if (extraFiles) Array.from(extraFiles).forEach(f => formData.append("global_extra", f));
    try {
      const endpoint = "/api/docs/finalize_ireps";
      const res = await fetch(`${API_BASE}${endpoint}`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.status === "needs_extra_answers") {
        setMissingDocQuestions(data.missing_questions || []);
        setPendingDocName(data.pending_doc || "");
        setError(data.message || "Please provide answers to the questions below to finalize the document.");
      } else if (data.status === "success") {
        setMissingDocQuestions([]);
        setPendingDocName("");
        if (data.generated_files) setGeneratedDecls(data.generated_files);
        setFinalZipUrl(data.local_path || data.zip_url);
        setUiStep(5);
      } else {
        setError(data.message || "Failed to merge documents.");
      }
    } catch (e) { setError("Network error: " + e.message); }
    setMergeLoading(false);
  };

  const currentStepNum = 
    uiStep === 1 ? 1 :
    (uiStep === "gcc" || uiStep === 2) ? 2 :
    (uiStep === "gem_review" || uiStep === 3) ? 3 :
    uiStep === 4 ? 4 : 5;

  return (
    <div className="phase-container">
      <div className="agent-header">
        <div className="agent-title">
          <span className="agent-icon">&#x1F4C4;</span>
          <h1>Document Processing Workflow</h1>
        </div>
      </div>
      <div className="phase-content">

        {/* 5-Step Visual Stepper Bar */}
        <div style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          width: "100%",
          maxWidth: "760px",
          margin: "0 auto 24px auto",
          padding: "16px 12px",
          background: "#ffffff",
          borderRadius: "10px",
          border: "1px solid #e2e8f0",
          boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
          boxSizing: "border-box"
        }}>
          {[
            { num: 1, label: "Upload" },
            { num: 2, label: "Review & Docs" },
            { num: 3, label: "Declarations" },
            { num: 4, label: "Extra Files" },
            { num: 5, label: "Final Package" }
          ].map((s, idx, arr) => {
            const isActive = currentStepNum === s.num;
            const isDone = currentStepNum > s.num;
            return (
              <React.Fragment key={s.num}>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    flex: "0 1 95px",
                    cursor: isDone ? "pointer" : "default",
                    userSelect: "none"
                  }}
                  onClick={() => {
                    if (isDone) {
                      if (s.num === 1) setUiStep(1);
                      else if (s.num === 2) setUiStep(2);
                      else if (s.num === 3) setUiStep(3);
                      else if (s.num === 4) setUiStep(4);
                    }
                  }}
                  title={isDone ? `Click to go back to Step ${s.num}: ${s.label}` : `Step ${s.num}: ${s.label}`}
                >
                  <div style={{
                    width: "30px",
                    height: "30px",
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "12px",
                    fontWeight: "bold",
                    background: isDone ? "#10b981" : (isActive ? "#2563eb" : "#f1f5f9"),
                    color: (isDone || isActive) ? "#ffffff" : "#64748b",
                    boxShadow: isActive ? "0 0 0 3px rgba(37, 99, 235, 0.2)" : "none",
                    transition: "all 0.2s"
                  }}>
                    {isDone ? "✓" : s.num}
                  </div>
                  <span style={{
                    fontSize: "11px",
                    lineHeight: "1.2",
                    textAlign: "center",
                    marginTop: "6px",
                    fontWeight: isActive ? "700" : (isDone ? "600" : "500"),
                    color: isActive ? "#1e293b" : (isDone ? "#10b981" : "#94a3b8")
                  }}>
                    {s.label}
                  </span>
                </div>
                {idx < arr.length - 1 && (
                  <div style={{
                    flex: 1,
                    height: "2px",
                    minWidth: "12px",
                    marginTop: "14px",
                    background: isDone ? "#10b981" : "#e2e8f0",
                    transition: "all 0.2s"
                  }} />
                )}
              </React.Fragment>
            );
          })}
        </div>

        {uiStep === 1 && (
          <div className="upload-box" style={{ maxWidth: "600px", margin: "0 auto" }}>
            <h2>Step 1: Map Tender Documents</h2>
            <p>Select the website, target company, and upload the NIT doc.</p>
            <div className="option-field" style={{ textAlign: "left", marginTop: "20px" }}>
              <label>Website</label>
              <select value={website} onChange={(e) => {
                const val = e.target.value;
                setWebsite(val);
                if (val === "gem" && file) triggerAtcFetch(file);
              }}>
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
              <label>
                {website === "nprocure" 
                  ? "Upload Tender / EOI Document (Full PDF)" 
                  : (website === "gem" ? "Upload GeM Bid Document (PDF)" : "Upload NIT Document (PDF)")}
              </label>
              <input type="file" accept=".pdf" className="file-input"
                onChange={(e) => {
                  const selected = e.target.files[0];
                  setFile(selected);
                  if (website === "gem") triggerAtcFetch(selected);
                }} />

            </div>
            {website === "gem" && (
              <div className="option-field" style={{ textAlign: "left", marginTop: "15px" }}>
                <label>Upload ATC / Tender Document (Optional)</label>
                <input type="file" accept=".pdf,.doc,.docx" className="file-input"
                  style={{ padding: "10px", marginTop: "5px" }}
                  onChange={(e) => setAtcUpload(e.target.files[0])} />
                {atcFetchLoading && (
                  <div style={{ fontSize: "12px", color: "#2563eb", marginTop: "6px", display: "flex", alignItems: "center", gap: "6px" }}>
                    <span>⏳ Auto-fetching buyer ATC &amp; SOW attachments from GeM...</span>
                  </div>
                )}
                {atcAutoFetched && !atcUpload && (
                  <div style={{ fontSize: "12px", color: "#16a34a", marginTop: "6px", background: "#f0fdf4", padding: "6px 10px", borderRadius: "4px", border: "1px solid #86efac" }}>
                    <strong>✅ Auto-Fetched from GeM:</strong> {atcAutoFetched.name} ({atcAutoFetched.count} attachment{atcAutoFetched.count > 1 ? "s" : ""} merged)
                  </div>
                )}
              </div>
            )}
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
                <strong>Forms needed from GCC / ATC:</strong>
                <ul style={{ margin: "8px 0 0 0", paddingLeft: "20px" }}>
                  {analyzeResponse.needs_gcc_list.map((item, i) => (
                    <li key={i} style={{ fontSize: "13px", marginBottom: "4px" }}>{item.line}</li>
                  ))}
                </ul>
              </div>
            )}
            {atcAutoFetched && !gccFile && (
              <div style={{ fontSize: "13px", color: "#166534", background: "#f0fdf4", border: "1px solid #86efac", padding: "8px 12px", borderRadius: "6px", marginBottom: "12px" }}>
                Using auto-fetched ATC document: <strong>{atcAutoFetched.name}</strong> ({atcAutoFetched.count} attachments merged)
              </div>
            )}
            <input type="file" accept=".pdf,.docx,.doc" className="file-input"
              style={{ padding: "10px", marginTop: "5px", width: "100%" }}
              onChange={(e) => setGccFile(e.target.files[0])} />
            <div style={{ display: "flex", gap: "10px", marginTop: "15px" }}>
              <button onClick={() => setUiStep(2)} style={{ flex: 1, padding: "12px", background: "#6b7280", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>
                Skip GCC
              </button>
              <button onClick={handleProcessGcc} disabled={(!gccFile && !atcAutoFetched && !atcUpload) || gccLoading}
                style={{ flex: 2, padding: "12px", background: "#8b5cf6", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>
                {gccLoading ? "Extracting Forms..." : (gccFile ? "Extract Forms from GCC" : (atcAutoFetched ? "Extract Forms from Auto-Fetched ATC" : "Extract Forms"))}
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
            {analyzeResponse.extracted_data && (
              <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "8px", padding: "12px", marginBottom: "20px" }}>
                <strong style={{ fontSize: "14px", color: "#166534" }}>Auto-Extracted Details (Editable):</strong>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginTop: "12px" }}>
                  {Object.entries(analyzeResponse.extracted_data)
                    .filter(([k]) => (website === "ireps" || k !== "railway"))
                    .map(([k, v]) => (
                    <div key={k} style={{ fontSize: "13px" }}>
                      <label style={{ display: "block", color: "#6b7280", textTransform: "capitalize", marginBottom: "4px" }}>
                        {k === "issuing_authority" 
                          ? (website === "gem" ? "Issuing Authority (Ministry / Dept / Office)" : (website === "nprocure" ? "Issuing Authority (Dept / Municipal Corp / Board)" : "Issuing Authority (Office / Railway)")) 
                          : (k === "place" ? "Place (City / Location)" : k.replace(/_/g, " "))}
                      </label>
                      <input type="text"
                        style={{ width: "95%", padding: "6px", border: "1px solid #86efac", borderRadius: "4px", fontSize: "13px" }}
                        value={missingFieldAnswers[k] !== undefined ? missingFieldAnswers[k] : (v || "")}
                        onChange={(e) => setMissingFieldAnswers({ ...missingFieldAnswers, [k]: e.target.value })}
                        placeholder={k === "issuing_authority" 
                          ? (website === "gem" ? "e.g. Ahmedabad Jailbhavan, BSNL" : (website === "nprocure" ? "e.g. Surat Municipal Corporation, GWSSB" : "e.g. Sr.DSTE/VSKP")) 
                          : (k === "place" ? "e.g. Ahmedabad, Surat, Vadodara, Delhi" : "")}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}
            {analyzeResponse.missing_fields && analyzeResponse.missing_fields.filter(f => website === "ireps" || f !== "railway").length > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <h3 style={{ fontSize: "16px", color: "#dc2626", marginBottom: "10px" }}>Missing Information Required:</h3>
                {analyzeResponse.missing_fields.filter(f => website === "ireps" || f !== "railway").map((f, i) => (
                  <div key={i} style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", textTransform: "capitalize" }}>
                      {f === "issuing_authority" 
                        ? (website === "gem" ? "Issuing Authority (Ministry / Dept / Office)" : (website === "nprocure" ? "Issuing Authority (Dept / Municipal Corp / Board)" : "Issuing Authority (Office / Railway Division - e.g. Sr.DSTE/VSKP)")) 
                        : (f === "place" ? "Place (City / Location - e.g. Ahmedabad)" : f.replace(/_/g, " "))}
                    </label>
                    <input type="text"
                      style={{ width: "100%", padding: "10px", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "14px" }}
                      value={missingFieldAnswers[f] || ""}
                      onChange={(e) => setMissingFieldAnswers({ ...missingFieldAnswers, [f]: e.target.value })}
                      placeholder={"Enter " + (f === "issuing_authority" 
                        ? (website === "gem" ? "Issuing Authority (e.g. Ahmedabad Jailbhavan)" : (website === "nprocure" ? "Issuing Authority (e.g. Surat Municipal Corporation)" : "Issuing Authority (e.g. Sr.DSTE/VSKP)")) 
                        : (f === "place" ? "Place / City (e.g. Ahmedabad)" : f.replace(/_/g, " "))) + "..."} />
                  </div>
                ))}
              </div>
            )}
            {analyzeResponse.proposed_merges && analyzeResponse.proposed_merges.length > 0 && (
                <div style={{ marginBottom: "25px" }}>
                  <h3 style={{ fontSize: "17px", color: "#1e3a8a", marginBottom: "8px", display: "flex", alignItems: "center", gap: "8px" }}>
                    <span>📋</span> Mandatory Documents &amp; Declarations Review
                  </h3>
                  <p style={{ fontSize: "13px", color: "#4b5563", marginBottom: "15px" }}>
                    For each mandatory requirement below, select whether to provide a <b>Document</b> (matched from library or manual upload), generate a <b>Declaration</b>, or <b>Both</b> (they will be automatically merged into a single PDF).
                  </p>
                  {analyzeResponse.proposed_merges.map((pm, i) => {
                    const isDocSelected = docSelections[pm.row_key] !== undefined ? !!docSelections[pm.row_key] : (pm.docs && pm.docs.length > 0);
                    const isDeclSelected = !!declarationSelections[pm.row_key];
                    const hasLibraryDocs = pm.docs && pm.docs.length > 0;
                    const hasCustomFile = customFiles[pm.row_key] && customFiles[pm.row_key].length > 0;

                    let mergeBadge = null;
                    if (isDocSelected && isDeclSelected) {
                      mergeBadge = (
                        <span style={{ fontSize: "12px", fontWeight: "600", padding: "4px 10px", borderRadius: "12px", background: "#dbeafe", color: "#1e40af", border: "1px solid #93c5fd" }}>
                          🔄 Both Selected: Document + Declaration will MERGE
                        </span>
                      );
                    } else if (isDocSelected) {
                      mergeBadge = (
                        <span style={{ fontSize: "12px", fontWeight: "600", padding: "4px 10px", borderRadius: "12px", background: "#f0fdf4", color: "#166534", border: "1px solid #86efac" }}>
                          📄 Document Only
                        </span>
                      );
                    } else if (isDeclSelected) {
                      mergeBadge = (
                        <span style={{ fontSize: "12px", fontWeight: "600", padding: "4px 10px", borderRadius: "12px", background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a" }}>
                          ✍️ Declaration Only
                        </span>
                      );
                    } else {
                      mergeBadge = (
                        <span style={{ fontSize: "12px", fontWeight: "600", padding: "4px 10px", borderRadius: "12px", background: "#f3f4f6", color: "#6b7280", border: "1px solid #d1d5db" }}>
                          ⚪ Skipped
                        </span>
                      );
                    }

                    return (
                      <div key={i} style={{
                        background: isDeclSelected && isDocSelected ? "#f8fafc" : (isDeclSelected ? "#fffbeb" : (isDocSelected ? "#f0fdf4" : "#f9fafb")),
                        border: "1px solid " + (isDeclSelected && isDocSelected ? "#93c5fd" : (isDeclSelected ? "#fde68a" : (isDocSelected ? "#86efac" : "#e5e7eb"))),
                        borderRadius: "10px",
                        padding: "16px",
                        marginBottom: "16px",
                        boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px", marginBottom: "10px" }}>
                          <div style={{ flex: 1 }}>
                            <span style={{ fontSize: "12px", fontWeight: "700", color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                              Requirement #{i + 1}
                            </span>
                            <p style={{ fontSize: "14px", fontWeight: "600", color: "#111827", margin: "4px 0 0 0", lineHeight: "1.4" }}>
                              {pm.line}
                            </p>
                            {pm.description && pm.description !== pm.line && (
                              <p style={{ fontSize: "12px", color: "#6b7280", margin: "4px 0 0 0" }}>
                                {pm.description}
                              </p>
                            )}
                          </div>
                          <div>{mergeBadge}</div>
                        </div>

                        {!hasLibraryDocs && (
                          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: "6px", padding: "8px 12px", marginBottom: "12px", fontSize: "12px", color: "#9a3412" }}>
                            ⚠️ <b>Notice:</b> Document not found automatically in library. You can manually upload the document below and/or select Declaration.
                          </div>
                        )}

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginTop: "10px" }}>
                          {/* OPTION 1: DOC TO MAP */}
                          <div style={{
                            background: "#ffffff",
                            border: "1px solid " + (isDocSelected ? "#3b82f6" : "#e5e7eb"),
                            borderRadius: "8px",
                            padding: "12px"
                          }}>
                            <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontWeight: "600", fontSize: "13px", color: isDocSelected ? "#1d4ed8" : "#374151" }}>
                              <input
                                type="checkbox"
                                checked={isDocSelected}
                                onChange={(e) => setDocSelections({ ...docSelections, [pm.row_key]: e.target.checked })}
                              />
                              <span>📂 Doc to Map {hasLibraryDocs ? "(From Library / Upload)" : "(Manual Upload)"}</span>
                            </label>

                            {isDocSelected && (
                              <div style={{ marginTop: "10px", paddingLeft: "24px" }}>
                                {hasLibraryDocs ? (
                                  <div style={{ marginBottom: "8px" }}>
                                    <span style={{ fontSize: "11px", color: "#6b7280", fontWeight: "600" }}>Library Matched Files:</span>
                                    {pm.docs.map((doc, j) => (
                                      <label key={j} style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px", fontSize: "12px", cursor: "pointer" }}>
                                        <input
                                          type="checkbox"
                                          checked={(mergeSelections[pm.row_key] || []).includes(doc.id)}
                                          onChange={(e) => {
                                            const cur = mergeSelections[pm.row_key] || [];
                                            if (e.target.checked) setMergeSelections(p => ({ ...p, [pm.row_key]: [...cur, doc.id] }));
                                            else setMergeSelections(p => ({ ...p, [pm.row_key]: cur.filter(id => id !== doc.id) }));
                                          }}
                                        />
                                        {doc.url ? (
                                          <a href={`${API_BASE}${doc.url}`} target="_blank" rel="noreferrer" style={{ color: "#2563eb", textDecoration: "underline" }} onClick={(e) => e.stopPropagation()}>
                                            {doc.name}
                                          </a>
                                        ) : (
                                          <span>{doc.name}</span>
                                        )}
                                      </label>
                                    ))}
                                  </div>
                                ) : (
                                  <div style={{ fontSize: "12px", color: "#6b7280", marginBottom: "8px" }}>
                                    Upload your document file below:
                                  </div>
                                )}

                                <div style={{ marginTop: "8px" }}>
                                  <label style={{ fontSize: "11px", fontWeight: "600", color: "#4b5563", display: "block", marginBottom: "4px" }}>
                                    {hasLibraryDocs ? "Upload Extra / Replacement File (PDF/DOCX):" : "Upload Document File (PDF/DOCX):"}
                                  </label>
                                  <input
                                    type="file"
                                    id={`custom_file_${pm.row_key}`}
                                    accept=".pdf,.docx,.doc"
                                    multiple
                                    style={{ fontSize: "12px", width: "100%" }}
                                    onChange={(e) => setCustomFiles({ ...customFiles, [pm.row_key]: e.target.files })}
                                  />
                                  {hasCustomFile && (
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                                      <span style={{ fontSize: "11px", color: "#16a34a" }}>
                                        ✓ {customFiles[pm.row_key].length} file(s) attached
                                      </span>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          const newFiles = { ...customFiles };
                                          delete newFiles[pm.row_key];
                                          setCustomFiles(newFiles);
                                          const el = document.getElementById(`custom_file_${pm.row_key}`);
                                          if (el) el.value = "";
                                        }}
                                        style={{ fontSize: "10px", padding: "2px 6px", background: "#ef4444", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                                      >
                                        Clear
                                      </button>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>

                          {/* OPTION 2: DECLARATION */}
                          <div style={{
                            background: "#ffffff",
                            border: "1px solid " + (isDeclSelected ? "#f59e0b" : "#e5e7eb"),
                            borderRadius: "8px",
                            padding: "12px"
                          }}>
                            <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontWeight: "600", fontSize: "13px", color: isDeclSelected ? "#b45309" : "#374151" }}>
                              <input
                                type="checkbox"
                                checked={isDeclSelected}
                                onChange={(e) => setDeclarationSelections({ ...declarationSelections, [pm.row_key]: e.target.checked })}
                              />
                              <span>✍️ Declaration</span>
                            </label>

                            {isDeclSelected && (
                              <div style={{ marginTop: "10px", paddingLeft: "24px" }}>
                                <label style={{ fontSize: "11px", fontWeight: "600", color: "#4b5563", display: "block", marginBottom: "4px" }}>
                                  Custom Declaration Text / Additional Points (Optional):
                                </label>
                                <textarea
                                  rows={3}
                                  value={declarationTexts[pm.row_key] || ""}
                                  onChange={(e) => setDeclarationTexts({ ...declarationTexts, [pm.row_key]: e.target.value })}
                                  placeholder="Add any specific text, clauses, undertakings, or details to include in this declaration..."
                                  style={{
                                    width: "100%",
                                    fontSize: "12px",
                                    padding: "8px",
                                    border: "1px solid #d1d5db",
                                    borderRadius: "6px",
                                    boxSizing: "border-box",
                                    fontFamily: "inherit"
                                  }}
                                />
                                <div style={{ fontSize: "11px", color: "#6b7280", marginTop: "4px", marginBottom: "8px" }}>
                                  ℹ️ AI analyzes the requirement description + your written text to draft a formal legal declaration signed with <b>Place: Ahmedabad</b>.
                                </div>

                                <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap", marginTop: "8px" }}>
                                  <button
                                    type="button"
                                    onClick={() => handleCreateRequirementDeclaration(pm.row_key, pm.line, pm.description)}
                                    disabled={singleDeclLoading[pm.row_key]}
                                    style={{
                                      background: createdDeclarations[pm.row_key] ? "#059669" : "#2563eb",
                                      color: "#ffffff",
                                      border: "none",
                                      borderRadius: "6px",
                                      padding: "8px 14px",
                                      fontSize: "12px",
                                      fontWeight: "600",
                                      cursor: singleDeclLoading[pm.row_key] ? "not-allowed" : "pointer",
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: "6px"
                                    }}
                                  >
                                    {singleDeclLoading[pm.row_key] ? (
                                      <>
                                        <span role="status" aria-hidden="true">⏳</span>
                                        Analyzing &amp; Creating Declaration...
                                      </>
                                    ) : createdDeclarations[pm.row_key] ? (
                                      <>🔄 Re-create Declaration</>
                                    ) : (
                                      <>✨ Create Declaration</>
                                    )}
                                  </button>

                                  {createdDeclarations[pm.row_key] && (
                                    <a
                                      href={`${API_BASE}${createdDeclarations[pm.row_key].url}`}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        fontSize: "12px",
                                        fontWeight: "600",
                                        color: "#1d4ed8",
                                        textDecoration: "underline",
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: "4px"
                                      }}
                                    >
                                      📄 View Created Declaration ({createdDeclarations[pm.row_key].name})
                                    </a>
                                  )}
                                </div>

                                {singleDeclError[pm.row_key] && (
                                  <div style={{ marginTop: "6px", fontSize: "11px", color: "#dc2626" }}>
                                    ⚠️ {singleDeclError[pm.row_key]}
                                  </div>
                                )}

                                {createdDeclarations[pm.row_key] && (
                                  <div style={{
                                    marginTop: "8px",
                                    padding: "8px 12px",
                                    background: "#f0fdf4",
                                    border: "1px solid #bbf7d0",
                                    borderRadius: "6px",
                                    fontSize: "11px",
                                    color: "#166534"
                                  }}>
                                    ✓ <b>Declaration Ready:</b> Analyzed requirement and custom text.
                                    {isDocSelected ? " It will be merged with your selected document." : " It will be submitted as this requirement's document."}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
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
          <div className="upload-box" style={{ maxWidth: "650px", margin: "0 auto", textAlign: "left" }}>
            <h2>Step 3: Create Custom Declarations</h2>
            <p style={{ color: "#555", fontSize: "13px", marginBottom: "15px" }}>
              Draft any extra formal declarations, undertakings, or certificates needed for this tender.
            </p>

            {localPath && (
              <div style={{ background: "#eef2ff", padding: "10px 14px", borderRadius: "6px", border: "1px solid #c7d2fe", marginBottom: "16px", color: "#1e40af", fontSize: "12px", wordBreak: "break-all" }}>
                📁 <b>Output Folder:</b> {localPath}
              </div>
            )}

            <div style={{ background: "#f8fafc", padding: "16px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <h3 style={{ fontSize: "15px", marginBottom: "8px", color: "#1e293b" }}>Write Custom Declaration Prompt</h3>
              <textarea
                placeholder="E.g. Create a GST Declaration stating that we are exempt from..., or Create an Undertaking confirming compliance with railway safety guidelines..."
                value={declPrompt}
                onChange={(e) => setDeclPrompt(e.target.value)}
                style={{ width: "100%", height: "100px", padding: "10px", marginTop: "6px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
              />
              <button
                onClick={handleCreateDecl}
                disabled={declLoading || !declPrompt.trim()}
                style={{ padding: "10px 16px", width: "100%", marginTop: "10px", cursor: (declLoading || !declPrompt.trim()) ? "not-allowed" : "pointer", background: "#10b981", color: "white", border: "none", borderRadius: "6px", fontWeight: "600", fontSize: "13px" }}
              >
                {declLoading ? "⏳ Generating PDF Declaration..." : "✨ Generate Custom Declaration PDF"}
              </button>
            </div>

            {generatedDecls.length > 0 && (
              <div style={{ marginTop: "20px", padding: "16px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "8px" }}>
                <strong style={{ fontSize: "14px", color: "#166534", display: "block", marginBottom: "8px" }}>
                  📄 Generated Documents &amp; Declarations ({generatedDecls.length}):
                </strong>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  {generatedDecls.map((d, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#ffffff", padding: "8px 12px", borderRadius: "4px", border: "1px solid #dcfce7" }}>
                      <span style={{ fontSize: "13px", color: "#334155" }}>{d.name}</span>
                      {d.url && (
                        <a href={`${API_BASE}${d.url}`} target="_blank" rel="noreferrer" style={{ color: "#2563eb", textDecoration: "underline", fontSize: "12px", fontWeight: "600" }}>
                          Preview
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: "12px", marginTop: "25px" }}>
              <button
                className="btn-start"
                onClick={() => setUiStep(4)}
                style={{ background: "#6b7280", flex: 1, color: "#fff", padding: "12px" }}
              >
                Skip to Step 4
              </button>
              <button
                className="btn-start"
                onClick={() => setUiStep(4)}
                style={{ background: "#2563eb", flex: 2, color: "#fff", padding: "12px" }}
              >
                Next: Add Extra Files (Step 4) →
              </button>
            </div>

            <div style={{ marginTop: "15px", textAlign: "center" }}>
              <button
                type="button"
                onClick={() => setUiStep(2)}
                style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", textDecoration: "underline", fontSize: "13px" }}
              >
                ← Back to Step 2 (Confirm Details)
              </button>
            </div>
          </div>
        )}

        {uiStep === 4 && (
          <div className="upload-box" style={{ maxWidth: "650px", margin: "0 auto", textAlign: "left" }}>
            <h2>Step 4: Add Extra Files</h2>
            <p style={{ color: "#555", fontSize: "13px", marginBottom: "15px" }}>
              Upload any remaining standalone PDFs, custom forms (.docx), or annexures to include in the final package.
            </p>
            <input
              type="file"
              multiple
              className="file-input"
              style={{ padding: "10px", width: "100%", boxSizing: "border-box" }}
              onChange={(e) => setExtraFiles(e.target.files)}
            />

            {extraFiles && extraFiles.length > 0 && (
              <div style={{ marginTop: "12px", padding: "10px 14px", background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "6px", fontSize: "13px", color: "#166534" }}>
                <strong>✓ Selected {extraFiles.length} file(s):</strong>
                <ul style={{ margin: "6px 0 0 0", paddingLeft: "20px" }}>
                  {Array.from(extraFiles).map((f, idx) => (
                    <li key={idx} style={{ marginBottom: "2px" }}>{f.name}</li>
                  ))}
                </ul>
              </div>
            )}

            {missingDocQuestions.length > 0 && (
              <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: "8px", padding: "16px", marginTop: "20px" }}>
                <h3 style={{ fontSize: "15px", color: "#b45309", marginBottom: "6px" }}>
                  ⚠️ Additional Information Needed for {pendingDocName || "Uploaded Form"}
                </h3>
                <p style={{ fontSize: "13px", color: "#78350f", marginBottom: "14px" }}>
                  Please answer the following to complete this document without any missing fields:
                </p>
                {missingDocQuestions.map((q, idx) => (
                  <div key={idx} style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: "600", color: "#374151", marginBottom: "4px" }}>
                      {q}
                    </label>
                    <input
                      type="text"
                      style={{ width: "100%", padding: "8px", border: "1px solid #d1d5db", borderRadius: "4px", fontSize: "13px", boxSizing: "border-box" }}
                      value={extraDocAnswers[q] || ""}
                      onChange={(e) => setExtraDocAnswers({ ...extraDocAnswers, [q]: e.target.value })}
                      placeholder="Type answer here..."
                    />
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", gap: "12px", marginTop: "30px" }}>
              <button
                className="btn-start"
                onClick={() => handleMerge(true)}
                disabled={mergeLoading}
                style={{ background: "#6b7280", flex: 1, color: "#fff", padding: "12px" }}
              >
                {mergeLoading ? "..." : "Skip & Finish"}
              </button>
              <button
                className="btn-start"
                onClick={() => handleMerge(false)}
                disabled={mergeLoading}
                style={{ background: "#10b981", flex: 2, color: "#fff", padding: "12px" }}
              >
                {mergeLoading ? "Finalizing Package..." : (missingDocQuestions.length > 0 ? "Apply Answers & Finalize" : "Finalize & Complete Package")}
              </button>
            </div>

            <div style={{ marginTop: "15px", textAlign: "center" }}>
              <button
                type="button"
                onClick={() => setUiStep(3)}
                style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", textDecoration: "underline", fontSize: "13px" }}
              >
                ← Back to Step 3 (Create Declarations)
              </button>
            </div>
          </div>
        )}

        {(uiStep === 5 || uiStep === "done") && (
          <div className="summary-preview" style={{ maxWidth: "800px", margin: "20px auto", textAlign: "left" }}>
            <div style={{ textAlign: "center", marginBottom: "15px" }}>
              <div style={{ fontSize: "60px", marginBottom: "10px" }}>🎉</div>
              <h3 style={{ marginBottom: "6px" }}>Final Package Ready!</h3>
              <p style={{ color: "#555" }}>Your tender documents and declarations have been mapped, generated, and finalized.</p>
            </div>

            <div style={{ background: "#eef2ff", padding: "15px", borderRadius: "8px", border: "1px solid #c7d2fe", margin: "15px 0", color: "#1e40af", fontWeight: "bold", wordBreak: "break-all" }}>
              📁 Local Folder Path: {finalZipUrl || localPath}
            </div>

            {generatedDecls.length > 0 && (
              <div style={{ marginTop: "20px", padding: "18px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                <strong style={{ fontSize: "15px", color: "#1e293b", display: "block", marginBottom: "10px" }}>
                  📄 Generated Documents &amp; Declarations ({generatedDecls.length}):
                </strong>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {generatedDecls.map((d, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#ffffff", padding: "10px 14px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ fontSize: "13px", fontWeight: "500", color: "#334155" }}>
                        {d.name}
                      </span>
                      {d.url && (
                        <a
                          href={`${API_BASE}${d.url}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: "#2563eb", textDecoration: "underline", fontSize: "13px", fontWeight: "600" }}
                        >
                          Preview / Download
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {excelUrl && (
              <div style={{ marginTop: "15px", textAlign: "center" }}>
                <a href={`${API_BASE}${excelUrl}`} target="_blank" rel="noreferrer"
                  style={{ display: "inline-block", padding: "10px 20px", background: "#2563eb", color: "white", borderRadius: "6px", textDecoration: "none", fontSize: "14px", fontWeight: "600" }}>
                  📊 Download Requirements Excel
                </a>
              </div>
            )}

            <div style={{ marginTop: "25px", textAlign: "center" }}>
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
