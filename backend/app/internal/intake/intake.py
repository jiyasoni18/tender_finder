import os
import shutil
import yaml
import datetime
import pythoncom
import argparse
import traceback
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

import sys
sys.path.append(str(Path(__file__).parent))

from app.internal.intake.pdf_parser import parse_nit_pdf
from app.internal.intake.excel_parser import parse_excel_requirements, update_excel_status
from app.internal.intake.ai_mapper import map_requirements_batch

try:
    from google import genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

def get_docx_placeholders(docx_path):
    try:
        from docx import Document
        import re
    except ImportError:
        return set()
    try:
        doc = Document(docx_path)
    except Exception:
        return set()
    text = ""
    for p in doc.paragraphs:
        text += p.text + "\n"
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text += p.text + "\n"
    return set(re.findall(r'\{\{([A-Z_]+)\}\}', text))

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
MASTER_DATA_DIR = BASE_DIR / "data" / "tender-system" / "company"
TENDERS_DIR = BASE_DIR / "data" / "tender-system" / "tenders"

def get_catalog_path(portal_type="ireps"):
    return BASE_DIR / "app" / "internal" / "catalog" / f"requirements_{portal_type}.yaml"

def get_docs_dir(company_name=""):
    c_lower = str(company_name).lower()
    if "arkonik" in c_lower:
        return Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\arkonic")
    else:
        return Path(r"c:\Users\DELL\Downloads\tender_finder\tender_finder\aquint")

def get_signature_path(company_name="", signatory_name=""):
    docs_dir = get_docs_dir(company_name)
    c_lower = str(company_name).lower()
    sig_lower = str(signatory_name).lower().strip()
    
    if "arkonik" in c_lower:
        if "twinkle chudawat" in sig_lower:
            return docs_dir / "dharam sir wife.jpeg"
        return docs_dir / "dharam sir.jpeg"
    else:
        return docs_dir / "bhargav sir2.jpeg"

def load_catalog(portal_type="ireps"):
    catalog_path = get_catalog_path(portal_type)
    if not catalog_path.exists():
        if portal_type.lower() != "ireps":
            catalog_path = get_catalog_path("ireps")
        if not catalog_path.exists():
            return []
    with open(catalog_path, 'r') as f:
        data = yaml.safe_load(f)
    reqs = data.get("requirements") if data else None
    return reqs if reqs is not None else []

def find_file_in_company_dir(canonical_id, company_name=""):
    docs_dir = get_docs_dir(company_name)
    c_lower = str(company_name).lower()
    
    if "arkonik" in c_lower:
        mapping = {
            "AOA_MOA": ["AOA.pdf.pdf", "MOA.pdf.pdf", "AOA_DNV & TDV(2).pdf", "MOA_DNV & TDV(2).pdf"],
            "POWER_OF_ATTORNEY_BR": ["BR.pdf"],
            "PAN_CARD": ["Arkonic PAN.pdf"],
            "GST_DECLARATION": ["ARKONIK GST.pdf", "Arkonik Fibertech GST.pdf"],
            "STARTUP_CERTIFICATE": ["ARKONIK STARTUP.pdf"],
            "STARTUPS_CERTIFICATE": ["ARKONIK STARTUP.pdf"],
            "BALANCE_SHEET": ["Arkonik Fibetech BSheet 01-04-25 to 31-03-26_CA certified.pdf"],
            "TURNOVER_FORMAT": ["ARKONIK TURNOVER DONE.pdf"],
            "MSME_CERTIFICATE": ["Arkonik MSME.pdf"],
            "PF_CERTIFICATE": ["Arkonik PF Certificate.pdf"],
            "ESIC": ["ESIC certificate......pdf"],
            "ITR": ["ARKONIK  ITR 2024-25.pdf", "ARKONIK FIBER FY 2023-24 ITR.pdf"],
            "INCORPORATION": ["INC-24_Certificate of Incorporation Pursuant To Change of Name_AA6440272 (1).pdf"],
            "SOLVENCY": ["Arkonik  Solcency SBI.pdf"],
            "MANDATE_FORM": ["MANDATE FORM.pdf"],
            "DIRECTOR_LIST": ["6.DIRECTOR LIST.docx"],
            "BID_FORM": ["BID FORM.docx"],
            "TENDER_FORM_FIRST_SHEET": ["BID FORM 1.docx", "BID FORM.docx"],
            "TENDER_FORM_SEC_SHEET": ["BID FORM.docx"],
            "STATEMENT_OF_DEVIATIONS_1": ["statement of deviations.docx"],
            "STATEMENT_OF_DEVIATIONS_2": ["statement of deviations.docx"],
            "CERTIFICATE_TO_BE_SUBMITTED": ["Certificate from Bidder for compliance.docx"],
            "BLACKLIST_UNDERTAKING": ["DECLARATION REGARDING NON BLACKLIST by GST authorities.pdf"],
            "L1_DECLARATION": ["Near Relation Certificates.docx", "Declaration form for relative.docx"],
            "PRESCRIBED_FORMAT_CERT": ["Certificate for fundamental principles of public buying.docx"],
            "EXPERIENCE_ACQUAINT": ["arkonik EXPERIENCE.pdf"]
        }
        if canonical_id in mapping:
            for possible_name in mapping[canonical_id]:
                for root, dirs, files in os.walk(docs_dir):
                    if possible_name in files:
                        return Path(root) / possible_name
                        
    # Fallback to catalog filename_hint if no mapping exists
    catalog = load_catalog("ireps")
    entry = next((item for item in catalog if item["id"] == canonical_id), None)
    if entry and entry.get("filename_hint"):
        filename_hint = entry["filename_hint"]
        for root, dirs, files in os.walk(docs_dir):
            if filename_hint in files:
                return Path(root) / filename_hint
    return None

def map_with_keywords(line, catalog):
    import re
    line_lower = str(line).lower().replace('\ufb01', 'fi').replace('\ufb02', 'fl')
    
    if 'annexure-v and v(a)' in line_lower or 'annexure v and v(a)' in line_lower or 'annexure-v and va' in line_lower or 'annexure v and va' in line_lower:
        return ["CERTIFICATE_TO_BE_SUBMITTED", "PRESCRIBED_FORMAT_CERT"]
    
    # 0. BLACKLIST OVERRIDE (Highest priority to avoid JV false positives)
    if 'blacklisted' in line_lower or 'debarred' in line_lower or 'black listed' in line_lower:
        return ['BLACKLIST_UNDERTAKING']

    # 1. RETIRED ENGINEER OVERRIDE
    if 'retired engineer' in line_lower or 'gazetted officer' in line_lower or 'retired from government service' in line_lower or 'retired railway' in line_lower:
        return ['RETIRED_RAILWAY_EMPLOYEES']

    # 2. ANNEXURE II A -> PRESCRIBED_FORMAT_CERT (Doc 4)
    if any(x in line_lower for x in ['annexure ii a', 'annexure iia', 'annexure-iia', 'annexure 2 a', 'annexure 2a', 'annexure ii-a']):
        return ['PRESCRIBED_FORMAT_CERT']

    # 3. STATUS OF FIRM / THEIR FIRMS
    if ('status of firm' in line_lower or 'status of their firm' in line_lower or 'status of their firms' in line_lower):
        if 'power of attorney' in line_lower or 'board of directors' in line_lower:
            # We don't return here immediately if it's a generic constitution request to allow falling through to regex
            pass
        else:
            return ['CERTIFICATE_TO_BE_SUBMITTED']

    # 3b. ANNEXURE-I / BANK DETAILS + CONSTITUTION OVERRIDE
    if ('constitution of firm' in line_lower or 'annexure-i' in line_lower or 'annexure i' in line_lower) and ('bank details' in line_lower or 'bank account' in line_lower):
        return ['BANK_DETAILS_CONSTITUTION', 'TENDER_FORM_FIRST_SHEET']

    # 3c. NEAR RELATIVE CERTIFICATE OVERRIDE
    if 'near relative' in line_lower or 'relative certificate' in line_lower:
        return [] # Let the AI or catalog mapping handle it so we don't trigger multi-entity rule below

    # 4. AOA/MOA vs POA vs JV
    is_generic_constitution = 'constitution of their firm' in line_lower or 'status of firm' in line_lower
    if not is_generic_constitution:
        results = []
        has_aoa = any(x in line_lower for x in ['moa', 'aoa', 'memorandum of association', 'article of association', 'memorandum of understanding'])
        has_company_keyword = 'company' in line_lower or 'private limited' in line_lower
        has_poa_br = 'power of attorney' in line_lower or 'partnership deed' in line_lower or 'board resolution' in line_lower
        has_jv = 'jv' in line_lower or 'joint venture' in line_lower or 'society' in line_lower or 'trust' in line_lower or 'llp' in line_lower
        has_partnership = 'partnership' in line_lower
        has_sole_prop = 'sole proprietorship' in line_lower or 'proprietorship' in line_lower
        
        # If it's a large multi-entity paragraph, make sure we suggest Company docs if Company is mentioned
        is_multi_entity = (has_company_keyword + has_jv + has_partnership + has_sole_prop) >= 2
        
        if has_aoa or (is_multi_entity and has_company_keyword):
            results.append('AOA_MOA')
            
        if has_poa_br or (is_multi_entity and has_partnership):
            if 'POWER_OF_ATTORNEY_BR' not in results:
                results.append('POWER_OF_ATTORNEY_BR')
                
        if has_jv:
            # Check if it's actually just asking for Annexure V/V(A)
            has_annex_v = 'annexure-v' in line_lower or 'annexure v ' in line_lower or 'annexure v,' in line_lower or 'annexure -v' in line_lower
            has_annex_va = 'annexure-v(a)' in line_lower or 'annexure v(a)' in line_lower or 'annexure-v (a)' in line_lower or 'annexure -va' in line_lower or '& annexure -va' in line_lower
            if has_annex_v and has_annex_va:
                results.extend(['CERTIFICATE_TO_BE_SUBMITTED', 'PRESCRIBED_FORMAT_CERT'])
            elif has_annex_v:
                results.append('CERTIFICATE_TO_BE_SUBMITTED')
            elif has_annex_va:
                results.append('PRESCRIBED_FORMAT_CERT')
            else:
                if 'JV_PARTNERSHIP_DECLARATION' not in results:
                    results.append('JV_PARTNERSHIP_DECLARATION')
                    
        if results:
            return results        
    # 5. EXPERIENCE OVERRIDE
    is_experience = any(x in line_lower for x in ['similar work', 'similar nature', 'experience', 'credential', 'completion certificate', ' loa ', 'letter of acceptance'])
    
    if is_experience and ('signal' in line_lower or 'signalling' in line_lower):
        return ['SIGNALING_EXPERIENCE']
    # 5b. TELECOM EXPERIENCE OVERRIDE
    elif is_experience and ('telecom' in line_lower or 'telecome' in line_lower):
        return ['TELECOME_EXPERIENCE']
    # 5c. GENERAL EXPERIENCE
    elif is_experience:
        return ['EXPERIENCE_ACQUAINT']

    # 6. TURNOVER / FINANCIAL OVERRIDE
    is_turnover = any(x in line_lower for x in ['turnover', 'turn over', 'financial eligibility', 'contractual payments', 'annual contractual turnover'])
    is_balance_sheet = any(x in line_lower for x in ['audited balance sheet', 'balance sheet', 'audit report'])
    
    if is_turnover and is_balance_sheet:
        return ['TURNOVER_FORMAT', 'BALANCE_SHEET']
    elif is_turnover:
        return ['TURNOVER_FORMAT']
    elif is_balance_sheet:
        return ['BALANCE_SHEET']

    # 5. ANNEXURE V / V(A) OVERRIDE
    has_annex_v = 'annexure-v' in line_lower or 'annexure v ' in line_lower or 'annexure v,' in line_lower or 'annexure -v' in line_lower
    has_annex_va = 'annexure-v(a)' in line_lower or 'annexure v(a)' in line_lower or 'annexure-v (a)' in line_lower or 'and v(a)' in line_lower or 'and v (a)' in line_lower or 'and va' in line_lower or 'annexure va' in line_lower or 'annexure-va' in line_lower or 'annexure -va' in line_lower or '& annexure -va' in line_lower

    if has_annex_v and has_annex_va:
        return ['CERTIFICATE_TO_BE_SUBMITTED', 'PRESCRIBED_FORMAT_CERT']
    elif has_annex_v:
        return ['CERTIFICATE_TO_BE_SUBMITTED']
    elif has_annex_va:
        return ['PRESCRIBED_FORMAT_CERT']

    # 6. MAF / OEM OVERRIDE
    is_maf = 'manufacturer\'s authorization form' in line_lower or 'manufacturers authorization form' in line_lower or ' maf ' in line_lower or '(maf)' in line_lower or 'oem authorization' in line_lower
    if is_maf:
        return ['MAF_DECLARATION', 'OEM_AUTHORIZATION_DECLARATION']

    # 7. BID SECURITY / BANK GUARANTEE -> STARTUP CERTIFICATE OVERRIDE
    if 'bid security' in line_lower and ('bank guarantee' in line_lower or 'clause no: (5)' in line_lower):
        return ['STARTUP_CERTIFICATE']

    # --- END OVERRIDES ---

    mapped_ids = []
    for req in catalog:
        for alias in req.get('aliases', []):
            pattern = r'(?<!\w)' + re.escape(alias.lower()) + r'(?!\w)'
            if re.search(pattern, line_lower):
                if req['id'] not in mapped_ids:
                    mapped_ids.append(req['id'])

    if 'BANK_DETAILS_CONSTITUTION' in mapped_ids and 'AOA_MOA' in mapped_ids:
        mapped_ids.remove('AOA_MOA')

    return mapped_ids

def map_with_gemini(line, catalog, api_key):
    if not api_key or not HAS_GEMINI:
        return None
    
    client = genai.Client(api_key=api_key)
    options = [req['id'] for req in catalog]
    options_str = ", ".join(options)
    
    prompt = f"""
    You are an AI assistant mapping railway tender requirements to canonical document IDs.
    Given this tender requirement: "{line}"
    Choose the BEST matching canonical ID from this list: [{options_str}].
    
    OVERRIDING JV/PARTNERSHIP RULE:
    - If the requirement specifically demands credentials for a Joint Venture (JV), Partnership Firm, Society, Trust, or LLP (e.g., "In case of JV submit...", "In case of Society/Trust...", "In case of LLP firm..."), you MUST return EXACTLY ONE ID: JV_PARTNERSHIP_DECLARATION. Do NOT return any other IDs (do not combine), even if other documents like turnover or AOA are mentioned.
    - CRITICAL EXCEPTION: Do NOT apply this rule (and do NOT return JV_PARTNERSHIP_DECLARATION) if the text is talking about "Partnership of Retired Railway Employees" or simply listing firm types (e.g., "Sole Proprietorship/Partnership/Company").

    MULTI-DOCUMENT RULES:
    If the requirement text clearly asks for multiple distinct documents (e.g., "submit AOA, Power of Attorney, and Blacklist Undertaking"), you MUST return all the relevant canonical IDs as a comma-separated list. 
    
    STRICT MAPPING RULES:
    - For Financial Eligibility/Turnover, return TURNOVER_FORMAT.
    - For Balance Sheet / Audit Report, return BALANCE_SHEET.
    - Do NOT merge Balance Sheet and Turnover into a single ID; they are separate documents. If both are requested, return both.
    - For Technical Eligibility/Similar Works/Experience, return ONLY: EXPERIENCE_ACQUAINT. Do NOT return multiple.
    - For Bid Security/EMD/Bank Guarantee, return ONLY: BID_SECURITY.
    - For Annexure-F / Blacklisted / Debarred, return ONLY: BLACKLIST_UNDERTAKING.
    - For PAN Card / Permanent Account Number, return: PAN_CARD.
    - For "Declaration regarding constitution of firm & Bank Details" or "Annexure-I" mentioning constitution/bank details, return: BANK_DETAILS_CONSTITUTION, TENDER_FORM_FIRST_SHEET.
    
    If none match, reply with NONE.
    Only reply with the ID or comma-separated IDs, nothing else.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
        )
        result = response.text.strip().replace(" ", "")
        
        if result == "NONE":
            return []
            
        mapped_ids = []
        for res_id in result.split(","):
            if res_id in options:
                mapped_ids.append(res_id)
                
        return mapped_ids
    except Exception as e:
        print(f"Gemini API error during mapping: {e}")
    return []


def load_company_data(company_name=""):
    filename = "master_data.yaml"
    c_lower = str(company_name).lower()
    
    # Try fetching from company-specific tender-system first
    docs_dir = get_docs_dir(company_name)
    master_data_path = docs_dir / filename
    
    if not master_data_path.exists():
        master_data_path = BASE_DIR / "data" / "tender-system" / "company" / filename
        if not master_data_path.exists():
            master_data_path = BASE_DIR.parent / "data" / "tender-system" / "company" / filename
        
    data = {}
    if master_data_path.exists():
        with open(master_data_path, 'r') as f:
            data = yaml.safe_load(f) or {}
            
    # Inject reference texts from documents directory
    doc_dir = get_docs_dir(company_name)
    reference_files = [
        "8.LIST OF WORK IN HAND.docx",
        "10.PLANT AND MACHINERY.docx",
        "6.ENGINEERING ORGANISATION AVAILABLE.docx",
        "7.LIST OF WORK COMPLETED.docx"
    ]
    
    reference_texts = {}
    try:
        from docx import Document
        for f_name in reference_files:
            f_path = doc_dir / f_name
            if f_path.exists():
                doc = Document(f_path)
                text_blocks = []
                for elem in doc.element.body:
                    if elem.tag.endswith('p'):
                        text_blocks.append(elem.text)
                    elif elem.tag.endswith('tbl'):
                        table_idx = len([t for t in text_blocks if t.startswith('--- TABLE')])
                        if table_idx < len(doc.tables):
                            text_blocks.append('--- TABLE ---')
                            for row in doc.tables[table_idx].rows:
                                text_blocks.append(' | '.join([cell.text.strip().replace('\n', ' ') for cell in row.cells]))
                reference_texts[f_name] = '\n'.join([t for t in text_blocks if t])
    except Exception as e:
        print(f"Failed to load reference texts: {e}")
        
    data["reference_texts"] = reference_texts
    return data

def fill_docx_template(template_path, output_path, replacements, signature_path=None, company_data=None):
    try:
        from docx import Document
        from docx.shared import Inches
    except ImportError:
        shutil.copy(template_path, output_path)
        return
        
    try:
        doc = Document(template_path)
    except Exception as e:
        import shutil
        print(f"Failed to open {template_path} as docx: {e}")
        shutil.copy(template_path, output_path)
        return
    for paragraph in doc.paragraphs:
        for key, value in replacements.items():
            if key in paragraph.text:
                for run in paragraph.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, str(value))
                if key in paragraph.text:
                    paragraph.text = paragraph.text.replace(key, str(value))
                    
        import re
        if "{{DATE}}" in replacements:
            date_val = str(replacements["{{DATE}}"])
            # Replace blank date lines like 'Date: _______' or 'Date: .........'
            if re.search(r'(?i)\bdate\s*:\s*[_]{3,}', paragraph.text):
                paragraph.text = re.sub(r'(?i)(\bdate\s*:\s*)[_]{3,}', r'\1' + date_val, paragraph.text)
            if re.search(r'(?i)\bdate\s*:\s*[\.]{3,}', paragraph.text):
                paragraph.text = re.sub(r'(?i)(\bdate\s*:\s*)[\.]{3,}', r'\1' + date_val, paragraph.text)
            if re.search(r'(?i)\bdated\s*:\s*[_]{3,}', paragraph.text):
                paragraph.text = re.sub(r'(?i)(\bdated\s*:\s*)[_]{3,}', r'\1' + date_val, paragraph.text)
            if re.search(r'(?i)\bdated\s*:\s*[\.]{3,}', paragraph.text):
                paragraph.text = re.sub(r'(?i)(\bdated\s*:\s*)[\.]{3,}', r'\1' + date_val, paragraph.text)
                    
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for key, value in replacements.items():
                        if key in paragraph.text:
                            for run in paragraph.runs:
                                if key in run.text:
                                    run.text = run.text.replace(key, str(value))
                            if key in paragraph.text:
                                paragraph.text = paragraph.text.replace(key, str(value))
                                
                    import re
                    if "{{DATE}}" in replacements:
                        date_val = str(replacements["{{DATE}}"])
                        if re.search(r'(?i)\bdate\s*:\s*[_]{3,}', paragraph.text):
                            paragraph.text = re.sub(r'(?i)(\bdate\s*:\s*)[_]{3,}', r'\1' + date_val, paragraph.text)
                        if re.search(r'(?i)\bdate\s*:\s*[\.]{3,}', paragraph.text):
                            paragraph.text = re.sub(r'(?i)(\bdate\s*:\s*)[\.]{3,}', r'\1' + date_val, paragraph.text)
                        if re.search(r'(?i)\bdated\s*:\s*[_]{3,}', paragraph.text):
                            paragraph.text = re.sub(r'(?i)(\bdated\s*:\s*)[_]{3,}', r'\1' + date_val, paragraph.text)
                        if re.search(r'(?i)\bdated\s*:\s*[\.]{3,}', paragraph.text):
                            paragraph.text = re.sub(r'(?i)(\bdated\s*:\s*)[\.]{3,}', r'\1' + date_val, paragraph.text)
                                
    if signature_path and Path(signature_path).exists() and company_data:
        # If the document already has images (inline shapes), assume it already contains a signature or letterhead
        if len(doc.inline_shapes) > 0:
            print("Document already contains an image (likely a signature or letterhead). Skipping signature insertion.")
            inserted = True
        else:
            inserted = False
            
        sig_keywords = ["signature of tenderer", "authorized signatory", "signature of the proprietor", "signature of bidder", "signature", "seal", "signatory"]
        signatory_name = company_data.get("signatory", {}).get("name", "")
        signatory_designation = company_data.get("signatory", {}).get("designation", "")
        company_name = company_data.get("company", {}).get("legal_name", "")
        
        # 1. First, search tables from bottom to top
        if not inserted:
            for table in reversed(doc.tables):
                for row in reversed(table.rows):
                    for cell in reversed(row.cells):
                        for paragraph in reversed(cell.paragraphs):
                            p_lower = paragraph.text.lower()
                            if any(k in p_lower for k in sig_keywords):
                                if not inserted:
                                    new_p = paragraph.insert_paragraph_before("")
                                    r = new_p.add_run()
                                    try:
                                        r.add_picture(str(signature_path), width=Inches(1.5))
                                    except:
                                        pass
                                    paragraph.insert_paragraph_before(f"{signatory_name}\n{signatory_designation}\n{company_name}")
                                    inserted = True
                                    break
                        if inserted: break
                    if inserted: break
                if inserted: break

        # 2. If not found in tables, search main paragraphs from bottom to top
        if not inserted:
            for paragraph in reversed(doc.paragraphs):
                p_lower = paragraph.text.lower()
                if any(k in p_lower for k in sig_keywords):
                    if not inserted:
                        new_p = paragraph.insert_paragraph_before("")
                        r = new_p.add_run()
                        try:
                            r.add_picture(str(signature_path), width=Inches(1.5))
                        except Exception as e:
                            print(f"Error adding signature image: {e}")
                        
                        info_p = paragraph.insert_paragraph_before(f"{signatory_name}\n{signatory_designation}\n{company_name}")
                        info_p.style = paragraph.style
                        inserted = True
                        break
                                    
        # 3. If STILL not inserted, append to the very end of the document
        if not inserted:
            doc.add_paragraph("\n")
            p = doc.add_paragraph(f"For {company_name}")
            try:
                p_sig = doc.add_paragraph()
                r = p_sig.add_run()
                r.add_picture(str(signature_path), width=Inches(1.5))
            except Exception as e:
                pass
            doc.add_paragraph(f"{signatory_name}\n{signatory_designation}")
                                    
    doc.save(output_path)

def convert_to_pdf_if_docx(docx_path):
    if str(docx_path).lower().endswith(".docx"):
        try:
            import subprocess
            pdf_path = str(docx_path).rsplit(".", 1)[0] + ".pdf"
            
            # Use subprocess to run docx2pdf in a separate process, avoiding threading/COM issues in FastAPI
            import os
            abs_docx = str(Path(docx_path).resolve())
            abs_pdf = str(Path(pdf_path).resolve())
            subprocess.run(["docx2pdf", abs_docx, abs_pdf], check=True, capture_output=True)
            
            if Path(abs_pdf).exists():
                try:
                    os.remove(abs_docx)
                except:
                    pass
                return Path(abs_pdf)
            else:
                raise Exception("PDF file was not created by docx2pdf.")
        except Exception as e:
            print(f"Failed to convert {docx_path} to PDF using docx2pdf: {e}")
            try:
                import win32com.client
                import pythoncom
                pythoncom.CoInitialize()
                pdf_path = str(docx_path).rsplit(".", 1)[0] + ".pdf"
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                word.DisplayAlerts = False
                try:
                    doc = word.Documents.Open(str(Path(docx_path).resolve()))
                    try:
                        doc.SaveAs(str(Path(pdf_path).resolve()), FileFormat=17)
                    finally:
                        doc.Close(0)
                finally:
                    word.Quit()
                os.remove(docx_path)
                return Path(pdf_path)
            except Exception as e2:
                print(f"Failed to convert {docx_path} to PDF using win32com fallback: {e2}")
    return docx_path

def get_tender_out_dir(tender_no, user_inputs, portal_type="ireps"):
    plc = user_inputs.get("place") or "PLACE"
    closing_dt = user_inputs.get("closing_date")
    
    import re
    plc_safe = re.sub(r'[\\/*?:"<>|]', '_', plc)
    
    if closing_dt:
        date_safe = closing_dt.replace("/", "-")
        date_safe = re.sub(r'[\\/*?:"<>|]', '_', date_safe)
    else:
        dt = user_inputs.get("date") or "DATE"
        import datetime
        try:
            dt_obj = datetime.datetime.strptime(dt, "%d/%m/%Y")
            date_safe = dt_obj.strftime("%d-%B")
        except:
            date_safe = dt.replace("/", "-")
            
    t_safe = ""
    if tender_no and str(tender_no).strip():
        t_safe = re.sub(r'[\\/*?:"<>|]', '_', str(tender_no).strip())
        
    if portal_type.lower() == "gem":
        prefix = "GEM"
        folder_name = f"{prefix}_{plc_safe}"
        if t_safe:
            folder_name += f"_{t_safe}"
        folder_name += f"_{date_safe}"
    else:
        prefix = "Railway"
        folder_name = f"{prefix}_{plc_safe}_{date_safe}"
        if t_safe:
            folder_name += f"_{t_safe}"
        
    return TENDERS_DIR / folder_name

def process_requirements(requirements_list, tender_no, catalog, is_excel=False, user_inputs=None, user_merges=None, dry_run=False, extra_pdfs=None, gcc_results=None, letterhead_path=None, custom_annexure_paths=None, portal_type="ireps", combine_flags=None):
    if user_inputs is None: user_inputs = {}
    if user_merges is None: user_merges = {}
    if combine_flags is None: combine_flags = {}
    if extra_pdfs is None: extra_pdfs = {}
    if gcc_results is None: gcc_results = {}
    
    company_name = user_inputs.get("company_name", "AQUIANT INFRATELE INDIA PRIVATE LIMITED")
    
    tender_out_dir = get_tender_out_dir(tender_no, user_inputs, portal_type)
    if not dry_run:
        if not tender_out_dir.exists():
            tender_out_dir.mkdir(parents=True, exist_ok=True)
            
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 0. Pre-map all requirements using Full-Context AI mapping
    print("Running Full-Context AI mapping engine...")
    ai_mappings = {}
    needs_ai = False
    for idx, req in enumerate(requirements_list):
        k = str(req.get("row_key") or req.get("row") or idx)
        if "canonical_ids" in req:
            ai_mappings[k] = req["canonical_ids"]
        else:
            needs_ai = True
            
    if needs_ai:
        ai_mappings.update(map_requirements_batch(requirements_list, catalog))
    
    results = {}
    missing_fields = set()
    proposed_merges = []
    needs_gcc_list = []
    needs_letterhead = False
    
    mapping_cache = {}
    generated_docs = {}
    
    # Fields required for document generation. Only ask user if NOT already populated from NIT.
    REQUIRED_FIELDS = {
        "tender_no": "Tender Number",
        "tender_name": "Tender Name",
        "issuing_authority": "Issuing Authority / Railway",
        "signatory_designation": "Signatory Designation",
        "days": "Validity (Days)",
        "bid_security_amount": "Bid Security Amount (Rs.)",
        "closing_date": "Tender Closing Date",
    }
    if portal_type == "ireps":
        REQUIRED_FIELDS["railway"] = "Railway / Division"
    if dry_run:
        for field in REQUIRED_FIELDS:
            if not user_inputs.get(field):
                missing_fields.add(field)

    
    for idx, req in enumerate(requirements_list):
        if is_excel:
            line = req["name"]
            key = req["row"]
        else:
            line = req
            key = idx
            
        print(f"- Input: {line}")
        canonical_ids = []
        generated_pdf_paths = []
        
        line_lower = str(line).lower()
        if 'letter head' in line_lower or 'letterhead' in line_lower:
            needs_letterhead = True
            

        
        # 0. Check explicit keyword overrides FIRST (bypassing AI if it's a known strict override)
        canonical_ids = map_with_keywords(line, [])
        if canonical_ids:
            print(f"  [Keyword Override] matched: {canonical_ids}")
        
        # 1. Use AI mapping as primary truth
        if not canonical_ids:
            canonical_ids = ai_mappings.get(str(key), [])
            if canonical_ids:
                print(f"  [AI Mapper] matched: {canonical_ids}")
                
        # 2. Fallback to basic keyword mapping
        if not canonical_ids:
            canonical_ids = map_with_keywords(line, catalog)
            if canonical_ids:
                print(f"  [Keyword Mapper] matched: {canonical_ids}")
        
        import re
        match = re.search(r'\b(form|annexure|appendix|proforma)\b[ \-]?([a-z0-9]+(?:\([a-z0-9]+\))?)\b', line_lower)
        is_explicit_form = bool(match)
        explicit_form_name = match.group(0).replace('-', ' ').replace('_', ' ') if match else None
        
        if is_explicit_form and match:
            ignored_suffixes = {"of", "in", "to", "for", "and", "the", "a", "is", "as", "by", "on"}
            if match.group(2).lower() in ignored_suffixes:
                is_explicit_form = False
                explicit_form_name = None
        
        # Check if the user uploaded a custom annexure for this explicitly
        matched_custom_annexure = None
        if custom_annexure_paths:
            if isinstance(custom_annexure_paths, dict) and str(key) in custom_annexure_paths:
                matched_custom_annexure = Path(custom_annexure_paths[str(key)][0])
            elif explicit_form_name and isinstance(custom_annexure_paths, list):
                for p in custom_annexure_paths:
                    p_stem = Path(p).stem.lower().replace('-', ' ').replace('_', ' ')
                    if explicit_form_name in p_stem:
                        matched_custom_annexure = Path(p)
                        break
            
        GENERIC_IDS = {"PRESCRIBED_FORMAT_CERT", "CERTIFICATE_TO_BE_SUBMITTED"}
        
        if is_explicit_form and not matched_custom_annexure:
            is_valid_annexure_v = explicit_form_name in ["annexure v", "annexure v a", "annexure va", "annexure v(a)", "annexure v (a)"]
            
            if str(key) in gcc_results and not is_valid_annexure_v:
                print(f"  => Explicit form found in GCC results. Overriding static mappings: {canonical_ids}")
                canonical_ids = []
            else:
                if gcc_results == {} and dry_run and not is_valid_annexure_v:
                    needs_gcc_list.append({"row_key": str(key), "line": str(line)})
                    print("  => Explicit form mentioned. Requesting GCC (keeping static mapping as fallback).")
                
                if not canonical_ids or (all(cid in GENERIC_IDS for cid in canonical_ids) and not is_valid_annexure_v):
                    canonical_ids = []
                    print("  (Discarding purely generic mapping. No valid fallback.)")
            
        if str(key) in user_merges:
            canonical_ids = [cid for cid in canonical_ids if cid in user_merges[str(key)]]
        
        _ANNEX_V_PAIR = {"CERTIFICATE_TO_BE_SUBMITTED", "PRESCRIBED_FORMAT_CERT"}
        _is_annex_v_and_va = set(canonical_ids) == _ANNEX_V_PAIR
        if _is_annex_v_and_va:
            canonical_ids = ["CERTIFICATE_TO_BE_SUBMITTED", "PRESCRIBED_FORMAT_CERT"]
            
        found = False
        notes = []
        upload_nums = []
        needs_info = False
        _is_annex_v_and_va = False  # Tracks if this row is the combined Annexure-V + V(A) pair
        
        if matched_custom_annexure:
            found = True
            notes.append(f"Mapped to custom uploaded annexure: {matched_custom_annexure.name}")
            print(f"  [+] Matched to custom upload: {matched_custom_annexure.name}")
            if not dry_run:
                try:
                    dest_path = tender_out_dir / f"{idx + 1:02d}_{matched_custom_annexure.name}"
                    shutil.copy(str(matched_custom_annexure), str(dest_path))
                    if str(dest_path).lower().endswith(".docx"):
                        from app.internal.intake.smart_filler import smart_fill_docx
                        company_data = load_company_data(company_name)
                        documents_dir = get_docs_dir(company_name)
                        
                        # Apply smart AI filling first
                        result = smart_fill_docx(str(dest_path), company_data, documents_dir, user_inputs)
                        
                        # Apply regex-based date and signature injection
                        company = company_data.get("company", {})
                        signatory = company_data.get("signatory", {})
                        statutory = company_data.get("statutory", {})
                        replacements = {
                            "{{COMPANY_NAME}}": user_inputs.get("company_name") or company.get("legal_name", "[COMPANY_NAME]"),
                            "{{DIVISION}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                            "{{DIVISON}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                            "{{RAILWAY}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                            "{{TENDER_NO}}": user_inputs.get("tender_no") or tender_no or "[TENDER_NO]",
                            "{{TENDER_NAME}}": user_inputs.get("tender_name") or "[TENDER_NAME]",
                            "{{PLACE}}": user_inputs.get("place") or company.get("registered_address", "Ahmedabad"),
                            "{{DATE}}": user_inputs.get("closing_date") or str(datetime.date.today().strftime("%d/%m/%Y")),
                            "{{DAYS}}": user_inputs.get("days") or "30",
                            "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name") or signatory.get("name", "[SIGNATORY_NAME]"),
                            "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation") or signatory.get("designation", "[DESIGNATION]"),
                            "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority") or "[ISSUING_AUTHORITY]",
                            "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount") or "[BID_SECURITY_AMOUNT]",
                            "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days") or "7",
                            "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days") or "15",
                            "{{STARTUP_DEPT}}": user_inputs.get("startup_dept") or "[STARTUP_DEPT]",
                            "{{STARTUP_REG_NO}}": user_inputs.get("startup_reg_no") or "[STARTUP_REG_NO]",
                            "{{STARTUP_VALID_UPTO}}": user_inputs.get("startup_valid_upto") or "[STARTUP_VALID_UPTO]",
                            "{{GSTIN}}": statutory.get("gstin") or "[GSTIN]",
                        }
                        sig_name = user_inputs.get("signatory_name", "")
                        sig_path = get_signature_path(company_name, sig_name)
                        fill_docx_template(dest_path, dest_path, replacements, signature_path=sig_path, company_data=company_data)
                        
                        final_pdf = convert_to_pdf_if_docx(dest_path)
                        generated_pdf_paths.append(final_pdf)
                        if result and result.get("success"):
                            notes.append("Filled custom uploaded docx using AI and templates.")
                        else:
                            notes.append("Custom uploaded docx AI fill failed.")
                    else:
                        generated_pdf_paths.append(dest_path)
                except Exception as e:
                    print(f"  [!] Failed to process custom uploaded doc: {e}")
        # Try to extract from GeM ATC regardless of canonical_ids if it's GeM, we don't already have gcc_results, and no custom upload was provided
        KYC_IDS = {"PAN_CARD", "GST_DECLARATION", "STARTUP_CERTIFICATE", "STARTUPS_CERTIFICATE", "BALANCE_SHEET", "TURNOVER_FORMAT", "MSME_CERTIFICATE", "PF_CERTIFICATE", "ESIC", "ITR", "INCORPORATION", "SOLVENCY", "DIRECTOR_LIST", "AOA_MOA", "MANDATE_FORM"}
        is_pure_kyc = bool(canonical_ids) and all(cid in KYC_IDS for cid in canonical_ids)
        
        if not matched_custom_annexure and not is_pure_kyc and str(key) not in gcc_results and portal_type.lower() == "gem" and extra_pdfs.get("atc_path"):
            atc_p = Path(extra_pdfs["atc_path"])
            if atc_p.exists():
                print(f"  [GeM] Attempting automatic extraction from ATC for {line}")
                try:
                    from app.internal.intake.gcc_parser import extract_form_from_gcc
                    raw_t = extract_form_from_gcc(str(atc_p), str(line), api_key)
                    if raw_t:
                        gcc_results[str(key)] = raw_t
                        print("  [GeM] Successfully extracted form from ATC.")
                except Exception as e:
                    print(f"  [GeM] Failed to extract from ATC: {e}")

        if str(key) in gcc_results:
            raw_text = gcc_results[str(key)]
            # If we extracted from ATC or GCC, prefer that over our generic static templates
            if canonical_ids and not matched_custom_annexure:
                print(f"  [GeM] Overriding canonical_ids {canonical_ids} because explicit format was extracted.")
                canonical_ids = []
                
            print(f"  [GCC Extractor] Extracting raw form for row {key} without filling...")
            
            import re
            from docx import Document
            base_name = re.sub(r'[\\/*?:"<>|]', "", str(line))[:30].strip()
            dest_docx = tender_out_dir / f"{idx + 1:02d}_{base_name}.docx"
            
            if not dry_run:
                try:
                    doc = Document()
                    for p in raw_text.split('\n'):
                        if p.strip():
                            doc.add_paragraph(p.strip())
                    doc.save(str(dest_docx))
                    
                    from app.internal.intake.smart_filler import smart_fill_docx
                    company_data = load_company_data(company_name)
                    documents_dir = get_docs_dir(company_name)
                    
                    result = smart_fill_docx(str(dest_docx), company_data, documents_dir, user_inputs)
                    
                    company = company_data.get("company", {})
                    signatory = company_data.get("signatory", {})
                    statutory = company_data.get("statutory", {})
                    replacements = {
                        "{{COMPANY_NAME}}": user_inputs.get("company_name") or company.get("legal_name", "[COMPANY_NAME]"),
                        "{{DIVISION}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                        "{{DIVISON}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                        "{{RAILWAY}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                        "{{TENDER_NO}}": user_inputs.get("tender_no") or tender_no or "[TENDER_NO]",
                        "{{TENDER_NAME}}": user_inputs.get("tender_name") or "[TENDER_NAME]",
                        "{{PLACE}}": user_inputs.get("place") or company.get("registered_address", "Ahmedabad"),
                        "{{DATE}}": user_inputs.get("closing_date") or str(datetime.date.today().strftime("%d/%m/%Y")),
                        "{{DAYS}}": user_inputs.get("days") or "30",
                        "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name") or signatory.get("name", "[SIGNATORY_NAME]"),
                        "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation") or signatory.get("designation", "[DESIGNATION]"),
                        "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority") or "[ISSUING_AUTHORITY]",
                        "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount") or "[BID_SECURITY_AMOUNT]",
                        "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days") or "7",
                        "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days") or "15",
                        "{{STARTUP_DEPT}}": user_inputs.get("startup_dept") or "[STARTUP_DEPT]",
                        "{{STARTUP_REG_NO}}": user_inputs.get("startup_reg_no") or "[STARTUP_REG_NO]",
                        "{{STARTUP_VALID_UPTO}}": user_inputs.get("startup_valid_upto") or "[STARTUP_VALID_UPTO]",
                        "{{GSTIN}}": statutory.get("gstin") or "[GSTIN]",
                    }
                    sig_name = user_inputs.get("signatory_name", "")
                    sig_path = get_signature_path(company_name, sig_name)
                    fill_docx_template(dest_docx, dest_docx, replacements, signature_path=sig_path, company_data=company_data)
                    
                    final_pdf = convert_to_pdf_if_docx(dest_docx)
                    generated_pdf_paths.append(final_pdf)
                    
                    if result and result.get("success"):
                        notes.append("Filled extracted form using AI from GCC.")
                    else:
                        notes.append("Extracted form from GCC. AI fill failed.")
                    found = True
                except Exception as e:
                    print(f"  [!] Failed to extract and fill doc from GCC: {e}")
                    notes.append("Failed to extract doc from GCC")
                    found = False
            else:
                notes.append("Will extract and fill form from GCC")
                found = True
        elif not canonical_ids and not matched_custom_annexure:
            print(f"  [!] Could not map requirement to catalog.")
            line_lower = str(line).lower()
            if 'annexure' in line_lower or 'clause' in line_lower or 'form' in line_lower or 'proforma' in line_lower:
                if gcc_results != {}:
                    # GCC was already provided and processed, but this row failed extraction
                    notes.append("Could not extract format from GCC. Please upload custom annexure manually.")
                else:
                    doc_name = "GCC or Annexure"
                    notes.append(f"Please provide {doc_name} to extract this format")
                    if not any(item["row_key"] == str(key) for item in needs_gcc_list):
                        needs_gcc_list.append({"row_key": str(key), "line": str(line)})
            else:
                notes.append("not properly discription")
        if dry_run and len(canonical_ids) > 0:
            docs = []
            for cid in canonical_ids:
                src_file = find_file_in_company_dir(cid, company_name)
                entry = next((item for item in catalog if item["id"] == cid), None)
                if src_file:
                    disp_name = src_file.name
                    if entry and entry.get("category") == "C" and disp_name.endswith(".txt"):
                        disp_name = disp_name.replace(".txt", ".pdf")
                    docs.append({"id": cid, "name": disp_name})
                else:
                    # If the file does not exist for this company, DO NOT fall back to Aquint's generic name
                    print(f"  [!] Missing file for {cid} for company {company_name}")
            if docs:
                proposed_merges.append({
                    "row_key": str(key),
                    "line": str(line),
                    "docs": docs
                })
        
        print(f"  => Mapped to: {', '.join(canonical_ids)}")
            
        req_index = idx + 1
        sub_idx = 1
            
        for canonical_id in canonical_ids:
            entry = next((item for item in catalog if item["id"] == canonical_id), None)
            if entry:
                src_file = find_file_in_company_dir(canonical_id, company_name)
                if not src_file:
                    print(f"  [!] No file configured or found for {canonical_id} in {company_name}")
                    notes.append(f"{canonical_id}: no file configured")
                elif src_file:
                    compulsory_reqs = [
                        "certificate to be submitted",
                        "declaration form for relative",
                        "declaration for retired railway employees",
                        "power of attorney board resolution",
                        "statement of deviations"
                    ]
                    if str(line).lower().strip() in compulsory_reqs:
                        import re
                        base_name = src_file.stem
                        base_name = re.sub(r'^\d+[\._]\s*', '', base_name).strip()
                        dest_filename = f"{base_name}{src_file.suffix}"
                    else:
                        dest_filename = f"{req_index:02d}_{src_file.name}"
                            
                    dest_path = tender_out_dir / dest_filename
                        
                    if entry.get("category") == "A":
                        if not dry_run:
                            shutil.copy(src_file, dest_path)
                            final_path = convert_to_pdf_if_docx(dest_path)
                            generated_pdf_paths.append(final_path)
                            print(f"  => Copied document to {final_path.name}")
                        notes.append(f"{canonical_id}: document find")
                        found = True
                            
                    elif entry.get("category") == "B":
                        notes.append(f"{canonical_id}: document edit")
                        if dry_run:
                            company_data = load_company_data(portal_type)
                            company = company_data.get("company", {})
                            signatory = company_data.get("signatory", {})
                            statutory = company_data.get("statutory", {})
                                
                            if canonical_id not in generated_docs:
                                placeholders = get_docx_placeholders(src_file)
                                if "TENDER_NAME" in placeholders and not user_inputs.get("tender_name"): missing_fields.add("tender_name")
                                if "ISSUING_AUTHORITY" in placeholders and not user_inputs.get("issuing_authority"): missing_fields.add("issuing_authority")
                                if "DATE" in placeholders and not user_inputs.get("closing_date"): missing_fields.add("closing_date")
                                if "PLACE" in placeholders and not user_inputs.get("place") and not company.get("registered_address"): missing_fields.add("place")
                                if "COMPANY_NAME" in placeholders and not user_inputs.get("company_name") and not company.get("legal_name"): missing_fields.add("company_name")
                                if "DIVISON" in placeholders and not user_inputs.get("railway"): missing_fields.add("railway")
                                if "RAILWAY" in placeholders and not user_inputs.get("railway"): missing_fields.add("railway")
                                if "SIGNATORY_NAME" in placeholders and not user_inputs.get("signatory_name") and not signatory.get("name"): missing_fields.add("signatory_name")
                                if "SIGNATORY_DESIGNATION" in placeholders and not user_inputs.get("signatory_designation") and not signatory.get("designation"): missing_fields.add("signatory_designation")
                                if "BID_SECURITY_AMOUNT" in placeholders and not user_inputs.get("bid_security_amount"): missing_fields.add("bid_security_amount")
                                if "EXECUTE_CONTRACT_DAYS" in placeholders and not user_inputs.get("execute_contract_days"): missing_fields.add("execute_contract_days")
                                if "COMMENCE_WORK_DAYS" in placeholders and not user_inputs.get("commence_work_days"): missing_fields.add("commence_work_days")
                                if "STARTUP_DEPT" in placeholders and not user_inputs.get("startup_dept"): missing_fields.add("startup_dept")
                                if "STARTUP_REG_NO" in placeholders and not user_inputs.get("startup_reg_no"): missing_fields.add("startup_reg_no")
                                if "STARTUP_VALID_UPTO" in placeholders and not user_inputs.get("startup_valid_upto"): missing_fields.add("startup_valid_upto")
                                if "GSTIN" in placeholders and not statutory.get("gstin"): missing_fields.add("gstin")
                                if missing_fields:
                                    needs_info = True
                                    
                        if not dry_run:
                            company_data = load_company_data(company_name)
                            company = company_data.get("company", {})
                            signatory = company_data.get("signatory", {})
                            statutory = company_data.get("statutory", {})
                                
                            replacements = {
                                "{{COMPANY_NAME}}": user_inputs.get("company_name") or company.get("legal_name", "[COMPANY_NAME]"),
                                "{{DIVISION}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                                "{{DIVISON}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                                "{{RAILWAY}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                                "{{TENDER_NO}}": user_inputs.get("tender_no") or tender_no or "[TENDER_NO]",
                                "{{TENDER_NAME}}": user_inputs.get("tender_name") or "[TENDER_NAME]",
                                "{{PLACE}}": user_inputs.get("place") or company.get("registered_address", "Ahmedabad"),
                                "{{DATE}}": user_inputs.get("closing_date") or str(datetime.date.today().strftime("%d/%m/%Y")),
                                "{{DAYS}}": user_inputs.get("days") or "30",
                                "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name") or signatory.get("name", "[SIGNATORY_NAME]"),
                                "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation") or signatory.get("designation", "[DESIGNATION]"),
                                "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority") or "[ISSUING_AUTHORITY]",
                                "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount") or "[BID_SECURITY_AMOUNT]",
                                "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days") or "7",
                                "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days") or "15",
                                "{{STARTUP_DEPT}}": user_inputs.get("startup_dept") or "[STARTUP_DEPT]",
                                "{{STARTUP_REG_NO}}": user_inputs.get("startup_reg_no") or "[STARTUP_REG_NO]",
                                "{{STARTUP_VALID_UPTO}}": user_inputs.get("startup_valid_upto") or "[STARTUP_VALID_UPTO]",
                                "{{GSTIN}}": statutory.get("gstin") or "[GSTIN]",
                                "{{PAN}}": statutory.get("pan") or "[PAN]",
                                "{{BANK_NAME}}": statutory.get("bank_name") or "[BANK_NAME]",
                                "{{BANK_BRANCH}}": statutory.get("bank_branch") or "[BANK_BRANCH]",
                                "{{ACCOUNT_NUMBER}}": statutory.get("account_number") or "[ACCOUNT_NUMBER]",
                                "{{IFSC_CODE}}": statutory.get("ifsc_code") or "[IFSC_CODE]",
                                "{{MICR_CODE}}": statutory.get("micr_code") or "[MICR_CODE]",
                            }
                            sig_name = user_inputs.get("signatory_name", "")
                            sig_path = get_signature_path(company_name, sig_name)
                            fill_docx_template(src_file, dest_path, replacements, signature_path=sig_path, company_data=company_data)
                            final_path = convert_to_pdf_if_docx(dest_path)
                            generated_pdf_paths.append(final_path)
                            print(f"  => Generated document to {final_path.name}")
                        found = True
                    elif entry.get("category") == "C":
                        # Dynamic format saved from previous GCC extractions
                        print(f"  [+] Found dynamic text format for {canonical_id}")
                        if not dry_run:
                            try:
                                with open(src_file, 'r', encoding='utf-8') as f:
                                    raw_text = f.read()
                                
                                from app.internal.intake.gcc_generator import generate_custom_doc_from_text
                                company_data = load_company_data(company_name)
                                documents_dir = get_docs_dir(company_name)
                                sig_name = user_inputs.get("signatory_name", "")
                                sig_path = get_signature_path(company_name, sig_name)
                                
                                dest_docx = tender_out_dir / f"{dest_filename.replace('.txt', '')}.docx"
                                generated_docx, req_lh, filled_txt = generate_custom_doc_from_text(
                                    raw_text, tender_no, user_inputs, company_data, dest_docx, letterhead_path, sig_path
                                )
                                final_pdf = convert_to_pdf_if_docx(generated_docx)
                                generated_pdf_paths.append(final_pdf)
                                print(f"  => Generated dynamic document to {final_pdf.name}")
                                found = True
                            except Exception as e:
                                print(f"  [!] Failed to generate from dynamic template: {e}")
                                notes.append(f"{canonical_id}: failed to generate")
                        else:
                            found = True
                            
                    else:
                        print(f"  => Unknown category handling.")
                        notes.append("not properly discription")
                else:
                    print(f"  [!] Missing file in company library: {entry['filename_hint']}")
                    notes.append(f"{canonical_id}: document not find")
                    
            sub_idx += 1
                
        # Now append any manual extra PDFs/DOCX uploaded by the user for this row
        if str(key) in extra_pdfs:
            for manual_file_path in extra_pdfs[str(key)]:
                manual_path = Path(manual_file_path)
                if manual_path.suffix.lower() in ('.docx', '.doc'):
                    # Fill template placeholders and convert to PDF
                    company_data = load_company_data(company_name)
                    company = company_data.get("company", {})
                    signatory = company_data.get("signatory", {})
                    statutory = company_data.get("statutory", {})
                    
                    replacements = {
                        "{{COMPANY_NAME}}": user_inputs.get("company_name") or company.get("legal_name", "[COMPANY_NAME]"),
                        "{{DIVISION}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                        "{{DIVISON}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                        "{{RAILWAY}}": user_inputs.get("railway") or "[RAILWAY/DIVISION]",
                        "{{TENDER_NO}}": user_inputs.get("tender_no") or tender_no or "[TENDER_NO]",
                        "{{TENDER_NAME}}": user_inputs.get("tender_name") or "[TENDER_NAME]",
                        "{{PLACE}}": user_inputs.get("place") or company.get("registered_address", "Ahmedabad"),
                        "{{DATE}}": user_inputs.get("closing_date") or str(datetime.date.today().strftime("%d/%m/%Y")),
                        "{{DAYS}}": user_inputs.get("days") or "30",
                        "{{SIGNATORY_NAME}}": user_inputs.get("signatory_name") or signatory.get("name", "[SIGNATORY_NAME]"),
                        "{{SIGNATORY_DESIGNATION}}": user_inputs.get("signatory_designation") or signatory.get("designation", "[DESIGNATION]"),
                        "{{ISSUING_AUTHORITY}}": user_inputs.get("issuing_authority") or "[ISSUING_AUTHORITY]",
                        "{{BID_SECURITY_AMOUNT}}": user_inputs.get("bid_security_amount") or "[BID_SECURITY_AMOUNT]",
                        "{{EXECUTE_CONTRACT_DAYS}}": user_inputs.get("execute_contract_days") or "7",
                        "{{COMMENCE_WORK_DAYS}}": user_inputs.get("commence_work_days") or "15",
                        "{{STARTUP_DEPT}}": user_inputs.get("startup_dept") or "[STARTUP_DEPT]",
                        "{{STARTUP_REG_NO}}": user_inputs.get("startup_reg_no") or "[STARTUP_REG_NO]",
                        "{{STARTUP_VALID_UPTO}}": user_inputs.get("startup_valid_upto") or "[STARTUP_VALID_UPTO]",
                        "{{GSTIN}}": statutory.get("gstin") or "[GSTIN]",
                    }
                    tmp_filled = manual_path.parent / f"_filled_{manual_path.name}"
                    sig_name = user_inputs.get("signatory_name", "")
                    sig_path = get_signature_path(company_name, sig_name)
                    fill_docx_template(manual_path, tmp_filled, replacements, signature_path=sig_path, company_data=company_data)
                    manual_path = convert_to_pdf_if_docx(tmp_filled)
                generated_pdf_paths.append(manual_path)
                found = True

                
        if not dry_run and generated_pdf_paths:
            do_combine = False
            if _is_annex_v_and_va:
                do_combine = True
            elif combine_flags and combine_flags.get(str(key)):
                do_combine = True
            elif len(generated_pdf_paths) > 1:
                do_combine = True
                
            if len(generated_pdf_paths) == 1 or not do_combine:
                for sub_i, single_doc in enumerate(generated_pdf_paths):
                    try:
                        if single_doc.parent != tender_out_dir:
                            import re
                            base_n = f"{(idx + 1):02d}_" + re.sub(r'[\\/*?:"<>|]', '', str(line))[:30].strip()
                            if len(generated_pdf_paths) > 1:
                                base_n += f"_{sub_i+1}"
                            dest_path = tender_out_dir / f"{base_n}{single_doc.suffix}"
                            shutil.copy(single_doc, dest_path)
                            upload_nums.append(dest_path.name)
                        else:
                            if len(generated_pdf_paths) > 1:
                                dest_path = tender_out_dir / f"{(idx + 1):02d}_{single_doc.stem}_{sub_i+1}{single_doc.suffix}"
                                shutil.move(single_doc, dest_path)
                                upload_nums.append(dest_path.name)
                            else:
                                upload_nums.append(single_doc.name)
                    except Exception:
                        upload_nums.append(single_doc.name)
            else:
                import fitz
                import re
                # Use a descriptive name for the special Annexure-V + V(A) combined pair
                if _is_annex_v_and_va:
                    merged_base = f"{(idx + 1):02d}_AnnexureV_and_VA"
                elif is_excel:
                    merged_base = f"{(idx + 1):02d}_Merged_" + re.sub(r'[\\/*?:"<>|]', '', str(line))[:30].strip()
                else:
                    merged_base = f"{(idx + 1):02d}_Merged_" + re.sub(r'[\\/*?:"<>|]', '', str(line))[:30].strip()
                    
                merged_pdf_path = tender_out_dir / f"{merged_base}.pdf"
                    
                try:
                    doc_result = fitz.open()
                    for pdf_path in generated_pdf_paths:
                        doc = fitz.open(str(pdf_path))
                        doc_result.insert_pdf(doc)
                        doc.close()
                    doc_result.save(str(merged_pdf_path), garbage=4, deflate=True)
                    doc_result.close()
                    
                    # User requested: "at the end you have to give merged doc only not the seprate... no need to give sepate"
                    # So we intentionally DO NOT copy individual files here anymore.
                    
                    max_mb = 7.5
                    if os.path.exists(str(merged_pdf_path)) and os.path.getsize(str(merged_pdf_path)) > max_mb * 1024 * 1024:
                        print(f"  => Compressing {merged_pdf_path.name} to fit under {max_mb}MB...")
                        temp_path = str(merged_pdf_path) + ".tmp.pdf"
                        try:
                            old_doc = fitz.open(str(merged_pdf_path))
                            new_doc = fitz.open()
                            mat = fitz.Matrix(1.5, 1.5)
                            for page in old_doc:
                                pix = page.get_pixmap(matrix=mat, alpha=False)
                                img_bytes = pix.tobytes("jpeg")
                                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                                new_page.insert_image(new_page.rect, stream=img_bytes)
                            new_doc.save(temp_path, garbage=4, deflate=True)
                            new_doc.close()
                            old_doc.close()
                            if os.path.getsize(temp_path) > max_mb * 1024 * 1024:
                                old_doc = fitz.open(temp_path)
                                new_doc = fitz.open()
                                mat = fitz.Matrix(1.0, 1.0)
                                for page in old_doc:
                                    pix = page.get_pixmap(matrix=mat, alpha=False)
                                    img_bytes = pix.tobytes("jpeg")
                                    new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                                    new_page.insert_image(new_page.rect, stream=img_bytes)
                                new_doc.save(temp_path, garbage=4, deflate=True)
                                new_doc.close()
                                old_doc.close()
                            shutil.move(temp_path, str(merged_pdf_path))
                        except Exception as e:
                            print(f"  [!] Compression failed: {e}")
                        
                    upload_nums.append(merged_pdf_path.name)
                    print(f"  => Merged {len(generated_pdf_paths)} documents into {merged_pdf_path.name}")
                        
                    # Delete the individual generated files if they are in tender_out_dir
                    for pdf_path in generated_pdf_paths:
                        try:
                            if pdf_path.parent == tender_out_dir:
                                pdf_path.unlink()
                        except:
                            pass
                except Exception as e:
                    print(f"  [!] Failed to merge PDFs: {e}")
                    for pdf_path in generated_pdf_paths:
                        upload_nums.append(pdf_path.name)
                
        results[key] = {
            "found": found, 
            "notes": " | ".join(notes), 
            "upload_num": ", ".join(upload_nums), 
            "needs_info": needs_info
        }
        print("")
        
    if not dry_run:
        print(f"Done! Prepared in:\n{tender_out_dir}")
    return results, list(missing_fields), proposed_merges, needs_gcc_list, needs_letterhead

def main():
    parser = argparse.ArgumentParser(description="Tender Requirement Intake (Phase 2)")
    parser.add_argument("file_path", help="Path to .xlsx or .pdf file")
    parser.add_argument("--tender-no", help="Provide Tender No (Required for Excel)", default=None)
    parser.add_argument("--tender-name", help="Provide Tender Name (Optional)", default="")
    args = parser.parse_args()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    catalog = load_catalog()
    file_path = Path(args.file_path)
    
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return
        
    ext = file_path.suffix.lower()
    
    if ext == ".pdf":
        print(f"Processing NIT PDF: {file_path}")
        tender_no, requirements, parsed_data = parse_nit_pdf(str(file_path), api_key)
        if not tender_no:
            print("Failed to extract Tender No from PDF. Please provide it manually.")
            tender_no = input("Enter Tender No: ").strip()
            
        print(f"Extracted Tender No: {tender_no}")
        print(f"Found {len(requirements)} mandatory requirements.")
        results, missing, proposed, needs_gcc, needs_lh = process_requirements(requirements, tender_no, catalog, is_excel=False, user_inputs={"tender_name": args.tender_name})
        
    elif ext == ".xlsx":
        print(f"Processing Excel List: {file_path}")
        tender_no = args.tender_no
        if not tender_no:
            tender_no = input("Enter Tender No: ").strip()
            
        reqs, h_row, d_col, r_col, s_col, u_col, n_col = parse_excel_requirements(str(file_path))
        print(f"Found {len(reqs)} mandatory requirements in Excel.")
        
        results, missing, proposed = process_requirements(reqs, tender_no, catalog, is_excel=True, user_inputs={"tender_name": args.tender_name})
        
        # Write back to excel
        update_excel_status(str(file_path), results, s_col, u_col, n_col)
        
        # Copy the Excel file into the folder so the user has it alongside the docs
        tender_out_dir = get_tender_out_dir(tender_no, {"tender_name": args.tender_name})
        dest_excel = tender_out_dir / f"Mapped_Requirements_{tender_no}.xlsx"
        try:
            shutil.copy(file_path, dest_excel)
            print(f"Copied Excel to {dest_excel}")
        except PermissionError:
            print(f"\n[!] ERROR: Could not copy {file_path} to {dest_excel}")
            print("Please close the Excel file if it is open in Microsoft Excel and try again.")
        
    else:
        print("Unsupported file format. Please provide .xlsx or .pdf")

if __name__ == "__main__":
    main()
