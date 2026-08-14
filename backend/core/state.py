"""
Runtime plumbing shared across workers: the queues, the shutdown signal, and a
persistent dedup ledger backed by PostgreSQL (or SQLite in local dev).
"""
from __future__ import annotations

import threading
from queue import Queue

from config import PIPELINE
from core.logging_setup import get_logger
from core.db import TenderRow, get_session, init_db

log = get_logger("state")

# Sentinel used to tell a worker "no more items, shut down"
SHUTDOWN = object()


class Pipeline:
    """Holds the three queues + retry queue and the global stop event."""

    def __init__(self) -> None:
        maxsize = PIPELINE.queue_maxsize
        self.queue_a: Queue = Queue(maxsize)      # downloaded docs  -> range checker
        self.queue_b: Queue = Queue(maxsize)      # passed docs      -> uploader
        self.queue_retry: Queue = Queue(maxsize)  # failed uploads   -> retry worker
        self.stop_event = threading.Event()
        self.completed_docs: list = []            # to build final report

    def request_stop(self) -> None:
        self.stop_event.set()

    @property
    def stopping(self) -> bool:
        return self.stop_event.is_set()


class Ledger:
    """
    Thread-safe dedup record backed by the database.
    Replaces the old JSON file approach.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Ensure DB tables exist on first use
        init_db()
        _seen, _completed = self._load_counts()
        log.info("Loaded ledger from DB: %d seen, %d completed", _seen, _completed)

    def _load_counts(self) -> tuple[int, int]:
        with get_session() as db:
            seen      = db.query(TenderRow).count()
            completed = db.query(TenderRow).filter(TenderRow.status == "completed").count()
        return seen, completed

    def is_new(self, doc_id: str) -> bool:
        with self._lock:
            with get_session() as db:
                row = db.query(TenderRow).filter(TenderRow.id == doc_id).first()
                return row is None

    def mark_seen(self, doc_id: str, source: str = "", detail_url: str = "",
                  value: float | None = None, closing_date: str | None = None) -> bool:
        """Register a doc_id. Returns True if it was new, False if duplicate."""
        with self._lock:
            with get_session() as db:
                row = db.query(TenderRow).filter(TenderRow.id == doc_id).first()
                if row:
                    return False  # duplicate
                row = TenderRow(
                    id=doc_id,
                    source=source,
                    status="seen",
                    value=value,
                    closing_date=str(closing_date) if closing_date else None,
                    detail_url=detail_url,
                )
                db.add(row)
                db.commit()
                return True

    def mark_passed(self, doc_id: str, summary: str = "", pdf_path: str = "",
                    files: list | None = None) -> None:
        with self._lock:
            with get_session() as db:
                row = db.query(TenderRow).filter(TenderRow.id == doc_id).first()
                if row:
                    row.status = "passed"
                    row.summary = summary
                    row.pdf_path = pdf_path
                    row.files = files or []
                    db.commit()

    def mark_rejected(self, doc_id: str, reason: str = "") -> None:
        with self._lock:
            with get_session() as db:
                row = db.query(TenderRow).filter(TenderRow.id == doc_id).first()
                if row:
                    row.status = "rejected"
                    row.reject_reason = reason
                    db.commit()

    def mark_completed(self, doc_id: str) -> None:
        with self._lock:
            with get_session() as db:
                row = db.query(TenderRow).filter(TenderRow.id == doc_id).first()
                if row:
                    row.status = "completed"
                    db.commit()

    def is_completed(self, doc_id: str) -> bool:
        with self._lock:
            with get_session() as db:
                row = db.query(TenderRow).filter(TenderRow.id == doc_id).first()
                return row is not None and row.status == "completed"

    def get_passed_tenders(self) -> list[dict]:
        """Return all passed/completed tenders for the Results Dashboard."""
        with get_session() as db:
            rows = (
                db.query(TenderRow)
                .filter(TenderRow.status.in_(["passed", "completed"]))
                .order_by(TenderRow.created_at.desc())
                .all()
            )
            return [
                {
                    "id": r.id,
                    "source": r.source,
                    "status": r.status,
                    "summary": r.summary or "No summary available.",
                    "detail_url": r.detail_url,
                    "pdf_path": r.pdf_path,
                    "files": r.files or [],
                    "value": r.value,
                    "closing_date": r.closing_date,
                }
                for r in rows
            ]
