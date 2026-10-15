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
    import re
    from docx.shared import Inches
    try:
        doc = docx.Document(template_path)
        place_val = "Ahmedabad"
        date_val = str(replacements.get("{{DATE}}") or replacements.get("{{CLOSING_DATE}}") or replacements.get("date") or "").strip()
        auth_val = str(replacements.get("{{ISSUING_AUTHORITY}}") or replacements.get("issuing_authority") or "").strip()
        rail_val = str(replacements.get("{{RAILWAY}}") or replacements.get("railway") or replacements.get("{{DIVISION}}") or "").strip()

        def document_has_signature(doc_obj):
            if len(doc_obj.inline_shapes) > 0:
                return True
            if len(doc_obj._element.xpath('.//w:drawing')) > 0:
                return True
            if len(doc_obj._element.xpath('.//w:pict')) > 0:
                return True
            if len(doc_obj._element.xpath('.//a:blip')) > 0:
                return True
            for rel in doc_obj.part.rels.values():
                if "image" in rel.target_ref.lower():
                    return True
            return False

        def safe_replace_text_in_p(p, replacer_fn):
            has_drawing = bool(p._element.xpath('.//w:drawing') or p._element.xpath('.//w:pict') or p._element.xpath('.//a:blip'))
            old_text = p.text
            new_text = replacer_fn(old_text)
            if old_text == new_text:
                return
            if not has_drawing:
                p.text = new_text
                return
            # Paragraph contains drawings/signature! NEVER touch or delete runs with drawings
            text_runs = [r for r in p.runs if not (r._element.xpath('.//w:drawing') or r._element.xpath('.//w:pict') or r._element.xpath('.//a:blip'))]
            if not text_runs:
                return
            text_runs[0].text = new_text
            for r in text_runs[1:]:
                r.text = ""

        def replacer(text):
            for k, v in replacements.items():
                if k in text:
                    text = text.replace(k, str(v))

            if place_val:
                text = re.sub(r'\{\{\s*place\s*\}\}', place_val, text, flags=re.IGNORECASE)
                text = re.sub(r'\[\s*place\s*\]', place_val, text, flags=re.IGNORECASE)
                text = re.sub(r'<\s*place\s*>', place_val, text, flags=re.IGNORECASE)
                text = re.sub(r'\[MISSING:\s*.*?(?:place|location).*?\]', place_val, text, flags=re.IGNORECASE)
                text = re.sub(r'(?i)(\bplace\s*:\s*)(?:(?!\bdate\b)[^\n\r\t])*(?=\bdate\b)', r'\g<1>' + place_val + '    ', text)
                text = re.sub(r'(?i)(\bplace\s*:\s*)(?:(?!\bdate\b)[^\n\r\t])*', r'\g<1>' + place_val, text)
                text = re.sub(r'(?i)(\bplace\s*:\s*)(?:' + place_val + r'\s*)+', r'Place: ' + place_val + ' ', text)

            if date_val:
                text = re.sub(r'\{\{\s*date\s*\}\}', date_val, text, flags=re.IGNORECASE)
                text = re.sub(r'\{\{\s*closing_date\s*\}\}', date_val, text, flags=re.IGNORECASE)
                text = re.sub(r'(?i)(\bdate\s*:\s*)[_]{2,}', r'\g<1>' + date_val, text)
                text = re.sub(r'(?i)(\bdate\s*:\s*)[\.]{2,}', r'\g<1>' + date_val, text)
                text = re.sub(r'(?i)(\bdate\s*)…+', r'\g<1>: ' + date_val, text)
                text = re.sub(r'(?i)(\bdated\s*:\s*)[_]{2,}', r'\g<1>' + date_val, text)
                text = re.sub(r'(?i)(\bdated\s*:\s*)[\.]{2,}', r'\g<1>' + date_val, text)
                text = re.sub(r'\[MISSING:\s*.*?(?:date|closing date).*?\]', date_val, text, flags=re.IGNORECASE)

            if auth_val:
                text = re.sub(r'\{\{\s*issuing_authority\s*\}\}', auth_val, text, flags=re.IGNORECASE)
                text = re.sub(r'\[MISSING:\s*.*?(?:issuing authority|authority|office).*?\]', auth_val, text, flags=re.IGNORECASE)

            if rail_val:
                text = re.sub(r'\{\{\s*railway\s*\}\}', rail_val, text, flags=re.IGNORECASE)
                text = re.sub(r'\{\{\s*divis[io]n\s*\}\}', rail_val, text, flags=re.IGNORECASE)
                text = re.sub(r'\[MISSING:\s*.*?(?:railway|division).*?\]', rail_val, text, flags=re.IGNORECASE)

            # Remove [Signature of ...] text placeholder
            text = re.sub(r'\[Signature\s*(?:of\s*[^\]]*)?\]', '', text, flags=re.IGNORECASE)

            # Remove any [MISSING: ...] tags for email, mobile, phone, telephone, fax, contact
            text = re.sub(r'\[MISSING:\s*.*?(?:email|mobile|phone|telephone|fax|contact).*?\]', '', text, flags=re.IGNORECASE)

            # Remove email and mobile lines in the signature / lower block
            text = re.sub(r'(?i)^\s*(?:email(?:\s*address|\s*id)?|mobile(?:\s*no\.?|\s*number|\s*num\.?)?|telephone(?:\s*no\.?|\s*number)?|phone(?:\s*no\.?|\s*number)?|contact(?:\s*no\.?|\s*number)?)\s*:.*$(?:\n)?', '', text, flags=re.MULTILINE)

            return text

        for p in doc.paragraphs:
            safe_replace_text_in_p(p, replacer)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        safe_replace_text_in_p(p, replacer)

        if signature_path and Path(signature_path).exists():
            if document_has_signature(doc):
                print(f"Document {output_path} already contains signature/image. Preserving existing signature without adding duplicate.")
            else:
                p = doc.add_paragraph()
                r = p.add_run()
                r.add_picture(str(signature_path), width=Inches(1.5))
        doc.save(output_path)
    except Exception as e:
        shutil.copy(template_path, output_path)

def save_tender_metadata(tender_no: str, user_inputs: dict, out_dir: Optional[Path] = None):
    if not tender_no:
        return
    import json as json_mod
    meta = {
        "{{COMPANY_NAME}}": user_inputs.get("company_name", ""),
        "{{DIVISION}}": user_inputs.get("railway", ""),
        "{{DIVISON}}": user_inputs.get("railway", ""),
        "{{RAILWAY}}": user_inputs.get("railway", ""),
        "{{TENDER_NO}}": user_inputs.get("tender_no", tender_no),
        "{{TENDER_NAME}}": user_inputs.get("tender_name", ""),
        "{{DATE}}": user_inputs.get("closing_date") or user_inputs.get("date", ""),
        "{{CLOSING_DATE}}": user_inputs.get("closing_date", ""),
        "{{DAYS}}": user_inputs.get("days", "30"),
        "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name", ""),
        "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation", ""),
        "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority", ""),
        "{{BID_SECURITY}}": user_inputs.get("bid_security_amount", ""),
        "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount", ""),
        "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days", "7"),
        "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days", "15"),
        **user_inputs,
        "{{PLACE}}": "Ahmedabad",
        "{{TENDER_PLACE}}": user_inputs.get("place", ""),
    }
    json_str = json_mod.dumps(meta, indent=2, ensure_ascii=False)
    paths_to_save = [
        config.DOWNLOADS_DIR / f"metadata_{tender_no}.json",
        config.DOWNLOADS_DIR / f"Filled_{tender_no}" / "metadata.json",
    ]
    if out_dir:
        paths_to_save.append(Path(out_dir) / "metadata.json")
    for p in paths_to_save:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json_str, encoding="utf-8")
        except Exception as e:
            logging.warning(f"Could not save metadata to {p}: {e}")

def load_tender_metadata(tender_no: str, out_dir: Optional[Path] = None) -> dict:
    import json as json_mod
    candidates = []
    if out_dir:
        candidates.append(Path(out_dir) / "metadata.json")
    if tender_no:
        candidates.append(config.DOWNLOADS_DIR / f"metadata_{tender_no}.json")
        candidates.append(config.DOWNLOADS_DIR / f"Filled_{tender_no}" / "metadata.json")
    for p in candidates:
        if p.exists():
            try:
                data = json_mod.loads(p.read_text(encoding="utf-8"))
                res = {}
                for k, v in data.items():
                    if k.startswith("{{") and k.endswith("}}"):
                        norm_k = k[2:-2].lower()
                        if norm_k == "bid_security": norm_k = "bid_security_amount"
                        res[norm_k] = str(v)
                    else:
                        res[k] = str(v)
                return res
            except Exception as e:
                logging.warning(f"Failed to read metadata from {p}: {e}")
    return {}

def extract_missing_nit_data(document_id: str, out_dir: Optional[Path] = None, user_inputs: dict = None) -> dict:
    if user_inputs is None:
        user_inputs = {}
    if user_inputs.get("issuing_authority") and user_inputs.get("railway") and user_inputs.get("tender_name"):
        return user_inputs
    nit_candidates = []
    if out_dir and Path(out_dir).exists():
        nit_candidates.extend(list(Path(out_dir).glob("*_NIT_*.pdf")))
        nit_candidates.extend(list(Path(out_dir).glob("*NIT*.pdf")))
        nit_candidates.extend(list(Path(out_dir).glob("*.pdf")))
    if document_id:
        nit_candidates.extend(list(config.DOWNLOADS_DIR.glob(f"*{document_id}*NIT*.pdf")))
        nit_candidates.extend(list(config.DOWNLOADS_DIR.glob(f"*{document_id}*.pdf")))
    for nit_p in nit_candidates:
        if nit_p.is_file() and ("nit" in nit_p.name.lower() or document_id in nit_p.name):
            try:
                from app.internal.intake.pdf_parser import parse_nit_pdf
                _, _, parsed = parse_nit_pdf(str(nit_p), config.GEMINI_API_KEY)
                if parsed:
                    for k in ["issuing_authority", "railway", "tender_no", "tender_name", "date", "closing_date", "days", "bid_security_amount"]:
                        if not user_inputs.get(k) and parsed.get(k):
                            user_inputs[k] = str(parsed[k])
                    if not user_inputs.get("place") and parsed.get("place"):
                        user_inputs["place"] = str(parsed["place"])
                if user_inputs.get("issuing_authority"):
                    break
            except Exception as e:
                logging.warning(f"Error extracting NIT data from candidate {nit_p}: {e}")
    if not user_inputs.get("issuing_authority") and user_inputs.get("railway"):
        user_inputs["issuing_authority"] = user_inputs["railway"]
    return user_inputs

router = APIRouter()

def download_and_unify_gem_atc(nit_pdf_path: Path, tender_no: str, orig_stem: str = "") -> tuple[Path | None, int]:
    """
    Scans a GeM NIT PDF for all buyer attachments (SOW, ATC, etc.),
    downloads each attachment, and unifies them into a single PDF: ATC_{tender_no}.pdf.
    Returns (unified_path, attachment_count).
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    import requests
    import logging
    import re
    import app.core.config as config

    if not nit_pdf_path.exists():
        return None, 0

    downloads_dir = config.DOWNLOADS_DIR
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # 1. Check if unified ATC already exists and is valid
    unified_path = downloads_dir / f"ATC_{tender_no}.pdf"
    clean_stem = nit_pdf_path.stem.replace('NIT_', '')
    clean_tender = tender_no.replace('NIT_', '')

    alt_candidates = [
        unified_path,
        downloads_dir / f"ATC_{clean_tender}.pdf",
        downloads_dir / f"ATC_{nit_pdf_path.stem}.pdf",
        downloads_dir / f"ATC_{clean_stem}.pdf",
    ]
    if orig_stem:
        clean_orig = orig_stem.replace('NIT_', '')
        alt_candidates.extend([
            downloads_dir / f"ATC_{orig_stem}.pdf",
            downloads_dir / f"ATC_{clean_orig}.pdf",
        ])

    # Add any ATC files in downloads_dir matching 5+ digit numbers in tender_no or stems
    search_str = f"{tender_no} {orig_stem} {nit_pdf_path.stem}"
    tokens = set(re.findall(r'\d{5,}', search_str))
    for tok in tokens:
        for f in downloads_dir.glob(f"ATC_*{tok}*.pdf"):
            if f not in alt_candidates:
                alt_candidates.append(f)

    # Also check significant keywords (e.g. VADODRA, AMBALA)
    words = [w for w in re.split(r'[^a-zA-Z0-9]+', search_str) if len(w) >= 5 and w.upper() not in ["TENDER", "REPORT", "DOWNLOADS", "GEMINI", "AQUIANT", "ARKONIC"]]
    for w in words:
        for f in downloads_dir.glob(f"ATC_*{w}*.pdf"):
            if f not in alt_candidates:
                alt_candidates.append(f)

    for cand in alt_candidates:
        if cand.exists() and cand.stat().st_size > 10000:
            try:
                t_doc = fitz.open(str(cand))
                p_cnt = len(t_doc)
                t_doc.close()
                if p_cnt > 0:
                    logging.info(f"Using existing unified ATC: {cand.name} ({p_cnt} pages)")
                    return cand, p_cnt
            except Exception:
                pass

    atc_uris = []
    try:
        doc = fitz.open(str(nit_pdf_path))
        for page in doc:
            for link in page.get_links():
                u = link.get("uri", "")
                if u and any(k in u.lower() for k in ["slafds", "get_atc_document", "atc", "sow"]):
                    if u not in atc_uris:
                        atc_uris.append(u)
    except Exception as e:
        logging.warning(f"Error parsing links from NIT {nit_pdf_path}: {e}")
        return None, 0

    if not atc_uris:
        return None, 0

    # Also check if any existing ATC file in downloads matches tokens found in the attachment URIs
    for uri in atc_uris:
        uri_tokens = set(re.findall(r'\d{5,}', uri))
        for tok in uri_tokens:
            for f in downloads_dir.glob(f"ATC_*{tok}*.pdf"):
                if f.exists() and f.stat().st_size > 10000:
                    try:
                        t_doc = fitz.open(str(f))
                        p_cnt = len(t_doc)
                        t_doc.close()
                        if p_cnt > 0:
                            logging.info(f"Using existing unified ATC matching URI token {tok}: {f.name} ({p_cnt} pages)")
                            return f, p_cnt
                    except Exception:
                        pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }

    downloaded_files = []

    for idx, uri in enumerate(atc_uris):
        ext = ".docx" if ".docx" in uri.lower() else ".pdf"
        part_candidates = [
            downloads_dir / f"ATC_{tender_no}_part_{idx+1}{ext}",
            downloads_dir / f"ATC_{clean_tender}_part_{idx+1}{ext}",
        ]
        if orig_stem:
            part_candidates.append(downloads_dir / f"ATC_{orig_stem}_part_{idx+1}{ext}")
            part_candidates.append(downloads_dir / f"ATC_{orig_stem.replace('NIT_', '')}_part_{idx+1}{ext}")

        cached_part = None
        for pc in part_candidates:
            if pc.exists() and pc.stat().st_size > 1000:
                cached_part = pc
                break

        if cached_part:
            logging.info(f"Reusing cached attachment part: {cached_part.name}")
            downloaded_files.append(cached_part)
            continue

        part_path = part_candidates[0]
        try:
            r = requests.get(uri, verify=False, timeout=(5, 12), headers=headers)
            if r.status_code == 200 and len(r.content) > 1000 and b"rejected" not in r.content.lower():
                part_path.write_bytes(r.content)
                downloaded_files.append(part_path)
            else:
                logging.warning(f"Download returned status {r.status_code} (bytes: {len(r.content)}) for {uri}")
        except Exception as e:
            logging.warning(f"Error downloading attachment from {uri}: {e}")

    # Fallback: if network downloads failed, check if any ATC file exists for this tender
    if not downloaded_files:
        for cand in downloads_dir.glob("ATC_*.pdf"):
            c_name = cand.name.lower()
            if any(t in c_name for t in tokens if len(t) >= 5) or any(w.lower() in c_name for w in words):
                if cand.is_file() and cand.stat().st_size > 10000:
                    logging.info(f"Using fallback matching ATC file: {cand.name}")
                    return cand, 1
        return None, 0

    if len(downloaded_files) == 1 and downloaded_files[0].suffix.lower() != ".pdf":
        return downloaded_files[0], 1

    unified_doc = fitz.open()
    total_merged = 0

    for f_path in downloaded_files:
        if f_path.suffix.lower() == ".pdf":
            try:
                sub_doc = fitz.open(str(f_path))
                unified_doc.insert_pdf(sub_doc)
                sub_doc.close()
                total_merged += 1
            except Exception as e:
                logging.warning(f"Error merging {f_path}: {e}")

    if total_merged > 0:
        unified_doc.save(str(unified_path))
        unified_doc.close()
        if orig_stem and orig_stem != tender_no:
            try:
                import shutil
                shutil.copyfile(unified_path, downloads_dir / f"ATC_{orig_stem}.pdf")
            except Exception:
                pass
        return unified_path, len(downloaded_files)
    elif downloaded_files:
        return downloaded_files[0], len(downloaded_files)

    return None, 0

@router.post("/api/docs/fetch_atc")
async def fetch_gem_atc(
    file: UploadFile = File(...),
    document_id: str | None = Form(None)
):
    import re
    import app.core.config as config
    try:
        content = await file.read()
        tender_name_stem = (file.filename or "gem_doc").replace(".pdf", "")
        clean_name = re.sub(r'[\\/*?:"<>|]', "_", str(document_id or tender_name_stem))
        
        saved_nit = config.DOWNLOADS_DIR / f"NIT_{clean_name}.pdf"
        saved_nit.write_bytes(content)
        
        atc_path, count = download_and_unify_gem_atc(saved_nit, clean_name, orig_stem=tender_name_stem)
        if atc_path and atc_path.exists():
            return {
                "status": "success",
                "atc_found": True,
                "atc_filename": atc_path.name,
                "attachments_count": count,
                "message": f"Fetched {count} buyer attachment(s) and unified into {atc_path.name}."
            }
        else:
            return {
                "status": "success",
                "atc_found": False,
                "atc_filename": None,
                "attachments_count": 0,
                "message": "No buyer attachments found in NIT."
            }
    except Exception as e:
        return {"status": "error", "message": f"Error fetching ATC: {e}"}

@router.post("/api/docs/map")
async def map_document(
    request: Request,
    company: str = Form(...),
    website: str = Form("ireps"),
    step: str = Form("generate"),
    document_id: str | None = Form(None),
    file: UploadFile = File(None),
    atc_file: UploadFile | None = File(None),
    atc_file_name: str | None = Form(None),
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
    declarations_data: str | None = Form(None),
    doc_selections_data: str | None = Form(None),
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

        def _clean_field(v, default=None):
            if v is None:
                return default
            if hasattr(v, "__class__") and "Form" in v.__class__.__name__:
                return default
            return str(v)

        company = _clean_field(company, "Arkonic")
        website = _clean_field(website, "ireps")
        step = _clean_field(step, "generate")
        document_id = _clean_field(document_id, None)
        atc_file_name = _clean_field(atc_file_name, None)
        tender_name = _clean_field(tender_name, None)
        place = _clean_field(place, None)
        railway = _clean_field(railway, None)
        signatory_name = _clean_field(signatory_name, None)
        signatory_designation = _clean_field(signatory_designation, None)
        date = _clean_field(date, None)
        days = _clean_field(days, None)
        issuing_authority = _clean_field(issuing_authority, None)
        bid_security_amount = _clean_field(bid_security_amount, None)
        execute_contract_days = _clean_field(execute_contract_days, None)
        commence_work_days = _clean_field(commence_work_days, None)
        closing_date = _clean_field(closing_date, None)
        merges_data = _clean_field(merges_data, None)
        gcc_results_data = _clean_field(gcc_results_data, None)
        declarations_data = _clean_field(declarations_data, None)
        doc_selections_data = _clean_field(doc_selections_data, None)

        if not hasattr(file, "filename") or not hasattr(file, "read"):
            file = None
        if not hasattr(atc_file, "filename") or not hasattr(atc_file, "read"):
            atc_file = None

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
            company_display = "AQUINT INFRATELE INDIA PRIVATE LIMITED"
            signatory_name_def = "BHARGAV NARENDRABHAI PRAJAPATI"
            signatory_designation_def = "Director"
        else:
            company_display = "ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
            signatory_name_def = "DHARAMRAJSINH NARENDRASINH VAGHELA"
            signatory_designation_def = "Managing Director"

        if website.lower() == "ireps":
            # ── IREPS PARSING ──
            if saved_nit_path and saved_nit_path.exists() and step == "analyze":
                t_no, pdf_reqs, parsed_data = parse_nit_pdf(str(saved_nit_path), api_key)
                if t_no: extracted_tender_no = t_no
                nit_data = parsed_data or {}
                
            if not extracted_tender_no and file and file.filename:
                extracted_tender_no = (file.filename or "").replace(".pdf", "")

            if not extracted_tender_no:
                return {"status": "error", "message": "Tender Number could not be found. Please enter it manually."}
                
            import re
            extracted_tender_no = re.sub(r'[\\/*?:"<>|]', "_", str(extracted_tender_no))

            if pdf_reqs:
                compulsory_reqs = [
                    "certificate to be submitted",
                    "declaration form for relative",
                    "declaration for retired railway employees",
                    "power of attorney board resolution",
                    "statement of deviations"
                ]
                for c in compulsory_reqs:
                    if not any(c in str(r).lower() for r in pdf_reqs):
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

        elif website.lower() == "nprocure":
            # ── NPROCURE PARSING ──
            if saved_nit_path and saved_nit_path.exists() and step == "analyze":
                from app.internal.intake.pdf_parser import parse_nprocure_pdf
                t_no, pdf_reqs, parsed_data = parse_nprocure_pdf(str(saved_nit_path), api_key)
                if t_no: extracted_tender_no = t_no
                nit_data = parsed_data or {}

            if not extracted_tender_no and file and file.filename:
                extracted_tender_no = (file.filename or "").replace(".pdf", "")

            if not extracted_tender_no:
                return {"status": "error", "message": "Tender Number could not be found. Please enter it manually."}
                
            import re
            extracted_tender_no = re.sub(r'[\\/*?:"<>|]', "_", str(extracted_tender_no))

            saved_excel_path = config.DOWNLOADS_DIR / f"Generated_Requirements_{extracted_tender_no}_nProcure.xlsx"
            h_row = d_col = r_col = s_col = u_col = n_col = None
            if pdf_reqs:
                excel_reqs, h_row, d_col, r_col, s_col, u_col, n_col = create_excel_from_requirements(str(saved_excel_path), pdf_reqs)
            elif saved_excel_path.exists():
                try:
                    excel_reqs, h_row, d_col, r_col, s_col, u_col, n_col = parse_excel_requirements(str(saved_excel_path))
                except Exception as e:
                    return {"status": "error", "message": f"Excel parsing error: {e}"}
            else:
                return {"status": "error", "message": "No requirements found in the nProcure document. Please ensure the document contains a doc checklist or EOI section."}
                
        else:
            # ── GEM PARSING ──
            if atc_file and hasattr(atc_file, "filename") and atc_file.filename and hasattr(atc_file, "read"):
                atc_content = await atc_file.read()
                atc_path = config.DOWNLOADS_DIR / atc_file.filename
                atc_path.write_bytes(atc_content)
            elif atc_file_name:
                cand = config.DOWNLOADS_DIR / atc_file_name
                if cand.exists():
                    atc_path = cand
                elif saved_nit_path and (saved_nit_path.parent / atc_file_name).exists():
                    atc_path = saved_nit_path.parent / atc_file_name
                
            if not extracted_tender_no and file and hasattr(file, "filename") and file.filename:
                extracted_tender_no = (file.filename or "").replace(".pdf", "")
            if not extracted_tender_no:
                return {"status": "error", "message": "Tender Number could not be found."}
                
            import re
            extracted_tender_no = re.sub(r'[\\/*?:"<>|]', "_", str(extracted_tender_no))

            # Attempt automatic ATC fetch & unify if not yet provided
            if not atc_path and saved_nit_path:
                try:
                    file_stem = file.filename.replace(".pdf", "") if file and file.filename else ""
                    unified_atc, count = download_and_unify_gem_atc(saved_nit_path, extracted_tender_no, orig_stem=file_stem)
                    if unified_atc and unified_atc.exists():
                        atc_path = unified_atc
                except Exception as e:
                    logging.warning(f"ATC fetch error: {e}")
                
            # Finding saved_excel_path across possible stem aliases
            file_stem = file.filename.replace('.pdf', '') if file and file.filename else ""
            excel_candidates = [
                config.DOWNLOADS_DIR / f"Generated_Requirements_{extracted_tender_no}_GeM.xlsx",
                config.DOWNLOADS_DIR / f"Generated_Requirements_{file_stem}_GeM.xlsx" if file_stem else None,
                config.DOWNLOADS_DIR / f"Generated_Requirements_{saved_nit_path.stem}_GeM.xlsx" if saved_nit_path else None
            ]
            saved_excel_path = None
            for ec in excel_candidates:
                if ec and ec.exists():
                    saved_excel_path = ec
                    break
            
            if not saved_excel_path:
                search_key = f"{extracted_tender_no} {file_stem} {saved_nit_path.stem if saved_nit_path else ''}"
                tokens = re.findall(r'\d{5,}', search_key)
                for tok in tokens:
                    matches = list(config.DOWNLOADS_DIR.glob(f"Generated_Requirements_*{tok}*_GeM.xlsx"))
                    if matches:
                        saved_excel_path = matches[0]
                        break
            
            if not saved_excel_path:
                saved_excel_path = config.DOWNLOADS_DIR / f"Generated_Requirements_{extracted_tender_no}_GeM.xlsx"
            
            saved_json_path = saved_excel_path.with_suffix(".json")
            h_row = d_col = r_col = s_col = u_col = n_col = None

            # Invalidate stale generic cache ONLY during step == "analyze"
            if step == "analyze" and saved_excel_path.exists() and atc_path and atc_path.exists():
                try:
                    if saved_json_path.exists():
                        cached_items = json_mod.loads(saved_json_path.read_text(encoding="utf-8"))
                        cached_lines = [str(item.get("name", "")).lower() for item in cached_items]
                        if any("requested in atc" in cl for cl in cached_lines) or len(cached_items) <= 5:
                            logging.info("Invalidating stale generic GeM cache in favor of full ATC checklist...")
                            saved_excel_path.unlink(missing_ok=True)
                            saved_json_path.unlink(missing_ok=True)
                except Exception as e:
                    logging.warning(f"Error checking cache staleness: {e}")
            
            if (step == "analyze" and not cached_llm_json) or not saved_excel_path.exists():
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
                        atc_text = atc_text[:300000]
                    except Exception: pass
                if len(atc_text.strip()) < 100:
                    atc_text = ""

                catalog = load_catalog("gem")
                catalog_summary = [f"ID: {c['id']} | Hint: {c.get('filename_hint', '')}" for c in catalog]
                catalog_str = "\n".join(catalog_summary)
                
                prompt = f"""
                You are an expert procurement assistant.
                We are preparing a bid for the company '{company_display}'.
                Read the attached Tender Document (NIT) text{" and the ATC document text" if atc_text else ""} and create a strict DOCUMENT MAPPING table.
                
                {"IMPORTANT: I have provided the ATC document. There is usually a clear 'List of documents to be submitted in GeM portal', 'Section-10 Checklist of documents to be submitted by the bidder', or 'General Parameter Checklist' table. You MUST extract this checklist EXACTLY as it appears. If a checklist table is available, extract every item verbatim. If no checklist table is available, extract all document requirements, compliance certificates, and documentary evidence requested under 'Buyer Added Bid Specific ATC' or 'Buyer Added Bid Specific terms and conditions'." if atc_text else "Extract all document requirements, compliance certificates, and documentary evidence requested in the NIT text (especially under 'Buyer Added Bid Specific ATC' or 'Buyer Added Bid Specific terms and conditions' or 'Documentary Evidence to be submitted') exactly as they appear."}
                
                CATALOG:
                {catalog_str}
                
                FINALLY, output a JSON block wrapped in ```json ... ``` with exactly three keys:
                1. "extracted_fields": Dictionary with:
                    "{{{{TENDER_NO}}}}": "...",
                    "{{{{TENDER_NAME}}}}": "...",
                    "{{{{PLACE}}}}": "Tender location, city, work location, or consignee/buyer office location as given in the NIT",
                    "{{{{DATE}}}}": "...",
                    "{{{{CLOSING_DATE}}}}": "...",
                    "{{{{ISSUING_AUTHORITY}}}}": "...",
                    "{{{{DAYS}}}}": "Bid Offer Validity in Days (e.g. 180, 150, 90)",
                    "{{{{BID_SECURITY_AMOUNT}}}}": "EMD Amount if required, or 'Not Required' / '0' / 'Exempted'",
                    "{{{{EXECUTE_CONTRACT_DAYS}}}}": "7",
                    "{{{{COMMENCE_WORK_DAYS}}}}": "15"
                2. "missing_fields": List of string questions for blanks to fill in docs.
                3. "requirements": List of objects:
                    [ {{ "description": "EXACT word-for-word text from the document. DO NOT change, rephrase, or summarize it.", "mapped_ids": ["ID1", "ID2"] }} ]
                    
                CRITICAL RULES:
                - If a checklist table exists, use it!
                - If no checklist table exists, extract all document submission clauses or compliance certificates from the text.
                - DO NOT merge multiple checklist items into one.
                - DO NOT rephrase descriptions. Copy them word-for-word exactly as they appear.
                - If an annexure/format for a requirement is EXPLICITLY PROVIDED inside the ATC document text (e.g. Annexure-I for Rule 175 Code of Integrity, Annexure-J for Rule 151 Debarment, Annexure-A, B, C, D, E, F, G, H, etc.), do NOT map it to our catalog (leave "mapped_ids": []). We will extract the exact format directly from the ATC to preserve its precise wording.
                - ONLY map to our catalog IDs if the format is NOT provided in the ATC document.
                - When a requirement asks for "Engineering Organisation Available", "Technical Manpower", or "Detailed list with name, age and designation of qualified experienced personnel", map to ["ENGINEERING_ORGANISATION"].

                
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
                excel_reqs = []
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

                    # If AI returned no requirements, try to extract buyer clauses from NIT text
                    if not gem_reqs:
                        nit_buyer_matches = re.findall(r'(?:[0-9]+\.|\*|\-)\s*([^\n\r]+(?:submitted|certificate|document|evidence|compliance|experience)[^\n\r]+)', nit_text, re.I)
                        for m in nit_buyer_matches[:10]:
                            clean_m = m.strip()
                            if len(clean_m) > 15:
                                gem_reqs.append({"line": clean_m, "canonical_ids": ["CERTIFICATE_TO_BE_SUBMITTED"]})

                    if not gem_reqs and saved_excel_path.exists():
                        try:
                            excel_reqs, h_row, d_col, r_col, s_col, u_col, n_col = parse_excel_requirements(str(saved_excel_path))
                        except Exception:
                            excel_reqs = []

                    if gem_reqs:
                        gem_strings = [r["line"] for r in gem_reqs]
                        _, h_row, d_col, r_col, s_col, u_col, n_col = create_excel_from_requirements(str(saved_excel_path), gem_strings)
                        
                        excel_reqs = [{"row": i+2, "name": r["line"], "canonical_ids": r.get("canonical_ids", [])} for i, r in enumerate(gem_reqs)]
                        
                        # Save canonical_ids to JSON so step=generate can read them
                        gem_json_path = saved_excel_path.with_suffix(".json")
                        gem_json_path.write_text(json_mod.dumps(excel_reqs), encoding="utf-8")
                    elif not excel_reqs:
                        default_lines = [
                            "Certificate from Bidder for compliance of Buyer Added ATC",
                            "Documentary evidence for office location and eligibility"
                        ]
                        _, h_row, d_col, r_col, s_col, u_col, n_col = create_excel_from_requirements(str(saved_excel_path), default_lines)
                        excel_reqs = [{"row": i+2, "name": line, "canonical_ids": ["CERTIFICATE_TO_BE_SUBMITTED"]} for i, line in enumerate(default_lines)]
                        gem_json_path = saved_excel_path.with_suffix(".json")
                        gem_json_path.write_text(json_mod.dumps(excel_reqs), encoding="utf-8")
                        
                    nit_data["tender_no"] = data.get("extracted_fields", {}).get("{{TENDER_NO}}", "")
                    nit_data["tender_name"] = data.get("extracted_fields", {}).get("{{TENDER_NAME}}", "")
                    extracted_place = data.get("extracted_fields", {}).get("{{PLACE}}") or data.get("extracted_fields", {}).get("place") or ""
                    nit_data["place"] = extracted_place.strip()
                    nit_data["date"] = data.get("extracted_fields", {}).get("{{DATE}}", "")
                    nit_data["closing_date"] = data.get("extracted_fields", {}).get("{{CLOSING_DATE}}", "")
                    nit_data["issuing_authority"] = data.get("extracted_fields", {}).get("{{ISSUING_AUTHORITY}}", "")
                    nit_data["days"] = data.get("extracted_fields", {}).get("{{DAYS}}", "")
                    nit_data["bid_security_amount"] = data.get("extracted_fields", {}).get("{{BID_SECURITY_AMOUNT}}", "")
                    nit_data["execute_contract_days"] = data.get("extracted_fields", {}).get("{{EXECUTE_CONTRACT_DAYS}}", "")
                    nit_data["commence_work_days"] = data.get("extracted_fields", {}).get("{{COMMENCE_WORK_DAYS}}", "")

                    # Robust regex fallbacks from nit_text
                    if not nit_data.get("place"):
                        m_gem_plc = re.search(r'(?:Consignee|Officer\s+and\s+Quantity|Consignee\s+Detail)[\s\S]{0,200}?(?:Address|City|Location)\s*[:\/\n\s]*([A-Za-z\s]{3,30}?)(?=[,\n\r\(\.]|$)', nit_text, re.IGNORECASE)
                        if m_gem_plc:
                            cand_p = m_gem_plc.group(1).strip()
                            if cand_p.lower() not in ["n/a", "not applicable", "india"]:
                                nit_data["place"] = cand_p
                    
                    # Robust regex fallbacks from nit_text
                    if not nit_data.get("days"):
                        m_val = re.search(r'(?:Bid\s+Offer\s+Validity|वैधता)[\s\S]{0,120}?(\d+)\s*(?:\(Days\)|\(दिन\)|Days|दिन)?', nit_text, re.I)
                        if m_val:
                            nit_data["days"] = m_val.group(1).strip()

                    if not nit_data.get("bid_security_amount"):
                        if re.search(r'(?:EMD\s*Detail|ईएमडी\s*विवरण)[\s\S]{0,100}?(?:Required|आवश्यकता)\s*[:\/\n\s]*No\b', nit_text, re.I):
                            nit_data["bid_security_amount"] = "Not Required"
                        else:
                            m_emd = re.search(r'(?:EMD\s*Amount|ईएमडी\s*राशि)\s*[:\/\n\s]*([0-9,]+)', nit_text, re.I)
                            if m_emd:
                                nit_data["bid_security_amount"] = m_emd.group(1).replace(",", "").strip()
                            elif re.search(r'EMD\s*EXEMPTION', nit_text, re.I):
                                nit_data["bid_security_amount"] = "Exempted"

                    if not nit_data.get("execute_contract_days"):
                        nit_data["execute_contract_days"] = "7"
                    if not nit_data.get("commence_work_days"):
                        nit_data["commence_work_days"] = "15"
                    
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
        if website.lower() == "ireps":
            user_inputs["railway"] = get_val(railway, nit_data.get("railway"))

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

        user_declarations = {}
        if declarations_data:
            try: user_declarations = json_mod.loads(declarations_data)
            except Exception: pass

        user_doc_selections = {}
        if doc_selections_data:
            try: user_doc_selections = json_mod.loads(doc_selections_data)
            except Exception: pass

        # ── STEP: analyze (dry-run) ──
        if step == "analyze":
            extra_pdfs = {}
            if atc_path and atc_path.exists():
                extra_pdfs["atc_path"] = str(atc_path)
                
            results, missing_fields, proposed_merges, needs_gcc_list, needs_letterhead = process_requirements(
                reqs, extracted_tender_no, catalog,
                is_excel=True, dry_run=True,
                user_inputs=user_inputs, user_merges=user_merges,
                combine_flags={}, portal_type=website.lower(),
                extra_pdfs=extra_pdfs,
                user_declarations=user_declarations,
                user_doc_selections=user_doc_selections
            )
            missing_fields_set = set(missing_fields) if isinstance(missing_fields, (list, tuple, set)) else set()
            if not user_inputs.get("issuing_authority"):
                if user_inputs.get("railway"):
                    user_inputs["issuing_authority"] = user_inputs["railway"]
                else:
                    missing_fields_set.add("issuing_authority")

            if not user_inputs.get("place"):
                missing_fields_set.add("place")

            if website.lower() in ["gem", "nprocure", "iti"]:
                missing_fields_set.discard("railway")
            if website.lower() == "nprocure":
                if not user_inputs.get("place"):
                    user_inputs["place"] = "Ahmedabad"
                    missing_fields_set.discard("place")

            missing_fields = sorted(list(missing_fields_set))

            save_tender_metadata(extracted_tender_no, user_inputs)
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
                portal_type=website.lower(),
                user_declarations=user_declarations,
                user_doc_selections=user_doc_selections
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

            # Persist full metadata to folder
            save_tender_metadata(extracted_tender_no, user_inputs, out_dir)

            return {
                "status": "success",
                "message": f"Document mapped and generated for {website}",
                "doc_url": "",
                "local_path": str(out_dir),
                "excel_url": f"/downloads/{saved_excel_path.name}" if saved_excel_path else None,
                "requirements": [],
                "generated_files": generated_files,
                "document_id": extracted_tender_no,
                "extracted_data": user_inputs,
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
            signatory_name = "BHARGAV NARENDRABHAI PRAJAPATI"
            signatory_designation = "Director"
            company_full = "AQUINT INFRATELE INDIA PRIVATE LIMITED"
        else:
            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\arkonic\dharam sir.jpeg")
            if not sig_file.exists():
                sig_file = Path(r"c:\Users\DELL\Desktop\Aquint com\dharam sir.jpeg")
            signatory_name = "DHARAMRAJSINH NARENDRASINH VAGHELA"
            signatory_designation = "Managing Director"
            company_full = "ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
            
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
        CRITICAL: Do NOT write "(To be submitted on the Letterhead of the Bidder)" or any similar instructions at the top. Just start with the title.
        CRITICAL: Do NOT use <hr> tags, horizontal lines, borders, or any fancy web styling. The output must look like a standard, formal, typed legal document.
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
        <div style="text-align: right; margin-top: 30px; font-size: 13px; line-height: 1.4;">
            <div style="display: inline-block; text-align: left;">
                <img src="{img_src}" width="120" style="margin-bottom: 5px; display: block;" />
                <b>Name:</b> {signatory_name}<br>
                <b>Designation:</b> {signatory_designation}<br>
                <b>Date:</b> {closing_date}<br>
                <b>Company:</b> {company_full.strip()}
            </div>
        </div>
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

@router.post("/api/docs/create_requirement_declaration")
async def create_requirement_declaration(request: Request):
    """
    Creates a formal legal declaration PDF for an IREPS requirement directly in Step 2.
    Analyzes both the requirement description and any user-written text / clauses.
    """
    try:
        import urllib.parse
        import re
        import asyncio
        from app.internal.intake.declaration_generator import generate_declaration_for_requirement
        
        form_data = await request.form()
        row_key = form_data.get("row_key", "0")
        description = form_data.get("description", "").strip()
        user_text = form_data.get("user_text", "").strip()
        company = form_data.get("company", "Aquint")
        doc_id = form_data.get("document_id", "Unknown")
        
        local_path_str = form_data.get("local_path")
        if local_path_str and Path(local_path_str).exists():
            out_dir = Path(local_path_str)
        else:
            out_dir = config.DOWNLOADS_DIR / f"Filled_{doc_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        user_inputs = load_tender_metadata(doc_id, out_dir)
        user_inputs = extract_missing_nit_data(doc_id, out_dir, user_inputs)
        
        for f in [
            "tender_name", "railway", "issuing_authority", "signatory_name",
            "signatory_designation", "closing_date", "date", "place",
            "bid_security_amount", "days", "execute_contract_days", "commence_work_days"
        ]:
            v = form_data.get(f)
            if v:
                user_inputs[f] = v
                
        clean_desc = re.sub(r'[\\/*?:"<>|]', '', description)[:30].strip() or f"Req_{row_key}"
        decl_filename = f"Declaration_Req_{row_key}_{clean_desc}.pdf"
        output_pdf_path = out_dir / decl_filename
        
        await asyncio.to_thread(
            generate_declaration_for_requirement,
            description=description,
            user_custom_text=user_text,
            company_name=company,
            tender_no=doc_id,
            user_inputs=user_inputs,
            output_pdf_path=output_pdf_path
        )
        
        if not output_pdf_path.exists():
            raise Exception("Declaration PDF was not generated.")
            
        return {
            "status": "success",
            "row_key": row_key,
            "name": decl_filename,
            "url": f"/file?path={urllib.parse.quote(str(output_pdf_path.resolve()))}",
            "pdf_path": str(output_pdf_path.resolve())
        }
    except Exception as e:
        logging.error(f"Error creating requirement declaration: {e}")
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
            
        website = form_data.get("website", "ireps")
        base_mapping_dir = Path(r"C:\Users\DELL\Downloads\Doc mapping")
        out_dir = base_mapping_dir / website.lower() / f"Merged_{document_id}"
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
                        
                        # Load user inputs from form_data and metadata
                        user_inputs = {}
                        for f in [
                            "issuing_authority", "railway", "tender_no", "tender_name",
                            "place", "date", "closing_date", "days", "bid_security_amount",
                            "execute_contract_days", "commence_work_days",
                            "signatory_name", "signatory_designation", "company_name"
                        ]:
                            val = form_data.get(f)
                            if val and str(val).strip():
                                user_inputs[f] = str(val).strip()

                        saved_meta = load_tender_metadata(document_id, out_dir)
                        for k, v in saved_meta.items():
                            if not user_inputs.get(k) and v:
                                user_inputs[k] = v

                        user_inputs = extract_missing_nit_data(document_id, out_dir, user_inputs)
                        
                        company_data = intake.load_company_data(company)
                        documents_dir = intake.get_docs_dir(company)

                        c_comp = company_data.get("company", {})
                        c_sig = company_data.get("signatory", {})
                        c_stat = company_data.get("statutory", {})
                        replacements = {
                            "{{COMPANY_NAME}}": user_inputs.get("company_name") or c_comp.get("legal_name", ""),
                            "{{DIVISION}}": user_inputs.get("railway", ""),
                            "{{DIVISON}}": user_inputs.get("railway", ""),
                            "{{RAILWAY}}": user_inputs.get("railway", ""),
                            "{{TENDER_NO}}": user_inputs.get("tender_no", document_id),
                            "{{TENDER_NAME}}": user_inputs.get("tender_name", ""),
                            "{{PLACE}}": "Ahmedabad",
                            "{{DATE}}": user_inputs.get("closing_date") or user_inputs.get("date", ""),
                            "{{DAYS}}": user_inputs.get("days", "30"),
                            "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name") or c_sig.get("name", ""),
                            "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation") or c_sig.get("designation", ""),
                            "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority") or user_inputs.get("railway", ""),
                            "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount", ""),
                            "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days", "7"),
                            "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days", "15"),
                            "{{GSTIN}}": c_stat.get("gstin", ""),
                            "{{PAN}}": c_stat.get("pan", ""),
                        }
                        fill_docx_template_global(g_path, g_path, replacements, signature_path=str(sig_file) if sig_file and sig_file.exists() else None)
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
                place = (meta.get("place") or meta.get("tender_place") or meta.get("{{TENDER_PLACE}}") or meta.get("{{PLACE}}") or "Unknown").replace("/", "_").replace("\\", "_").replace(" ", "")
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
    gcc_file: UploadFile | None = File(None),
    gcc_file_name: str | None = Form(None),
    needs_gcc_list: str = Form("[]")
):
    import json
    from app.internal.intake.gcc_parser import extract_form_from_gcc
    from app.core import config
    
    try:
        saved_path = None
        if gcc_file and gcc_file.filename:
            saved_path = config.DOWNLOADS_DIR / gcc_file.filename
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            content_bytes = await gcc_file.read()
            saved_path.write_bytes(content_bytes)
        elif gcc_file_name:
            cand = config.DOWNLOADS_DIR / gcc_file_name
            if cand.exists():
                saved_path = cand

        if not saved_path or not saved_path.exists():
            return {"success": False, "message": "No GCC or ATC file found or provided."}
        
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
    import shutil
    import urllib.parse
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
            
        # Load user inputs from form_data FIRST
        user_inputs = {}
        for f in [
            "issuing_authority", "railway", "tender_no", "tender_name",
            "place", "date", "closing_date", "days", "bid_security_amount",
            "execute_contract_days", "commence_work_days",
            "signatory_name", "signatory_designation", "company_name"
        ]:
            val = form_data.get(f)
            if val and str(val).strip():
                user_inputs[f] = str(val).strip()

        # Merge with saved metadata
        saved_meta = load_tender_metadata(document_id, out_dir)
        for k, v in saved_meta.items():
            if not user_inputs.get(k) and v:
                user_inputs[k] = v

        # If any core NIT fields (especially issuing_authority) are missing, fetch directly from NIT
        user_inputs = extract_missing_nit_data(document_id, out_dir, user_inputs)
        save_tender_metadata(document_id, user_inputs, out_dir)

        # Parse extra answers from user if provided
        extra_answers = {}
        extra_answers_raw = form_data.get("extra_answers")
        if extra_answers_raw:
            try:
                extra_answers = json.loads(extra_answers_raw)
            except Exception:
                pass
                
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
                            if not user_inputs.get("signatory_name"): user_inputs["signatory_name"] = "BHARGAV NARENDRABHAI PRAJAPATI"
                            if not user_inputs.get("signatory_designation"): user_inputs["signatory_designation"] = "Director"
                            if not user_inputs.get("company_name"): user_inputs["company_name"] = "AQUINT INFRATELE INDIA PRIVATE LIMITED"
                        else:
                            sig_file = Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\arkonic\dharam sir.jpeg")
                            if not user_inputs.get("signatory_name"): user_inputs["signatory_name"] = "DHARAMRAJSINH NARENDRASINH VAGHELA"
                            if not user_inputs.get("signatory_designation"): user_inputs["signatory_designation"] = "Managing Director"
                            if not user_inputs.get("company_name"): user_inputs["company_name"] = "ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
                        
                        import app.internal.intake.smart_filler as sf
                        import app.internal.intake.intake as intake
                        
                        company_data = await asyncio.to_thread(intake.load_company_data, company)
                        documents_dir = intake.get_docs_dir(company)

                        # 1. Direct template placeholder replacement
                        c_comp = company_data.get("company", {})
                        c_sig = company_data.get("signatory", {})
                        c_stat = company_data.get("statutory", {})
                        replacements = {
                            "{{COMPANY_NAME}}": user_inputs.get("company_name") or c_comp.get("legal_name", ""),
                            "{{DIVISION}}": user_inputs.get("railway", ""),
                            "{{DIVISON}}": user_inputs.get("railway", ""),
                            "{{RAILWAY}}": user_inputs.get("railway", ""),
                            "{{TENDER_NO}}": user_inputs.get("tender_no", document_id),
                            "{{TENDER_NAME}}": user_inputs.get("tender_name", ""),
                            "{{PLACE}}": "Ahmedabad",
                            "{{DATE}}": user_inputs.get("closing_date") or user_inputs.get("date", ""),
                            "{{DAYS}}": user_inputs.get("days", "30"),
                            "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name") or c_sig.get("name", ""),
                            "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation") or c_sig.get("designation", ""),
                            "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority") or user_inputs.get("railway", ""),
                            "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount", ""),
                            "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days", "7"),
                            "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days", "15"),
                            "{{GSTIN}}": c_stat.get("gstin", ""),
                            "{{PAN}}": c_stat.get("pan", ""),
                        }
                        fill_docx_template_global(g_path, g_path, replacements, signature_path=str(sig_file) if sig_file and sig_file.exists() else None)

                        # 2. Smart fill using AI
                        fill_res = await asyncio.to_thread(sf.smart_fill_docx, str(g_path), company_data, documents_dir, user_inputs, extra_answers)
                        
                        missing_q = fill_res.get("missing_questions", []) if fill_res else []
                        unanswered_q = [q for q in missing_q if not any(k.strip().lower() in q.lower() or q.strip().lower() in k.lower() for k, v in extra_answers.items() if v)]
                        
                        if unanswered_q and not form_data.get("force_finalize"):
                            return {
                                "status": "needs_extra_answers",
                                "message": f"Document '{g_file.filename}' requires additional information to complete.",
                                "file_name": g_file.filename,
                                "missing_questions": unanswered_q,
                                "document_id": document_id,
                                "local_path": str(out_dir)
                            }

                        # 3. Convert to PDF using subprocess (avoids COM/threading issues)
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
                
        website = form_data.get("website", "ireps")
        base_mapping_dir = Path(r"C:\Users\DELL\Downloads\Doc mapping")
        # Ensure correct folder path matching mapping
        final_folder_path = base_mapping_dir / website.lower() / f"Mapped_Docs_{document_id}"
        
        # out_dir might already be the mapped folder if user skipped step 4, or we need to ensure it's there
        if out_dir.resolve() != final_folder_path.resolve():
            # If not already there, we should copy/move, but `out_dir` should already be the right path based on earlier logic in this file.
            pass
            
        generated_files = []
        if out_dir and out_dir.exists():
            for f_path in out_dir.iterdir():
                if f_path.is_file() and not f_path.name.endswith(".json"):
                    f_url = f"/file?path={urllib.parse.quote(str(f_path.resolve()))}"
                    generated_files.append({"name": f_path.name, "url": f_url})
            generated_files.sort(key=lambda x: x["name"])

        return {
            "status": "success",
            "message": "Package finalized successfully.",
            "local_path": str(out_dir),
            "generated_files": generated_files
        }
    except Exception as e:
        logging.error(f"Error finalizing IREPS: {e}")
        return {"status": "error", "message": str(e)}

