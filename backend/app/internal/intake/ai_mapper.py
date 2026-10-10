import os
import json
try:
    from google import genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

def map_requirements_batch(reqs, catalog):
    """
    Takes a list of requirements: [{"row": index, "name": text}]
    and the catalog.
    Returns a dictionary mapping row -> [canonical_ids]
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not HAS_GEMINI or not reqs:
        print("Skipping AI batch mapping (Gemini not available or no reqs).")
        return {}

    client = genai.Client(api_key=api_key)
    
    # Simplify catalog for the prompt to save tokens
    catalog_summary = []
    for c in catalog:
        # Include ID and top aliases to help the model
        aliases = c.get("aliases", [])[:6]
        desc = c.get("filename_hint", "")
        catalog_summary.append(f"ID: {c['id']} | Hint: {desc} | Keywords: {', '.join(aliases)}")
        
    catalog_str = "\n".join(catalog_summary)
    
    req_summary = []
    for r in reqs:
        req_summary.append(f"Row {r['row']}: {r['name']}")
    req_str = "\n".join(req_summary)
    
    prompt = f"""
You are an expert AI assistant that maps tender requirements to standard documents.
Here is the CATALOG of available standard documents:
{catalog_str}

Here are the tender requirements extracted from an Excel sheet:
{req_str}

Your task is to intelligently map each requirement Row to the most appropriate CATALOG ID(s).
- Look at the full context of the requirement. Sometimes it mentions merged docs or multiple abbreviations (like "AOA, MOA" or "POA+BR"). Map to ALL applicable IDs.

STRICT MAPPING RULES:
- OVERRIDING JV/PARTNERSHIP RULE: If the requirement strictly only asks for Joint Venture, Partnership, Society, Trust, or LLP documents, return JV_PARTNERSHIP_DECLARATION. However, if the requirement is a large paragraph listing MULTIPLE entity types (e.g. Sole Proprietor, Partnership, JV, and Company), you MUST return ALL applicable IDs (e.g. AOA_MOA for Company, JV_PARTNERSHIP_DECLARATION for JV, POWER_OF_ATTORNEY_BR for Partnership) so the user can choose which one applies to their specific company type.
- For Financial Eligibility/Turnover, return TURNOVER_FORMAT.
- For Balance Sheet / Audit Report, return BALANCE_SHEET.
- Do NOT merge Balance Sheet and Turnover into a single ID; they are separate documents. If both are requested, return both.
- For Technical Eligibility/Similar Works/Experience, return ONLY: EXPERIENCE_ACQUAINT. Do NOT return multiple.

- If a requirement does not clearly map to anything in the catalog, return an empty array for that row.
- Return ONLY valid JSON in the exact following format. Do not include markdown codeblocks or any other text.

Format:
{{
  "1": ["ID_1", "ID_2"],
  "2": [],
  "3": ["ID_3"]
}}
"""
    
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
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
                
            mapping = json.loads(result_text.strip())
            
            # Validate against catalog IDs
            valid_ids = {c["id"] for c in catalog}
            clean_mapping = {}
            for row_str, ids in mapping.items():
                if not isinstance(ids, list):
                    continue
                valid_row_ids = [i for i in ids if i in valid_ids]
                clean_mapping[row_str] = valid_row_ids
                
            print(f"AI Batch Mapper [{model_name}] successfully processed {len(clean_mapping)} rows.")
            return clean_mapping
            
        except Exception as e:
            err_str = str(e)
            print(f"Error during AI batch mapping (attempt {attempt+1}/{len(FALLBACK_MODELS)}, model={model_name}): {err_str[:120]}")
            if attempt == len(FALLBACK_MODELS) - 1:
                return {}
            # On 429 (quota), skip immediately; on other errors wait briefly
            if "429" not in err_str and "RESOURCE_EXHAUSTED" not in err_str:
                time.sleep(2)
