import os
import shutil
import yaml
import argparse
from pathlib import Path
from google import genai
from google.genai import types

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
CATALOG_PATH = BASE_DIR / "tender-system" / "app" / "catalog" / "requirements.yaml"
COMPANY_DOCS_DIR = BASE_DIR / "data" / "tender-system" / "company"
TENDERS_DIR = BASE_DIR / "data" / "tender-system" / "tenders"

def load_catalog():
    with open(CATALOG_PATH, 'r') as f:
        data = yaml.safe_load(f)
    return data.get("requirements", [])

def find_file_in_company_dir(filename_hint):
    for root, dirs, files in os.walk(COMPANY_DOCS_DIR):
        for file in files:
            if file == filename_hint:
                return Path(root) / file
    return None

def map_with_keywords(line, catalog):
    line_lower = line.lower()
    for req in catalog:
        for alias in req.get('aliases', []):
            if alias.lower() in line_lower:
                return req['id']
    return None

def map_with_gemini(line, catalog):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set. Skipping AI mapping.")
        return None
    
    client = genai.Client(api_key=api_key)
    
    options = [req['id'] for req in catalog]
    options_str = ", ".join(options)
    
    prompt = f"""
    You are an AI assistant helping to map tender document requirements to canonical IDs.
    Given this tender requirement: "{line}"
    Choose the best matching canonical ID from this list: [{options_str}].
    If none match, reply with NONE.
    Only reply with the ID itself. No markdown, no explanations.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
        )
        result = response.text.strip()
        if result in options:
            return result
    except Exception as e:
        print(f"Gemini API error: {e}")
    return None

def main():
    parser = argparse.ArgumentParser(description="Tender Requirement Intake")
    parser.add_argument("tender_id", help="ID of the tender (e.g. Tender-123)")
    parser.add_argument("requirements_file", help="Text file containing one requirement per line")
    args = parser.parse_args()
    
    catalog = load_catalog()
    
    # Create tender output folder
    tender_out_dir = TENDERS_DIR / args.tender_id / "04_attachments"
    os.makedirs(tender_out_dir, exist_ok=True)
    
    with open(args.requirements_file, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    
    print(f"Processing {len(lines)} requirements for {args.tender_id}...\n")
    
    doc_counter = 1
    
    for line in lines:
        print(f"- Input: {line}")
        # 1. Keyword mapping
        canonical_id = map_with_keywords(line, catalog)
        if not canonical_id:
            # 2. AI Fallback
            print("  (Using Gemini fallback...)")
            canonical_id = map_with_gemini(line, catalog)
            
        if not canonical_id or canonical_id == "NONE":
            print(f"  [!] Could not map requirement to catalog.")
            continue
            
        print(f"  => Mapped to: {canonical_id}")
        
        # Look up catalog entry
        entry = next((item for item in catalog if item["id"] == canonical_id), None)
        if entry and entry.get("category") == "A":
            src_file = find_file_in_company_dir(entry["filename_hint"])
            if src_file:
                # Add numbering prefix
                dest_filename = f"{doc_counter:02d}_{src_file.name}"
                dest_path = tender_out_dir / dest_filename
                shutil.copy2(src_file, dest_path)
                print(f"  => Copied document to {dest_filename}")
                doc_counter += 1
            else:
                print(f"  [!] Missing file in company library: {entry['filename_hint']}")
        else:
            print(f"  => Category B/C handling not yet implemented.")
        
        print("")
        
    print(f"Done! {doc_counter - 1} documents prepared in:\n{tender_out_dir}")

if __name__ == "__main__":
    main()
