import asyncio
import logging
import threading
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import SITES, PIPELINE
import config
from core.db import init_db
from core.state import Pipeline, Ledger
from sites.registry import build_scraper
from workers.downloader import Downloader
from workers.range_checker import RangeChecker
from workers.retry_worker import RetryWorker
from workers.uploader import Uploader

app = FastAPI(title="TenderFinder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket log streaming ───────────────────────────────────────────────────
active_websockets: list[WebSocket] = []
loop_ref: asyncio.AbstractEventLoop | None = None

class WebSocketLogHandler(logging.Handler):
    def emit(self, record):
        pass  # replaced on startup


ws_handler = WebSocketLogHandler()
ws_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-7s | %(name)-14s | %(message)s',
    datefmt='%H:%M:%S'
))
logging.getLogger().addHandler(ws_handler)


@app.on_event("startup")
async def startup_event():
    global loop_ref
    loop_ref = asyncio.get_running_loop()

    # Initialize DB tables on startup
    init_db()

    def emit_safe(record):
        log_entry = ws_handler.format(record)
        if not active_websockets or not loop_ref or loop_ref.is_closed():
            return

        async def send():
            for ws in list(active_websockets):
                try:
                    await ws.send_text(log_entry)
                except Exception:
                    pass

        asyncio.run_coroutine_threadsafe(send(), loop_ref)

    ws_handler.emit = emit_safe


# ── Pipeline management ───────────────────────────────────────────────────────
pipeline_instance: Pipeline | None = None
pipeline_thread: threading.Thread | None = None
_ledger: Ledger | None = None  # shared singleton


def _get_ledger() -> Ledger:
    global _ledger
    if _ledger is None:
        _ledger = Ledger()
    return _ledger


def run_scraper(site_choice: str) -> None:
    global pipeline_instance
    try:
        if site_choice == "1":
            site_conf = next((s for s in SITES if s.name == "ireps"), None)
        else:
            site_conf = next((s for s in SITES if s.name == "tenderdetail"), None)

        if not site_conf:
            logging.error("Invalid site selected")
            return

        site_conf.enabled = True

        pipeline = Pipeline()
        pipeline_instance = pipeline
        ledger = _get_ledger()

        threads = []
        scraper = build_scraper(site_conf)
        threads.append(Downloader(site_conf, pipeline, ledger, scraper=scraper))
        threads.append(RangeChecker(pipeline, ledger))   # pass ledger
        threads.append(Uploader(pipeline, ledger))
        threads.append(RetryWorker(pipeline, ledger))

        logging.info("Starting pipeline for %s...", site_conf.name)
        for t in threads:
            t.start()

        # Wait only for the Downloader to finish its job
        threads[0].join()
        
        # Tell the other background threads (RangeChecker, Uploader, RetryWorker) to stop
        if pipeline_instance:
            pipeline_instance.request_stop()

        # Wait for the background threads to cleanly exit
        for t in threads[1:]:
            t.join()

        logging.info("Pipeline stopped cleanly.")
    except Exception as e:
        logging.exception("Scraper error: %s", e)
    finally:
        pipeline_instance = None


@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.post("/api/start")
async def start_scraper(site: dict):
    global pipeline_thread, pipeline_instance

    choice = site.get("choice", "2")
    save_path = site.get("save_path", "").strip()

    if save_path:
        custom_dir = Path(save_path)
        custom_dir.mkdir(parents=True, exist_ok=True)
        config.DOWNLOADS_DIR = custom_dir
        (config.BASE_DIR / ".save_path").write_text(save_path, encoding="utf-8")
    else:
        config.DOWNLOADS_DIR = config.BASE_DIR / "downloads"
        config.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        save_file = config.BASE_DIR / ".save_path"
        if save_file.exists():
            save_file.unlink()

    if pipeline_instance and not pipeline_instance.stopping:
        return {"status": "error", "message": "Scraper is already running"}

    pipeline_thread = threading.Thread(target=run_scraper, args=(choice,), daemon=True)
    pipeline_thread.start()

    return {"status": "success", "message": f"Started scraping site {choice}"}


@app.post("/api/stop")
async def stop_scraper():
    global pipeline_instance
    if pipeline_instance:
        pipeline_instance.request_stop()
        return {"status": "success", "message": "Stopping scraper..."}
    return {"status": "error", "message": "Scraper is not running"}


@app.get("/api/status")
async def get_status():
    if pipeline_instance and not pipeline_instance.stopping:
        return {"status": "running"}
    return {"status": "idle"}


@app.get("/api/results")
async def get_results():
    """Read passed tenders from the database."""
    ledger = _get_ledger()
    db_results = ledger.get_passed_tenders()

    results = []
    for row in db_results:
        tender_id = row["id"]
        summary = row.get("summary") or "No summary available."
        details_pdf = None
        original_docs = []

        def _make_url(path_str: str, fname: str) -> str:
            """Return the right URL depending on whether the path is absolute."""
            p = Path(path_str)
            if p.is_absolute():
                # Serve via the /file endpoint using the absolute path
                return "/file?path=" + urllib.parse.quote(str(p), safe="")
            else:
                # path_str contains the relative path (e.g. folder/file.pdf). 
                # Replace Windows backslashes with forward slashes for the URL.
                url_path = path_str.replace("\\", "/")
                return f"/downloads/{url_path}"

        # Build file URLs from the files list stored in DB
        files = row.get("files") or []
        for stored_path in files:
            fname = Path(stored_path).name
            url = _make_url(stored_path, fname)
            if fname.startswith("Summary_") and fname.endswith(".pdf"):
                details_pdf = url
            elif fname.endswith(".txt") and fname.startswith("Summary_"):
                pass  # text version, don't show separately
            elif not fname.endswith(".html"):
                original_docs.append(url)

        # Fallback: scan default DOWNLOADS_DIR sub-folder
        tender_dir = config.DOWNLOADS_DIR / tender_id
        if tender_dir.is_dir():
            for f in tender_dir.iterdir():
                url = f"/downloads/{tender_id}/{f.name}"
                if f.name.startswith("Summary_") and f.name.endswith(".pdf"):
                    if not details_pdf:
                        details_pdf = url
                elif f.suffix.lower() in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"]:
                    if url not in original_docs and not f.name.startswith("Summary_"):
                        original_docs.append(url)

        # Fallback: scan IREPS custom folder
        ireps_base = Path(r"C:\Users\DELL\Downloads\IREPS_Tenders")
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in tender_id)[:100]
        ireps_dir = ireps_base / safe_id
        if ireps_dir.is_dir():
            for f in ireps_dir.iterdir():
                abs_url = "/file?path=" + urllib.parse.quote(str(f), safe="")
                if f.name.startswith("Summary_") and f.name.endswith(".pdf"):
                    if not details_pdf:
                        details_pdf = abs_url
                elif f.suffix.lower() in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"]:
                    if abs_url not in original_docs and not f.name.startswith("Summary_"):
                        original_docs.append(abs_url)

        if details_pdf or original_docs:
            results.append({
                "id": tender_id,
                "source": row.get("source", ""),
                "summary": summary[:250] + "..." if len(summary) > 250 else summary,
                "details_pdf": details_pdf,
                "original_docs": original_docs,
                "value": row.get("value"),
                "closing_date": row.get("closing_date"),
            })

    return results


@app.get("/file")
async def serve_absolute_file(path: str):
    """Serve a file given its absolute filesystem path (used for IREPS custom folder)."""
    full_path = Path(path)
    if full_path.exists() and full_path.is_file():
        return FileResponse(str(full_path))
    return {"status": "error", "message": f"File not found: {path}"}


@app.get("/downloads/{file_path:path}")
async def serve_file(file_path: str):
    full_path = config.DOWNLOADS_DIR / file_path
    if full_path.exists() and full_path.is_file():
        return FileResponse(str(full_path))
    return {"status": "error", "message": "File not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
