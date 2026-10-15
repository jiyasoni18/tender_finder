import json
import urllib.request
import time
import os
from pathlib import Path
import pandas as pd
import requests

try:
    from dotenv import load_dotenv
    _base = Path(__file__).resolve().parent.parent
    for _env_path in [_base / ".env", _base.parent / ".env"]:
        if _env_path.exists():
            load_dotenv(dotenv_path=_env_path, override=False)
            break
    else:
        load_dotenv()
except ImportError:
    pass

APP_ID = os.getenv("LARK_APP_ID", "")
APP_SECRET = os.getenv("LARK_APP_SECRET", "")
APP_TOKEN = os.getenv("LARK_BITABLE_APP_TOKEN", os.getenv("LARK_APP_TOKEN", ""))
TABLE_ID = os.getenv("LARK_BITABLE_TABLE_ID", os.getenv("LARK_TABLE_ID", ""))

MAX_RETRIES = 5
RETRY_DELAY = 3
TOKEN_REFRESH_INTERVAL = 55 * 60

SERVICE_NAME_MAP = {
    "TELECOMMUNICATION SYSTEMS": "OPTICAL FIBRE COMMUNICATIONS",
    "MECHANICAL ENGINEERING":    "RAILWAY SIGNALLING AND CONTROL SYSTEMS",
    "CIVIL ENGINEERING":         "DIGITAL INFRASTRUCTURE",
    "SOLAR":                     "RENEWABLE SERVICES ",
    "SOFTWARE SERVICES":         "MICROWAVE COMMUNICATIONS",
    "DATA CENTRE SERVICES":      "MICROWAVE COMMUNICATIONS",
}

class TokenManager:
    def __init__(self):
        self._token = None
        self._fetched_at = 0

    def get(self):
        if not self._token or (time.time() - self._fetched_at) >= TOKEN_REFRESH_INTERVAL:
            url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal/"
            data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as response:
                    res = json.loads(response.read().decode())
                    self._token = res.get("tenant_access_token")
                    self._fetched_at = time.time()
            except urllib.error.HTTPError as e:
                print(f"Auth Error: {e.code} {e.reason}")
                return None
        return self._token

def get_table_fields(tm: TokenManager):
    token = tm.get()
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        items = res.get("data", {}).get("items", [])
        return {item["field_name"]: item["type"] for item in items}

def upload_single_record_with_retry(url, fields, tm, rec_num, total):
    payload = json.dumps({"fields": fields}).encode("utf-8")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            token = tm.get()
            req_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"
            }
            req = urllib.request.Request(url, data=payload, headers=req_headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                res = json.loads(response.read().decode())
                if res.get("code") == 0:
                    return True
                else:
                    return False
        except Exception as e:
            wait = RETRY_DELAY * (2 ** (attempt - 1))
            if attempt < MAX_RETRIES:
                time.sleep(wait)
            else:
                return False

def parse_custom_rows(custom_rows_str: str) -> list[int]:
    rows = set()
    if not custom_rows_str or not custom_rows_str.strip():
        return list(rows)
    parts = custom_rows_str.replace(" ", "").split(",")
    for p in parts:
        if not p:
            continue
        if "-" in p:
            try:
                start, end = map(int, p.split("-"))
                for i in range(start, end + 1):
                    rows.add(i)
            except ValueError:
                pass
        else:
            try:
                rows.add(int(p))
            except ValueError:
                pass
    return sorted(list(rows))

def process_lark_upload(file_path: str, custom_rows_str: str = "") -> dict:
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        return {"status": "error", "message": f"Failed to read Excel: {str(e)}"}
    
    # 1-based indexing for rows
    target_rows = parse_custom_rows(custom_rows_str)
    
    if target_rows:
        # Filter dataframe based on target_rows (1-based -> 0-based index)
        # We only keep rows where (index + 1) is in target_rows
        valid_rows = [r - 1 for r in target_rows if 0 <= (r - 1) < len(df)]
        df = df.iloc[valid_rows]
    
    if df.empty:
        return {"status": "error", "message": "No rows to process."}

    tm = TokenManager()
    
    try:
        fields_meta = get_table_fields(tm)
    except Exception as e:
        return {"status": "error", "message": f"Failed to get table fields: {str(e)}"}

    record_url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    
    success_count = 0
    failed_rows = []
    
    total = len(df)
    
    for i in range(total):
        row_data = df.iloc[i]
        # Get the original 1-based row number from the dataframe index
        rec_num = df.index[i] + 1
        
        fields = {}
        for k, v in row_data.to_dict().items():
            if pd.isna(v):
                continue
            
            # Map specific column values if needed
            if k == "SERVICE NAME" and v in SERVICE_NAME_MAP:
                v = SERVICE_NAME_MAP[v]
                
            # Basic type conversion to string for safety, but check fields_meta if needed
            # In retry_failed script, it just uses a dictionary mapping
            # This is a simplified version, it assumes string conversion is mostly fine
            # or relies on python's json.dumps.
            if isinstance(v, (int, float)):
                # If it's a date or just number, might need specific handling, 
                # but let's pass it as is to json serialization
                pass
                
            fields[str(k)] = v
            
        success = upload_single_record_with_retry(record_url, fields, tm, rec_num, total)
        if success:
            success_count += 1
        else:
            failed_rows.append(rec_num)

    return {
        "status": "success", 
        "message": f"Successfully uploaded {success_count} records.",
        "success_count": success_count,
        "failed_rows": failed_rows
    }
