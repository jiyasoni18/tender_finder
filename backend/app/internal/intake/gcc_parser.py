import fitz
import json
from google import genai
from dotenv import load_dotenv
import re
import time

load_dotenv(override=True)

from app.internal.intake.model_state import get_model_idx, increment_model_idx

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
def extract_form_name(line_text):
    match = re.search(r'\b(form|annexure|appendix|proforma)[ \-]?([a-z0-9]+)\b', line_text, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return line_text.strip()

def find_page_for_form(doc, line_text, api_key):
    form_name = extract_form_name(line_text)
    
    # Try ToC first
    toc = doc.get_toc()
    if toc:
        for lvl, title, page in toc:
            if form_name.lower() in title.lower():
                return page
                
    # Fallback to Gemini on the first 20 pages
    index_text = ""
    for i in range(min(20, len(doc))):
        index_text += f"--- PAGE {i+1} ---\n"
        index_text += doc[i].get_text() + "\n"
        
    clean_text = re.sub(r'--- PAGE \d+ ---', '', index_text).strip()
    if len(clean_text) < 50:
        # Scanned PDF, no text available for indexing
        return -1
        
        
    client = genai.Client(api_key=api_key)
    prompt = f"""
    You are looking for a specific form or annexure in a standard General Conditions of Contract (GCC) document's index/table of contents.
    Requirement mentioned by the tender: "{line_text}"
    
    CRITICAL INSTRUCTION: The Annexure/Form number mentioned in the requirement (e.g. "Annexure-IV") often DOES NOT match the numbering in this standard GCC document. 
    You must search the index primarily by the **meaning/description** of the required form (e.g., if the requirement asks for "works in hand", look for a title like "Details of works in hand" regardless of its Annexure number).
    
    Look through the following text (which contains the first 20 pages of the document, including the index).
    Find the page number where this specific form/annexure starts.
    Respond ONLY with the page number as an integer. If you cannot find a semantically matching form, respond with -1.
    
    Index Text:
    {index_text}
    """
    
    try:
        response = call_gemini_with_retry(client, prompt)
        page_num_str = response.text.strip()
        # Extract first integer found
        match = re.search(r'\d+', page_num_str)
        if match:
            return int(match.group())
    except Exception as e:
        print(f"Error finding page via Gemini: {e}")
        
    return -1

def extract_form_from_gcc(pdf_path, line_text, api_key):
    if not api_key:
        print("No API key for GCC extraction")
        return None
        
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Failed to open GCC PDF: {e}")
        return None
        
    form_name = extract_form_name(line_text)
    
    if len(doc) <= 40:
        print(f"Document is short ({len(doc)} pages), passing full text to Gemini for {form_name}")
        start_page = 1
        found_page = 1
        # It will extract the whole document in the next block because we limit end_idx
    else:
        start_page = find_page_for_form(doc, line_text, api_key)
        
        if start_page == -1 or start_page > len(doc):
            print(f"Could not find page for {form_name} in index. Falling back to full text search.")
            # Fallback: text search in document
            found_page = -1
            for i in range(len(doc)):
                text = doc[i].get_text()
                if form_name.lower() in text.lower():
                    found_page = i + 1 # 1-indexed
                    break
            
            if found_page != -1:
                start_page = found_page
            else:
                print(f"Could not find {form_name} anywhere in the document.")
                return None
            
    if len(doc) <= 40:
        idx = 0
        end_idx = len(doc)
    else:
        # Extract from start_page to start_page + 4 (usually forms are 1-4 pages)
        idx = max(0, start_page - 1)
        end_idx = min(len(doc), idx + 5)
        
    text_chunk = ""
    for i in range(idx, end_idx):
        text_chunk += doc[i].get_text()
        
    if len(text_chunk.strip()) < 50:
        print("Not enough text extracted (likely scanned). Cannot extract form verbatim.")
        return None
            
    client = genai.Client(api_key=api_key)
    prompt = f"""
    You are an expert at extracting specific forms/annexures from Tender documents.
    I need you to extract the EXACT, VERBATIM text and formatting for the following form: "{form_name}"
    (Originally requested as: "{line_text}")
    
    Extract the entire form content, from its title down to the signature blocks.
    DO NOT summarize. Maintain the layout (e.g., placeholders like _________, tables, lists).
    If you cannot find the form, return exactly "NOT_FOUND".
    
    Document Text:
    {text_chunk}
    """
    
    try:
        response = call_gemini_with_retry(client, prompt)
        result = response.text.strip()
        if "NOT_FOUND" in result and len(result) < 20:
            return None
        return result
    except Exception as e:
        print(f"Error extracting form text via Gemini: {e}")
        return None

def extract_form_from_missing_annexures(pdf_path: str, line_text: str, api_key: str):
    """
    Directly passes the PDF to Gemini Vision to extract the specific form.
    This works perfectly for scanned images (unlike get_text()) and allows
    Gemini to 'see' which page corresponds to which annexure.
    """
    from google.genai import types
    client = genai.Client(api_key=api_key)
    form_name = extract_form_name(line_text)
    
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
    except Exception as e:
        print(f"Failed to read PDF bytes: {e}")
        return None
        
    prompt = f"""
    You are an expert at extracting specific forms/annexures from Tender documents.
    I have attached a PDF file that contains one or more missing annexures.
    
    I need you to look at the pages and extract the EXACT, VERBATIM text and formatting for the following form: "{form_name}"
    (Originally requested as: "{line_text}")
    
    Find the page(s) that match this form. Look at the top of the pages for the annexure number.
    Extract the entire form content, from its title down to the signature blocks.
    DO NOT summarize. Maintain the layout (e.g., placeholders like _________, tables, lists).
    If you absolutely cannot find this form in the attached PDF, return exactly "NOT_FOUND".
    """
    
    contents = [
        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
        prompt
    ]
    
    try:
        response = call_gemini_with_retry(client, contents)
        result = response.text.strip()
        if "NOT_FOUND" in result and len(result) < 20:
            return None
        return result
    except Exception as e:
        print(f"Error extracting form from missing annexures via Gemini: {e}")
        return None

