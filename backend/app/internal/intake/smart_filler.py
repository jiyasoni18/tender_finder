import os
import json
from pathlib import Path
import docx
from google import genai
from app.internal.intake.model_state import get_model_idx, increment_model_idx
import datetime

def get_all_document_names(documents_dir: Path):
    if not documents_dir or not documents_dir.exists():
        return []
    return [f.name for f in documents_dir.iterdir() if f.is_file()]

def smart_fill_docx(docx_path: str, company_data: dict, documents_dir: Path, user_inputs: dict):
    """
    Reads a DOCX, uses AI to figure out how to fill blanks, what attachments to pull,
    and if it needs a letterhead. Modifies the DOCX in place and returns metadata.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"success": False, "message": "No API key"}

    client = genai.Client(api_key=api_key)
    
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
    
    context_str = f"""
    Company Legal Name: {user_inputs.get('company_name') or company.get('legal_name', '')}
    Tender Number: {user_inputs.get('tender_no', '')}
    Tender Name: {user_inputs.get('tender_name', '')}
    Railway/Division: {user_inputs.get('railway', '')}
    Issuing Authority: {user_inputs.get('issuing_authority', '')}
    Registered Address: {user_inputs.get('place') or company.get('registered_address', '')}
    Signatory Name: {user_inputs.get('signatory_name') or signatory.get('name', '')}
    Signatory Designation: {user_inputs.get('signatory_designation') or signatory.get('designation', '')}
    Date: {datetime.date.today().strftime('%d/%m/%Y')}
    Validity (Days): {user_inputs.get('days', '')}
    Bid Security Amount: {user_inputs.get('bid_security_amount', '')}
    Execute Contract Days: {user_inputs.get('execute_contract_days', '')}
    Commence Work Days: {user_inputs.get('commence_work_days', '')}
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
1. Identify blocks of text that contain blanks (like `_________` or `<Bank Name>`) or fields that need to be filled.
2. Fill in the blanks using the following priority:
   - FIRST: Look for the information in the Document Text Blocks itself (e.g., if the document header mentions "Tender No. 1234", use "1234" to fill the Tender Number blank).
   - SECOND: Use the provided Company Context Data.
   - THIRD: If the data is truly unavailable in both the document text and the context, insert a missing tag strictly in this format: `[MISSING: <Question asking user for the info>]`. HOWEVER, if the blank explicitly says "(if applicable)", "(optional)", or similar, and the information is not provided in the context, do NOT ask the user. Instead, fill it with "N/A" or leave it blank as appropriate.
3. CRITICAL: For "Date", "Tender No.", or "Tender Name" blanks, ALWAYS fill them using the context provided (do not ask the user for them) unless they strictly require some other specific date/number not provided.

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
- Preserve the general structure of the text EXACTLY. If the original text contains newlines (`\n`), tabs (`\t`), or specific indentation, you MUST preserve them in your `new_text`. DO NOT squash multiple lines into a single line.
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
                return {"success": False, "message": "AI failed to process the document."}

    if not response_json:
        return {"success": False, "message": "No response from AI."}

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
                            p.text = rep.get("new_text", "")
                        else:
                            p.text = p.text.replace(rep.get("original_text", ""), rep.get("new_text", ""))
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
                    p.text = rep.get("new_text", "")
        except Exception as e:
            print(f"Failed to replace block: {e}")

    try:
        doc.save(docx_path)
    except Exception as e:
        return {"success": False, "message": f"Failed to save modified DOCX: {e}"}

    # Identify missing questions
    import re
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

    missing_questions = list(set(missing_questions))

    # Deterministic check for letterhead requirement instead of relying on AI
    doc_text_lower = " ".join([p.get("text", "") for p in paragraphs_text]).lower()
    needs_letterhead = "letterhead" in doc_text_lower or "letter head" in doc_text_lower

    return {
        "success": True,
        "needs_letterhead": needs_letterhead,
        "attachments": [],
        "missing_questions": missing_questions
    }
