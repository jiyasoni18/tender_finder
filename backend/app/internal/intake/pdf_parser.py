import fitz
import json
from google import genai

def parse_nit_pdf(pdf_path, api_key):
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for PDF parsing.")
        
    print(f"Reading PDF: {pdf_path}")
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text += page.get_text()
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None, [], {}
        
    # Provide the full text to Gemini since it has a massive context window (1M+ tokens)
    # We remove the 30,000 char limit so it can actually see sections deep in the document.
    text = text[:800000] 

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are an expert at extracting information from Tender NIT (Notice Inviting Tender) documents.
    I will provide you with the text of an NIT document.
    Please extract the following fields if they are available:
    1. The Tender Number (DOC NO)
    2. A complete list of mandatory documents required to be submitted by the bidder for the TENDER BID / BID SUBMISSION. 
       **CRITICAL**: You must actively search for sections titled "ELIGIBILITY CONDITIONS", "Standard Financial Criteria", "Standard Technical Criteria", or any "Documents Uploading" section. If a table lists documents with a column saying 'Allowed(Mandatory)' or 'Allowed (Mandatory)', you MUST extract ALL of those documents.
       **EXCLUSIONS - OPTIONAL**: Do NOT extract any documents that are marked as 'optional', 'allowed (optional)', 'Allowed(Optional)', or anything similar. Only mandatory documents should be extracted.
       **IMPORTANT FORMATTING**: Do NOT summarize, shorten, or cut any part of the requirements. You MUST take the whole text and extract the EXACT, full, verbatim text of the requirement as it appears in the NIT. If it is a long paragraph, extract the entire paragraph exactly as written.
       **NO SPLITTING**: If multiple documents or criteria are mentioned in a single continuous paragraph, bullet point, or table row, you MUST extract that ENTIRE paragraph/row as ONE SINGLE string item in the `requirements` array. Do NOT split a single paragraph into multiple items.
       **EXCLUSIONS**: Do NOT extract post-award deliverables, site execution reports, or testing documents that the contractor must submit during or after the work (e.g., Signal Sighting report, Signal test report, maintenance registers, testing records, alteration drawings, etc.). Only extract documents required to be uploaded with the initial bid.
       **EXCLUSIONS - CONDITIONAL ENTITIES**: Do NOT extract documents that are only required conditionally based on the bidder's entity type (e.g., Joint Venture (JV), Partnership Firm, HUF, LLP, Consortium). Even if the text says "Non submission shall lead to summary rejection", IGNORE it unless it is explicitly listed in a general "Mandatory Documents" table for all bidders.
       **NO INVENTIONS OR SUBSTITUTIONS**: Do not invent, guess, or hallucinate any descriptions. ONLY extract text that actually exists in the provided NIT. If the NIT only gives a reference to another document or chapter (for example: "For Standard Technical Criteria, please refer Para No.1.1.1 of Chapter-I..."), you MUST extract that EXACT reference text. Do NOT replace it with what you think the criteria actually is.
       **DO NOT DEDUPLICATE**: If a document is asked for multiple times, you MUST extract it multiple times. Do not skip it.
    3. Tender Name or Description (Title or Name of Work). **CRITICAL**: Do NOT truncate or summarize this. Extract the full, exact name of work even if it is very long, spans multiple lines, or contains Roman numerals/multiple items.
    4. Place/Location of the work or office
    5. Date (Issue date of the tender. Do not use the tender opening date.)
    6. Validity (Days) (Look for 'Offer validity', 'Validity of Offer', 'Tender Validity'. Usually 30, 45, 60, 90, or 120 days. Extract just the number if possible)
    7. Issuing Authority (Look for 'Office of the...', 'For and on behalf of President of India', e.g. 'Dy.C.E./G.A', 'Sr.DSTE/VSKP'. Extract exactly the short authority designation shown at the top or bottom of the NIT)
    8. Execute Contract Days (Days allowed to execute contract after notice, usually 7)
    9. Commence Work Days (Days allowed to commence work after order, usually 15)
    10. Railway Division/Zone (Look for the Railway division or zone at the very top of the document, e.g., "North Eastern Railway", "WESTERN RAILWAY")
    11. Tender Closing Date (Look for 'Closing Date and Time', 'Tender Closing Date', or 'Bidding closing date'. DO NOT use 'Date of opening of tender'. Extract just the date, e.g. "25/08/2026")
    12. Bid Security Amount (Look for 'Bid Security', 'Earnest Money Deposit', 'EMD Amount'. Extract the number/amount in Rs)

    Respond ONLY with a valid JSON object in this exact format, with no markdown formatting or backticks. If a field is not found, leave it as an empty string.
    {{
        "tender_no": "TENDER-NUM-123",
        "requirements": [
            "Document 1 name",
            "Document 2 name"
        ],
        "tender_name": "Tender for Construction",
        "issuing_authority": "Western Railway",
        "place": "New Delhi",
        "date": "12/10/2026",
        "days": "30",
        "execute_contract_days": "7",
        "commence_work_days": "15",
        "railway": "NORTH CENTRAL RLY",
        "closing_date": "25/08/2026",
        "bid_security_amount": "50000"
    }}

    NIT Text:
    {text}
    """
    
    print("Extracting Tender details using Gemini...")
    import time
    # Order: fastest/cheapest with quota first, escalate if needed
    FALLBACK_MODELS = [
        'gemini-3.5-flash-lite',   # Fast, cheap, quota available
        'gemini-3.1-flash-lite',   # Fallback lite
        'gemini-3.6-flash',        # Mid tier
        'gemini-3.5-flash',        # May be quota-exhausted — try last
    ]
    for attempt, model_name in enumerate(FALLBACK_MODELS):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            result_text = response.text.strip()
            
            # Clean up any potential markdown backticks
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
                
            data = json.loads(result_text.strip())
            print(f"PDF parsed successfully using [{model_name}].")
            return data.get("tender_no"), data.get("requirements", []), data
        except Exception as e:
            err_str = str(e)
            print(f"Error calling Gemini or parsing JSON (attempt {attempt+1}/{len(FALLBACK_MODELS)}, model={model_name}): {err_str[:150]}")
            if attempt == len(FALLBACK_MODELS) - 1:
                print("Raw response was:")
                print(response.text if 'response' in locals() else "No response")
                return None, [], {}
            # On 429 (quota), skip immediately; on other errors wait briefly
            if "429" not in err_str and "RESOURCE_EXHAUSTED" not in err_str:
                time.sleep(2)
