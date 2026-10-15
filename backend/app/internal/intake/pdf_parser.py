import fitz
import json
import re
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
            
            # Heuristic extraction fallback if issuing_authority is missing
            import re
            if not data.get("issuing_authority"):
                match_auth = re.search(r'(?:Office\s+of\s+(?:the\s+)?|acting\s+through\s+(?:the\s+)?|Dy\.?\s*C\.?E\.?|Sr\.?\s*DSTE|Sr\.?\s*DEN|DRM|General\s+Manager|Chief\s+Engineer)([A-Za-z0-9\/\.\-\s]{3,40}?(?:Railway|Division|Const|Signal|Engg|HQ|VSKP|PRYJ|RTM|SUR|BVP|ADI|BCT)?)', text, re.IGNORECASE)
                if match_auth:
                    data["issuing_authority"] = match_auth.group(0).strip()
                elif data.get("railway"):
                    data["issuing_authority"] = data["railway"]

            if not data.get("railway"):
                match_rly = re.search(r'\b(Western\s+Railway|Northern\s+Railway|North\s+Western\s+Railway|North\s+Central\s+Railway|South\s+Coast\s+Railway|Central\s+Railway|Eastern\s+Railway|East\s+Central\s+Railway|East\s+Coast\s+Railway|Southern\s+Railway|South\s+Central\s+Railway|South\s+Eastern\s+Railway|South\s+East\s+Central\s+Railway|South\s+Western\s+Railway|West\s+Central\s+Railway|North\s+Eastern\s+Railway|Northeast\s+Frontier\s+Railway)\b', text, re.IGNORECASE)
                if match_rly:
                    data["railway"] = match_rly.group(1).strip()

            # Fallback heuristic for tender place if not extracted by AI
            if not data.get("place") or str(data.get("place")).strip().lower() in ["", "none", "null", "n/a", "india"]:
                match_plc = re.search(r'(?:Place\s+of\s+work|Work\s+site|Location\s+of\s+work|Location|Place)\s*[:\-]\s*([A-Za-z\s]{3,30}?)(?=[,\n\r\(\.]|$)', text, re.IGNORECASE)
                if match_plc:
                    cand_plc = match_plc.group(1).strip()
                    if len(cand_plc) >= 3 and cand_plc.lower() not in ["not applicable", "n/a", "as per tender", "as per nit", "india"]:
                        data["place"] = cand_plc
                elif data.get("issuing_authority"):
                    city_abbrevs = {
                        "VSKP": "Visakhapatnam", "ADI": "Ahmedabad", "BRC": "Vadodara",
                        "RTM": "Ratlam", "KOTA": "Kota", "BVP": "Bhavnagar", "BCT": "Mumbai",
                        "PRYJ": "Prayagraj", "SUR": "Solapur", "NDLS": "New Delhi", "JHS": "Jhansi"
                    }
                    for abbr, city in city_abbrevs.items():
                        if abbr in str(data["issuing_authority"]).upper():
                            data["place"] = city
                            break

            print(f"PDF parsed successfully using [{model_name}]. Issuing Authority: {data.get('issuing_authority')}, Place: {data.get('place')}")
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

def parse_nprocure_pdf(pdf_path, api_key):
    """
    Parses an nProcure (tender.nprocure.com) tender document, RFP, or EOI PDF.
    Searches for sections containing 'doc checklist', 'document checklist', 'checklist',
    'eoi', 'documents to be submitted', 'eligibility criteria', or 'technical bid'.
    Extracts tender metadata and the complete list of mandatory document requirements.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for PDF parsing.")
        
    print(f"Reading nProcure PDF: {pdf_path}")
    explicit_checklist_indicators = [
        "check list", "checklist", "doc checklist", "document checklist",
        "particulars of documents to be submitted", "documents to be submitted",
        "list of documents to be submitted", "documents to be uploaded",
        "eoi checklist", "checklist for eoi", "checklist of documents",
        "submission checklist", "cover-1 checklist", "cover 1 checklist",
        "stage-1 checklist", "technical bid checklist", "eoi document list",
        "documents required for eoi", "list of documents for eoi"
    ]

    selected_pages = []
    total_pages = 0
    explicit_checklist_pages = set()
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        # 1. Search specifically for explicit Check List / EOI tables
        for p_idx in range(total_pages):
            page_text = doc[p_idx].get_text()
            p_lower = page_text.lower()
            
            has_indicator = any(ind in p_lower for ind in explicit_checklist_indicators)
            if has_indicator:
                lines = [l.strip() for l in page_text.split('\n') if l.strip()]
                # Verify it has tabular structure, numbered rows, or substantial checklist lines (avoiding isolated 1-line TOC mentions)
                has_items = (
                    any(re.match(r'^\s*(\d+|[a-z]\))\s+', l) for l in lines)
                    or "particulars" in p_lower
                    or "documents name in bid" in p_lower
                    or "comment" in p_lower
                    or "submitted" in p_lower
                    or "uploaded" in p_lower
                )
                if has_items and len(lines) > 6:
                    explicit_checklist_pages.add(p_idx)
                    # Checklists commonly span multiple consecutive pages
                    if p_idx + 1 < total_pages:
                        explicit_checklist_pages.add(p_idx + 1)
                    if p_idx + 2 < total_pages:
                        explicit_checklist_pages.add(p_idx + 2)

        print(f"nProcure PDF has {total_pages} pages. Detected checklist pages: {[p + 1 for p in sorted(list(explicit_checklist_pages))]}")

        # 2. Add opening pages (for tender metadata, tender no, authority, EMD) and closing pages
        first_pages = set(range(min(8, total_pages)))
        last_pages = set(range(max(0, total_pages - 6), total_pages))

        # 3. Format the text for the LLM with the checklist clearly demarcated at the top
        checklist_text = ""
        for p in sorted(list(explicit_checklist_pages)):
            checklist_text += f"\n--- Checklist Page {p + 1} ---\n" + doc[p].get_text()

        overview_text = ""
        for p in sorted(list(first_pages | last_pages)):
            if p not in explicit_checklist_pages:
                overview_text += f"\n--- Page {p + 1} ---\n" + doc[p].get_text()

        # If no explicit checklist found, also include general pages matching broader keywords
        extra_matched_text = ""
        if not explicit_checklist_pages and total_pages > 8:
            general_keywords = ["eligibility criteria", "qualification criteria", "annexure", "proforma", "undertaking"]
            for page_idx in range(total_pages):
                if page_idx not in first_pages and page_idx not in last_pages:
                    p_txt = doc[page_idx].get_text()
                    if any(kw in p_txt.lower() for kw in general_keywords):
                        extra_matched_text += f"\n--- Page {page_idx + 1} ---\n" + p_txt

        full_text = f"""
=== SECTION A: OFFICIAL BID SUBMISSION CHECKLIST / EOI CHECKLIST TABLE (HIGHEST PRIORITY) ===
{checklist_text if checklist_text.strip() else "[No dedicated checklist table detected. Refer to sections below.]"}

=== SECTION B: TENDER OVERVIEW, NIT & GENERAL METADATA ===
{overview_text}

=== SECTION C: OTHER RELEVANT SECTIONS (ELIGIBILITY / ANNEXURES) ===
{extra_matched_text}
"""
    except Exception as e:
        print(f"Error reading nProcure PDF: {e}")
        return None, [], {}

    full_text = full_text[:800000]

    client = genai.Client(api_key=api_key)

    prompt = f"""
    You are an expert procurement attorney and bid manager specializing in Gujarat State Government e-Procurement tenders (nProcure / tender.nprocure.com).
    
    I will provide you with the text of an nProcure tender document, Request for Proposal (RFP), or Expression of Interest (EOI).
    
    Please extract the following fields if they are available:
    1. The Tender Number / Tender ID / Notice No. / EOI No. / RFP No. (Look for "Tender Notice No.", "Tender ID", "NIT No.", "Bid No.", "RFP No.", "EOI No.")
    2. A complete list of mandatory documents required to be submitted by the bidder with the bid.
       **CRITICAL NPROCURE RULE (OFFICIAL CHECKLIST AS SINGLE SOURCE OF TRUTH)**:
       - In nProcure / Gujarat Government tenders, the official 'Check List' / 'Checklist of documents' / 'Particulars of documents to be submitted' / 'EOI Checklist' table is the AUTHORITATIVE list of bid submission documents.
       - If SECTION A contains a 'Check List' or 'Particulars of documents to be submitted' or 'Checklist of documents' or 'EOI Checklist' table:
         YOU MUST EXTRACT EVERY NUMBERED ROW FROM THAT CHECKLIST TABLE VERBATIM IN NUMERICAL ORDER (e.g., items 1 through 27).
       - Do NOT substitute or replace the checklist table items with general eligibility criteria or RFP text from other sections.
       - Extract each item verbatim as written in the checklist column (e.g. 'Particulars of documents to be submitted').
       - Extract the full description of each item without truncating.
       - If no explicit checklist table is present, extract all mandatory documents specified under eligibility criteria, technical bid submission, and mandatory annexures.
       **NO INVENTIONS**: Do NOT invent or hallucinate requirements. Extract only documents explicitly listed in the document.
       **EXCLUDE POST-AWARD**: Do NOT extract documents to be submitted after contract award (e.g., performance progress reports, daily logs during work execution).
    3. Tender Name or Description (Title or Name of Work / Project title). Extract the full name without truncating.
    4. Issuing Authority / Client Name / Department / Organization (e.g., "Gujarat Fibre Grid Network Limited", "Surat Municipal Corporation", "Ahmedabad Municipal Corporation", "GETCO", "Gujarat Metro Rail Corporation", "Roads & Buildings Department", etc.)
    5. Place / Location of the work or office (e.g., Surat, Ahmedabad, Gandhinagar, Vadodara, Rajkot, or Gujarat. If not explicitly found, return "Ahmedabad")
    6. Date (Tender publication / issue date)
    7. Validity (Days) (Tender offer validity, usually 90, 120, or 180 days. Return just the number)
    8. Tender Closing Date (Submission deadline / last date for bid submission. Extract just the date, e.g. "25/10/2026")
    9. Bid Security Amount (EMD Amount / Earnest Money Deposit in Rs.)

    Respond ONLY with a valid JSON object in this exact format, with no markdown formatting or backticks:
    {{
        "tender_no": "TENDER-NUM-123",
        "requirements": [
            "Document 1 name / description verbatim",
            "Document 2 name / description verbatim"
        ],
        "tender_name": "Full name of work or project",
        "issuing_authority": "Surat Municipal Corporation",
        "place": "Surat",
        "date": "15/10/2026",
        "days": "120",
        "closing_date": "25/10/2026",
        "bid_security_amount": "50000"
    }}

    Tender Text:
    {full_text}
    """

    print("Extracting nProcure Tender details using Gemini...")
    import time
    FALLBACK_MODELS = [
        'gemini-3.5-flash-lite',
        'gemini-3.1-flash-lite',
        'gemini-3.6-flash',
        'gemini-3.5-flash',
    ]
    for attempt, model_name in enumerate(FALLBACK_MODELS):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            result_text = response.text.strip()
            
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
                
            data = json.loads(result_text.strip())

            # Fallback heuristic for place if not extracted
            if not data.get("place") or str(data.get("place")).strip().lower() in ["", "none", "null", "n/a", "india"]:
                data["place"] = "Ahmedabad"

            print(f"nProcure PDF parsed successfully using [{model_name}]. Found {len(data.get('requirements', []))} requirements. Authority: {data.get('issuing_authority')}")
            return data.get("tender_no"), data.get("requirements", []), data
        except Exception as e:
            err_str = str(e)
            print(f"Error calling Gemini for nProcure (attempt {attempt+1}/{len(FALLBACK_MODELS)}, model={model_name}): {err_str[:150]}")
            if attempt == len(FALLBACK_MODELS) - 1:
                return None, [], {}
            if "429" not in err_str and "RESOURCE_EXHAUSTED" not in err_str:
                time.sleep(2)
