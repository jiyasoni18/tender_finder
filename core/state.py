"""
Runtime plumbing shared across workers: the queues, the shutdown signal, and a
persistent dedup ledger so restarts don't re-process the same tender.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from queue import Queue

from config import PIPELINE, STATE_DIR
from core.logging_setup import get_logger

log = get_logger("state")

# --- Sentinel used to tell a worker "no more items, shut down" -------------- #
SHUTDOWN = object()


class Pipeline:
    """Holds the three queues + retry queue and the global stop event."""

    def __init__(self) -> None:
        maxsize = PIPELINE.queue_maxsize
        self.queue_a: Queue = Queue(maxsize)   # downloaded docs  -> range checker
        self.queue_b: Queue = Queue(maxsize)   # passed docs      -> uploader
        self.queue_retry: Queue = Queue(maxsize)  # failed uploads -> retry worker
        self.stop_event = threading.Event()
        self.completed_docs: list = []         # to build final report

    def request_stop(self) -> None:
        self.stop_event.set()

    @property
    def stopping(self) -> bool:
        return self.stop_event.is_set()


class Ledger:
    """
    Thread-safe record of doc_ids we've already seen and completed. Persisted to
    disk so a crash/restart doesn't re-download or re-upload the same tenders.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (STATE_DIR / "ledger.json")
        self._lock = threading.Lock()
        self._seen: set[str] = set()       # ever entered the pipeline
        self._completed: set[str] = set()  # successfully uploaded
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._seen = set(data.get("seen", []))
                self._completed = set(data.get("completed", []))
                log.info("Loaded ledger: %d seen, %d completed",
                         len(self._seen), len(self._completed))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Could not read ledger (%s); starting fresh", exc)

    def _flush(self) -> None:
        import time
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"seen": sorted(self._seen), "completed": sorted(self._completed)},
            indent=2,
        ))
        for _ in range(5):
            try:
                tmp.replace(self._path)  # atomic on POSIX
                break
            except PermissionError:
                time.sleep(0.2)

    def is_new(self, doc_id: str) -> bool:
        with self._lock:
            return doc_id not in self._seen

    def mark_seen(self, doc_id: str) -> bool:
        """Register a doc_id. Returns True if it was new, False if a duplicate."""
        with self._lock:
            if doc_id in self._seen:
                return False
            self._seen.add(doc_id)
            self._flush()
            return True

    def mark_completed(self, doc_id: str) -> None:
        with self._lock:
            self._completed.add(doc_id)
            self._flush()

    def is_completed(self, doc_id: str) -> bool:
        with self._lock:
            return doc_id in self._completed
