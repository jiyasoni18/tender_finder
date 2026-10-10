import os
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from google import genai
import json
import datetime

from app.internal.intake.model_state import get_model_idx, increment_model_idx
_LOCAL_DOCS_CONTEXT = None

def get_local_docs_context(company_name=""):
    global _LOCAL_DOCS_CONTEXT
    if _LOCAL_DOCS_CONTEXT is not None:
        return _LOCAL_DOCS_CONTEXT
        
    from app.internal.intake.intake import get_docs_dir
    docs_dir = get_docs_dir(company_name)
    all_text = "=== COMPANY REFERENCE DOCUMENTS ===\n"
    if docs_dir.exists():
        import docx
        for f in docs_dir.glob("*.docx"):
            try:
                doc = docx.Document(f)
                text = f"--- Document: {f.name} ---\n"
                for p in doc.paragraphs:
                    if p.text.strip(): text += p.text.strip() + "\n"
                for table in doc.tables:
                    for row in table.rows:
                        text += " | ".join([cell.text.strip().replace("\n", " ") for cell in row.cells]) + "\n"
                all_text += text + "\n\n"
            except Exception:
                pass
    _LOCAL_DOCS_CONTEXT = all_text
    return _LOCAL_DOCS_CONTEXT

_global_model_idx = 0

def generate_custom_doc_from_text(raw_text, tender_no, user_inputs, company_data, dest_path, letterhead_path=None, sig_path=None, api_key=None):
    """
    Takes raw annexure text extracted from GCC, fills it out using company details,
    and generates a formatted Word document.
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        
    client = genai.Client(api_key=api_key)
    
    company = company_data.get("company", {})
    signatory = company_data.get("signatory", {})
    statutory = company_data.get("statutory", {})
    
    # Construct context for Gemini
    context = f"""
    Tender No: {tender_no}
    Tender Name: {user_inputs.get("tender_name", "")}
    Railway/Division: {user_inputs.get("railway", "")}
    Issuing Authority: {user_inputs.get("issuing_authority", "")}
    
    Company Legal Name: {company.get("legal_name", "")}
    Company Address: {company.get("registered_address", "")}
    
    Signatory Name: {signatory.get("name", "")}
    Signatory Designation: {signatory.get("designation", "")}
    Signatory Email: {signatory.get("email", "")}
    Signatory Phone: {signatory.get("phone", "")}
    
    GSTIN: {statutory.get("gstin", "")}
    PAN: {statutory.get("pan", "")}
    """
    
    company_name = user_inputs.get("company_name", "")
    local_docs_context = get_local_docs_context(company_name)
    
    prompt = f"""
    You are an expert legal assistant drafting documents for a tender submission.
    
    Here is the exact format of an Annexure/Form extracted from the tender's GCC:
    ---
    {raw_text}
    ---
    
    Here are our company's details and the tender information:
    ---
    {context}
    ---
    
    Here is the data from our local company documents (such as Work in Hand, Completed Works, Court Cases, etc). 
    USE THIS DATA to accurately fill out any tables or fields that ask for this information!
    {local_docs_context}
    
    Your task:
    1. Fill out the Annexure text completely. Replace ALL blank lines (like ____ or .....), placeholders (like [Name], (Name of Firm)), and variable fields with the correct information from our company details OR from the local company documents provided above. IF the raw text provided is just a short descriptive paragraph (e.g. "Submit a declaration for XYZ") and not an actual format, YOU MUST CREATE a professional, properly formatted Declaration from scratch based on that description.
    2. Dates: Whenever a "Date" or "Date of effect" or similar is requested and left blank, ALWAYS fill it with `{datetime.date.today().strftime('%d/%m/%Y')}`. Do not ask the user for dates.
    3. ONLY if a specific piece of information (like Age, Emolument, Name of Personnel, etc.) is completely missing from BOTH our company details AND the local company documents, replace that blank with a clear tag exactly like this: [MISSING: description of missing info]. Do not invent facts or random data.
    4. Signatures: You MUST include the final signatory block (Name, Designation, Signature lines, Company Name) at the bottom of the document. If it is missing from the original format, YOU MUST add it properly at the bottom. Our software will search for the word "Signature" in your output and automatically stamp the company's signature image there.
    5. Format the output professionally. Preserve all line breaks (`\n`), indentation, and tabular structures exactly as they appear in the raw text. Do not squash signature blocks or multiline text into a single line.
    
    Respond ONLY with a JSON object in this exact format, with no markdown code blocks:
    {{
        "blocks": [
            {{
                "type": "paragraph",
                "text": "The text of a single paragraph here."
            }},
            {{
                "type": "table",
                "headers": ["Col1", "Col2", "Col3"],
                "rows": [
                    ["Row1Val1", "Row1Val2", "Row1Val3"],
                    ["Row2Val1", "Row2Val2", "Row2Val3"]
                ]
            }}
        ]
    }}
    IMPORTANT: You must structure the document into blocks. Use "paragraph" for regular text and "table" for any tabular data. 
    Preserve all tables found in the raw annexure format! Fill the tables with data from the company reference documents.
    """
    
    def call_gemini_with_retry(client, prompt, max_retries=6):
        models = ['gemini-3.1-flash-lite', 'gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.7-flash']
        
        for attempt in range(max_retries):
            current_model = models[get_model_idx() % len(models)]
            try:
                return client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                )
            except Exception as e:
                error_str = str(e)
                if any(err in error_str for err in ["429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND", "503", "UNAVAILABLE", "500", "INTERNAL"]):
                    if attempt == max_retries - 1:
                        raise e
                    print(f"  [Auto-Fix Success] Google Free Tier limit hit on {current_model}. Seamlessly bypassing and shifting to next model...")
                    increment_model_idx()
                else:
                    raise e
                    
    try:
        response = call_gemini_with_retry(client, prompt)
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        data = json.loads(result_text.strip())
        blocks = data.get("blocks", [])
        
    except Exception as e:
        print(f"Error calling Gemini to fill GCC format: {e}")
        blocks = [{"type": "paragraph", "text": p} for p in raw_text.split('\n') if p.strip()]

    # Deterministic check for letterhead requirement
    requires_letterhead = "letterhead" in raw_text.lower() or "letter head" in raw_text.lower()
        
    # Create Document
    doc = Document()
    
    # Insert Letterhead if required and available
    if requires_letterhead and letterhead_path and Path(letterhead_path).exists():
        try:
            section = doc.sections[0]
            header = section.header
            header_para = header.paragraphs[0]
            run = header_para.add_run()
            run.add_picture(str(letterhead_path), width=Inches(6.0)) # Adjust width as needed
        except Exception as e:
            print(f"Failed to insert letterhead: {e}")
            
    # Add the filled text via blocks
    for block in blocks:
        btype = block.get("type")
        if btype == "paragraph":
            text = block.get("text", "").strip()
            if text:
                p = doc.add_paragraph(text)
                if any(kw in text.lower() for kw in ["signature", "signatory", "seal"]):
                    if sig_path and Path(sig_path).exists():
                        try:
                            r = p.add_run()
                            r.add_break()
                            r.add_picture(str(sig_path), width=Inches(1.5))
                        except Exception as e:
                            print(f"Failed to insert signature: {e}")
        elif btype == "table":
            headers = block.get("headers", [])
            rows = block.get("rows", [])
            
            num_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
            if num_cols > 0:
                table = doc.add_table(rows=0, cols=num_cols)
                table.style = 'Table Grid'
                
                if headers:
                    hdr_cells = table.add_row().cells
                    for i, hdr in enumerate(headers):
                        if i < len(hdr_cells):
                            hdr_cells[i].text = str(hdr)
                
                for row_data in rows:
                    row_cells = table.add_row().cells
                    for i, val in enumerate(row_data):
                        if i < len(row_cells):
                            cell_text = str(val)
                            row_cells[i].text = cell_text
                            if any(kw in cell_text.lower() for kw in ["signature", "signatory", "seal"]):
                                if sig_path and Path(sig_path).exists():
                                    try:
                                        p = row_cells[i].paragraphs[0]
                                        r = p.add_run()
                                        r.add_break()
                                        r.add_picture(str(sig_path), width=Inches(1.5))
                                    except Exception as e:
                                        print(f"Failed to insert signature in table: {e}")
                doc.add_paragraph() # spacing after table
    
    # Save document
    doc.save(str(dest_path))
    return dest_path, requires_letterhead, ""
