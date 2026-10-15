import json
import urllib.request
import time
import os
import logging
from pathlib import Path
import pandas as pd
import requests

def refresh_env():
    try:
        from dotenv import load_dotenv
        _base = Path(__file__).resolve().parent.parent
        for _env_path in [_base / ".env", _base.parent / ".env"]:
            if _env_path.exists():
                load_dotenv(dotenv_path=_env_path, override=True)
                break
        else:
            load_dotenv(override=True)
    except ImportError:
        pass

refresh_env()

def get_app_id() -> str:
    val = os.getenv("LARK_APP_ID", "").strip()
    if not val:
        refresh_env()
        val = os.getenv("LARK_APP_ID", "").strip()
    return val

def get_app_secret() -> str:
    val = os.getenv("LARK_APP_SECRET", "").strip()
    if not val:
        refresh_env()
        val = os.getenv("LARK_APP_SECRET", "").strip()
    return val

def get_app_token() -> str:
    val = os.getenv("LARK_BITABLE_APP_TOKEN", os.getenv("LARK_APP_TOKEN", "")).strip()
    if not val:
        refresh_env()
        val = os.getenv("LARK_BITABLE_APP_TOKEN", os.getenv("LARK_APP_TOKEN", "")).strip()
    return val

def get_table_id() -> str:
    val = os.getenv("LARK_BITABLE_TABLE_ID", os.getenv("LARK_TABLE_ID", "")).strip()
    if not val:
        refresh_env()
        val = os.getenv("LARK_BITABLE_TABLE_ID", os.getenv("LARK_TABLE_ID", "")).strip()
    return val

# Backward compatibility module attributes
APP_ID = get_app_id()
APP_SECRET = get_app_secret()
APP_TOKEN = get_app_token()
TABLE_ID = get_table_id()

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
        app_id = get_app_id()
        app_secret = get_app_secret()
        if not self._token or (time.time() - self._fetched_at) >= TOKEN_REFRESH_INTERVAL:
            url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal/"
            data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as response:
                    res = json.loads(response.read().decode())
                    self._token = res.get("tenant_access_token")
                    self._fetched_at = time.time()
            except urllib.error.HTTPError as e:
                logging.error(f"Lark Auth Error: {e.code} {e.reason}")
                return None
            except Exception as e:
                logging.error(f"Lark Auth Request Error: {e}")
                return None
        return self._token

def get_table_fields(tm: TokenManager) -> dict:
    token = tm.get()
    app_token = get_app_token()
    table_id = get_table_id()
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        items = res.get("data", {}).get("items", [])
        return {item["field_name"]: item["type"] for item in items}

def upload_bitable_file(file_path: str, tm: TokenManager) -> str | None:
    p = Path(str(file_path).strip().strip('"').strip("'"))
    if not p.exists() or not p.is_file():
        return None
    url = "https://open.larksuite.com/open-apis/drive/v1/medias/upload_all"
    token = tm.get()
    app_token = get_app_token()
    try:
        with open(p, "rb") as fh:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "file_name": p.name,
                    "parent_type": "bitable_file",
                    "parent_node": app_token,
                    "size": p.stat().st_size,
                },
                files={"file": (p.name, fh, "application/octet-stream")},
                timeout=60,
            )
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("file_token")
        else:
            logging.warning(f"File upload to Lark failed for {p.name}: {data.get('code')} - {data.get('msg')}")
    except Exception as e:
        logging.warning(f"File upload exception for {p.name}: {e}")
    return None

def upload_single_record_with_retry(url, fields, tm, rec_num, total) -> tuple[bool, str]:
    payload = json.dumps({"fields": fields}, default=str).encode("utf-8")
    last_err = ""
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
                    return True, ""
                else:
                    last_err = f"Lark error {res.get('code')}: {res.get('msg')}"
                    logging.warning(f"Row {rec_num} failed: {last_err}")
                    return False, last_err
        except Exception as e:
            last_err = str(e)
            wait = RETRY_DELAY * (2 ** (attempt - 1))
            if attempt < MAX_RETRIES:
                time.sleep(wait)
            else:
                logging.error(f"Row {rec_num} failed after retries: {last_err}")
                return False, last_err
    return False, last_err

def parse_custom_rows(custom_rows_str: str) -> list[int]:
    rows = set()
    if not custom_rows_str or not str(custom_rows_str).strip():
        return list(rows)
    parts = str(custom_rows_str).replace(" ", "").split(",")
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
    
    # Target rows (1-based index)
    target_rows = parse_custom_rows(custom_rows_str)
    
    if target_rows:
        valid_rows = [r - 1 for r in target_rows if 0 <= (r - 1) < len(df)]
        df = df.iloc[valid_rows]
    
    if df.empty:
        return {"status": "error", "message": "No rows to process."}

    tm = TokenManager()
    
    try:
        fields_meta = get_table_fields(tm)
    except Exception as e:
        return {"status": "error", "message": f"Failed to get table fields: {str(e)}"}

    app_token = get_app_token()
    table_id = get_table_id()
    if not app_token or not table_id:
        return {"status": "error", "message": "Lark Bitable credentials not configured in backend/.env"}

    record_url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    
    meta_lookup = {k.lower().strip(): (k, v) for k, v in fields_meta.items()}

    success_count = 0
    failed_rows = []
    
    total = len(df)
    
    for i in range(total):
        row_data = df.iloc[i]
        rec_num = df.index[i] + 1
        
        fields = {}
        for col_name, v in row_data.to_dict().items():
            if pd.isna(v):
                continue
            
            cleaned_col = str(col_name).strip()
            match = meta_lookup.get(cleaned_col.lower())
            if not match:
                # Skip columns not in Lark table schema (e.g. Test, Text 6)
                continue

            target_field_name, field_type = match

            # Service Name mapping
            if target_field_name.lower() in ("service name", "service_name"):
                v_str = str(v).strip()
                v = SERVICE_NAME_MAP.get(v_str, v_str)

            # Type 5: Date / Time (milliseconds timestamp)
            if field_type == 5:
                try:
                    ts = pd.to_datetime(v)
                    v = int(ts.timestamp() * 1000)
                except Exception:
                    continue

            # Type 2: Number
            elif field_type == 2:
                try:
                    v = float(v) if "." in str(v) else int(v)
                except Exception:
                    continue

            # Type 17: Attachment
            elif field_type == 17:
                if isinstance(v, str) and (
                    v.lower().endswith(".pdf") or v.lower().endswith(".xlsx") or 
                    v.lower().endswith(".docx") or v.lower().endswith(".zip") or 
                    "\\" in v or "/" in v
                ):
                    file_tok = upload_bitable_file(v, tm)
                    if file_tok:
                        v = [{"file_token": file_tok}]
                    else:
                        continue
                else:
                    continue

            # Type 3: Single Select / Type 1: Text
            elif field_type == 3:
                v = str(v).strip()
            elif field_type == 1:
                v = str(v)

            fields[target_field_name] = v

        success, err_msg = upload_single_record_with_retry(record_url, fields, tm, rec_num, total)
        if success:
            success_count += 1
        else:
            failed_rows.append(rec_num)

    if success_count == 0 and failed_rows:
        return {
            "status": "error",
            "message": f"Upload failed for row(s): {failed_rows}. Please check backend logs for details.",
            "success_count": 0,
            "failed_rows": failed_rows
        }

    return {
        "status": "success", 
        "message": f"Successfully uploaded {success_count} record(s)." + (f" ({len(failed_rows)} failed: {failed_rows})" if failed_rows else ""),
        "success_count": success_count,
        "failed_rows": failed_rows
    }
