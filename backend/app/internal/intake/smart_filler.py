import os
import json
from pathlib import Path
import docx
from google import genai
from app.internal.intake.model_state import get_model_idx, increment_model_idx
import datetime

from dotenv import load_dotenv
load_dotenv(override=True)

def get_all_document_names(documents_dir: Path):
    if not documents_dir or not documents_dir.exists():
        return []
    return [f.name for f in documents_dir.iterdir() if f.is_file()]

def smart_fill_docx(docx_path: str, company_data: dict, documents_dir: Path, user_inputs: dict, extra_answers: dict = None):
    """
    Reads a DOCX, uses AI to figure out how to fill blanks, what attachments to pull,
    and if it needs a letterhead. Modifies the DOCX in place and returns metadata.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else None
    
    try:
        doc = docx.Document(docx_path)
    except Exception as e:
        return {"success": False, "message": f"Could not read DOCX: {e}"}

    # Extract all text to send to AI
    paragraphs_text = []
    for i, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        if text:
            paragraphs_text.append({"type": "p", "index": i, "text": text})

    for t_idx, table in enumerate(doc.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                for p_idx, p in enumerate(cell.paragraphs):
                    text = p.text.strip()
                    if text:
                        paragraphs_text.append({
                            "type": "cell", 
                            "t_idx": t_idx, 
                            "r_idx": r_idx, 
                            "c_idx": c_idx, 
                            "p_idx": p_idx, 
                            "text": text
                        })

    doc_text_json = json.dumps(paragraphs_text, indent=2)
    available_docs = get_all_document_names(documents_dir)
    
    # Format company data for the prompt
    company = company_data.get("company", {})
    signatory = company_data.get("signatory", {})
    statutory = company_data.get("statutory", {})
    
    issuing_auth = user_inputs.get('issuing_authority') or user_inputs.get('railway', '')
    railway_val = user_inputs.get('railway') or issuing_auth
    
    context_str = f"""
    Company Legal Name: {user_inputs.get('company_name') or company.get('legal_name', '')}
    Tender Number: {user_inputs.get('tender_no', '')}
    Tender Name: {user_inputs.get('tender_name', '')}
    Railway/Division: {railway_val}
    Issuing Authority / Office: {issuing_auth}
    Place / City: Ahmedabad
    Registered Address: {company.get('registered_address', '')}
    Signatory Name: {user_inputs.get('signatory_name') or signatory.get('name', '')}
    Signatory Designation: {user_inputs.get('signatory_designation') or signatory.get('designation', '')}
    Date: {datetime.date.today().strftime('%d/%m/%Y')}
    Validity (Days): {user_inputs.get('days', '30')}
    Bid Security Amount: {user_inputs.get('bid_security_amount', '')}
    Execute Contract Days: {user_inputs.get('execute_contract_days', '7')}
    Commence Work Days: {user_inputs.get('commence_work_days', '15')}
    Tender Closing Date: {user_inputs.get('closing_date', '')}
    DIPP / Startup Registration Number: {user_inputs.get('startup_reg_no', '')}
    DIPP / Startup Validity Date: {user_inputs.get('startup_valid_upto', '')}
    GSTIN: {statutory.get('gstin', '')}
    PAN: {statutory.get('pan', '')}
    Bank Name: {statutory.get('bank_name', '')}
    Bank Branch: {statutory.get('bank_branch', '')}
    Account Number: {statutory.get('account_number', '')}
    IFSC Code: {statutory.get('ifsc_code', '')}
    MICR Code: {statutory.get('micr_code', '')}
    """

    prompt = f"""
You are an expert legal document assistant. I am providing you with the extracted text blocks of a blank form (Annexure).
Your task is to:
1. Identify blocks of text that contain blanks (such as `_________`, dotted lines `………………` or `.............`, or `<Bank Name>`) or fields that need to be filled.
2. CRITICAL - PRESERVE EXACT WORDING:
   DO NOT REWRITE, CHANGE, OR REPHRASE ANY LEGAL DECLARATIONS, STATUTORY TEXT, OR CLAUSES (e.g. Code of Integrity under Rule 175, Debarment under Rule 151, Prevention of Corruption Act, EPF Act, etc.).
   Keep the exact wording and structure of the original form verbatim. ONLY fill in the blanks/placeholders.
3. Fill in the blanks using the following priority:
   - FIRST: Look for the information in the Document Text Blocks itself (e.g., if the document header mentions "Tender No. 1234", use "1234" to fill the Tender Number blank).
   - SECOND: Use the provided Company Context Data.
   - THIRD: If the data is truly unavailable in both the document text and the context, insert a missing tag strictly in this format: `[MISSING: <Question asking user for the info>]`. HOWEVER, if the blank explicitly says "(if applicable)", "(optional)", or similar, and the information is not provided in the context, do NOT ask the user. Instead, fill it with "N/A" or leave it blank as appropriate.
4. SPECIFIC GUIDANCE FOR COMMON BLANKS:
   - "I…………………………………….(authorized signatory)" or "I……………………(authorized signatory)": ALWAYS fill as `I, {user_inputs.get('signatory_name') or signatory.get('name', '')}, {user_inputs.get('signatory_designation') or signatory.get('designation', '')}, (authorized signatory)`
   - "I…………………………………….(name of the contractor/ agency)": ALWAYS fill as `I, {user_inputs.get('signatory_name') or signatory.get('name', '')}, {user_inputs.get('signatory_designation') or signatory.get('designation', '')}, for and on behalf of {user_inputs.get('company_name') or company.get('legal_name', '')} (name of the contractor/ agency)`
   - "M/S ____________________" or "M/S ………………": ALWAYS fill as `M/S {user_inputs.get('company_name') or company.get('legal_name', '')}`
   - "item/job of ____________________": ALWAYS fill with Tender Name ({user_inputs.get('tender_name', '')})
   - EMD / Tender document cost blanks (e.g. `enclosed a DD/Cheque/RTGS/BG for Rs………… bearing No………… Transaction Ref/UTR no…… dated………… of (Bank name & Branch)…………`):
     If Bid Security / EMD is Exempted, Not Required, or 0, fill as: `enclosed a DD/Cheque/RTGS/BG for Rs. Nil (Exempted - MSE / Startup) bearing No. N/A Transaction Ref/UTR no. N/A dated {user_inputs.get('closing_date') or datetime.date.today().strftime('%d/%m/%Y')} of (Bank name & Branch) N/A (Exempted) towards the cost of E-Tender document along with the EMD.`
   - Previous transgressions / debarment lists (e.g. under Rule 175 Code of Integrity: `(a)`, `(b)`): ALWAYS fill as `(a) NIL` and `(b) NIL` (the bidder has no previous transgressions).
   - NEVER leave trailing dots on dates or lines (e.g. `Date: 15/10/2026……` MUST be cleanly written as `Date: 15/10/2026`).
5. CRITICAL FIELD FILLING (NEVER leave [MISSING: ...] for these fields):
   - "Issuing Authority" or "office of..." or "office of the...": ALWAYS fill using Issuing Authority / Office ({issuing_auth}) or Railway ({railway_val}).
   - "Railway" / "Division": ALWAYS fill using Railway/Division ({railway_val}).
   - "Date": ALWAYS fill with {datetime.date.today().strftime('%d/%m/%Y')} or the tender date from context.
   - "Tender No." / "Tender Number": ALWAYS fill using Tender Number from context.
   - "Tender Name" / "Name of Work": ALWAYS fill using Tender Name from context.
   - "Place" / "Location" / "Place:": ALWAYS fill with "Ahmedabad" (the bidder's signing city). NEVER use the tender location, work site, or railway location for Place:. Place MUST ALWAYS be "Ahmedabad".
   - "Signatory" / "Company Name" / "Address": ALWAYS fill from the Company Context Data.
6. CRITICAL RULES FOR LOWER PART / SIGNATORY / SIGNATURE BLOCK:
   - For the lower part (signatory block / signature section at the bottom of the document):
     * ONLY the following fields are needed:
       - Signature (leave as "Signature:" or blank line for signature)
       - Name: {user_inputs.get('signatory_name') or signatory.get('name', '')}
       - Designation / Position: {user_inputs.get('signatory_designation') or signatory.get('designation', '')}
       - Date: {user_inputs.get('closing_date') or datetime.date.today().strftime('%d/%m/%Y')}
       - Place: Ahmedabad
     * STRICTLY DO NOT ask for, require, or insert `[MISSING: ...]` for Email Address, Mobile No., Phone, Telephone, Fax, or Contact details.
     * If the original document contains lines like "Email Address: _______", "Mobile No.: _______", "Telephone: _______", leave them completely blank, omit them, or write "N/A". NEVER create [MISSING: What is the email address?] or [MISSING: What is the mobile number?].
     * DO NOT write `[Signature of ...]`. For signature lines, write `Signature:` or leave blank for signature.

Company Context Data:
{context_str}

Document Text Blocks:
{doc_text_json}

Return ONLY a valid JSON object with the following structure:
{{
    "replacements": [
        {{
            "type": "p", // or "cell" based on the input
            "index": 0, // only if type is "p"
            "t_idx": 0, "r_idx": 0, "c_idx": 0, "p_idx": 0, // only if type is "cell"
            "original_text": "Exact original text of the block",
            "new_text": "Text with blanks filled or [MISSING: ...] tags inserted"
        }}
    ]
}}

Rules for replacements:
- ONLY include blocks that ACTUALLY require changes. Do not include blocks that don't have blanks.
- The `new_text` will completely replace the `original_text` in that specific paragraph/cell, so ensure you provide the FULL paragraph text, not just the filled value.
- Preserve the general structure of the text EXACTLY. If the original text contains newlines (`\\n`), tabs (`\\t`), or specific indentation, you MUST preserve them in your `new_text`. DO NOT squash multiple lines into a single line.
- CRITICAL: DO NOT use any Markdown formatting in your response for `new_text` (such as `|` for tables, `**` for bold, or `<br>` for line breaks). You are replacing text inside an existing Microsoft Word document paragraph or table cell. You must return only the exact plain text string.
- CRITICAL: NEVER write the word "missing", "blank", or "N/A" by itself when data is unavailable. You MUST strictly use the exact format `[MISSING: <Question>]` (e.g. `[MISSING: What is the tender name?]`). Failure to use this exact bracket format will break the system.
"""

    models = ['gemini-3.1-flash-lite', 'gemini-3.5-flash-lite', 'gemini-3.5-flash']
    
    response_json = None
    for attempt in range(6):
        current_model = models[get_model_idx() % len(models)]
        try:
            resp = client.models.generate_content(
                model=current_model,
                contents=prompt,
            )
            resp_text = resp.text.strip()
            if resp_text.startswith("```json"):
                resp_text = resp_text[7:]
            if resp_text.endswith("```"):
                resp_text = resp_text[:-3]
                
            response_json = json.loads(resp_text)
            break
        except Exception as e:
            error_str = str(e)
            if any(err in error_str for err in ["429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND", "503", "UNAVAILABLE", "500", "INTERNAL"]):
                increment_model_idx()
            elif attempt == 5:
                print(f"Failed to parse Gemini response: {e}")
                response_json = {"replacements": []}

    if not response_json:
        response_json = {"replacements": []}

    def safe_set_paragraph_text(p, new_text):
        has_drawing = bool(p._element.xpath('.//w:drawing') or p._element.xpath('.//w:pict') or p._element.xpath('.//a:blip'))
        if not has_drawing:
            if p.text != new_text:
                p.text = new_text
            return
        # Paragraph has drawings/signature! NEVER wipe out child elements
        text_runs = [r for r in p.runs if not (r._element.xpath('.//w:drawing') or r._element.xpath('.//w:pict') or r._element.xpath('.//a:blip'))]
        if not text_runs:
            return
        text_runs[0].text = new_text
        for r in text_runs[1:]:
            r.text = ""

    # Apply replacements
    for rep in response_json.get("replacements", []):
        try:
            if rep["type"] == "p":
                idx = rep["index"]
                if 0 <= idx < len(doc.paragraphs):
                    p = doc.paragraphs[idx]
                    orig = rep.get("original_text", "").strip()
                    if orig and (p.text.strip() == orig or orig in p.text.strip()):
                        if p.text.strip() == orig:
                            safe_set_paragraph_text(p, rep.get("new_text", ""))
                        else:
                            new_val = p.text.replace(rep.get("original_text", ""), rep.get("new_text", ""))
                            safe_set_paragraph_text(p, new_val)
            elif rep["type"] == "cell":
                t_idx = rep["t_idx"]
                r_idx = rep["r_idx"]
                c_idx = rep["c_idx"]
                p_idx = rep["p_idx"]
                
                table = doc.tables[t_idx]
                row = table.rows[r_idx]
                cell = row.cells[c_idx]
                p = cell.paragraphs[p_idx]
                
                if p.text.strip() == rep.get("original_text", "").strip():
                    safe_set_paragraph_text(p, rep.get("new_text", ""))
        except Exception as e:
            print(f"Failed to replace block: {e}")

    # Auto-resolve any authority, railway, or tender fields if Gemini mistakenly inserted a MISSING tag
    import re
    auth_val = issuing_auth
    rail_val = railway_val
    t_no_val = user_inputs.get('tender_no', '')
    t_name_val = user_inputs.get('tender_name', '')
    date_val = user_inputs.get('closing_date') or datetime.date.today().strftime('%d/%m/%Y')
    place_val = 'Ahmedabad'
    sig_name = user_inputs.get('signatory_name') or signatory.get('name', '')
    sig_desig = user_inputs.get('signatory_designation') or signatory.get('designation', '')
    comp_name = user_inputs.get('company_name') or company.get('legal_name', '')
    emd_amount = str(user_inputs.get('bid_security_amount', '')).strip()
    is_emd_exempt = not emd_amount or any(term in emd_amount.lower() for term in ["exempt", "not required", "nil", "0", "waiver", "mse", "startup"])

    def resolve_text(text: str) -> str:
        if not text:
            return text
        if extra_answers:
            for q_k, ans_v in extra_answers.items():
                if ans_v:
                    clean_k = re.escape(q_k.strip().strip("[]?"))
                    text = re.sub(rf'\[MISSING:\s*.*?' + clean_k + r'.*?\]', str(ans_v), text, flags=re.IGNORECASE)
                    if q_k in text:
                        text = text.replace(q_k, str(ans_v))
        if auth_val:
            text = re.sub(r'\[MISSING:\s*.*?(?:issuing authority|authority|office).*?\]', auth_val, text, flags=re.IGNORECASE)
        if rail_val:
            text = re.sub(r'\[MISSING:\s*.*?(?:railway|division).*?\]', rail_val, text, flags=re.IGNORECASE)
        if t_no_val:
            text = re.sub(r'\[MISSING:\s*.*?(?:tender no|tender number).*?\]', t_no_val, text, flags=re.IGNORECASE)
        if t_name_val:
            text = re.sub(r'\[MISSING:\s*.*?(?:tender name|name of work).*?\]', t_name_val, text, flags=re.IGNORECASE)
        if date_val:
            text = re.sub(r'\[MISSING:\s*.*?(?:date|closing date).*?\]', date_val, text, flags=re.IGNORECASE)
        if place_val:
            text = re.sub(r'\[MISSING:\s*.*?(?:place|location).*?\]', place_val, text, flags=re.IGNORECASE)
            text = re.sub(r'\{\{\s*place\s*\}\}', place_val, text, flags=re.IGNORECASE)
            text = re.sub(r'\[\s*place\s*\]', place_val, text, flags=re.IGNORECASE)
            text = re.sub(r'<\s*place\s*>', place_val, text, flags=re.IGNORECASE)
            text = re.sub(r'(?i)(\bplace\s*:\s*)(?:(?!\bdate\b)[^\n\r\t])*(?=\bdate\b)', r'\g<1>' + place_val + '    ', text)
            text = re.sub(r'(?i)(\bplace\s*:\s*)(?:(?!\bdate\b)[^\n\r\t])*', r'\g<1>' + place_val, text)
            text = re.sub(r'(?i)(\bplace\s*:\s*)(?:' + place_val + r'\s*)+', r'Place: ' + place_val + ' ', text)

        # Signatory blank e.g. "I…………………………………….(authorized signatory)" or "I……………………(authorized signatory)"
        if sig_name:
            sig_intro = f"I, {sig_name}" + (f", {sig_desig}" if sig_desig else "")
            text = re.sub(r'I\s*[\.ـ_…]{3,}\s*\((?:authorized signatory|signatory|authorized)\)', f'{sig_intro}, (authorized signatory)', text, flags=re.IGNORECASE)
            text = re.sub(r'I\s*[\.ـ_…]{3,}\s*(?=hereby\s+declare|hereby\s+certify|hereby\s+state)', f'{sig_intro}, ', text, flags=re.IGNORECASE)
            if comp_name:
                text = re.sub(r'I\s*[\.ـ_…]{3,}\s*\((?:name of the contractor\/ agency|name of the contractor|name of contractor\/agency|contractor)\)', f'{sig_intro}, for and on behalf of {comp_name} (name of the contractor/ agency)', text, flags=re.IGNORECASE)

        # Signatory name & capacity replacements (e.g. "Name : ________________", "(Name of the Authorized Signatory)", "In the capacity of : _____________")
        if sig_name:
            text = re.sub(r'\(\s*Name of the (?:Authorized\s+)?Signatory\s*\)', f'{sig_name}', text, flags=re.IGNORECASE)
            text = re.sub(r'(?i)\bName\s*(?:of\s*(?:the\s*)?(?:authorized\s*signatory|signatory|tenderer))\s*:\s*[\.ـ_…_]{2,}', f'Name : {sig_name}', text)
            text = re.sub(r'(?i)\bName\s*(?:of\s*(?:the\s*)?(?:authorized\s*signatory|signatory|tenderer))\s*:\s*$', f'Name : {sig_name}', text, flags=re.MULTILINE)
            text = re.sub(r'(?i)\bName\s*:\s*[\.ـ_…_]{2,}', f'Name : {sig_name}', text)
            text = re.sub(r'(?i)\bName\s*:\s*$', f'Name : {sig_name}', text, flags=re.MULTILINE)

        if sig_desig:
            text = re.sub(r'(?i)\b(?:In\s+the\s+capacity\s+of|Designation)\s*:\s*[\.ـ_…_]{2,}', f'In the capacity of : {sig_desig}', text)
            text = re.sub(r'(?i)\b(?:In\s+the\s+capacity\s+of|Designation)\s*:\s*$', f'In the capacity of : {sig_desig}', text, flags=re.MULTILINE)
            text = re.sub(r'\(\s*(?:Capacity|Designation)\s+of\s+the\s+(?:Authorized\s+)?Signatory\s*\)', f'{sig_desig}', text, flags=re.IGNORECASE)

        if comp_name:
            text = re.sub(r'(?i)\b(?:Duly\s+authorized\s+to\s+sign\s+(?:the\s+bid\s+)?for\s+and\s+)?on\s+behalf\s+of\s*:\s*[\.ـ_…_]{2,}', f'on behalf of : {comp_name}', text)
            text = re.sub(r'(?i)\b(?:Duly\s+authorized\s+to\s+sign\s+(?:the\s+bid\s+)?for\s+and\s+)?on\s+behalf\s+of\s*:\s*$', f'on behalf of : {comp_name}', text, flags=re.MULTILINE)
            text = re.sub(r'(?i)\bName\s+of\s+(?:the\s+)?(?:Firm|Company|Bidder|Agency)\s*:\s*[\.ـ_…_]{2,}', f'Name of the Firm: {comp_name}', text)
            text = re.sub(r'(?i)\bName\s+of\s+(?:the\s+)?(?:Firm|Company|Bidder|Agency)\s*:\s*$', f'Name of the Firm: {comp_name}', text, flags=re.MULTILINE)

        # Company blank e.g. "M/S ________________" or "M/S ………………"
        if comp_name:
            text = re.sub(r'(?:M\/S|M\/s|M\/s\.)\s*[\.ـ_…]{3,}', f'M/S {comp_name}', text)
            text = re.sub(r'(?i)\bName of the\s*(?:e-)?Tenderer\s*:\s*[\.ـ_…]+', f'Name of the e-Tenderer: {comp_name}', text)
            text = re.sub(r'(?i)\bName of the\s*(?:e-)?Tenderer\s*:\s*$', f'Name of the e-Tenderer: {comp_name}', text, flags=re.MULTILINE)

        # Item/job blank e.g. "for the item/job of ________________"
        if t_name_val:
            text = re.sub(r'(?i)(?:item\/job\s+of|work\s+of|tender\s+for)\s*[\.ـ_…]{3,}', f'item/job of {t_name_val}', text)

        # Tender No blank e.g. "tender no. ________________"
        if t_no_val:
            text = re.sub(r'(?i)(?:tender\s+no\.?|gem\s+bid\s+no\.?)\s*[\.ـ_…]{3,}', f'Tender No. {t_no_val}', text)

        # EMD / Tender document cost blanks
        if is_emd_exempt:
            text = re.sub(r'Rs\.?\s*[\.ـ_…]{3,}', 'Rs. Nil (Exempted - MSE / Startup) ', text)
            text = re.sub(r'bearing\s+No\.?\s*[\.ـ_…]{3,}', 'bearing No. N/A ', text)
            text = re.sub(r'(?:Transaction\s+Ref\/)?UTR\s*(?:no\.?)?\s*[\.ـ_…]{3,}', 'Transaction Ref/UTR no. N/A ', text, flags=re.IGNORECASE)
            text = re.sub(r'\(Bank\s+name\s*&\s*Branch\)\s*[\.ـ_…]{3,}', '(Bank name & Branch) N/A (Exempted)', text, flags=re.IGNORECASE)
        else:
            text = re.sub(r'Rs\.?\s*[\.ـ_…]{3,}', f'Rs. {emd_amount} ', text)

        # Dates: replace "dated............" or trailing dots after a date like "15/10/2026……"
        if date_val:
            text = re.sub(r'(?i)\bdated\s*[\.ـ_…]{3,}', f'dated {date_val} ', text)
            text = re.sub(r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\s*[\.ـ_…]+', r'\g<1>', text)

        # Clean trailing dots after labels like "Seal of the e-Tenderer............", "Signature of...", "Place:..."
        text = re.sub(r'(?i)\bSeal of the\s*(?:e-)?Tenderer\s*[\.ـ_…]+', 'Seal of the e-Tenderer', text)
        text = re.sub(r'(?i)(\bplace\s*:\s*[A-Za-z\s]+?)\s*[\.ـ_…]+', r'\g<1>', text)
        text = re.sub(r'(?i)(\bSignature\s*(?:of[^:\n]+)?\s*:?)\s*[\.ـ_…]+', r'\g<1>', text)

        # Clean up transgression blanks in Code of Integrity Rule 175:
        if 'transgressions' in text.lower() or 'rule 175' in text.lower():
            text = re.sub(r'\(a\)\s*[\.ـ_…\s]*(?=\(b\))', '(a) NIL\n', text)
            text = re.sub(r'\(b\)\s*[\.ـ_…\s]*(?=\n|We undertake)', '(b) NIL\n', text)

        # Remove [Signature of ...] text placeholder
        text = re.sub(r'\[Signature\s*(?:of\s*[^\]]*)?\]', '', text, flags=re.IGNORECASE)

        # Remove any [MISSING: ...] tags for email, mobile, phone, telephone, contact, fax
        text = re.sub(r'\[MISSING:\s*.*?(?:email|mobile|phone|telephone|fax|contact).*?\]', '', text, flags=re.IGNORECASE)

        # In the lower part / signature block, remove lines asking for email or mobile
        text = re.sub(r'(?i)^\s*(?:email(?:\s*address|\s*id)?|mobile(?:\s*no\.?|\s*number|\s*num\.?)?|telephone(?:\s*no\.?|\s*number)?|phone(?:\s*no\.?|\s*number)?|contact(?:\s*no\.?|\s*number)?)\s*:.*$(?:\n)?', '', text, flags=re.MULTILINE)

        return text

    def apply_resolve_to_p(p):
        old_text = p.text
        new_text = resolve_text(old_text)
        if old_text != new_text:
            safe_set_paragraph_text(p, new_text)

    for p in doc.paragraphs:
        apply_resolve_to_p(p)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    apply_resolve_to_p(p)

    try:
        doc.save(docx_path)
    except Exception as e:
        return {"success": False, "message": f"Failed to save modified DOCX: {e}"}

    # Identify any truly remaining missing questions
    missing_questions = []
    for p in doc.paragraphs:
        matches = re.findall(r'\[MISSING:\s*(.*?)\]', p.text)
        missing_questions.extend(matches)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    matches = re.findall(r'\[MISSING:\s*(.*?)\]', p.text)
                    missing_questions.extend(matches)

    # Filter out email, mobile, phone, telephone, contact questions
    filtered = []
    for q in set(missing_questions):
        ql = q.lower()
        if any(term in ql for term in ["email", "mobile", "phone", "telephone", "fax", "contact"]):
            continue
        filtered.append(q)
    missing_questions = filtered

    # Deterministic check for letterhead requirement instead of relying on AI
    doc_text_lower = " ".join([p.get("text", "") for p in paragraphs_text]).lower()
    needs_letterhead = "letterhead" in doc_text_lower or "letter head" in doc_text_lower

    return {
        "success": True,
        "needs_letterhead": needs_letterhead,
        "attachments": [],
        "missing_questions": missing_questions
    }
