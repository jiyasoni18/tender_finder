"""
Worker 2 — Range Checker.

Pulls from Queue A, makes sure the value/date fields are populated (extracting
from the PDF if the scraper didn't already provide them), applies the range
rules, and routes the doc: passed -> Queue B, rejected -> rejected/ folder + log.
"""

from __future__ import annotations

import shutil
import threading
from queue import Empty

from config import REJECTED_DIR
from core.extract import enrich_from_pdf, read_pdf_text
from core.summarize import generate_tender_report
from core.report import generate_single_report
from core.logging_setup import get_logger
from core.models import Status, TenderDoc
from core.rules import check_ranges
from core.state import SHUTDOWN, Pipeline


class RangeChecker(threading.Thread):
    def __init__(self, pipeline: Pipeline) -> None:
        super().__init__(name="range-checker", daemon=True)
        self.pipeline = pipeline
        self.log = get_logger("range_checker")

    def run(self) -> None:
        self.log.info("Range checker started")
        while True:
            try:
                item = self.pipeline.queue_a.get(timeout=1.0)
            except Empty:
                if self.pipeline.stopping:
                    break
                continue
            if item is SHUTDOWN:
                self.pipeline.queue_a.task_done()
                break
            try:
                self._process(item)
            except Exception as exc:  # noqa: BLE001
                self.log.exception("Error checking %s: %s", item.doc_id, exc)
            finally:
                self.pipeline.queue_a.task_done()
        self.log.info("Range checker stopped")

    def _process(self, doc: TenderDoc) -> None:
        # Fill in whatever the scraper couldn't give us straight from the listing.
        enrich_from_pdf(doc)

        verdict = check_ranges(doc)
        if verdict.passed:
            doc.status = Status.PASSED
            self.log.info("PASS  %s -> Queue B", doc)
            
            # Generate summary report if PDF exists
            if doc.pdf_path and doc.pdf_path.exists():
                self.log.info("Generating Gemini summary report for %s...", doc.doc_id)
                pdf_text = read_pdf_text(doc.pdf_path)
                summary, report_html = generate_tender_report(doc, pdf_text)
                doc.summary = summary
                doc.report_html = report_html
                self.log.info("Generated summary (%s chars, %s html chars)", len(summary), len(report_html))
                
                # Save the single PDF in the tender's folder
                generate_single_report(doc)
            
            self.pipeline.queue_b.put(doc)
        else:
            doc.status = Status.REJECTED
            doc.reject_reason = verdict.reason
            self._reject(doc)

    def _reject(self, doc: TenderDoc) -> None:
        self.log.info("REJECT %s (%s)", doc, doc.reject_reason)
        # Move the PDF into rejected/ and drop a sidecar .txt with the reason.
        if doc.pdf_path and doc.pdf_path.exists():
            dest = REJECTED_DIR / doc.pdf_path.name
            pdf_parent = doc.pdf_path.parent
            try:
                shutil.move(str(doc.pdf_path), dest)
                doc.pdf_path = dest
                
                # Delete the whole folder for rejected tenders
                if pdf_parent.is_dir() and "IREPS_Tenders" in str(pdf_parent):
                    shutil.rmtree(pdf_parent, ignore_errors=True)
            except OSError as exc:
                self.log.warning("Could not move rejected PDF or delete folder: %s", exc)
        
        reason_file = REJECTED_DIR / f"{doc.source}_{doc.doc_id}.txt"
        reason_file.write_text(
            f"{doc}\nreason: {doc.reject_reason}\n", encoding="utf-8"
        )
