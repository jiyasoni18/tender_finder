import os
import threading
from datetime import datetime
from collections import defaultdict
import openpyxl
from openpyxl.styles import Font
from app.core.logging_setup import get_logger
from app.core.config import REPORTS_DIR
from app.core.db import get_session, TenderRow

log = get_logger("excel_ledger")

def sync_excel_ledger_blocking():
    """
    Reads all records from the TenderRow database, groups them by month-year,
    and updates the corresponding monthly Excel ledger files.
    """
    try:
        with get_session() as db:
            rows = db.query(TenderRow).order_by(TenderRow.created_at.desc()).all()
            
            if not rows:
                return

            # Group rows by YYYY-MM
            grouped = defaultdict(list)
            for r in rows:
                if r.created_at:
                    month_key = r.created_at.strftime("%Y_%m")
                else:
                    month_key = "Unknown_Date"
                grouped[month_key].append(r)
            
            # Create reports directory if it doesn't exist
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            
            headers = [
                "Tender ID", "Source", "Status", "Value", "Closing Date",
                "Created At", "Reject Reason", "Summary", "PDF Path", "URL"
            ]
            
            for month_key, tenders in grouped.items():
                file_path = REPORTS_DIR / f"Tenders_Ledger_{month_key}.xlsx"
                
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = f"Tenders {month_key}"
                
                # Write headers
                ws.append(headers)
                for col_idx, _ in enumerate(headers, 1):
                    ws.cell(row=1, column=col_idx).font = Font(bold=True)
                    
                # Write rows
                for t in tenders:
                    ws.append([
                        t.id,
                        t.source,
                        t.status,
                        t.value,
                        t.closing_date,
                        t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else "",
                        t.reject_reason,
                        t.summary,
                        t.pdf_path,
                        t.detail_url
                    ])
                
                # Basic column width adjustments
                ws.column_dimensions['A'].width = 30
                ws.column_dimensions['B'].width = 15
                ws.column_dimensions['C'].width = 15
                ws.column_dimensions['D'].width = 15
                ws.column_dimensions['E'].width = 20
                ws.column_dimensions['F'].width = 20
                ws.column_dimensions['G'].width = 30
                ws.column_dimensions['H'].width = 50
                ws.column_dimensions['I'].width = 40
                ws.column_dimensions['J'].width = 50
                
                # Save to a temporary file first to avoid corruption, then rename
                temp_path = file_path.with_suffix(".tmp.xlsx")
                wb.save(temp_path)
                os.replace(temp_path, file_path)
                
    except Exception as e:
        log.error("Failed to sync Excel ledger: %s", e)

def sync_excel_ledger_async():
    """
    Runs the sync in a background thread so it doesn't block the caller.
    """
    threading.Thread(target=sync_excel_ledger_blocking, daemon=True, name="excel-ledger-sync").start()
