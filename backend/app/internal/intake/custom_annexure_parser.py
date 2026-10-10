import os
import json
import fitz  # PyMuPDF
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from google import genai
from app.internal.intake.model_state import get_model_idx, increment_model_idx
from google.genai import types

_global_model_idx_custom = 0

def process_custom_annexures(annexure_paths, user_inputs, tender_no, company_data, out_dir):
    """
    Takes a list of file paths (images/PDFs of blank annexures), 
    uses AI to fill them with company_data, and saves them as DOCX in out_dir.
    Returns a list of generated DOCX paths.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("No Gemini API key found. Skipping custom annexures.")
        return []
        
    client = genai.Client(api_key=api_key)
    generated_docs = []
    
    # Format company data for the prompt
    company = company_data.get("company", {})
    signatory = company_data.get("signatory", {})
    statutory = company_data.get("statutory", {})
    
    context_str = f"""
    Company Legal Name: {user_inputs.get('company_name') or company.get('legal_name', '')}
    Tender Number: {tender_no}
    Tender Name: {user_inputs.get('tender_name', '')}
    Railway/Division: {user_inputs.get('railway', '')}
    Registered Address: {user_inputs.get('place') or company.get('registered_address', '')}
    Signatory Name: {user_inputs.get('signatory_name') or signatory.get('name', '')}
    Signatory Designation: {user_inputs.get('signatory_designation') or signatory.get('designation', '')}
    GSTIN: {statutory.get('gstin', '')}
    PAN: {statutory.get('pan', '')}
    Bank Name: {statutory.get('bank_name', '')}
    Bank Branch: {statutory.get('bank_branch', '')}
    Account Number: {statutory.get('account_number', '')}
    IFSC Code: {statutory.get('ifsc_code', '')}
    MICR Code: {statutory.get('micr_code', '')}
    """
    
    for i, file_path in enumerate(annexure_paths):
        path = Path(file_path)
        if not path.exists():
            continue
            
        print(f"Processing custom annexure: {path.name}")
        images = []
        
        # If PDF, convert pages to images
        if path.suffix.lower() == '.pdf':
            try:
                doc = fitz.open(str(path))
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    pix = page.get_pixmap(dpi=150)
                    img_data = pix.tobytes("jpeg")
                    images.append(img_data)
            except Exception as e:
                print(f"Error reading PDF {path.name}: {e}")
                continue
        elif path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
            try:
                with open(str(path), 'rb') as f:
                    images.append(f.read())
            except Exception as e:
                print(f"Error reading image {path.name}: {e}")
                continue
                
        if not images:
            continue
            
        # Prepare contents for Gemini
        prompt = f"""
        You are an expert data entry and document formatting assistant.
        I am providing you with images of a blank form/annexure. 
        Your task is to:
        1. Read the form and understand its layout (headings, paragraphs, tables).
        2. FILL IN the blank fields using the context data below.
        3. Output the fully filled form as a structured JSON array.
        
        Context Data:
        {context_str}
        
        Output Requirements:
        Return ONLY a JSON array. Do not include markdown code blocks like ```json.
        The array should contain objects representing the document flow from top to bottom.
        
        Allowed Object Types:
        - {{"type": "heading", "text": "Heading Text", "level": 1}} 
          (level can be 1, 2, or 3)
        - {{"type": "paragraph", "text": "Paragraph text..."}}
        - {{"type": "table", "rows": [["Cell 1", "Cell 2"], ["Row 2", "Row 2"]]}}
          (rows is a 2D array of strings. Ensure all rows have the same number of columns)
          
        If a field in the form asks for something you have in the Context Data, fill it in the text or table cell. 
        If you don't have the data, leave it blank or as ________.
        """
        
        contents = [prompt]
        for img_data in images:
            contents.append(
                types.Part.from_bytes(
                    data=img_data,
                    mime_type='image/jpeg'
                )
            )
            
        def call_gemini_with_retry(client, contents, max_retries=6):
            models = ['gemini-3.1-flash-lite', 'gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.7-flash']
            for attempt in range(max_retries):
                current_model = models[get_model_idx() % len(models)]
                try:
                    return client.models.generate_content(
                        model=current_model,
                        contents=contents,
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
            # We use 1.5-flash since 3.1-flash-lite doesn't support structured output reliably
            response = call_gemini_with_retry(client, contents)
            
            # Clean up the response
            resp_text = response.text.strip()
            if resp_text.startswith("```json"):
                resp_text = resp_text[7:]
            if resp_text.endswith("```"):
                resp_text = resp_text[:-3]
                
            doc_struct = json.loads(resp_text)
            
            # Reconstruct as DOCX
            doc = Document()
            
            # Add Tender No at top right
            p = doc.add_paragraph(f"Tender No: {tender_no}")
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            
            for item in doc_struct:
                item_type = item.get("type")
                if item_type == "heading":
                    doc.add_heading(item.get("text", ""), level=item.get("level", 1))
                elif item_type == "paragraph":
                    doc.add_paragraph(item.get("text", ""))
                elif item_type == "table":
                    rows_data = item.get("rows", [])
                    if rows_data:
                        cols = len(rows_data[0])
                        table = doc.add_table(rows=len(rows_data), cols=cols)
                        table.style = 'Table Grid'
                        for r_idx, row_data in enumerate(rows_data):
                            row_cells = table.rows[r_idx].cells
                            for c_idx, cell_data in enumerate(row_data):
                                if c_idx < cols:
                                    row_cells[c_idx].text = str(cell_data)
                                    
            out_path = out_dir / f"Custom_{path.stem}.docx"
            doc.save(str(out_path))
            generated_docs.append(out_path)
            
        except Exception as e:
            print(f"Error generating or parsing response for {path.name}: {e}")
            
    return generated_docs
