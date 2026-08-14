"""
Worker 2 — Range Checker.

Pulls from Queue A, makes sure the value/date fields are populated (extracting
from the PDF if the scraper didn't already provide them), applies the range
rules, and routes the doc: passed -> Queue B, rejected -> DB.
"""

from __future__ import annotations

import shutil
import threading
from queue import Empty

from config import REJECTED_DIR
import config
from core.extract import enrich_from_pdf, read_pdf_text
from core.summarize import generate_tender_report
from core.report import generate_single_report
from core.logging_setup import get_logger
from core.models import Status, TenderDoc
from core.rules import check_ranges
from core.state import SHUTDOWN, Pipeline


class RangeChecker(threading.Thread):
    def __init__(self, pipeline: Pipeline, ledger) -> None:
        super().__init__(name="range-checker", daemon=True)
        self.pipeline = pipeline
        self.ledger = ledger
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
        enrich_from_pdf(doc)

        verdict = check_ranges(doc)
        if verdict.passed:
            doc.status = Status.PASSED
            self.log.info("PASS  %s -> Queue B", doc)

            # ── Collect PDF text from ALL files in the tender folder ───────────
            summary_txt = ""
            files_list = []
            
            tender_dir = doc.pdf_path.parent if doc.pdf_path else None
            
            # Gather every PDF in the folder (original docs first, summary last)
            pdf_texts = []
            if tender_dir and tender_dir.is_dir():
                for f in sorted(tender_dir.iterdir()):
                    if f.suffix.lower() == ".pdf" and not f.name.startswith("Summary_"):
                        txt = read_pdf_text(f)
                        if txt.strip():
                            pdf_texts.append(txt)
                            self.log.info("Read %d chars from %s", len(txt), f.name)

            # If no text from individual files, fall back to pdf_path itself
            if not pdf_texts and doc.pdf_path and doc.pdf_path.exists():
                t = read_pdf_text(doc.pdf_path)
                if t.strip():
                    pdf_texts.append(t)

            combined_text = "\n\n".join(pdf_texts)

            if combined_text.strip():
                self.log.info("Generating Gemini summary report for %s (%d chars of text)...", doc.doc_id, len(combined_text))
                summary_txt, report_html = generate_tender_report(doc, combined_text)
                doc.summary = summary_txt
                doc.report_html = report_html
                self.log.info("Generated summary (%d chars)", len(summary_txt))
                generate_single_report(doc)
            else:
                self.log.warning("No readable PDF text found for %s — skipping Gemini summary.", doc.doc_id)

            # Build file list for the DB
            if tender_dir and tender_dir.is_dir():
                for f in tender_dir.iterdir():
                    if f.is_file():
                        try:
                            files_list.append(str(f.relative_to(config.DOWNLOADS_DIR)))
                        except ValueError:
                            # File is outside DOWNLOADS_DIR (e.g. IREPS custom folder)
                            files_list.append(str(f))

            # Persist to DB
            self.ledger.mark_passed(
                doc_id=doc.doc_id,
                summary=summary_txt,
                pdf_path=str(doc.pdf_path) if doc.pdf_path else "",
                files=files_list,
            )

            self.pipeline.queue_b.put(doc)
        else:
            doc.status = Status.REJECTED
            doc.reject_reason = verdict.reason
            self._reject(doc)

    def _reject(self, doc: TenderDoc) -> None:
        self.log.info("REJECT %s (%s)", doc, doc.reject_reason)

        # Delete the tender's local folder (no need to keep rejected files on disk)
        if doc.pdf_path and doc.pdf_path.exists():
            pdf_parent = doc.pdf_path.parent
            try:
                if pdf_parent.is_dir():
                    shutil.rmtree(pdf_parent, ignore_errors=True)
            except OSError as exc:
                self.log.warning("Could not delete rejected folder: %s", exc)

        # Record rejection in DB
        self.ledger.mark_rejected(doc_id=doc.doc_id, reason=doc.reject_reason or "")
