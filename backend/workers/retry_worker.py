"""
Retry Worker.

Docs that failed to upload (usually transient network/Lark issues) land on the
retry queue. This worker waits a cooldown, then tries again — putting successes
into completed/ and re-queueing failures until max_upload_attempts is reached.
It runs independently, so a slow retry never blocks the downloader or checker.
"""

from __future__ import annotations

import shutil
import threading
from queue import Empty

from config import COMPLETED_DIR, PIPELINE, REJECTED_DIR
from core.logging_setup import get_logger
from core.models import Status, TenderDoc
from core.state import SHUTDOWN, Ledger, Pipeline
from lark_client import LarkError, build_lark_client


class RetryWorker(threading.Thread):
    def __init__(self, pipeline: Pipeline, ledger: Ledger) -> None:
        super().__init__(name="retry", daemon=True)
        self.pipeline = pipeline
        self.ledger = ledger
        self.client = build_lark_client()
        self.log = get_logger("retry")

    def run(self) -> None:
        self.log.info("Retry worker started")
        while True:
            try:
                item = self.pipeline.queue_retry.get(timeout=1.0)
            except Empty:
                if self.pipeline.stopping:
                    break
                continue
            if item is SHUTDOWN:
                self.pipeline.queue_retry.task_done()
                break
            try:
                self._retry(item)
            finally:
                self.pipeline.queue_retry.task_done()
        self.log.info("Retry worker stopped")

    def _retry(self, doc: TenderDoc) -> None:
        if self.ledger.is_completed(doc.doc_id):
            return

        # Cooldown before re-attempting (interruptible for fast shutdown).
        self.pipeline.stop_event.wait(PIPELINE.retry_delay_seconds)
        if self.pipeline.stopping:
            # Put it back so it isn't lost; it'll be drained/persisted on exit.
            self.pipeline.queue_retry.put(doc)
            return

        doc.upload_attempts += 1
        self.log.info("Retry attempt %d for %s", doc.upload_attempts, doc.doc_id)
        try:
            self.client.send(doc)
        except (LarkError, Exception) as exc:  # noqa: BLE001
            if doc.upload_attempts >= PIPELINE.max_upload_attempts:
                self._give_up(doc, str(exc))
            else:
                self.log.warning("Retry failed for %s: %s (will try again)", doc.doc_id, exc)
                self.pipeline.queue_retry.put(doc)
            return

        # Success on retry.
        doc.status = Status.COMPLETED
        self.ledger.mark_completed(doc.doc_id)
        if doc.pdf_path and doc.pdf_path.exists():
            try:
                dest = COMPLETED_DIR / doc.pdf_path.name
                shutil.move(str(doc.pdf_path), dest)
                doc.pdf_path = dest
            except OSError:
                pass
        self.log.info("COMPLETED %s ✓ (after %d attempts)", doc.doc_id, doc.upload_attempts)

    def _give_up(self, doc: TenderDoc, reason: str) -> None:
        doc.status = Status.FAILED
        doc.reject_reason = f"upload gave up after {doc.upload_attempts} attempts: {reason}"
        self.log.error("GIVE UP on %s: %s", doc.doc_id, reason)
        fail_file = REJECTED_DIR / f"FAILED_{doc.source}_{doc.doc_id}.txt"
        fail_file.write_text(f"{doc}\n{doc.reject_reason}\n", encoding="utf-8")
