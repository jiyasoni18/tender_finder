"""
Worker 3 — Lark Uploader.

Pulls passed docs from Queue B and hands them to the Lark client. On success the
PDF moves to completed/ and the ledger records it. On a recoverable failure the
doc goes to the retry queue instead of being lost.
"""

from __future__ import annotations

import shutil
import threading
from queue import Empty

from config import COMPLETED_DIR
from core.logging_setup import get_logger
from core.models import Status, TenderDoc
from core.state import SHUTDOWN, Ledger, Pipeline
from lark_client import LarkError, build_lark_client


class Uploader(threading.Thread):
    def __init__(self, pipeline: Pipeline, ledger: Ledger, name: str = "uploader") -> None:
        super().__init__(name=name, daemon=True)
        self.pipeline = pipeline
        self.ledger = ledger
        self.client = build_lark_client()
        self.log = get_logger("uploader")

    def run(self) -> None:
        self.log.info("Uploader started (mode=%s)", self.client.config.mode)
        while True:
            try:
                item = self.pipeline.queue_b.get(timeout=1.0)
            except Empty:
                if self.pipeline.stopping:
                    break
                continue
            if item is SHUTDOWN:
                self.pipeline.queue_b.task_done()
                break
            try:
                self._upload(item)
            finally:
                self.pipeline.queue_b.task_done()
        self.log.info("Uploader stopped")

    def _upload(self, doc: TenderDoc) -> None:
        if self.ledger.is_completed(doc.doc_id):
            self.log.debug("%s already completed; skipping", doc.doc_id)
            return

        doc.status = Status.UPLOADING
        doc.upload_attempts += 1
        try:
            self.client.send(doc)
        except LarkError as exc:
            # Recoverable — hand off to the retry worker.
            self.log.warning("Upload failed for %s: %s -> retry queue", doc.doc_id, exc)
            doc.status = Status.FAILED
            doc.reject_reason = str(exc)
            self.pipeline.queue_retry.put(doc)
            return
        except Exception as exc:  # noqa: BLE001 - unexpected: still don't lose it
            self.log.exception("Unexpected upload error for %s: %s", doc.doc_id, exc)
            self.pipeline.queue_retry.put(doc)
            return

        self._complete(doc)

    def _complete(self, doc: TenderDoc) -> None:
        doc.status = Status.COMPLETED
        self.ledger.mark_completed(doc.doc_id)
        if doc.pdf_path and doc.pdf_path.exists():
            dest = COMPLETED_DIR / doc.pdf_path.name
            try:
                shutil.copy2(str(doc.pdf_path), dest)
                # Keep doc.pdf_path pointing to the original so it stays in IREPS_Tenders
            except OSError as exc:
                self.log.warning("Could not move completed PDF: %s", exc)
        self.pipeline.completed_docs.append(doc)
        self.log.info("COMPLETED %s ✓", doc.doc_id)
