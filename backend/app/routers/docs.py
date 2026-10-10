import shutil
from typing import Optional, List, Dict, Any
import markdown
import asyncio
import logging
import threading
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from app.core.pdf_generator import generate_pdf_from_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import SITES, PIPELINE
import app.core.config as config
from app.core.db import init_db
from app.core.state import Pipeline, Ledger

from google import genai
gemini_client = None
if config.GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
else:
    logging.warning("GEMINI_API_KEY is not set.")
from fastapi import APIRouter, File, UploadFile, Request, Form, Response, Depends, BackgroundTasks

def convert_to_pdf_global(docx_path):
    if str(docx_path).lower().endswith(".docx"):
        try:
            import subprocess
            import os
            from pathlib import Path
            pdf_path = str(docx_path).rsplit(".", 1)[0] + ".pdf"
            abs_docx = str(Path(docx_path).resolve())
            abs_pdf = str(Path(pdf_path).resolve())
            subprocess.run(["docx2pdf", abs_docx, abs_pdf], check=True, capture_output=True)
            if Path(abs_pdf).exists():
                try:
                    os.remove(abs_docx)
                except:
                    pass
                return Path(abs_pdf)
        except Exception as e:
            pass
    return docx_path

def fill_docx_template_global(template_path, output_path, replacements, signature_path=None):
    import docx
    from docx.shared import Inches
    try:
        doc = docx.Document(template_path)
        for p in doc.paragraphs:
            for k, v in replacements.items():
                if k in p.text:
                    p.text = p.text.replace(k, str(v))
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for k, v in replacements.items():
                            if k in p.text:
                                p.text = p.text.replace(k, str(v))
        if signature_path:
            p = doc.add_paragraph()
            r = p.add_run()
            r.add_picture(signature_path, width=Inches(1.5))
        doc.save(output_path)
    except Exception as e:
        shutil.copy(template_path, output_path)

router = APIRouter()

@router.post("/api/docs/map")
async def map_document(
    request: Request,
    company: str = Form(...),
    website: str = Form("ireps"),
    step: str = Form("generate"),
    document_id: str | None = Form(None),
    file: UploadFile = File(None),
    atc_file: UploadFile | None = File(None),
    extra_answers: str = Form(None),
    cached_llm_json: str = Form(None),
    tender_name: str | None = Form(None),
    place: str | None = Form(None),
    railway: str | None = Form(None),
    signatory_name: str | None = Form(None),
    signatory_designation: str | None = Form(None),
    date: str | None = Form(None),
    days: str | None = Form(None),
    issuing_authority: str | None = Form(None),
    bid_security_amount: str | None = Form(None),
    execute_contract_days: str | None = Form(None),
    commence_work_days: str | None = Form(None),
    closing_date: str | None = Form(None),
    merges_data: str | None = Form(None),
    gcc_results_data: str | None = Form(None),
):
    """
    Map a document for a selected company using the uploaded NIT file.
    step=analyze -> dry_run=True, returns missing_fields/proposed_merges/needs_gcc
    step=generate -> full document generation
    """
    import os
    import json as json_mod
    import fitz
    import time
    from pathlib import Path
    import logging
    from app.internal.intake.pdf_parser import parse_nit_pdf
    from app.internal.intake.intake import process_requirements, load_catalog, get_tender_out_dir
    from app.internal.intake.excel_parser import create_excel_from_requirements, parse_excel_requirements, update_excel_status
    import app.core.config as config
    from google import genai
    
    try:
        form_data = await request.form()

        # Save uploaded NIT file
        saved_nit_path = None
        if file and file.filename:
            content_bytes = await file.read()
            nit_file_path = config.DOWNLOADS_DIR / file.filename
            nit_file_path.parent.mkdir(parents=True, exist_ok=True)
            nit_file_path.write_bytes(content_bytes)
            saved_nit_path = nit_file_path

        api_key = config.GEMINI_API_KEY
        extracted_tender_no = document_id
        pdf_reqs = []
        nit_data = {}
        atc_path = None

        comp_lower = company.lower()
        if comp_lower in ["aquint", "aquiant", "aquiaint"]:
            company_display = "AQUIANT INFRATELE INDIA PRIVATE LIMITED"
            signatory_name_def = "Bhargav Kalaria"
            signatory_designation_def = "Managing Director"
        else:
            company_display = "ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
            signatory_name_def = "DHARAMRAJSINH NARENDRASINH VAGHELA"
            signatory_designation_def = "Managing Director"

        if website.lower() != "gem":
            # ── IREPS PARSING ──
            if saved_nit_path and saved_nit_path.exists() and step == "analyze":
                t_no, pdf_reqs, parsed_data = parse_nit_pdf(str(saved_nit_path), api_key)
                if t_no: extracted_tender_no = t_no
                nit_data = parsed_data or {}
                
            if not extracted_tender_no and file and file.filename:
                extracted_tender_no = (file.filename or "").replace(".pdf", "")

            if not extracted_tender_no:
                return {"status": "error", "message": "Tender Number could not be found. Please enter it manually."}

            if pdf_reqs:
                compulsory_reqs = [
                    "certificate to be submitted",
                    "declaration form for relative",
                    "declaration for retired railway employees",
                    "power of attorney board resolution",
                    "statement of deviations"
                ]
                for c in compulsory_reqs:
                    pdf_reqs.append(c)

            saved_excel_path = config.DOWNLOADS_DIR / f"Generated_Requirements_{extracted_tender_no}.xlsx"
            h_row = d_col = r_col = s_col = u_col = n_col = None
            if pdf_reqs:
                excel_reqs, h_row, d_col, r_col, s_col, u_col, n_col = create_excel_from_requirements(str(saved_excel_path), pdf_reqs)
            elif saved_excel_path.exists():
                try:
                    excel_reqs, h_row, d_col, r_col, s_col, u_col, n_col = parse_excel_requirements(str(saved_excel_path))
                except Exception as e:
                    return {"status": "error", "message": f"Excel parsing error: {e}"}
            else:
                return {"status": "error", "message": "No requirements found. Please upload the NIT PDF."}
                
        else:
            # ── GEM PARSING ──
            if atc_file:
                atc_content = await atc_file.read()
                atc_path = config.DOWNLOADS_DIR / atc_file.filename
                atc_path.write_bytes(atc_content)
                
            if not extracted_tender_no and file and file.filename:
                extracted_tender_no = (file.filename or "").replace(".pdf", "")
            if not extracted_tender_no:
                return {"status": "error", "message": "Tender Number could not be found."}
                
            saved_excel_path = config.DOWNLOADS_DIR / f"Generated_Requirements_{extracted_tender_no}_GeM.xlsx"
            h_row = d_col = r_col = s_col = u_col = n_col = None
            
            if step == "analyze" and not cached_llm_json:
                import requests
                # Attempt ATC download if not provided
                if not atc_path and saved_nit_path:
                    try:
                        doc = fitz.open(str(saved_nit_path))
                        atc_uris = []
                        for page in doc:
                            for link in page.get_links():
                                u = link.get("uri", "")
                                if u and ("slafds" in u.lower() or "get_atc_document" in u.lower() or "atc" in u.lower()):
                                    if "slafds" in u.lower() or "get_atc_document" in u.lower(): atc_uris.insert(0, u)
                                    else: atc_uris.append(u)
                        for uri in atc_uris:
                            headers = { "User-Agent": "Mozilla/5.0", "Accept": "*/*" }
                            atc_res = requests.get(uri, verify=False, timeout=30, headers=headers)
                            if atc_res.status_code == 200 and b"rejected" not in atc_res.content.lower():
                                ext = ".docx" if ".docx" in uri.lower() else ".pdf"
                                atc_path = saved_nit_path.with_name(f"ATC_{extracted_tender_no}{ext}")
                                atc_path.write_bytes(atc_res.content)
                                break
                    except Exception as e:
                        logging.warning(f"ATC fetch error: {e}")
                
                # Extract text
                nit_text = ""
                try:
                    if saved_nit_path:
                        doc_pdf = fitz.open(str(saved_nit_path))
                        for page in doc_pdf: nit_text += page.get_text()
                        nit_text = nit_text[:400000]
                except Exception: pass
                
                atc_text = ""
                if atc_path and atc_path.exists():
                    try:
                        if atc_path.suffix.lower() == ".pdf":
                            doc_atc = fitz.open(str(atc_path))
                            for page in doc_atc: atc_text += page.get_text()
                        elif atc_path.suffix.lower() in [".docx", ".doc"]:
                            import docx
                            d = docx.Document(str(atc_path))
                            atc_text = "\n".join([p.text for p in d.paragraphs])
                        atc_text = atc_text[:200000]
                    except Exception: pass

                catalog = load_catalog("gem")
                catalog_summary = [f"ID: {c['id']} | Hint: {c.get('filename_hint', '')}" for c in catalog]
                catalog_str = "\n".join(catalog_summary)
                
                prompt = f"""
                You are an expert procurement assistant.
                We are preparing a bid for the company '{company_display}'.
                Read the attached Tender Document (NIT) text{" and the ATC document text" if atc_text else ""} and create a strict DOCUMENT MAPPING table.
                
                {"IMPORTANT: I have provided the ATC document. There is usually a clear 'List of documents to be submitted in GeM portal' or a 'General Parameter Checklist' table. You MUST extract this checklist EXACTLY as it appears. DO NOT extract requirements from general text paragraphs like 'Eligibility Criteria' if a checklist table is available. DO NOT summarize, merge, or change a single word of the descriptions. Maintain the exact order. If there are 17 items in the checklist, you must return 17 items." if atc_text else "Extract all document requirements exactly as they appear without summarizing or changing words."}
                
                CATALOG:
                {catalog_str}
                
                FINALLY, output a JSON block wrapped in ```json ... ``` with exactly three keys:
                1. "extracted_fields": Dictionary with:
                    "{{{{TENDER_NO}}}}": "...", "{{{{TENDER_NAME}}}}": "...", "{{{{PLACE}}}}": "...", "{{{{DATE}}}}": "...", "{{{{CLOSING_DATE}}}}": "...", "{{{{ISSUING_AUTHORITY}}}}": "..."
                2. "missing_fields": List of string questions for blanks to fill in docs.
                3. "requirements": List of objects:
                    [ {{ "description": "EXACT word-for-word text from the document. DO NOT change, rephrase, or summarize it.", "mapped_ids": ["ID1", "ID2"] }} ]
                    
                CRITICAL RULES:
                - DO NOT extract from 'Eligibility Criteria' text if a 'List of documents to be submitted' or 'General Parameter Checklist' table exists. Use the table!
                - DO NOT merge multiple checklist items into one.
                - DO NOT rephrase descriptions. Copy them word-for-word exactly as they appear in the checklist.
                - If an annexure/format for a requirement is EXPLICITLY PROVIDED inside the ATC document text, do NOT map it to our catalog (leave "mapped_ids": []). We will extract the format directly from the ATC.
                - ONLY map to our catalog IDs if the format is NOT provided in the ATC document.

                
                --- TENDER DOCUMENT (NIT) TEXT ---
                {nit_text}
                
                {("--- ATC DOCUMENT TEXT ---\n" + atc_text) if atc_text else ""}
                """
                
                import re
                client = genai.Client(api_key=api_key)
                response_text = ""
                for model_name in ["gemini-3.5-flash-lite", "gemini-3.5-flash"]:
                    try:
                        response = client.models.generate_content(model=model_name, contents=prompt)
                        response_text = response.text
                        break
                    except Exception as e:
                        if "429" in str(e): break
                        time.sleep(2)
                        
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    data = json_mod.loads(json_match.group(1))
                    
                    # Convert to excel_reqs format
                    gem_reqs = []
                    for r in data.get("requirements", []):
                        if r.get("description"):
                            gem_reqs.append({
                                "line": r["description"],
                                "canonical_ids": r.get("mapped_ids", [])
                            })
                    if gem_reqs:
                        gem_strings = [r["line"] for r in gem_reqs]
                        _, h_row, d_col, r_col, s_col, u_col, n_col = create_excel_from_requirements(str(saved_excel_path), gem_strings)
                        
                        excel_reqs = [{"row": i+2, "name": r["line"], "canonical_ids": r["canonical_ids"]} for i, r in enumerate(gem_reqs)]
                        
                        # Save canonical_ids to JSON so step=generate can read them
                        gem_json_path = saved_excel_path.with_suffix(".json")
                        gem_json_path.write_text(json_mod.dumps(excel_reqs), encoding="utf-8")
                        
                    nit_data["tender_no"] = data.get("extracted_fields", {}).get("{{TENDER_NO}}", "")
                    nit_data["tender_name"] = data.get("extracted_fields", {}).get("{{TENDER_NAME}}", "")
                    nit_data["place"] = data.get("extracted_fields", {}).get("{{PLACE}}", "")
                    nit_data["date"] = data.get("extracted_fields", {}).get("{{DATE}}", "")
                    nit_data["closing_date"] = data.get("extracted_fields", {}).get("{{CLOSING_DATE}}", "")
                    nit_data["issuing_authority"] = data.get("extracted_fields", {}).get("{{ISSUING_AUTHORITY}}", "")
                    
                else:
                    return {"status": "error", "message": "Failed to extract JSON from AI."}

            elif saved_excel_path.exists():
                try:
                    excel_reqs, h_row, d_col, r_col, s_col, u_col, n_col = parse_excel_requirements(str(saved_excel_path))
                    
                    # Load canonical_ids from JSON
                    gem_json_path = saved_excel_path.with_suffix(".json")
                    if gem_json_path.exists():
                        try:
                            cached_gem_reqs = json_mod.loads(gem_json_path.read_text(encoding="utf-8"))
                            for i, r in enumerate(excel_reqs):
                                if i < len(cached_gem_reqs):
                                    r["canonical_ids"] = cached_gem_reqs[i].get("canonical_ids", [])
                        except Exception:
                            pass
                except Exception as e:
                    return {"status": "error", "message": f"Excel parsing error: {e}"}
            else:
                return {"status": "error", "message": "No requirements found for GeM."}

        # ── COMMON LOGIC FOR IREPS AND GEM ──
        reqs = excel_reqs
        catalog = load_catalog(website.lower())

        def get_val(form_val, n_val):
            if form_val and str(form_val).strip(): return str(form_val).strip()
            if n_val and str(n_val).strip(): return str(n_val).strip()
            return None

        user_inputs = {
            "tender_no":             get_val(document_id, nit_data.get("tender_no")) or extracted_tender_no,
            "tender_name":           get_val(tender_name, nit_data.get("tender_name")),
            "company_name":          company_display,
            "place":                 get_val(place, nit_data.get("place")),
            "railway":               get_val(railway, nit_data.get("railway")),
            "signatory_name":        get_val(signatory_name, nit_data.get("signatory_name")) or signatory_name_def,
            "signatory_designation": get_val(signatory_designation, nit_data.get("signatory_designation")) or signatory_designation_def,
            "date":                  get_val(date, nit_data.get("date")),
            "days":                  get_val(days, nit_data.get("days")),
            "issuing_authority":     get_val(issuing_authority, nit_data.get("issuing_authority")),
            "bid_security_amount":   get_val(bid_security_amount, nit_data.get("bid_security_amount")),
            "execute_contract_days": get_val(execute_contract_days, nit_data.get("execute_contract_days")),
            "commence_work_days":    get_val(commence_work_days, nit_data.get("commence_work_days")),
            "closing_date":          get_val(closing_date, nit_data.get("closing_date")),
        }

        if step == "generate" and website.lower() == "gem":
            for k, v in user_inputs.items():
                if not v:
                    user_inputs[k] = "N/A"


        user_merges = {}
        if merges_data:
            try: user_merges = json_mod.loads(merges_data)
            except Exception: pass

        gcc_results = {}
        if gcc_results_data:
            try: gcc_results = json_mod.loads(gcc_results_data)
            except Exception: pass

        # ── STEP: analyze (dry-run) ──
        if step == "analyze":
            results, missing_fields, proposed_merges, needs_gcc_list, needs_letterhead = process_requirements(
                reqs, extracted_tender_no, catalog,
                is_excel=True, dry_run=True,
                user_inputs=user_inputs, user_merges=user_merges,
                combine_flags={}, portal_type=website.lower()
            )
            needs_info  = len(missing_fields) > 0
            needs_merge = len(proposed_merges) > 0

            if needs_info or needs_merge or needs_gcc_list or needs_letterhead:
                return {
                    "status": "needs_info",
                    "needs_info": needs_info,
                    "needs_merge": needs_merge,
                    "needs_gcc": len(needs_gcc_list) > 0,
                    "needs_letterhead": needs_letterhead,
                    "needs_gcc_list": needs_gcc_list,
                    "extracted_tender_no": extracted_tender_no,
                    "extracted_data": user_inputs,
                    "missing_fields": list(missing_fields),
                    "proposed_merges": proposed_merges,
                    "excel_url": f"/downloads/{saved_excel_path.name}",
                }
            step = "generate"  # nothing missing, generate right away

        # ── STEP: generate ──
        if step == "generate":
            import shutil
            custom_paths = {}
            for key, val in form_data.multi_items():
                if key.startswith("req_") and key.endswith("_custom"):
                    if not val.filename:
                        continue
                    row_key = key.split("_")[1]
                    import uuid
                    safe_filename = f"{uuid.uuid4().hex[:8]}_{val.filename}"
                    f_path = config.DOWNLOADS_DIR / safe_filename
                    f_path.write_bytes(val.file.read())
                    if row_key not in custom_paths:
                        custom_paths[row_key] = []
                    custom_paths[row_key].append(str(f_path))

            extra_pdfs = {}
            if atc_path and atc_path.exists():
                extra_pdfs["atc_path"] = str(atc_path)
            else:
                for ext in [".pdf", ".docx", ".doc"]:
                    p = config.DOWNLOADS_DIR / f"ATC_{extracted_tender_no}{ext}"
                    if p.exists():
                        extra_pdfs["atc_path"] = str(p)
                        break

            results, _, _, _, _ = process_requirements(
                reqs, extracted_tender_no, catalog,
                is_excel=True, dry_run=False,
                user_inputs=user_inputs, user_merges=user_merges,
                gcc_results=gcc_results, extra_pdfs=extra_pdfs, combine_flags={},
                custom_annexure_paths=custom_paths,
                portal_type=website.lower()
            )

            out_dir = get_tender_out_dir(extracted_tender_no, user_inputs, website.lower())
            out_dir.mkdir(parents=True, exist_ok=True)

            if saved_excel_path and saved_excel_path.exists() and s_col:
                try:
                    update_excel_status(str(saved_excel_path), results, s_col, u_col, n_col)
                    shutil.copy(saved_excel_path, out_dir / f"Mapped_Requirements_{extracted_tender_no}.xlsx")
                except Exception:
                    pass
            
            # Copy original documents to the folder
            try:
                from app.internal.intake.intake import convert_to_pdf_if_docx
                
                if saved_nit_path and saved_nit_path.exists():
                    c_path = out_dir / saved_nit_path.name
                    shutil.copy(saved_nit_path, c_path)
                    if c_path.suffix.lower() in [".docx", ".doc"]:
                        convert_to_pdf_if_docx(c_path)
                elif file and file.filename:
                    nit_p = config.DOWNLOADS_DIR / file.filename
                    if nit_p.exists():
                        c_path = out_dir / nit_p.name
                        shutil.copy(nit_p, c_path)
                        if c_path.suffix.lower() in [".docx", ".doc"]:
                            convert_to_pdf_if_docx(c_path)
                
                # Check for ATC
                if atc_path and atc_path.exists():
                    c_path = out_dir / atc_path.name
                    shutil.copy(atc_path, c_path)
                    if c_path.suffix.lower() in [".docx", ".doc"]:
                        convert_to_pdf_if_docx(c_path)
                else:
                    for ext in [".pdf", ".docx", ".doc"]:
                        p = config.DOWNLOADS_DIR / f"ATC_{extracted_tender_no}{ext}"
                        if p.exists():
                            c_path = out_dir / p.name
                            shutil.copy(p, c_path)
                            if c_path.suffix.lower() in [".docx", ".doc"]:
                                convert_to_pdf_if_docx(c_path)
                            break
            except Exception as e:
                logging.warning(f"Failed to copy original docs to out_dir: {e}")

            generated_files = []
            if out_dir and out_dir.exists():
                import urllib.parse
                for f_path in out_dir.iterdir():
                    if f_path.is_file() and not f_path.name.endswith(".json"):
                        f_url = f"/file?path={urllib.parse.quote(str(f_path.resolve()))}"
                        generated_files.append({"name": f_path.name, "url": f_url})
                generated_files.sort(key=lambda x: x["name"])

            return {
                "status": "success",
                "message": f"Document mapped and generated for {website}",
                "doc_url": "",
                "local_path": str(out_dir),
                "excel_url": f"/downloads/{saved_excel_path.name}" if saved_excel_path else None,
                "requirements": [],
                "generated_files": generated_files,
                "document_id": extracted_tender_no,
            }

        return {"status": "error", "message": f"Unknown step: {step}"}
        
    except Exception as e:
        logging.error(f"Doc Map error: {e}")
        return {"status": "error", "message": f"Failed to map doc: {e}"}

@router.post("/api/docs/extract_annexures")
async def extract_annexures(
    company: str = Form(...),
    document_id: str = Form(...),
    file: UploadFile = File(...)
):
    import re
    import time
    import uuid
    import json
    
    try:
        content = await file.read()
        file_path = config.DOWNLOADS_DIR / file.filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured.")
            
        def get_md_content(comp: str):
            if comp.lower() == "arkonic":
                path = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\GEM_DOCUMENT_LIBRARY.md")
                return path.read_text(encoding="utf-8") if path.exists() else ""
            elif comp.lower() in ["aquiant", "aquint"]:
                path = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\AQUIANT_DOCUMENT_LIBRARY.md")
                return path.read_text(encoding="utf-8") if path.exists() else ""
            return ""
            
        md_content = get_md_content(company)
        company_display = "Aquint Infratele India Pvt. Ltd." if company.lower() in ["aquint", "aquiant"] else "Arkonik Fibertech (I) Pvt. Ltd."
        
        # Load replacements for custom doc editing
        replacements = {}
        meta_path = config.DOWNLOADS_DIR / f"Filled_{document_id}" / "metadata.json"
        if meta_path.exists():
            try:
                replacements = json.loads(meta_path.read_text(encoding="utf-8"))
            except:
                pass
                
        uploaded_file = gemini_client.files.upload(file=str(file_path))
        
        import base64
        if company.lower() in ["aquint"]:
            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\aquint\bhargav sir2.jpeg")
            signatory_name = "Bhargav Kalaria"
            signatory_designation = "Managing Director"
        else:
            sig_file = Path(r"c:\Users\DELL\Desktop\Aquint com\dharam sir.jpeg")
            signatory_name = "DHARAMRAJSINH NARENDRASINH VAGHELA"
            signatory_designation = "Managing Director"
            
        img_src = ""
        if sig_file.exists():
            b64_sig = base64.b64encode(sig_file.read_bytes()).decode('utf-8')
            img_src = f"data:image/jpeg;base64,{b64_sig}"
            
        prompt = f"""
        You are an expert procurement assistant.
        The user has uploaded an ATC / Tender Document that contains various empty Annexure formats, declarations, or forms that need to be filled and submitted.
        
        Your task:
        1. Extract all the blank annexure forms/declarations from the uploaded document.
        2. Fill them out using the details of our company: {company_display}.
        
        Our Company Details (Document Library Rules):
        {md_content}
        
        Tender Metadata (Use if relevant for filling Tender No, Date, etc.):
        {json.dumps(replacements, indent=2) if replacements else "None"}
        
        Output EXACTLY AND ONLY HTML code. Do NOT wrap in ```html markdown tags. 
        Start with <html><body> and end with </body></html>.
        Format the annexures professionally with tables, bold text, and proper spacing so it looks exactly like the original forms but filled.
        Sign off with the company name and an Authorized Signatory block at the bottom of each form, exactly like this:
        <br><br><br>
        <img src="{img_src}" width="150" />
        <br>
        <b>{signatory_name}</b><br>
        <b>{signatory_designation}</b><br>
        <b>{company_display}</b>
        
        Use <div style="page-break-after: always;"></div> between different annexures.
        """
        
        FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash"]
        response = None
        for model_name in FALLBACK_MODELS:
            try:
                logging.info(f"Trying model: {model_name} for annexure extraction")
                response = gemini_client.models.generate_content(model=model_name, contents=[uploaded_file, prompt])
                logging.info(f"Success with model: {model_name}")
                break
            except Exception as e:
                logging.warning(f"Model {model_name} failed: {str(e)[:80]}")
                if model_name == FALLBACK_MODELS[-1]:
                    raise e
                time.sleep(2)
                
        html_content = response.text
        html_content = re.sub(r"^```(?:markdown|html)?\s*", "", html_content, flags=re.MULTILINE)
        html_content = re.sub(r"```\s*$", "", html_content, flags=re.MULTILINE)
        
        template_path = Path("backend/core/pdf_template.html")
        if not template_path.exists():
            template_path = Path("core/pdf_template.html")
            
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
        else:
            template = "<html><body>{{CONTENT}}</body></html>"
            
        full_html = template.replace("{{TENDER_NO}}", document_id).replace("{{TENDER_TITLE}}", "Extracted Annexures").replace("{{CONTENT}}", html_content)
        
        pdf_name = f"Extracted_Annexures_{uuid.uuid4().hex[:6]}.pdf"
        out_dir = config.DOWNLOADS_DIR / f"Filled_{document_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / pdf_name
        
        await asyncio.to_thread(generate_pdf_from_html, full_html, str(pdf_path))
        
        return {
            "status": "success",
            "message": "Annexures extracted successfully.",
            "name": "Extracted Annexures",
            "url": f"/file?path={urllib.parse.quote(str(pdf_path))}"
        }
    except Exception as e:
        logging.error(f"Extract Annexures error: {e}")
        return {"status": "error", "message": f"Failed to extract annexures: {e}"}

@router.post("/api/docs/create_decl")
async def create_declaration(request: Request):
    try:
        import base64
        from app.core.pdf_generator import generate_pdf_from_html
        form_data = await request.form()
        doc_id = form_data.get("document_id", "Unknown")
        company = form_data.get("company", "Aquint")
        prompt = form_data.get("prompt", "Create a standard declaration.")
        closing_date = form_data.get("closing_date", "Date: _________________")
        
        local_path_str = form_data.get("local_path")
        if local_path_str:
            import pathlib
            out_dir = pathlib.Path(local_path_str)
        else:
            out_dir = config.DOWNLOADS_DIR / f"Filled_{doc_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # Load signature
        if company.lower() in ["aquint"]:
            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\aquint\bhargav sir2.jpeg")
            signatory_name = "Bhargav Kalaria"
            signatory_designation = "Managing Director"
            company_full = " AQUINT INFRATELE INDIA PRIVATE LIMITED"
        else:
            sig_file = Path(r"c:\Users\DELL\Desktop\Aquint com\dharam sir.jpeg")
            signatory_name = "DHARAMRAJSINH NARENDRASINH VAGHELA"
            signatory_designation = "Managing Director"
            company_full = " ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
            
        img_src = ""
        if sig_file.exists():
            b64_sig = base64.b64encode(sig_file.read_bytes()).decode('utf-8')
            img_src = f"data:image/jpeg;base64,{b64_sig}"
            
        ai_prompt = f"""
        You are drafting a professional, legal declaration for a railway tender.
        Company: {company_full}
        Tender No: {doc_id}
        User Request: {prompt}
        
        Write the complete text of the declaration as beautiful HTML. 
        Do NOT include ```html markdown tags. Just pure HTML.
        Use standard fonts (sans-serif), proper margins, and line heights.
        Include a professional title, and the body text fulfilling the user's request.
        Do NOT include a signature block. The signature block will be appended programmatically.
        """
        
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        models = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3.6-flash', 'gemini-3.5-flash']
        response = None
        for model_name in models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=ai_prompt,
                )
                html_content = response.text.strip()
                break
            except Exception as e:
                err_str = str(e)
                print(f"Failed with {model_name}: {err_str[:100]}")
                if "429" not in err_str and "RESOURCE_EXHAUSTED" not in err_str:
                    import time; time.sleep(2)
        
        if not response:
            raise Exception("All fallback models exhausted for create_declaration.")
        if html_content.startswith("```html"):
            html_content = html_content[7:]
        if html_content.endswith("```"):
            html_content = html_content[:-3]
            
        # Append the signature block programmatically
        signature_html = f"""
        <br><br><br>
        <img src="{img_src}" width="150" />
        <br>
        <b>Name:</b> {signatory_name}<br>
        <b>Designation:</b> {signatory_designation}<br>
        <b>Date:</b> {closing_date}<br>
        <b>Company Name:</b> {company_full}
        """
        html_content += signature_html
            
        import uuid
        import asyncio
        name = f"Declaration_{uuid.uuid4().hex[:6]}.pdf"
        dummy_file = out_dir / name
        
        await asyncio.to_thread(generate_pdf_from_html, html_content, str(dummy_file))
        
        return {
            "status": "success",
            "name": name,
            "url": f"/file?path={urllib.parse.quote(str(dummy_file))}"
        }
    except Exception as e:
        logging.error(f"Error creating declaration: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/api/docs/merge")
async def merge_documents(request: Request):
    """
    Merges selected generated files and any custom uploaded files into a single ZIP.
    Expects dynamic form data:
    document_id: string
    req_{i}_docs: JSON string of selected internal URLs
    req_{i}_custom: UploadFile list for custom docs for this requirement
    """
    import json
    import os
    import zipfile
    
    try:
        form_data = await request.form()
        document_id = form_data.get("document_id")
        if not document_id:
            return {"status": "error", "message": "Missing document_id"}
            
        out_dir = config.DOWNLOADS_DIR / f"Merged_{document_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # Load replacements for custom doc editing
        replacements = {}
        meta_path = config.DOWNLOADS_DIR / f"Filled_{document_id}" / "metadata.json"
        if meta_path.exists():
            try:
                replacements = json.loads(meta_path.read_text(encoding="utf-8"))
            except:
                pass
                
        company_name_from_rep = replacements.get("{{COMPANY_NAME}}", "").lower()
        if "aquint" in company_name_from_rep or "aquiant" in company_name_from_rep:
            sig_file_path = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\aquint\bhargav sir2.jpeg")
        else:
            sig_file_path = Path(r"c:\Users\DELL\Desktop\Aquint com\dharam sir.jpeg")
        
        # GeM specific merging
        website = form_data.get("website", "ireps")
        
        import fitz
        if website == "gem":
            all_req_pdfs = []
            
            # Iterate over form fields to find requirements (same as IREPS)
            for key in form_data.keys():
                if key.startswith("req_") and key.endswith("_docs"):
                    req_idx = key.split("_")[1]
                    docs_json = form_data.get(key)
                    req_name = form_data.get(f"req_{req_idx}_name", "Requirement")
                    
                    import re
                    clean_name = re.sub(r'[^\w\s-]', '', req_name).strip()[:35]
                    if not clean_name:
                        clean_name = "Requirement"
                        
                    req_folder = out_dir / f"{int(req_idx):02d}_{clean_name}_Temp"
                    req_folder.mkdir(parents=True, exist_ok=True)
                    
                    pdfs_to_merge = []
                    
                    # 1. Gather selected mapped docs
                    if docs_json:
                        try:
                            urls = json.loads(docs_json)
                            for url in urls:
                                rel_path = url.split("/downloads/", 1)[-1]
                                src_path = config.DOWNLOADS_DIR / rel_path
                                if src_path.exists():
                                    dest = req_folder / src_path.name
                                    shutil.copy(src_path, dest)
                                    if dest.suffix.lower() == '.pdf':
                                        pdfs_to_merge.append(dest)
                        except Exception as e:
                            logging.error(f"Error gathering mapped docs: {e}")
                            
                    # 2. Gather custom uploaded docs
                    custom_files = form_data.getlist(f"req_{req_idx}_custom")
                    for c_file in custom_files:
                        if hasattr(c_file, "filename") and c_file.filename:
                            c_path = req_folder / f"{c_file.filename}"
                            c_content = await c_file.read()
                            c_path.write_bytes(c_content)
                            if c_path.suffix.lower() == '.pdf':
                                pdfs_to_merge.append(c_path)
                            elif c_path.suffix.lower() == '.docx':
                                fill_docx_template_global(str(c_path), str(c_path), replacements, signature_path=str(sig_file_path))
                                converted = convert_to_pdf_global(c_path)
                                if str(converted) != str(c_path) and Path(converted).exists():
                                    pdfs_to_merge.append(Path(converted))
                                    c_path.unlink(missing_ok=True)
                            elif c_path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                                img_pdf_path = req_folder / f"{c_path.stem}.pdf"
                                img_doc = fitz.open()
                                img_page = img_doc.new_page()
                                img_doc.insert_image(img_page, img_page.rect, filename=str(c_path))
                                img_doc.save(str(img_pdf_path))
                                img_doc.close()
                                pdfs_to_merge.append(img_pdf_path)
                                
                    # 3. Merge PDFs into a single file for this requirement
                    final_req_pdf = out_dir / f"{int(req_idx):02d}_{clean_name}.pdf"
                    if pdfs_to_merge:
                        merged_doc = fitz.open()
                        for pdf_path in pdfs_to_merge:
                            try:
                                doc_to_add = fitz.open(str(pdf_path))
                                merged_doc.insert_pdf(doc_to_add)
                                doc_to_add.close()
                            except Exception as e:
                                logging.error(f"Could not merge {pdf_path}: {e}")
                        if merged_doc.page_count > 0:
                            merged_doc.save(str(final_req_pdf))
                            all_req_pdfs.append(final_req_pdf)
                        merged_doc.close()
                        
                    # Cleanup temp folder
                    shutil.rmtree(req_folder, ignore_errors=True)

            # Pull Aquint Global docs
            filled_dir = config.DOWNLOADS_DIR / f"Filled_{document_id}"
            if filled_dir.exists():
                for f in filled_dir.glob("AquintGlobal_*.pdf"):
                    if f.is_file():
                        all_req_pdfs.append(f)
                        shutil.copy(f, out_dir / f.name)
                        
            # Merge all requirement PDFs into one final document
            if all_req_pdfs:
                all_req_pdfs.sort(key=lambda p: p.name) # Ensure sorted order
                final_merged_doc = fitz.open()
                for pdf_path in all_req_pdfs:
                    try:
                        doc_to_add = fitz.open(str(pdf_path))
                        final_merged_doc.insert_pdf(doc_to_add)
                        doc_to_add.close()
                    except Exception as e:
                        logging.error(f"Could not merge {pdf_path} into final doc: {e}")
                if final_merged_doc.page_count > 0:
                    final_merged_doc.save(str(out_dir / "Final_Merged_Document.pdf"))
                final_merged_doc.close()

            # Handle global extra files for GeM
            global_extras = form_data.getlist("global_extra")
            for g_file in global_extras:
                if hasattr(g_file, "filename") and g_file.filename:
                    g_path = out_dir / f"Extra_{g_file.filename}"
                    g_content = await g_file.read()
                    g_path.write_bytes(g_content)
                    
            final_folder_name = f"GeM_Merged_{document_id}"
            final_out_dir = config.DOWNLOADS_DIR / final_folder_name
            if final_out_dir.exists():
                shutil.rmtree(final_out_dir, ignore_errors=True)
            shutil.move(str(out_dir), str(final_out_dir))
            
            # Delete Filled folder as it is no longer necessary
            if filled_dir.exists():
                shutil.rmtree(filled_dir, ignore_errors=True)
                
            return {
                "status": "success",
                "message": "GeM Document Merged successfully.",
                "local_path": str(final_out_dir.resolve())
            }
            
        # IREPS specific merging
        # Iterate over form fields to find requirements
        for key in form_data.keys():
            if key.startswith("req_") and key.endswith("_docs"):
                req_idx = key.split("_")[1] # e.g. "1", "2"
                docs_json = form_data.get(key)
                
                req_name = form_data.get(f"req_{req_idx}_name", "Requirement")
                import re
                clean_name = re.sub(r'[^\w\s-]', '', req_name).strip()[:35]
                if not clean_name:
                    clean_name = "Requirement"
                
                req_folder = out_dir / f"{int(req_idx):02d}_{clean_name}_Temp"
                req_folder.mkdir(parents=True, exist_ok=True)
                
                pdfs_to_merge = []
                other_files = []
                
                # 1. Gather selected mapped docs
                if docs_json:
                    try:
                        urls = json.loads(docs_json)
                        for url in urls:
                            rel_path = url.split("/downloads/", 1)[-1]
                            src_path = config.DOWNLOADS_DIR / rel_path
                            if src_path.exists():
                                dest = req_folder / src_path.name
                                shutil.copy(src_path, dest)
                                if dest.suffix.lower() == '.pdf':
                                    pdfs_to_merge.append(dest)
                                else:
                                    other_files.append(dest)
                    except Exception as e:
                        logging.error(f"Error gathering mapped docs: {e}")
                
                # 2. Gather custom uploaded docs
                custom_files = form_data.getlist(f"req_{req_idx}_custom")
                for c_file in custom_files:
                    if hasattr(c_file, "filename") and c_file.filename:
                        c_path = req_folder / f"{c_file.filename}"
                        c_content = await c_file.read()
                        c_path.write_bytes(c_content)
                        if c_path.suffix.lower() == '.pdf':
                            pdfs_to_merge.append(c_path)
                        elif c_path.suffix.lower() == '.docx':
                            # Apply editing with extracted fields
                            fill_docx_template_global(str(c_path), str(c_path), replacements, signature_path=str(sig_file_path))
                            converted = convert_to_pdf_global(c_path)
                            if str(converted) != str(c_path) and Path(converted).exists():
                                pdfs_to_merge.append(Path(converted))
                                c_path.unlink(missing_ok=True) # delete the docx
                            else:
                                other_files.append(c_path)
                        elif c_path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                            # Convert image to PDF using fitz
                            img_pdf_path = req_folder / f"{c_path.stem}.pdf"
                            img_doc = fitz.open()
                            img_page = img_doc.new_page()
                            img_rect = img_page.rect
                            img_doc.insert_image(img_page, img_rect, filename=str(c_path))
                            img_doc.save(str(img_pdf_path))
                            img_doc.close()
                            pdfs_to_merge.append(img_pdf_path)
                        else:
                            other_files.append(c_path)
                            
                # 3. Merge PDFs into a single file
                final_req_pdf = out_dir / f"{int(req_idx):02d}_{clean_name}.pdf"
                if pdfs_to_merge:
                    merged_doc = fitz.open()
                    for pdf_path in pdfs_to_merge:
                        try:
                            doc_to_add = fitz.open(str(pdf_path))
                            merged_doc.insert_pdf(doc_to_add)
                            doc_to_add.close()
                        except Exception as e:
                            logging.error(f"Could not merge {pdf_path}: {e}")
                            other_files.append(pdf_path) # Fallback to separate file if merge fails
                    if merged_doc.page_count > 0:
                        merged_doc.save(str(final_req_pdf))
                    merged_doc.close()
                
                # 4. Move any non-PDF files (e.g. excels, word docs) to the main out_dir
                for f in other_files:
                    try:
                        shutil.copy(f, out_dir / f"{int(req_idx):02d}_{f.name}")
                    except:
                        pass
                        
                # Cleanup temp folder
                shutil.rmtree(req_folder, ignore_errors=True)
                
        # 5. Handle extra manual declarations
        extra_decls_json = form_data.get("extra_decls")
        if extra_decls_json:
            try:
                urls = json.loads(extra_decls_json)
                for url in urls:
                    rel_path = url.split("/downloads/", 1)[-1]
                    src_path = config.DOWNLOADS_DIR / rel_path
                    if src_path.exists():
                        shutil.copy(src_path, out_dir / f"Extra_Decl_{src_path.name}")
            except Exception as e:
                logging.error(f"Error gathering extra decls: {e}")
                
        # 6. Handle global extra files
        global_extras = form_data.getlist("global_extra")
        for g_file in global_extras:
            if hasattr(g_file, "filename") and g_file.filename:
                g_path = out_dir / f"Extra_{g_file.filename}"
                g_content = await g_file.read()
                g_path.write_bytes(g_content)
                
                # Check if it is a docx to process
                if g_path.suffix.lower() == '.docx':
                    try:
                        # Load signature path based on company
                        company = form_data.get("company", "Aquint")
                        if company.lower() in ["aquint"]:
                            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\aquint\bhargav sir2.jpeg")
                        else:
                            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\arkonic\dharam sir.jpeg")
                        
                        # Apply smart filler / template fill using smart_fill_docx from intake
                        import app.internal.intake.smart_filler as sf
                        import app.internal.intake.intake as intake
                        import app.core.config as config
                        
                        # Load user inputs from meta
                        user_inputs = {}
                        meta_path = config.DOWNLOADS_DIR / f"Filled_{document_id}" / "metadata.json"
                        if meta_path.exists():
                            import json
                            meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
                            user_inputs["place"] = meta_data.get("{{PLACE}}", "")
                            user_inputs["closing_date"] = meta_data.get("{{DATE}}", "")
                        
                        company_data = intake.load_company_data(company)
                        documents_dir = intake.get_docs_dir(company)
                        sf.smart_fill_docx(str(g_path), company_data, documents_dir, user_inputs)
                        
                        # Convert to PDF
                        converted = convert_to_pdf_global(g_path)
                        if str(converted) != str(g_path) and Path(converted).exists():
                            g_path.unlink(missing_ok=True)
                    except Exception as e:
                        logging.error(f"Error processing global extra docx: {e}")
                        
        # Create final destination folder path based on metadata
        meta_path = config.DOWNLOADS_DIR / f"Filled_{document_id}" / "metadata.json"
        
        # Default name if metadata isn't found
        final_folder_name = f"railway_Unknown_{document_id}"
        
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                place = meta.get("{{PLACE}}", "Unknown").replace("/", "_").replace("\\", "_").replace(" ", "")
                date_str = meta.get("{{DATE}}", "Date").replace("/", "_").replace("\\", "_").replace(" ", "")
                t_no = meta.get("{{TENDER_NO}}", document_id).replace("/", "_").replace("\\", "_").replace(" ", "")
                final_folder_name = f"railway_{place}_{date_str}_{t_no}"
            except Exception as e:
                logging.error(f"Error parsing metadata: {e}")
                
        final_out_dir = config.DOWNLOADS_DIR / final_folder_name
        
        # Remove it if it exists to cleanly recreate
        if final_out_dir.exists():
            shutil.rmtree(final_out_dir, ignore_errors=True)
            
        # Move everything from temp out_dir to final_out_dir
        shutil.move(str(out_dir), str(final_out_dir))
        
        # Pull the Aquint Global docs from the original Filled folder
        filled_dir = config.DOWNLOADS_DIR / f"Filled_{document_id}"
        if filled_dir.exists():
            import re
            for f in filled_dir.glob("AquintGlobal_*.pdf"):
                if f.is_file():
                    clean_name = f.name.replace("AquintGlobal_", "")
                    clean_name = re.sub(r'^\d+\.', '', clean_name).strip() # Remove "1." prefix
                    shutil.copy(f, final_out_dir / clean_name)
                    
        return {
            "status": "success",
            "message": "Local folder created successfully.",
            "local_path": str(final_out_dir.resolve())
        }
    except Exception as e:
        logging.error(f"Merge error: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/api/docs/process_gcc")
async def process_gcc(
    request: Request,
    gcc_file: UploadFile = File(...),
    needs_gcc_list: str = Form("[]")
):
    import json
    from app.internal.intake.gcc_parser import extract_form_from_gcc
    from app.core import config
    
    try:
        if not gcc_file or not gcc_file.filename:
            return {"success": False, "message": "No GCC file provided."}
            
        saved_path = config.DOWNLOADS_DIR / gcc_file.filename
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        content_bytes = await gcc_file.read()
        saved_path.write_bytes(content_bytes)
        
        needs_list = json.loads(needs_gcc_list)
        api_key = config.GEMINI_API_KEY
        
        extracted_results = {}
        failed_gcc = []
        
        for item in needs_list:
            row_key = item.get("row_key")
            line_text = item.get("line")
            extracted = extract_form_from_gcc(str(saved_path), line_text, api_key)
            if extracted:
                extracted_results[row_key] = extracted
            else:
                failed_gcc.append(item)
                
        return {
            "success": True, 
            "gcc_results": extracted_results,
            "failed_gcc": failed_gcc,
            "message": f"Processed GCC successfully. Extracted {len(extracted_results)} forms."
        }
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@router.post("/api/docs/finalize_ireps")
async def finalize_ireps(request: Request):
    """
    Finalizes the IREPS ZIP file by adding custom declarations and extra files.
    If no base documents exist (user skipped generation), creates the output dir on the fly.
    """
    import json
    import os
    import zipfile
    from pathlib import Path
    import logging
    import asyncio
    import app.core.config as config
    
    try:
        form_data = await request.form()
        document_id = form_data.get("document_id")
        local_path_str = form_data.get("local_path")
        company = form_data.get("company", "Aquint")
        
        if not document_id:
            return {"status": "error", "message": "Missing document_id"}
            
        if local_path_str:
            out_dir = Path(local_path_str)
        else:
            out_dir = config.DOWNLOADS_DIR / document_id
            
        # Create the output directory if it doesn't exist (user may have skipped doc generation)
        out_dir.mkdir(parents=True, exist_ok=True)
            
        # Load user inputs from metadata if available
        user_inputs = {}
        meta_path = config.DOWNLOADS_DIR / f"Filled_{document_id}" / "metadata.json"
        if meta_path.exists():
            try:
                meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
                user_inputs["place"] = meta_data.get("{{PLACE}}", "")
                user_inputs["closing_date"] = meta_data.get("{{DATE}}", "")
                user_inputs["tender_no"] = meta_data.get("{{TENDER_NO}}", "")
                user_inputs["tender_name"] = meta_data.get("{{TENDER_NAME}}", "")
                user_inputs["railway"] = meta_data.get("{{RAILWAY}}", "")
                user_inputs["issuing_authority"] = meta_data.get("{{ISSUING_AUTHORITY}}", "")
                user_inputs["days"] = meta_data.get("{{DAYS}}", "")
                user_inputs["bid_security_amount"] = meta_data.get("{{BID_SECURITY}}", "")
                user_inputs["execute_contract_days"] = meta_data.get("{{EXECUTE_CONTRACT_DAYS}}", "")
                user_inputs["commence_work_days"] = meta_data.get("{{COMMENCE_WORK_DAYS}}", "")
            except Exception as e:
                logging.warning(f"Could not load metadata: {e}")
                
        extra_decls_json = form_data.get("extra_decls")
        if extra_decls_json:
            try:
                decl_urls = json.loads(extra_decls_json)
                for url in decl_urls:
                    if "/file?path=" in url:
                        import urllib.parse
                        path_str = urllib.parse.unquote(url.split("/file?path=", 1)[-1])
                        src_path = Path(path_str)
                    else:
                        rel_path = url.split("/downloads/", 1)[-1]
                        src_path = config.DOWNLOADS_DIR / rel_path
                    if src_path.exists():
                        try:
                            shutil.copy(src_path, out_dir / src_path.name)
                        except shutil.SameFileError:
                            pass
            except Exception as e:
                logging.error(f"Error gathering extra declarations: {e}")
                
        global_extras = form_data.getlist("global_extra")
        for g_file in global_extras:
            if hasattr(g_file, "filename") and g_file.filename:
                g_path = out_dir / g_file.filename
                g_content = await g_file.read()
                g_path.write_bytes(g_content)
                
                # Process docx files: fill details + convert to PDF
                if g_path.suffix.lower() == '.docx':
                    try:
                        # Determine signature path based on company
                        if company.lower() in ["aquint"]:
                            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\aquint\bhargav sir2.jpeg")
                            user_inputs["signatory_name"] = "Bhargav Kalaria"
                            user_inputs["signatory_designation"] = "Managing Director"
                            user_inputs["company_name"] = "AQUIANT INFRATELE INDIA PRIVATE LIMITED"
                        else:
                            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\arkonic\dharam sir.jpeg")
                            user_inputs["signatory_name"] = "DHARAMRAJSINH NARENDRASINH VAGHELA"
                            user_inputs["signatory_designation"] = "Managing Director"
                            user_inputs["company_name"] = "ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
                        
                        # Load company data & apply smart fill in a thread (AI call)
                        import app.internal.intake.smart_filler as sf
                        import app.internal.intake.intake as intake
                        
                        company_data = await asyncio.to_thread(intake.load_company_data, company)
                        documents_dir = intake.get_docs_dir(company)
                        await asyncio.to_thread(sf.smart_fill_docx, str(g_path), company_data, documents_dir, user_inputs)
                        
                        # Convert to PDF using subprocess (avoids COM/threading issues)
                        def _convert_docx_to_pdf(docx_p):
                            import subprocess
                            pdf_p = str(docx_p).rsplit(".", 1)[0] + ".pdf"
                            try:
                                subprocess.run(
                                    ["docx2pdf", str(docx_p.resolve()), str(Path(pdf_p).resolve())],
                                    check=True, capture_output=True, timeout=120
                                )
                                if Path(pdf_p).exists():
                                    try:
                                        os.remove(str(docx_p))
                                    except Exception:
                                        pass
                                    return Path(pdf_p)
                            except Exception as e:
                                logging.error(f"docx2pdf failed for {docx_p}: {e}")
                            return docx_p
                        
                        converted = await asyncio.to_thread(_convert_docx_to_pdf, g_path)
                        logging.info(f"Converted extra docx: {g_path.name} -> {Path(converted).name}")
                    except Exception as e:
                        logging.error(f"Error processing global extra docx '{g_file.filename}': {e}")
                
        final_zip_path = config.DOWNLOADS_DIR / f"Mapped_Docs_{document_id}.zip"
        await asyncio.to_thread(
            shutil.make_archive,
            str(final_zip_path.with_suffix("")), "zip", str(out_dir)
        )
        
        return {
            "status": "success",
            "message": "Package finalized successfully.",
            "zip_url": f"/downloads/{final_zip_path.name}",
            "local_path": str(out_dir) if form_data.get("website", "ireps").lower() == "gem" else None
        }
    except Exception as e:
        logging.error(f"Error finalizing IREPS: {e}")
        return {"status": "error", "message": str(e)}

