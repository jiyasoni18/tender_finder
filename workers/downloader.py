"""
Worker 1 — Downloader.

One downloader thread per enabled site. Each logs in, polls for new tenders,
downloads the PDF for anything it hasn't seen before, and drops a TenderDoc onto
Queue A. It NEVER waits for range-checking or uploading — that's the whole point
of the queue.
"""

from __future__ import annotations

import threading

from config import PIPELINE, SiteConfig
from core.logging_setup import get_logger
from core.models import TenderDoc
from core.state import Ledger, Pipeline
from sites.registry import build_scraper


class Downloader(threading.Thread):
    def __init__(self, site: SiteConfig, pipeline: Pipeline, ledger: Ledger, scraper=None) -> None:
        super().__init__(name=f"dl-{site.name}", daemon=True)
        self.site = site
        self.pipeline = pipeline
        self.ledger = ledger
        self.log = get_logger(f"downloader.{site.name}")
        # Use the pre-built scraper (already logged in from the main thread) if provided
        self.scraper = scraper if scraper is not None else build_scraper(site)
        self.downloaded_count = 0

    def run(self) -> None:
        self.log.info("Downloader started for '%s'", self.site.name)
        try:
            self._loop()
        finally:
            try:
                self.scraper.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self.log.info("Downloader for '%s' stopped", self.site.name)

    def _loop(self) -> None:
        while not self.pipeline.stopping:
            try:
                self.scraper.ensure_login()
                self._poll_once()
            except EOFError:
                # input() was called from a background thread — this should never happen
                # if login was done correctly in the main thread. Log and stop.
                self.log.error(
                    "EOFError in '%s': login() was called from a background thread. "
                    "This is a bug — login must happen in the main thread.",
                    self.site.name
                )
                break
            except Exception as exc:  # noqa: BLE001
                # A site error must not kill the thread — log, back off, retry.
                self.log.exception("Error polling '%s': %s", self.site.name, exc)
                # Do NOT reset _logged_in here — we cannot re-login from a background thread.
                # The session will be reused as-is on the next poll.

            # Interruptible wait so shutdown is snappy.
            if PIPELINE.max_downloads > 0 and self.downloaded_count >= PIPELINE.max_downloads:
                break
                
            self.pipeline.stop_event.wait(self.site.poll_interval_seconds)

    def _poll_once(self) -> None:
        listings = self.scraper.find_new_tenders()
        new = [l for l in listings if self.ledger.is_new(l.doc_id)]
        if not new:
            self.log.debug("No new tenders for '%s'", self.site.name)
            return

        self.log.info("%d new tender(s) on '%s'", len(new), self.site.name)
        for listing in new:
            if self.pipeline.stopping:
                break
                
            if PIPELINE.max_downloads > 0 and self.downloaded_count >= PIPELINE.max_downloads:
                self.log.info("Reached max_downloads (%d) for site '%s'", PIPELINE.max_downloads, self.site.name)
                self.pipeline.request_stop() # or just stop this thread by setting a flag, but request_stop stops the pipeline. Alternatively, just break and exit loop.
                break
                
            # Claim the id first so two runs can't double-download it.
            if not self.ledger.mark_seen(listing.doc_id):
                continue
            try:
                doc: TenderDoc = self.scraper.download(listing)
            except Exception as exc:  # noqa: BLE001
                self.log.error("Download failed for %s: %s", listing.doc_id, exc)
                continue
            self.log.info("Downloaded %s -> Queue A", doc.doc_id)
            self.pipeline.queue_a.put(doc)
            self.downloaded_count += 1
            
            if PIPELINE.max_downloads > 0 and self.downloaded_count >= PIPELINE.max_downloads:
                self.log.info("Reached max_downloads (%d) for site '%s', stopping this downloader.", PIPELINE.max_downloads, self.site.name)
                # Setting pipeline to stop will stop all downloaders. 
                # If we only want to stop this thread, we could just return from _loop.
                # Since max_downloads is generally for testing or quota, stopping the thread is safer.
                break
