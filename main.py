"""
Tender pipeline entry point.

Wires up the queues, spins one Downloader per enabled site plus the range
checker, uploader, and retry worker, then runs until Ctrl-C. Each stage is an
independent thread connected only by queues, exactly like the architecture:

    site -> [Downloader] -> Queue A -> [Range Checker] --pass--> Queue B
                                              |                     |
                                           reject             [Uploader] --fail--> Queue Retry
                                              v                     |                     |
                                        rejected/            completed/          [Retry Worker] -> completed/
"""

from __future__ import annotations

import signal
import sys
import threading

from config import PIPELINE, SITES
from core.logging_setup import get_logger
from core.state import SHUTDOWN, Ledger, Pipeline
from core.report import generate_final_report
from sites.registry import build_scraper
from workers.downloader import Downloader
from workers.range_checker import RangeChecker
from workers.retry_worker import RetryWorker
from workers.uploader import Uploader

log = get_logger("main")


def build_threads(pipeline: Pipeline, ledger: Ledger, scrapers: dict) -> list[threading.Thread]:
    threads: list[threading.Thread] = []

    enabled_sites = [s for s in SITES if s.enabled]
    if not enabled_sites:
        log.warning("No sites enabled in config.SITES — nothing to download.")
    for site in enabled_sites:
        threads.append(Downloader(site, pipeline, ledger, scraper=scrapers.get(site.name)))

    threads.append(RangeChecker(pipeline))
    threads.append(Uploader(pipeline, ledger))
    threads.append(RetryWorker(pipeline, ledger))
    return threads


def main() -> int:
    print("\n" + "="*60)
    print("Welcome to Tender Finder!")
    print("1. IREPS (ireps.gov.in)")
    print("2. Tender Detail (tenderdetail.com)")
    choice = input("Which site would you like to scrape? Enter 1 or 2: ").strip()
    
    # Disable all sites first
    for site in SITES:
        site.enabled = False
        
    if choice == "1":
        for site in SITES:
            if site.name == "ireps":
                site.enabled = True
    elif choice == "2":
        for site in SITES:
            if site.name == "tenderdetail":
                site.enabled = True
    else:
        print("Invalid choice. Exiting.")
        return 1

    log.info("=" * 60)
    log.info("Tender pipeline starting")
    log.info("Sites enabled: %s", [s.name for s in SITES if s.enabled] or "NONE")
    log.info("=" * 60)

    # Login in the MAIN thread so input() works (background threads cannot use input())
    scrapers = {}
    for site in [s for s in SITES if s.enabled]:
        scraper = build_scraper(site)
        try:
            log.info("Logging in to '%s'...", site.name)
            scraper.login()
            scrapers[site.name] = scraper
            log.info("Login successful for '%s'.", site.name)
        except Exception as exc:
            log.error("Login failed for '%s': %s — skipping site.", site.name, exc)

    pipeline = Pipeline()
    ledger = Ledger()
    threads = build_threads(pipeline, ledger, scrapers)

    stop_requested = threading.Event()

    def handle_signal(signum, _frame):
        log.info("Signal %s received — shutting down gracefully...", signum)
        stop_requested.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    for t in threads:
        t.start()

    # Main thread just waits for a stop signal.
    try:
        while not stop_requested.is_set():
            stop_requested.wait(0.5)
    finally:
        _shutdown(pipeline, threads)

    log.info("Pipeline stopped cleanly.")
    return 0


def _shutdown(pipeline: Pipeline, threads: list[threading.Thread]) -> None:
    pipeline.request_stop()
    # Wake any worker blocked on a queue.get() with sentinels.
    for q in (pipeline.queue_a, pipeline.queue_b, pipeline.queue_retry):
        q.put(SHUTDOWN)

    for t in threads:
        t.join(timeout=PIPELINE.shutdown_grace_seconds)
        if t.is_alive():
            log.warning("Thread %s did not stop within grace period", t.name)
            
    # Generate the final report with all completed tenders
    if hasattr(pipeline, 'completed_docs') and pipeline.completed_docs:
        generate_final_report(pipeline.completed_docs)


if __name__ == "__main__":
    sys.exit(main())
