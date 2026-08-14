"""Shared data model that travels through the queues."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    DOWNLOADED = "downloaded"
    PASSED = "passed"
    REJECTED = "rejected"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TenderDoc:
    """
    One tender advertisement as it flows through the pipeline.

    The downloader fills the identity + file fields; the range checker fills the
    extracted fields + verdict; the uploader flips status to COMPLETED/FAILED.
    """

    # Identity ------------------------------------------------------------- #
    doc_id: str                     # stable, unique key used for dedup
    source: str                     # site name, e.g. "ireps"
    title: str = ""
    detail_url: str = ""

    # Files ---------------------------------------------------------------- #
    pdf_path: Path | None = None    # where the downloaded PDF lives locally

    # Extracted fields (Worker 2) ------------------------------------------ #
    value: float | None = None          # tender value in rupees
    closing_date: date | None = None
    published_date: date | None = None

    # Verdict / bookkeeping ------------------------------------------------ #
    status: Status = Status.DOWNLOADED
    reject_reason: str = ""
    upload_attempts: int = 0
    summary: str = ""
    report_html: str = ""
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["pdf_path"] = str(self.pdf_path) if self.pdf_path else None
        d["closing_date"] = self.closing_date.isoformat() if self.closing_date else None
        d["published_date"] = self.published_date.isoformat() if self.published_date else None
        return d

    def __str__(self) -> str:  # compact log-friendly form
        val = f"₹{self.value:,.0f}" if self.value is not None else "?"
        cd = self.closing_date.isoformat() if self.closing_date else "?"
        return f"[{self.source}:{self.doc_id}] {self.title[:48]!r} value={val} close={cd}"
